#!/usr/bin/env python3
"""
afpub_to_markdown.py  —  Extract text from Affinity Publisher .afpub files

USAGE
─────
  python afpub_to_markdown.py book.afpub
      → writes book.md alongside the source file

  python afpub_to_markdown.py book.afpub output.md
      → writes to an explicit path

  python afpub_to_markdown.py --dump-styles book.afpub
      → prints every style ID found, its run count, and sample text.
        Use this when setting up styles.yaml for a new book or template.

  python afpub_to_markdown.py --analyze-styles book.afpub
      → comprehensive style analysis: template names, all run IDs, YAML status.
        Optimised for copy-pasting to an AI to update styles.yaml.

  python afpub_to_markdown.py *.afpub
      → batch-converts every .afpub in the current directory

REQUIREMENTS
────────────
  Python 3.8+   No third-party packages required.
  styles.yaml must live in the same folder as this script (or the .exe).

HOW PAGE ORDER WORKS
─────────────────────
  Affinity Publisher stores text frames in layer/creation order, not reading
  order. This extractor recovers correct page order by processing the file
  spread by spread (each spread = one double-page). Within each spread,
  blocks are sorted so heading-level styles appear before body styles,
  which fixes the most common misordering (e.g. a title frame stored after
  the body text it heads). Master/template spreads (those containing an
  unusually large number of unique blocks) are automatically skipped.

PACKAGING AS A STANDALONE EXECUTABLE
──────────────────────────────────────
  Install PyInstaller once:
    pip install pyinstaller

  Windows — build afpub_to_markdown.exe:
    pyinstaller --onefile --add-data "styles.yaml;." afpub_to_markdown.py
    (distribute dist/afpub_to_markdown.exe alongside styles.yaml)

  macOS — build a binary:
    pyinstaller --onefile --add-data "styles.yaml:." afpub_to_markdown.py
    (distribute dist/afpub_to_markdown alongside styles.yaml)

  On Windows, zstd.dll must be present alongside the .exe.
  Download from: https://github.com/facebook/zstd/releases
  (grab the zstd-vX.Y.Z-win64.zip, extract zstd.dll)
"""

import sys
import struct
import ctypes
import glob
from pathlib import Path
from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
# Minimal YAML parser  (stdlib only — no PyYAML needed)
# ─────────────────────────────────────────────────────────────────────────────

def _load_styles_yaml(yaml_path: Path) -> tuple[dict, str]:
    style_map: dict[int, dict] = {}
    fallback = "warn"

    if not yaml_path.exists():
        print(f"[WARNING] styles.yaml not found at {yaml_path}")
        print("          All text will be treated as plain body text.")
        return style_map, fallback

    lines = yaml_path.read_text(encoding="utf-8").splitlines()
    current: dict = {}
    in_styles = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "styles:":
            in_styles = True
            continue
        if line.startswith("fallback:"):
            fallback = line.split(":", 1)[1].strip().strip('"').strip("'")
            continue
        if not in_styles:
            continue
        if line.startswith("- id:"):
            if current and "id" in current and "markdown" in current:
                style_map[current["id"]] = current
            val = line.split(":", 1)[1].strip()
            current = {"id": int(val)}
            continue
        if ":" in line and not line.startswith("-"):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in ("id", "markdown", "name", "note"):
                current[key] = int(val) if key == "id" else val

    if current and "id" in current and "markdown" in current:
        style_map[current["id"]] = current

    return style_map, fallback


# ─────────────────────────────────────────────────────────────────────────────
# zstd decompression via system libzstd
# ─────────────────────────────────────────────────────────────────────────────

class _InBuf(ctypes.Structure):
    _fields_ = [("src",  ctypes.c_void_p),
                ("size", ctypes.c_size_t),
                ("pos",  ctypes.c_size_t)]

class _OutBuf(ctypes.Structure):
    _fields_ = [("dst",  ctypes.c_void_p),
                ("size", ctypes.c_size_t),
                ("pos",  ctypes.c_size_t)]


def _load_zstd():
    candidates = [
        "zstd.dll", "libzstd.dll",
        "libzstd.dylib", "libzstd.1.dylib",
        "libzstd.so.1", "libzstd.so",
    ]
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
            lib.ZSTD_isError.restype           = ctypes.c_uint
            lib.ZSTD_getErrorName.restype      = ctypes.c_char_p
            lib.ZSTD_createDStream.restype     = ctypes.c_void_p
            lib.ZSTD_freeDStream.argtypes      = [ctypes.c_void_p]
            lib.ZSTD_initDStream.argtypes      = [ctypes.c_void_p]
            lib.ZSTD_initDStream.restype       = ctypes.c_size_t
            lib.ZSTD_decompressStream.restype  = ctypes.c_size_t
            lib.ZSTD_decompressStream.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_OutBuf),
                ctypes.POINTER(_InBuf),
            ]
            return lib
        except OSError:
            continue
    return None


def _zstd_decompress(compressed: bytes, lib) -> bytes:
    CHUNK   = 4 * 1024 * 1024
    src     = (ctypes.c_uint8 * len(compressed)).from_buffer_copy(compressed)
    dst     = (ctypes.c_uint8 * CHUNK)()
    dstream = lib.ZSTD_createDStream()
    lib.ZSTD_initDStream(dstream)
    in_buf  = _InBuf(ctypes.cast(src, ctypes.c_void_p), len(compressed), 0)
    output  = bytearray()
    try:
        while True:
            out_buf = _OutBuf(ctypes.cast(dst, ctypes.c_void_p), CHUNK, 0)
            ret = lib.ZSTD_decompressStream(
                dstream, ctypes.byref(out_buf), ctypes.byref(in_buf)
            )
            if out_buf.pos:
                output.extend(dst[:out_buf.pos])
            if lib.ZSTD_isError(ret):
                raise RuntimeError(
                    f"zstd error: {lib.ZSTD_getErrorName(ret).decode()}"
                )
            if ret == 0 or in_buf.pos >= len(compressed):
                break
    finally:
        lib.ZSTD_freeDStream(dstream)
    return bytes(output)


