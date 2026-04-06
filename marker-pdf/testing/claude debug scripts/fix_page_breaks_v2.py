"""
REPLACE the entire fix_page_breaks function in run.py with this version.
Find: def fix_page_breaks(md):
Replace everything up to (but not including): def fix_pullquote_fragments(md):
"""

def fix_page_breaks(md):
    """Rejoin text split mid-sentence at PDF page/column boundaries.
    Rule: if a body text line does not end with sentence-ending punctuation,
    the sentence is unfinished and the next body text line is its continuation.
    Handles both blank-line gaps and direct newline breaks."""
    lines = md.splitlines(); out = []; i = 0
    _STRUCT = ('#', '>', '<<', '-', '|', '![', '*', '<Callout', '<sup')
    _END_PUNCT = set('.!?:;\'"*)]' + '\u201d')
    while i < len(lines):
        line = lines[i]
        s = line.rstrip()
        if (s and len(s) > 40
                and not any(s.startswith(p) for p in _STRUCT)
                and s[-1] not in _END_PUNCT):
            j = i + 1
            # Skip one blank line if present
            if j < len(lines) and not lines[j].strip(): j += 1
            # Join with next body text line
            if j < len(lines):
                cont = lines[j].lstrip()
                if cont and not any(cont.startswith(p) for p in _STRUCT):
                    out.append(s + ' ' + cont)
                    i = j + 1; continue
        out.append(line); i += 1
    return '\n'.join(out)
