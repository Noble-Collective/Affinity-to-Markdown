# .afpub Binary Converter (Archived)

This was the Phase 1 approach: parsing Affinity Publisher's `.afpub` binary format directly.

**Status:** Abandoned in favor of the PDF-based pipeline (`marker-pdf/`).

**Why it was abandoned:** Affinity's `.afpub` format is proprietary and undocumented. While reverse-engineering worked for a single test file, the format varies between Affinity versions and document complexity. The PDF-based approach is more reliable since PDFs are a stable, well-documented format.

## Files

- `afpub_to_markdown.py` — The main extractor (~1800 lines). Decompresses zstd payload, parses spread boundaries, extracts text blocks with character/paragraph run lists, converts to Markdown.
- `styles.yaml` — Style ID → Markdown role mapping for the HomeStead book.

## How it worked

```
.afpub file → zstd decompress → find spreads → extract text blocks
→ parse char/para run lists → resolve styles → Markdown output
```

See `AFPUB_EXTRACTOR_README.md` in the project's Claude context files for the full technical reference.