# ─────────────────────────────────────────────────────────────────────────────
# .afpub binary constants and helpers
# ─────────────────────────────────────────────────────────────────────────────

_ZSTD_MAGIC = bytes([0x28, 0xB5, 0x2F, 0xFD])
_LINE_SEP   = "\u2028"
_PARA_SEP   = "\u2029"

_HEADING_SORT_ORDER = {
    "#":     0,
    "##":    1,
    "###":   2,
    "####":  3,
    "#####": 4,
}


def _decompress_afpub(path: Path, zstd_lib) -> bytes:
    raw    = path.read_bytes()
    offset = raw.find(_ZSTD_MAGIC)
    if offset == -1:
        raise ValueError("No zstd frame found — is this a valid .afpub file?")
    return _zstd_decompress(raw[offset:], zstd_lib)


# ─────────────────────────────────────────────────────────────────────────────
# Spread discovery
# ─────────────────────────────────────────────────────────────────────────────

def _find_spread_boundaries(data: bytes) -> list[tuple[int, int]]:
    _SPREAD_TAG = b'drpS'
    _UTF8_TAGS  = (b'+8ftU', b'gUtf8+')

    positions: list[int] = []
    pos = 0
    while True:
        p = data.find(_SPREAD_TAG, pos)
        if p == -1:
            break
        positions.append(p)
        pos = p + 1

    if not positions:
        return [(0, len(data))]

    boundaries: list[tuple[int, int]] = []
    for i, sp_start in enumerate(positions):
        sp_end = positions[i + 1] if i + 1 < len(positions) else len(data)
        scan_end = min(sp_end, sp_start + 1_000_000)
        has_text = any(
            data.find(tag, sp_start, scan_end) != -1
            for tag in _UTF8_TAGS
        )
        if has_text:
            boundaries.append((sp_start, sp_end))

    return boundaries


# ─────────────────────────────────────────────────────────────────────────────
# Run-list parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_run_list(data: bytes, pos: int, run_count: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for _ in range(run_count):
        if pos + 4 <= len(data) and data[pos:pos+4] == b'RAlG':
            pos += 6
        while (pos < len(data)
               and data[pos] in (0x00, 0x01)
               and (pos + 1 >= len(data) or data[pos + 1] != 0x78)):
            pos += 1

        if not (pos + 9 <= len(data)
                and data[pos] == 0x07
                and data[pos+1:pos+5] == b'xdnI'):
            _XDNI = bytes([0x07, 0x78, 0x64, 0x6e, 0x49])
            next_pos = data.find(_XDNI, pos, pos + 2000)
            if next_pos == -1:
                break
            pos = next_pos

        if (pos + 9 > len(data)
                or data[pos] != 0x07
                or data[pos+1:pos+5] != b'xdnI'):
            break
        char_idx = struct.unpack_from('<I', data, pos + 5)[0]
        pos += 9
        if pos + 5 > len(data) or data[pos:pos+5] != b'1metI':
            break
        item_type = data[pos + 5]
        if item_type == 0x02 or item_type == 0x01:
            style_id = struct.unpack_from('<H', data, pos + 6)[0]
            pos += 10
        else:
            style_id = data[pos + 6]
            pos += 9
        runs.append((char_idx, style_id))
    return runs


# ─────────────────────────────────────────────────────────────────────────────
# Text block extraction within a byte region
# ─────────────────────────────────────────────────────────────────────────────

def _extract_blocks_in_region(
    data: bytes,
    region_start: int,
    region_end: int,
) -> list[tuple[int, str, list, list]]:
    _UTF8_TAGS = (b'+8ftU', b'gUtf8+')
    _ATTR_TAG  = b'2ttAG'
    results: list[tuple[int, str, list, list]] = []
    pos = region_start

    while pos < region_end:
        best = -1
        for tag in _UTF8_TAGS:
            idx = data.find(tag, pos, region_end)
            if idx != -1 and (best == -1 or idx < best):
                best = idx
        if best == -1:
            break

        block_len = struct.unpack_from('<I', data, best + 5)[0]
        text_start = best + 9
        text_end   = text_start + block_len

        if block_len < 1 or block_len > 500_000 or text_end > region_end:
            pos = best + 1
            continue

        _TXFM_TAG = b'MFxT'
        pre_scan_start = max(region_start, best - 100)
        if _TXFM_TAG in data[pre_scan_start:best]:
            pos = text_end
            continue

        try:
            text = data[text_start:text_end].decode('utf-8', errors='replace')
        except Exception:
            pos = best + 1
            continue

        text = (text
                .replace(_PARA_SEP, _LINE_SEP)
                .replace('\t', '')
                .replace('\u201c', '"')
                .replace('\u201d', '"')
                .replace('\u2018', "'")
                .replace('\u2019', "'")
                )

        runs: list[tuple[int, int]] = []
        para_runs: list[tuple[int, int]] = []
        scan = text_end
        if scan < len(data) and data[scan] == 0x00:
            scan += 1
        if scan + 5 <= len(data) and data[scan:scan+5] == _ATTR_TAG:
            scan += 6
            if scan + 4 <= len(data) and data[scan:scan+4] == b'SAlG':
                scan += 6
        if (scan + 5 <= len(data)
                and data[scan] == 0xB2
                and data[scan+1:scan+5] == b'snuR'):
            scan += 5
            run_count = struct.unpack_from('<I', data, scan)[0]
            scan += 4
            if 1 <= run_count <= 300:
                runs = _parse_run_list(data, scan, run_count)

        _PARA_ATTR_TAG = b'2ttAP'
        para_scan_end = min(len(data), text_end + 5000)
        for _tag in _UTF8_TAGS:
            _next = data.find(_tag, text_end + 1, para_scan_end)
            if _next != -1:
                para_scan_end = _next
        p_pos = data.find(_PARA_ATTR_TAG, text_end, para_scan_end)
        if p_pos != -1:
            p_scan = p_pos + 6
            if p_scan + 4 <= len(data) and data[p_scan:p_scan+4] == b'SAaP':
                p_scan += 6
            if (p_scan + 5 <= len(data)
                    and data[p_scan] == 0xB2
                    and data[p_scan+1:p_scan+5] == b'snuR'):
                p_scan += 5
                p_count = struct.unpack_from('<I', data, p_scan)[0]
                p_scan += 4
                if 1 <= p_count <= 300:
                    para_runs = _parse_run_list(data, p_scan, p_count)

        if text.strip():
            results.append((best, text, runs, para_runs))

        pos = text_end

    results = _join_linked_frames(results)
    return results


