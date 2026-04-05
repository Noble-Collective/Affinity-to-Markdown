# PDF-to-Markdown Converter — Context for New Conversations

## Who You're Working With

Steve (GitHub: steve-lundy) is building a document conversion pipeline for Noble Collective — converting Affinity Publisher book PDFs to Markdown. The project is for a book called *HomeStead* (a Christian parenting rite of passage curriculum). The team is small with mixed technical ability. Steve prefers Claude to handle as much as possible directly (pushing to GitHub, editing files, running tests) rather than acting as a manual go-between.

**Steve's philosophy:** Rule-based over content-specific. All conversion logic in `run.py` must be generic — driven by font properties (weight, size ratio, position), never by specific text content. Content-specific entries belong only in `templates/<book>/pdf_config.yaml`. The system must work for many books, not just HomeStead.

---

## Repository & Local Setup

**Repo:** `Noble-Collective/Affinity-to-Markdown` on GitHub, `main` branch
**Local:** `C:\Users\Steve\Affinity-to-Markdown` (Steve uses Git Bash on Windows)
**Working dir for git commands:** `~/Affinity-to-Markdown/marker-pdf` (not repo root)
**Python:** 3.11 venv at `marker-pdf\venv311` (activate: `source venv311/Scripts/activate`)
**Run command:** `python run.py "path/to/raw.md" "path/to/book.pdf" --postprocess`

**Key files:**
- `marker-pdf/run.py` (~75KB, ~1300 lines, 50 functions) — ALL conversion logic
- `marker-pdf/templates/homestead/pdf_config.yaml` (~200 lines) — book-specific config
- `marker-pdf/README.md` (~32KB) — comprehensive architecture documentation
- `marker-pdf/testing/claude debug scripts/extract_pdf_data.py` — extracts PyMuPDF data to JSON for offline testing

---

## MCP Tools Available

- **filesystem:** Read/write/edit files directly on Steve's Windows machine at `C:\Users\Steve\Affinity-to-Markdown\`
- **github:** Push/pull/create files on `Noble-Collective/Affinity-to-Markdown`

---

## How the Pipeline Works

Two-layer pipeline: Marker (ML) does initial PDF-to-Markdown extraction, then 35 post-processing passes correct its mistakes using font data from PyMuPDF.

```
PDF -> [1] PyMuPDF font scan -> [2] Marker ML -> raw.md -> [3] 35 post-processing passes -> output.md
```

### Layer 1: PyMuPDF Font Scan (9 build_* functions)
Scans the PDF and builds lookup data structures:
- `heading_map`: {normalized_text: [level, ...]} from font ratio rules
- `heading_order`: [(text, level), ...] in document order
- `skip_set`: running headers, page numbers, decorative text
- `bq_set` / `cit_set`: blockquote/citation text (small font, <=0.88x body)
- `verse_map`: hymn verse text with proper line breaks
- `callout_texts`: pull-quote text from callout font signature (~1.6x body, regular weight)
- `inline_bold`: [(phrase, context_line), ...] bold phrases with PDF line context
- `verse_sup`: small bold text for verse number superscripts
- `right_aligned_map`: short right-aligned body-size text (citations)
- `rotated_subdivisions`: rotated sidebar heading labels

### Layer 2: Marker ML
Layout detection (surya model), text extraction (pdftext), paragraph joining, list detection, blockquote detection. Produces raw.md.

### Layer 3: Post-Processing (35 passes in strict order)
Font-data-driven corrections applied by `post_process()`. Order matters — several passes have critical ordering dependencies (documented below).

---

## Critical Ordering Dependencies

These were learned the hard way through regressions:

1. **fix_page_breaks runs ONLY after fix_callouts** — running before merges standalone callout text into body paragraphs, breaking Phase 1 callout removal
2. **Callout punctuation (moving `.` inside `</Callout>`) runs AFTER fix_page_breaks** — lines ending `.</Callout>` end with `>` not `.`, which fix_page_breaks doesn't recognize as sentence punctuation. Running before caused 40+ paragraph merges.
3. **fix_callouts runs AFTER fix_heading_hierarchy** — heading rearrangement changes line positions
4. **H6+body split (Phase 2c) is a post-pass in fix_heading_hierarchy** — lines enter as H5, get shifted to H6, so the H6-to-bold branch never sees them

---

## Key Design Decisions & Learnings

### Font data is the source of truth
The heading_map from PyMuPDF determines what IS a heading. Marker's heading assignments are corrected or overridden by this data. No content matching for heading detection.

