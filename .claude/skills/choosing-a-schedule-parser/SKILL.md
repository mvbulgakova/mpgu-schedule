---
name: choosing-a-schedule-parser
description: Use when deciding how to extract groups from an MPGU source file (PDF/xlsx/gsheets/nextcloud) — picks deterministic parsing vs the Surya column pipeline, and explains the page-segmentation and merged-cell traps.
---

# Choosing a Schedule Parser

## Overview

**Core principle:** deterministic parsing first (exact, fast, free); the Surya
column pipeline (render → table-rec → per-column VLM → majority vote) only when
there is no usable text layer or the table cells are unrecoverable.

## Decision

1. Open the PDF. Does page 1 have an extractable text layer (>~60 chars)?
   - **Yes, and `pdfplumber` tables come out clean** → `PDFParser`
     (`scraper/parsers/pdf_parser.py`). Deterministic. Done.
   - **Yes, but cells are character-interleaved** (e.g. `ИнДоосцт.р Н`, narrow
     overlapping subgroup columns — preschool) → text is useless for tables.
     Use the **Surya column pipeline** (treat like a scan).
   - **No text layer** (scanned image) → **Surya column pipeline**
     (`scraper/parsers/surya_column_parser.py`, or
     `reparse_vision.py --surya`).
2. `.xlsx`/`.xls` → `ExcelParser`. Always handles merged cells (see below).
3. Google Sheets → CSV export per book; each MPGU gsheets link is a SEPARATE
   book, not tabs of one — process every link.
4. nextcloud `oc.mpgu.su/s/<id>` → resolve to the underlying PDF, then apply the
   rules above (most are scans → Surya).

## Deterministic traps (already fixed — keep them working)

- **Page = course.** Many PDFs put "1 курс"/"2 курс" on separate pages with
  their OWN group codes. The parser segments on tables that carry their own
  codes; continuation pages (no codes) attach to the current segment. Do not
  regress this — it is why math 22→33 and social got their senior cohorts.
- **Excel merged cells.** Group headers / days / time-slots live in merged
  cells; the value sits only in the top-left. `_rows_with_merged` spills it
  across the range. Without it lessons lose their group/day binding.
- **Header layouts.** `_find_mpgu_header` knows день-in-col-B, col-C, and the
  ОЗФО/ЗФО день-in-col-A layout. When the header row holds course descriptions
  ("1 курс (1 группа)") instead of codes, the real codes are one row down.

## When Surya is WORSE — do not use it

- Files with a clean text layer: Surya only loses fidelity and is slow.
- Institutes where the deterministic parse already matches the source
  (verified) — e.g. digital: Surya dropped the master groups and leaked a
  pedagogy code. **Compare before replacing; keep the better source.**

## Anti-pattern: reaching for the VLM first

The VLM/Surya path is the fallback, not the default. It is slow (CPU table-rec
+ many VLM calls), it can hallucinate or leak codes across columns, and it needs
majority voting to be trustworthy. Exhaust deterministic parsing first.