def _join_linked_frames(
    blocks: list[tuple[int, str, list, list]],
) -> list[tuple[int, str, list, list]]:
    if len(blocks) < 2:
        return blocks

    joined: list[tuple[int, str, list, list]] = []
    i = 0
    while i < len(blocks):
        offset, text, runs, para_runs = blocks[i]

        while i + 1 < len(blocks):
            cur_stripped = text.rstrip('\x00').rstrip()
            if len(cur_stripped) < 20 or not cur_stripped[-1].isalpha():
                break
            next_offset, next_text, next_runs, next_para_runs = blocks[i + 1]
            next_clean = next_text.lstrip('\x00').lstrip()
            if not next_clean or not next_clean[0].islower():
                break

            cur_for_join = text.rstrip('\x00')
            base_len = len(cur_for_join)
            text = cur_for_join + next_text

            if next_runs:
                offset_runs = [(ce + base_len, sid) for ce, sid in next_runs]
                runs = runs + offset_runs
            if next_para_runs:
                offset_para = [(ce + base_len, sid) for ce, sid in next_para_runs]
                para_runs = para_runs + offset_para

            i += 1

        joined.append((offset, text, runs, para_runs))
        i += 1

    return joined


# ─────────────────────────────────────────────────────────────────────────────
# Within-spread ordering
# ─────────────────────────────────────────────────────────────────────────────

def _heading_priority(runs: list[tuple[int, int]], style_map: dict) -> int:
    best = 5
    for _, style_id in runs:
        entry = style_map.get(style_id)
        if entry:
            prefix = entry.get("markdown", "")
            priority = _HEADING_SORT_ORDER.get(prefix, 5)
            if priority < best:
                best = priority
    return best


def _sort_spread_blocks(
    blocks: list[tuple[int, str, list, list]],
    style_map: dict,
) -> list[tuple[int, str, list, list]]:
    if len(blocks) < 2:
        return blocks

    priorities = [_heading_priority(b[2], style_map) for b in blocks]
    top_hp = min(priorities)
    if top_hp >= 5:
        return blocks

    top_idx = next(i for i, p in enumerate(priorities) if p == top_hp)
    top_block = blocks[top_idx]
    top_offset = top_block[0]

    after  = [b for b in blocks if b[0] > top_offset]
    before = [b for b in blocks if b[0] < top_offset]

    if not after or len(before) <= 1:
        if len(before) >= 2:
            sub_heads = [b for b in before
                         if _heading_priority(b[2], style_map) < 5]
            body_blocks = [b for b in before
                           if _heading_priority(b[2], style_map) >= 5]
            if (len(sub_heads) > 0
                    and len(sub_heads) == len(body_blocks)
                    and min(b[0] for b in sub_heads) > max(b[0] for b in body_blocks)):
                interleaved = []
                for sh, bd in zip(sub_heads, body_blocks):
                    interleaved.append(sh)
                    interleaved.append(bd)
                return [top_block] + after + interleaved

        return [top_block] + after + before

    before_rev = before[::-1]

    before_heading = [b for b in before_rev
                      if _heading_priority(b[2], style_map) < 5]
    if before_heading:
        closest_bh_dist = min(abs(b[0] - top_offset) for b in before_heading)
        close_after = [b for b in after
                       if abs(b[0] - top_offset) < closest_bh_dist]
        far_after   = [b for b in after
                       if abs(b[0] - top_offset) >= closest_bh_dist]
    else:
        close_after = after
        far_after   = []

    farthest_after_dist = max(abs(b[0] - top_offset) for b in after)
    before_close = [b for b in before_rev
                    if abs(b[0] - top_offset) <= farthest_after_dist]
    before_far   = [b for b in before_rev
                    if abs(b[0] - top_offset) > farthest_after_dist]

    return [top_block] + close_after + before_close + far_after + before_far


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication
# ─────────────────────────────────────────────────────────────────────────────

class _SeenTexts:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_new(self, text: str) -> bool:
        key = text.strip()[:80]
        if not key or key in self._seen:
            return False
        self._seen.add(key)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Block → Markdown conversion
# ─────────────────────────────────────────────────────────────────────────────

def _is_content(text: str) -> bool:
    return any(c.isalpha() for c in text)


def _spaced_append(lines: list[str], new_line: str) -> None:
    if lines:
        prev = lines[-1]
        if prev.startswith(">") and new_line.startswith("<<"):
            lines.append(new_line)
            return
        if (prev.endswith("  ")
                and not new_line.startswith("#")
                and not new_line.startswith(">")
                and not new_line.startswith("<<")):
            lines.append(new_line)
            return
        lines.append("")
        lines.append(new_line)
    else:
        lines.append(new_line)