### Page breaks follow punctuation rules
In well-edited body text, every paragraph ends with sentence-ending punctuation (`.!?:;*)]'`). Any body text line NOT ending with punctuation is an unfinished sentence split at a page boundary. Zero false positives across ~4,600 lines.

### Smart quote-ending
Quote characters (`"`, `'`, right double quote) only count as sentence-ending if preceded by `.!?'`. Prevents false matches on lines ending mid-sentence with quoted text like `"I will dwell in the house of the Lord forever"`.

### Context-aware inline bold
`build_inline_bold_set` returns `[(phrase, context_line), ...]` where context_line is the full PDF line text. `fix_inline_bold` requires non-trivial context words to match in the target line before applying bold. This prevents false positives: "Church" only bolds in `**Church**: How much of a priority...` not in `Sabbath Rest and Church Fellowship`. Backward compatible with old `List[str]` format.

### The converter is a QA tool
Truncated text in output often comes from the PDF source, not a converter bug. The pipeline surfaces Affinity Publisher layout issues.

---

## Workflow for Editing run.py

**IMPORTANT — follow this strictly:**

1. **Make changes and test in Claude's container first** — run the full pipeline, verify output, regression check
2. **For small changes** (a few lines, no regex special chars): apply via `filesystem:edit_file` directly to Steve's local file
3. **For changes containing regex special chars** (`$`, `*`, `\`): export the file via `present_files` for Steve to download — `filesystem:edit_file` mangles these characters, causing duplication/corruption
4. **Steve pushes to GitHub** from local git — `github:push_files` truncates files over ~60KB; never use it for run.py
5. **Never use `filesystem:write_file` for large files** — rewrites entire file, very slow

**Git workflow:**
- Claude pushes small files (README, config) directly via GitHub MCP
- Steve pushes run.py from local: `git add run.py && git commit -m "message" && git push`
- After Claude pushes to GitHub, Steve must `git pull --rebase` before pushing
- When Claude pushes while Steve has uncommitted changes, Steve runs `git checkout -- <file>` before `git pull --rebase`
- Provide simple one-line git commands for easy pasting into Git Bash
- Avoid `!` and `?` in commit messages (Git Bash interprets them) — use single quotes

---

## Diagnosing Output Issues (Enforced Workflow)

When Steve reports something wrong in the output:

1. Check raw Marker output (is the problem in Marker's extraction?)
2. Check PyMuPDF font/position data (what does the font scan say?)
3. Trace through pipeline passes (which pass introduced/missed the issue?)
4. Identify root cause
5. Design rule-level fix based on PDF properties (font, size, ratio, position)
6. **Get explicit approval before any text-specific fix**

---

## Offline Testing in Claude's Container

The container doesn't have PyMuPDF/fitz, but Steve uploads:
- **Raw Marker output:** `testing/raw.md`
- **PDF font data JSON:** `testing/pdf_data.json` (generated by `extract_pdf_data.py`)

**Offline harness:** `run_offline.py` loads the JSON, constructs all the data structures, and calls `post_process()`. Run with: `cd /home/claude/marker-pdf && python3 run_offline.py`

**IMPORTANT:** The JSON must be regenerated after changes to any `build_*` function. Steve runs: `python "testing/claude debug scripts/extract_pdf_data.py" "testing/<pdf_file>.pdf"`

---

## Current Output Stats (v58, latest known-good)

```
Lines:        4591      H1:      5      H2:     17      H3:     40
H4:            116      H5:    373      H6:    119
Blockquotes:   141      Citations: 192  Bullets: 222    Numbered: 251
Callouts:       50      Superscripts: 174
Bold instances: 464     Tables:   90
```

---

## Post-Processing Pipeline (35 passes, strict order)

```
 1. Image/rule strip
 2. fix_pullquote_fragments
 3. fix_headings (remap using heading_map)
 4. fix_verse_labels
 5. fix_double_blockquote_citations
 6. fix_blockquotes (bq_set -> >, cit_set -> <<, right_aligned -> <<)
 7. Decorative pull-quote removal (> *...text"*)
 8. fix_blockquote_continuations
 9. fix_citations
10. fix_bullet_numbers
11. fix_hyphenation
12. fix_empty_tables
13. fix_toc_tables
14. fix_final_review_table
15. fix_inline_bold (context-aware)
16. fix_junk_content
17. fix_artwork_images
18. fix_missing_headings
19. fix_dedup_headings
20. fix_heading_fragments
21. fix_missing_section_headings
22. fix_discussion_question_groups
23. fix_structural_labels
24. fix_bold_bullets
25. Citation bold strip
26. fix_front_matter
27. fix_heading_hierarchy (4-phase: sessions, level shifts, subdivisions, cleanup)
28. fix_callouts (Phase 1: remove standalone, Phase 2: tag inline)
29. Callout adjacency merge
30. fix_page_breaks (punctuation rule, smart quote-ending)
31. Callout punctuation (move . inside </Callout>)
32. Verse superscript conversion
33. Bold verse spacing
34. Table bullet fix
35. Triple-blank collapse
```

---

## pdf_config.yaml Structure (Homestead)

```yaml
body_font: auto
headings: [6 ratio-based rules mapping weight+ratio to level 1-5]
skip_large_ratio: 2.4
running_header_signature: [2 rules]
quote_max_ratio: 0.88
citation_max_chars: 80
verse_label_signature: [2 rules]
callout_signature: [1 rule, regular weight, 1.55-1.65x]
citation_patterns: [2 regexes for "Book N:N" format]
discussion_question_labels: [3 H5 headings inserted before question groups]
discussion_heading_pattern: "Discussion Questions"
skip_line_patterns: [3 regexes for decorative labels]
skip_table_markers: ["SEARCHING"]
table_to_list: [1 entry converting Final Review table]
front_matter_corrections: { ends_before, remove_lines, text_replacements }
heading_hierarchy:
  front_matter_label, parts[3], session_map[17], trailing_section,
  subdivision_labels[3], rotated_subdivision_labels[18],
  subdivision_overrides[2], heading_text_fixes[1], remove_artifact_headings[1]
```

---

## What's Been Done (Session History)

### Phase 1: Foundation (March 2026)
- Template system, ratio-based headings, --save-raw/--postprocess modes
- Verse extraction, discussion question groups, structural label cleanup
- Marker bug patches, Gemini LLM integration

### Phase 2: Font-driven post-processing (Early April 2026)
- build_heading_map with heading_order for missing heading detection
- build_callout_set + fix_callouts (two-pass inline tagging)
- build_inline_bold_set + fix_inline_bold
- Empty table removal, bold bullet fix, multi-level heading map

### Phase 3: Page breaks & heading hierarchy (Mid April 2026)
- fix_page_breaks (punctuation-termination rule)
- fix_heading_hierarchy (4-phase: sessions, level shifts, subdivisions, cleanup)
- fix_blockquote_continuations, decorative pull-quote removal
- H6+body split, fix_front_matter, fix_toc_tables, fix_artwork_images
- build_rotated_subdivisions, build_verse_superscript_set, build_right_aligned_citations

### Phase 4: Context-aware bold & polish (Late April 2026)
- Context-aware build_inline_bold_set returning [(phrase, context_line), ...]
- Smart quote-ending in fix_page_breaks
- Callout punctuation inside tags (ordering lesson: must run after fix_page_breaks)
- Table bullet fix

---

## On the Horizon

- Full book validation — systematic comparison of all sessions
- Deploy to Cloud Run — update app.py/converter.py for new pipeline
- OCR evaluation — test image-rendered instruction blocks
- Auto-generate question tags for the Noble Imprint app

---

## Homestead Book Font Map

Body text: `TimesNewRomanPSMT @ 10pt`

| Ratio | Weight  | Role |
|-------|---------|------|
| 2.0   | regular | H1 (session title) |
| 2.0   | bold    | H3 (movement title) |
| 1.4   | italic  | H2 (subtitle) |
| 1.4   | bold    | H4 (section heading) |
| 1.8   | bold    | H4 (Next Steps) |
| 1.2   | bold    | H5 (song title, subsection) |
| 1.0   | regular | Body text |
| 0.8   | regular | Blockquote / citation |
| 1.6   | regular | Callout (pull-quote) |
| 0.95  | bold    | Running header (SKIP) |
| 0.7   | bold    | Verse superscript |

---

## How to Start a Session

1. **Read the README** on GitHub: `marker-pdf/README.md` has full architecture docs
2. **Read this context document** for workflow, learnings, and current state
3. **Ask Steve** what he wants to work on
4. **If editing run.py:** Follow the enforced workflow (test in container first, small edits via filesystem:edit_file, regex edits via file export)
5. **If diagnosing an issue:** Follow the enforced diagnostic workflow (raw -> font data -> pipeline trace -> root cause -> rule-level fix)
