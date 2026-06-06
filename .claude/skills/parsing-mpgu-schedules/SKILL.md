---
name: parsing-mpgu-schedules
description: Use when extracting, reparsing, fixing, or auditing MPGU schedule data for any institute (the institutes/* JSON in the data branch) — routes to the parser-choice, group-code, safe-merge, completeness and publishing skills. Invoke at the start of any schedule-data task.
---

# Parsing MPGU Schedules

## Overview

MPGU publishes per-institute timetables in wildly inconsistent formats: text
PDFs, scanned PDFs (no text layer), Excel, Google Sheets, and nextcloud links.
The data lives as one JSON per group under `institutes/<id>/groups/` on the
`data` branch, with a manifest `institutes/<id>/schedule.json` and a roll-up
`meta/index.json`.

**Core principle:** clean, code-named groups with no data loss. A wrong or
garbled group code is worse than a missing group. Counts can look fine while
hiding missing scans/заочка/магистратура — never trust the count alone.

## The pipeline (always in this order)

1. **Enumerate sources** for the institute (PDF / xlsx / gsheets / nextcloud).
2. **Choose a parser** → invoke `choosing-a-schedule-parser`. Deterministic
   first; Surya column pipeline only for scans / character-interleaved tables.
3. **Normalise group codes** → invoke `handling-mpgu-group-codes` (homoglyphs,
   the code regex, majority-vote across pages).
4. **Verify completeness** → invoke `verifying-schedule-completeness` BEFORE
   writing. Compare parsed-unique vs current data; explain every LOSE and GAIN.
5. **Merge safely** → invoke `safe-schedule-data-merges` (additive-no-loss by
   default; replace only for garbage-named institutes).
6. **Publish** → invoke `publishing-schedule-data` (write groups, sync
   `meta/index.json`, commit + push to `data`).

## Hard rules

- **Never push a count without diffing against current data first.** Run the
  parsed-vs-data comparison and read out LOSE / GAIN. Investigate every LOSE.
- **Verify lesson counts, not just names.** Geography looked "+10" but several
  were misreads with 4 lessons each — only checking content caught it.
- **A file that yields 0 groups is a signal, not a no-op.** It is either junk
  (задолженности/ликвидация/график) or a missed scan/hard-format with real
  groups (this is how physics silently lost its заочка + магистратура).
- Homoglyph letters in codes (Latin V/O/Z, digit↔Cyrillic 3↔З 0↔О) are real on
  MPGU sources — handle them, do not "correct" them away blindly.

## Anti-pattern: "the count looks reasonable, ship it"

Counts hide gaps. history (56), physics (16), geography (21), social (26) all
looked plausible and all were incomplete. The only honest completeness check is
the source audit in `verifying-schedule-completeness`.