def _block_to_md(
    text: str,
    runs: list[tuple[int, int]],
    para_runs: list[tuple[int, int]],
    style_map: dict,
    fallback: str,
    warnings: list[tuple[str, str]],
    callout_texts: list[str] | None = None,
) -> list[str]:
    lines: list[str] = []

    clean_check = text.replace(_LINE_SEP, '').strip().rstrip('\x00')
    if not _is_content(clean_check) and len(clean_check) < 8:
        return lines

    if not runs:
        paras = text.split(_LINE_SEP)
        for k, para in enumerate(paras):
            para = para.strip().rstrip('\x00')
            if not para or not _is_content(para):
                continue
            if k > 0 and lines:
                lines[-1] += '  '
                lines.append(para)
            else:
                _spaced_append(lines, para)
        return lines

    segments: list[tuple[str, int, int]] = []
    prev_end = 0
    for char_end, style_id in runs:
        segments.append((text[prev_end:char_end], style_id, prev_end))
        prev_end = char_end
    tail = text[prev_end:].strip().rstrip('\x00')
    if tail and runs:
        segments.append((tail, runs[-1][1], prev_end))

    _BODY_PREFIXES = {"", ">"}

    resolved: list[tuple[str, str, int]] = []
    for i, (seg, sid, seg_offset) in enumerate(segments):
        entry = style_map.get(sid)
        if entry is None:
            if fallback == "skip":
                resolved.append((seg, "SKIP", seg_offset))
                continue
            if fallback == "warn":
                sample = seg.replace(_LINE_SEP, " ").strip()[:60]
                warnings.append((
                    f"sid_{sid}",
                    f"Unknown style ID {sid} — treated as body text.  "
                    f"Sample: '{sample}'"
                ))
            resolved.append((seg, "", seg_offset))
        else:
            resolved.append((seg, entry.get("markdown", ""), seg_offset))

    for idx in range(len(resolved) - 1):
        seg_a, role_a, off_a = resolved[idx]
        seg_b, role_b, off_b = resolved[idx + 1]
        if not seg_a or not seg_b:
            continue
        sep_pos = seg_a.rfind(_LINE_SEP)
        if sep_pos < 0:
            stripped_a = seg_a.strip().rstrip('\x00')
            if (1 <= len(stripped_a) <= 3
                    and stripped_a[0].isupper()
                    and seg_b.lstrip('\x00')
                    and seg_b.lstrip('\x00')[0].islower()):
                resolved[idx] = ("", role_a, off_a)
                resolved[idx + 1] = (stripped_a + seg_b, role_b, off_b)
            continue
        trailing = seg_a[sep_pos + 1:]
        trailing_stripped = trailing.strip().rstrip('\x00')
        if not (1 <= len(trailing_stripped) <= 3 and trailing_stripped[0].isupper()):
            continue
        next_start = seg_b.lstrip('\x00')
        if not next_start or not next_start[0].islower():
            continue
        resolved[idx] = (seg_a[:sep_pos + 1], role_a, off_a)
        resolved[idx + 1] = (trailing_stripped + seg_b, role_b, off_b)

    resolved = [(s, r, o) for s, r, o in resolved
                 if s.strip().rstrip('\x00') or _LINE_SEP in s]

    def _neighbour_prefix(idx: int) -> str:
        if 0 <= idx < len(resolved):
            return resolved[idx][1]
        return "NONE"

    def _neighbour_text(idx: int) -> str:
        if 0 <= idx < len(resolved):
            return resolved[idx][0]
        return ""

    def _para_style_at(char_idx: int) -> int:
        for ce, psid in para_runs:
            if char_idx < ce:
                return psid
        return 0

    _list_counter = 0
    _prev_was_numbered = False

    for i, (seg, role, seg_offset) in enumerate(resolved):
        if role == "SKIP":
            if lines and lines[-1] and not lines[-1].endswith(' '):
                lines[-1] += ' '
            continue

        if role == "callout":
            continue

        if role == "superscript":
            clean = seg.strip().rstrip('\x00')
            if clean and lines:
                prev_seg_text = _neighbour_text(i - 1)
                prev_ends_sep = prev_seg_text.endswith(_LINE_SEP)
                prev_is_heading = lines[-1].lstrip().startswith('#')
                if prev_ends_sep or prev_is_heading:
                    _spaced_append(lines, f"<sup>{clean}</sup>")
                else:
                    lines[-1] = lines[-1].rstrip() + f" <sup>{clean}</sup>"
            elif clean:
                lines.append(f"<sup>{clean}</sup>")
            continue

        is_inline_style = role in ("italic", "bold")
        if is_inline_style:
            prev_role = _neighbour_prefix(i - 1)
            prev_seg_text = _neighbour_text(i - 1)
            prev_ends_sep = prev_seg_text.endswith(_LINE_SEP) or prev_seg_text.endswith('\u2029')
            left_hosted = (prev_role in _BODY_PREFIXES and not prev_ends_sep)

            next_role = _neighbour_prefix(i + 1)
            next_seg_text = _neighbour_text(i + 1)
            next_starts_sep = next_seg_text.startswith(_LINE_SEP) or next_seg_text.startswith('\u2029')
            right_hosted = (next_role in _BODY_PREFIXES and not next_starts_sep)

            if not (left_hosted or right_hosted):
                role = ""

        wrapper = ""
        if role == "italic":
            wrapper = "*"
        elif role == "bold":
            wrapper = "**"

        if is_inline_style and wrapper:
            clean = seg.strip().rstrip('\x00')
            if not clean or not _is_content(clean):
                continue

            prev_line = lines[-1] if lines else ""
            prev_stripped = prev_line.rstrip()
            if (clean[0].islower()
                    and prev_stripped
                    and len(prev_stripped) <= 3
                    and not prev_stripped.startswith('#')
                    and not prev_stripped.endswith('  ')):
                lines[-1] = prev_stripped + clean + ' '
                continue

            clean_display = clean.replace(_LINE_SEP, '  \n')
            token = f"{wrapper}{clean_display}{wrapper}"

            if left_hosted and prev_line and not prev_line.endswith('\n'):
                if prev_line[-1] not in (' ', '\n', '(', '"', "'"):
                    lines[-1] = lines[-1] + ' '
                lines[-1] = lines[-1] + token + ' '
            else:
                _p_style = _para_style_at(seg_offset)
                _p_entry = style_map.get(_p_style)
                _p_md = _p_entry.get("markdown", "") if _p_entry else ""
                _p_numbered = (_p_md == "1.")
                _p_bullet = (_p_md == "-")
                if _p_numbered:
                    if not _prev_was_numbered:
                        _list_counter = 0
                    _list_counter += 1
                    _prev_was_numbered = True
                    _spaced_append(lines, f"{_list_counter}. {token} ")
                elif _p_bullet:
                    _prev_was_numbered = False
                    _spaced_append(lines, f"- {token} ")
                else:
                    _prev_was_numbered = False
                    _spaced_append(lines, token + ' ')
            continue

        first_para = True
        is_first_split = True
        _CITE_THRESHOLD = 80
        prev_para_len = 0
        _para_char_offset = seg_offset
        _prev_para_run_id = None
        for raw_para in seg.split(_LINE_SEP):
            had_leading_space = raw_para != raw_para.lstrip()
            para = raw_para.strip().rstrip('\x00')
            if not para or not _is_content(para):
                if (para and lines
                        and any(c in para for c in '.?!\u2026')
                        and not para.startswith('#')):
                    lines[-1] = lines[-1].rstrip() + para
                is_first_split = False
                _para_char_offset += len(raw_para) + 1
                continue

            effective_role = role if (role.startswith('#') and len(para) > 3) else (
                role if not role.startswith('#') else ""
            )

            if (effective_role.startswith('#')
                    and para.startswith('Session')
                    and ':' in para):
                continue

            if (effective_role == ">"
                    and len(para) < _CITE_THRESHOLD
                    and prev_para_len >= _CITE_THRESHOLD):
                effective_role = "<<"

            prev_para_len = len(para)

            _cur_para_style = _para_style_at(_para_char_offset)
            _para_style_entry = style_map.get(_cur_para_style)
            _para_md = (_para_style_entry.get("markdown", "")
                        if _para_style_entry else "")
            _is_numbered = (_para_md == "1.")
            _is_bullet = (_para_md == "-")
            _is_list = _is_numbered or _is_bullet

            if _para_md == "<<" and not effective_role.startswith('#'):
                effective_role = "<<"

            if _is_numbered:
                if not _prev_was_numbered:
                    _list_counter = 0
                _prev_was_numbered = True
            else:
                _prev_was_numbered = False

            _para_char_offset += len(raw_para) + 1

            _PARA_BREAK_THRESHOLD = 80
            if not first_para and lines and not effective_role and not _is_list:
                crossed_boundary = (_prev_para_run_id is not None
                                    and _cur_para_style != _prev_para_run_id)
                prev_content = lines[-1].rstrip()
                long_both = (len(prev_content) > _PARA_BREAK_THRESHOLD
                             and len(para) > _PARA_BREAK_THRESHOLD)
                if crossed_boundary or long_both:
                    _spaced_append(lines, para)
                else:
                    lines[-1] += '  '
                    lines.append(para)
                _prev_para_run_id = _cur_para_style
                first_para = False
                is_first_split = False
                continue

            _prev_para_run_id = _cur_para_style

            prev_line = lines[-1] if lines else ""
            prev_is_heading = prev_line.lstrip().startswith('#')
            prev_has_linebreak = prev_line.endswith('  ')

            mid_word = (prev_line
                        and not prev_line.endswith(' ')
                        and not prev_is_heading
                        and para[0].islower()
                        and not had_leading_space)
            mid_sentence = (prev_line
                            and (prev_line.endswith(' ') or
                                 (not prev_line.endswith(' ') and had_leading_space))
                            and not prev_has_linebreak
                            and not prev_is_heading
                            and para[0].islower()
                            and not effective_role)

            prev_stripped = prev_line.rstrip()
            prev_is_p_italic = (prev_stripped.startswith('*')
                                and not prev_stripped.startswith('**')
                                and prev_stripped.endswith('*')
                                and not prev_stripped.endswith('**'))
            post_inline = (is_first_split
                           and prev_line
                           and (prev_stripped.endswith('**')
                                or (prev_stripped.endswith('*')
                                    and not prev_stripped.endswith('**')))
                           and not prev_is_p_italic
                           and not prev_is_heading
                           and not prev_line.lstrip().startswith('>')
                           and not prev_line.lstrip().startswith('<<')
                           and not effective_role)

            post_superscript = (is_first_split
                                and prev_stripped.endswith('</sup>')
                                and not effective_role)

            colon_join = (para.startswith(':')
                          and prev_line
                          and not prev_is_heading
                          and not prev_has_linebreak
                          and len(prev_line.strip()) <= 40
                          and not effective_role)

            if mid_word or mid_sentence:
                lines[-1] = lines[-1].rstrip() + ('' if mid_word else ' ') + para
            elif colon_join:
                lines[-1] = lines[-1].rstrip() + para
            elif post_inline or post_superscript:
                lines[-1] = lines[-1].rstrip() + ' ' + para
            else:
                if _is_numbered:
                    _list_counter += 1
                    new_line = f"{_list_counter}. {para}"
                elif _is_bullet:
                    new_line = f"- {para}"
                elif effective_role == "p_italic":
                    new_line = f"*{para}*"
                elif effective_role:
                    new_line = f"{effective_role} {para}"
                else:
                    new_line = para
                _spaced_append(lines, new_line)

            first_para = False
            is_first_split = False

    if callout_texts:
        for idx, line in enumerate(lines):
            if not line or line.startswith('#') or line.startswith('>') or line.startswith('<<'):
                continue
            for ct in callout_texts:
                if ct in line:
                    line = line.replace(ct, f"<Callout>{ct}</Callout>", 1)
                elif ct.endswith('.') and ct[:-1] in line:
                    core = ct[:-1]
                    line = line.replace(core, f"<Callout>{core}</Callout>", 1)
            lines[idx] = line

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# --dump-styles mode
# ─────────────────────────────────────────────────────────────────────────────

def _dump_styles(data: bytes) -> None:
    boundaries = _find_spread_boundaries(data)
    id_info: dict[int, dict] = defaultdict(lambda: {"count": 0, "samples": []})

    for sp_start, sp_end in boundaries:
        for _, text, runs, _ in _extract_blocks_in_region(data, sp_start, sp_end):
            prev = 0
            for char_end, style_id in runs:
                seg   = text[prev:char_end]
                prev  = char_end
                clean = (seg.replace(_LINE_SEP, " ")
                            .strip().rstrip('\x00'))
                if clean and _is_content(clean):
                    info = id_info[style_id]
                    info["count"] += 1
                    if len(info["samples"]) < 2:
                        info["samples"].append(clean[:70])

    print(f"\n{'ID':>6}  {'Runs':>5}  Sample text")
    print("\u2500" * 82)
    for sid in sorted(id_info.keys()):
        info   = id_info[sid]
        sample = info["samples"][0] if info["samples"] else "(empty)"
        print(f"{sid:>6}  {info['count']:>5}  {sample}")
    print()
    print(f"Total unique style IDs: {len(id_info)}")
    print(
        "Copy the IDs you care about into styles.yaml "
        "and assign a markdown prefix.\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# --analyze-styles mode
# ─────────────────────────────────────────────────────────────────────────────

def _get_template_style_names(data: bytes) -> list[str]:
    """
    Extract all style names stored in the Affinity template's irtS blocks.
    These are the canonical human-readable names Affinity assigned to each style.
    Returns deduplicated names in document order.
    """
    _IRTS = b'\xab\x69\x72\x74\x53'
    names: list[str] = []
    seen: set[str] = set()
    pos = 0
    while True:
        p = data.find(_IRTS, pos)
        if p == -1:
            break
        try:
            name_len = struct.unpack_from('<I', data, p + 13)[0]
            if 0 < name_len <= 80:
                name = data[p+17:p+17+name_len].decode('utf-8', errors='replace')
                if name.isprintable() and len(name) >= 2 and '\x00' not in name and name not in seen:
                    names.append(name)
                    seen.add(name)
        except Exception:
            pass
        pos = p + 1
    return names


def _auto_resolve_style_ids(data: bytes) -> dict[str, int]:
    """
    Use back-reference correlation to auto-resolve style names to run IDs.
    Each style definition contains xdnI/1metI entries referencing specific
    para-run boundaries in text blocks. By finding the char_run that contains
    the start of the referenced para-run, we identify the style's run ID.
    Returns {name: run_id} for high-confidence matches (>=2 corroborating refs).
    """
    _IRTS = b'\xab\x69\x72\x74\x53'
    _BJSB = b'\xb1sjb'

    style_refs: dict[str, list[tuple[int, int]]] = {}
    pos = 0
    while True:
        p = data.find(_IRTS, pos)
        if p == -1:
            break
        try:
            name_len = struct.unpack_from('<I', data, p + 13)[0]
            if 0 < name_len <= 80:
                name = data[p+17:p+17+name_len].decode('utf-8', errors='replace')
                name_end = p + 17 + name_len
            else:
                pos = p + 1
                continue
        except Exception:
            pos = p + 1
            continue

        bjsb_pos = data.find(_BJSB, name_end, name_end + 10)
        if bjsb_pos == -1:
            pos = p + 1
            continue
        count_pos = bjsb_pos + 5
        try:
            count = struct.unpack_from('<I', data, count_pos)[0]
            if count > 50:
                pos = p + 1
                continue
        except Exception:
            pos = p + 1
            continue

        prop_end = count_pos + 4 + (count * 5)
        refs: list[tuple[int, int]] = []
        scan = prop_end
        max_scan = min(len(data), prop_end + 600)
        while scan < max_scan - 15:
            while scan < max_scan and data[scan] in (0x00, 0x01):
                if scan + 1 < len(data) and data[scan + 1] == 0x78:
                    break
                scan += 1
            if scan + 9 >= max_scan:
                break
            if data[scan] == 0x07 and data[scan+1:scan+5] == b'xdnI':
                char_end = struct.unpack_from('<I', data, scan + 5)[0]
                scan += 9
                if scan + 5 <= len(data) and data[scan:scan+5] == b'1metI':
                    item_type = data[scan + 5]
                    if item_type in (0x01, 0x02):
                        ref_sid = struct.unpack_from('<H', data, scan + 6)[0]
                        refs.append((char_end, ref_sid))
                        scan += 10
                        continue
            break

        if name.isprintable() and len(name) >= 2 and refs:
            style_refs[name] = refs
        pos = p + 1

    bounds = _find_spread_boundaries(data)
    block_info: list[tuple[list, list]] = []
    for sp_start, sp_end in bounds:
        blocks = _extract_blocks_in_region(data, sp_start, sp_end)
        if sum(len(t) for _, t, _, _ in blocks) > 100_000:
            continue
        for _, text, char_runs, para_runs in blocks:
            intervals = []
            prev = 0
            for para_end, para_sid in para_runs:
                intervals.append((prev, para_end, para_sid))
                prev = para_end
            block_info.append((char_runs, intervals))

    resolved: dict[str, int] = {}
    for name, refs in style_refs.items():
        candidates: dict[int, int] = {}
        for target_end, target_sid in refs:
            for char_runs, intervals in block_info:
                for para_start, para_end, para_sid in intervals:
                    if para_end == target_end and para_sid == target_sid:
                        prev_e = 0
                        for char_end, char_sid in char_runs:
                            if prev_e <= para_start <= char_end:
                                candidates[char_sid] = candidates.get(char_sid, 0) + 1
                                break
                            prev_e = char_end
        if candidates:
            best = max(candidates, key=lambda k: candidates[k])
            total = sum(candidates.values())
            if candidates[best] >= 2 and candidates[best] / total >= 0.6:
                resolved[name] = best
    return resolved


def _analyze_styles(
    afpub_path: Path,
    style_map: dict,
    zstd_lib,
) -> None:
    """
    Produce a comprehensive style analysis report optimised for copy-pasting
    to an AI assistant to update styles.yaml for a new book or template.

    Combines --dump-styles and a consistency-check into one unified output:
      1. Canonical style names from the Affinity template binary
      2. All character-style run IDs with sample text and YAML status
      3. All paragraph-style run IDs with sample text and YAML status
      4. YAML entries not seen in this file (possibly stale / different template)
      5. AI instructions for completing the mapping

    Usage:
        python afpub_to_markdown.py --analyze-styles book.afpub
    """
    data = _decompress_afpub(afpub_path, zstd_lib)
    template_names = _get_template_style_names(data)
    auto_resolved  = _auto_resolve_style_ids(data)

    bounds = _find_spread_boundaries(data)
    char_id_info: dict[int, dict] = defaultdict(lambda: {"count": 0, "samples": []})
    para_id_samples: dict[int, list] = defaultdict(list)
    _MASTER_LIMIT = 100_000

    for sp_start, sp_end in bounds:
        blocks = _extract_blocks_in_region(data, sp_start, sp_end)
        if sum(len(t) for _, t, _, _ in blocks) > _MASTER_LIMIT:
            continue
        for _, text, char_runs, para_runs in blocks:
            prev = 0
            for char_end, char_sid in char_runs:
                seg = text[prev:char_end].replace(_LINE_SEP, " ").strip().rstrip('\x00')
                if seg and _is_content(seg):
                    char_id_info[char_sid]["count"] += 1
                    if len(char_id_info[char_sid]["samples"]) < 2:
                        char_id_info[char_sid]["samples"].append(seg[:70])
                prev = char_end
            prev = 0
            for para_end, para_sid in para_runs:
                seg = text[prev:para_end].replace(_LINE_SEP, " ").strip().rstrip('\x00')
                if seg and _is_content(seg) and len(para_id_samples[para_sid]) < 2:
                    para_id_samples[para_sid].append(seg[:70])
                prev = para_end

    all_char_ids      = set(char_id_info.keys())
    all_para_ids      = set(para_id_samples.keys())
    all_seen_ids      = all_char_ids | all_para_ids
    mapped_ids        = set(style_map.keys())
    missing_from_file = mapped_ids - all_seen_ids

    def _yi(sid: int) -> str:
        entry = style_map.get(sid)
        if entry is None:
            return "NOT IN YAML"
        role = entry.get("markdown", "")
        name = entry.get("name", "")
        s = f"role={role!r}"
        if name:
            s += f"  [{name}]"
        return s

    W   = 72
    SEP = "=" * W
    print(SEP)
    print(f"STYLE ANALYSIS: {afpub_path.name}")
    print(SEP)
    print()

    print("## 1. STYLE NAMES IN THIS AFFINITY TEMPLATE")
    print("   Stable human-readable names from the binary.")
    print("   Use these to identify what each numeric run ID represents.")
    print()
    for name in template_names:
        run_id = auto_resolved.get(name)
        if run_id:
            yi   = _yi(run_id)
            flag = "[auto-resolved]"
        else:
            yaml_match = next((sid for sid, e in style_map.items() if e.get("name") == name), None)
            if yaml_match:
                run_id = yaml_match
                yi     = _yi(yaml_match)
                flag   = "[yaml name match]"
            else:
                run_id = None
                yi     = "UNMAPPED"
                flag   = "[needs mapping]"
        id_str = str(run_id) if run_id else "???"
        print(f"  {name!r:<48s}  id={id_str:<6s}  {yi}  {flag}")
    print()

    print("## 2. CHARACTER STYLE RUN IDs")
    print("   Numeric IDs from text run lists, sorted by frequency.")
    print()
    print(f"  {'ID':>5}  {'#':>4}  {'YAML status':<40}  Sample text")
    print("  " + "-" * (W - 2))
    for sid in sorted(char_id_info.keys(), key=lambda x: -char_id_info[x]["count"]):
        info      = char_id_info[sid]
        yi        = _yi(sid)
        sample    = (info["samples"][0] if info["samples"] else "(no text)").replace("\n", " ")
        auto_name = next((n for n, rid in auto_resolved.items() if rid == sid), "")
        name_hint = f" [{auto_name}]" if auto_name else ""
        new_flag  = "  *** NEW ***" if sid not in mapped_ids else ""
        print(f"  {sid:5d}  {info['count']:4d}  {yi:<40s}  {sample[:40]}{name_hint}{new_flag}")
    print()

    print("## 3. PARAGRAPH STYLE RUN IDs")
    print("   Para-level styles. Only '1.' / '-' / '<<' roles are used here.")
    print()
    print(f"  {'ID':>5}  {'YAML status':<40}  Sample text")
    print("  " + "-" * (W - 2))
    for sid in sorted(all_para_ids):
        yi       = _yi(sid)
        sample   = (para_id_samples[sid][0] if para_id_samples[sid] else "(no text)").replace("\n", " ")
        new_flag = "  *** NEW ***" if sid not in mapped_ids else ""
        print(f"  {sid:5d}  {yi:<40s}  {sample[:40]}{new_flag}")
    print()

    if missing_from_file:
        print("## 4. YAML ENTRIES NOT SEEN IN THIS FILE")
        print("   In styles.yaml but absent from this file (stale or different template).")
        print()
        for sid in sorted(missing_from_file):
            print(f"  {sid:5d}  {_yi(sid)}")
        print()

    new_ids = all_seen_ids - mapped_ids
    print("## SUMMARY")
    print(f"  Char run IDs in file:    {len(all_char_ids)}")
    print(f"  Para run IDs in file:    {len(all_para_ids)}")
    print(f"  Already mapped in yaml:  {len(all_seen_ids & mapped_ids)}")
    print(f"  Not yet mapped:          {len(new_ids)}")
    if missing_from_file:
        print(f"  In yaml, not in file:    {len(missing_from_file)}")
    print()

    print("## AI INSTRUCTIONS")
    print("""
Using the sections above, update (or create) styles.yaml for this template.

STEP 1 — Match style names to run IDs:
  Section 1 lists canonical Affinity style names. IDs marked [auto-resolved]
  are confirmed. For others, use Section 2 sample text to make the match.
  Example: 'Main Body Text' -> ID whose sample is body paragraph text.

STEP 2 — Assign markdown roles:

  Character styles (Section 2):
    "#" "##" "###" "####" "#####" "######"  heading levels H1-H6
    ""           plain body text
    ">"          blockquote
    "bold"       inline **bold** (inside body paragraphs)
    "italic"     inline *italic* (inside body paragraphs)
    "p_italic"   full paragraph in italics (sub-section instructions)
    "superscript" <sup>N</sup> verse numbers
    "callout"    pull-quote callout (standalone skipped, text marked inline)
    "SKIP"       omit entirely (nav labels, page numbers, UI chrome)

  Paragraph styles (Section 3):
    "1."   numbered list items
    "-"    bullet list items
    "<<"   right-aligned citation / scripture reference

STEP 3 — Output format:
  Provide complete updated styles.yaml, or diff showing only changed entries.
""")
    print(SEP)


# ─────────────────────────────────────────────────────────────────────────────
# Main conversion
# ─────────────────────────────────────────────────────────────────────────────

def _convert(
    afpub_path: Path,
    output_path: Path,
    style_map: dict,
    fallback: str,
    zstd_lib,
) -> None:
    print(f"  Reading       {afpub_path.name}")
    data = _decompress_afpub(afpub_path, zstd_lib)
    print(f"  Decompressed  {len(data):,} bytes")

    boundaries = _find_spread_boundaries(data)
    print(f"  Found         {len(boundaries)} spreads")

    seen      = _SeenTexts()
    warnings: list[tuple[str, str]] = []
    md_chunks: list[str] = []

    processed_blocks = 0
    skipped_master = 0

    callout_texts: list[str] = []
    for sp_start, sp_end in boundaries:
        all_blocks = _extract_blocks_in_region(data, sp_start, sp_end)
        total_chars = sum(len(t) for _, t, _, _ in all_blocks)
        if total_chars > 100_000:
            continue
        for _, text, runs, _ in all_blocks:
            prev_end_ct = 0
            for ce, sid in runs:
                entry = style_map.get(sid)
                if entry and entry.get("markdown") == "callout":
                    seg = text[prev_end_ct:ce].strip().rstrip('\x00')
                    if seg and len(seg) > 10:
                        callout_texts.append(seg)
                prev_end_ct = ce

    callout_texts = sorted(set(callout_texts), key=len, reverse=True)

    _MASTER_SPREAD_CHAR_LIMIT = 100_000

    for sp_idx, (sp_start, sp_end) in enumerate(boundaries):
        raw_blocks = _extract_blocks_in_region(data, sp_start, sp_end)

        total_chars = sum(len(t) for _, t, _, _ in raw_blocks)
        if total_chars > _MASTER_SPREAD_CHAR_LIMIT:
            skipped_master += 1
            continue

        best_block: dict[str, tuple[int, str, list, list]] = {}
        for offset, text, runs, para_runs in raw_blocks:
            key = text.strip()[:80]
            if not key or not _is_content(key):
                continue
            existing = best_block.get(key)
            if existing is None or len(runs) > len(existing[2]):
                best_block[key] = (offset, text, runs, para_runs)
        unique_in_spread = list(best_block.values())

        sorted_blocks = _sort_spread_blocks(unique_in_spread, style_map)

        for offset, text, runs, para_runs in sorted_blocks:
            if not seen.is_new(text):
                continue

            paras = _block_to_md(text, runs, para_runs, style_map, fallback, warnings, callout_texts)
            if paras:
                md_chunks.extend(paras)
                md_chunks.append("")
                processed_blocks += 1

    final: list[str] = []
    blank_streak = 0
    for line in md_chunks:
        if line == "":
            blank_streak += 1
            if blank_streak == 1:
                final.append("")
        else:
            blank_streak = 0
            final.append(line)

    output_text = "\n".join(final).strip() + "\n"
    output_text = output_text.replace('\u2026', '...')

    output_path.write_text(output_text, encoding="utf-8")

    print(f"  Written       {output_path}  ({len(final)} lines)")
    print(f"  Processed     {processed_blocks} text blocks across {len(boundaries)} spreads")
    if skipped_master:
        print(f"  Skipped       {skipped_master} master/template spread(s)")

    if warnings:
        seen_keys: set[str] = set()
        unique_warns = [
            (k, msg) for k, msg in warnings
            if k not in seen_keys and not seen_keys.add(k)  # type: ignore
        ]
        print(f"\n  {len(unique_warns)} style warning(s):")
        for _, msg in unique_warns:
            print(f"  \u26a0  {msg}")
        print(
            "\n  Run --analyze-styles for a full report, "
            "then update styles.yaml."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    if getattr(sys, 'frozen', False):
        script_dir = Path(sys._MEIPASS)   # type: ignore[attr-defined]
    else:
        script_dir = Path(__file__).resolve().parent
    styles_path = script_dir / "styles.yaml"

    zstd_lib = _load_zstd()
    if zstd_lib is None:
        print("ERROR: libzstd not found.")
        print("  Windows : place zstd.dll alongside the .exe")
        print("            (https://github.com/facebook/zstd/releases)")
        print("  macOS   : brew install zstd")
        print("  Linux   : sudo apt install libzstd1")
        sys.exit(1)

    # --dump-styles / --analyze-styles flags
    dump_mode    = False
    analyze_mode = False
    if args and args[0] == "--dump-styles":
        dump_mode = True
        args = args[1:]
    elif args and args[0] == "--analyze-styles":
        analyze_mode = True
        args = args[1:]

    style_map, fallback = _load_styles_yaml(styles_path)
    print(f"Loaded {len(style_map)} style mappings  (fallback: {fallback!r})")

    explicit_output: Path | None = None
    if not dump_mode and not analyze_mode and len(args) >= 2:
        candidate = Path(args[-1])
        if candidate.suffix.lower() == ".md":
            explicit_output = candidate
            args = args[:-1]

    input_paths: list[Path] = []
    for arg in args:
        matches = glob.glob(arg)
        if matches:
            input_paths.extend(Path(m) for m in sorted(matches))
        else:
            input_paths.append(Path(arg))

    if not input_paths:
        print("ERROR: No input files found.")
        sys.exit(1)

    for i, afpub_path in enumerate(input_paths):
        print(f"\n[{i+1}/{len(input_paths)}] {afpub_path}")

        if not afpub_path.exists():
            print("  SKIP — file not found")
            continue
        if afpub_path.suffix.lower() != ".afpub":
            print("  SKIP — not an .afpub file")
            continue

        try:
            if dump_mode:
                data = _decompress_afpub(afpub_path, zstd_lib)
                _dump_styles(data)
            elif analyze_mode:
                _analyze_styles(afpub_path, style_map, zstd_lib)
            else:
                output_path = (explicit_output
                               if explicit_output is not None
                               else afpub_path.with_suffix(".md"))
                _convert(afpub_path, output_path, style_map, fallback, zstd_lib)

        except Exception as exc:
            print(f"  ERROR: {exc}")
            import traceback
            traceback.print_exc()

    print("\nDone.")


if __name__ == "__main__":
    main()
