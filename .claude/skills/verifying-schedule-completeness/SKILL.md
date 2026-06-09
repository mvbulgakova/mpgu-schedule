---
name: verifying-schedule-completeness
description: Use before claiming an MPGU institute is complete or before publishing parsed groups — audits every source file for zero-yield gaps and diffs parsed-unique codes against the current data branch (LOSE/GAIN). Counts alone never prove completeness.
---

# Verifying Schedule Completeness

## Overview

**Core principle:** the group count cannot prove completeness. Several
institutes (history 56, physics 16, geography 21, social 26) looked plausible
and were all missing groups. Only a source-vs-data diff is honest.

## The audit (run BEFORE writing/publishing)

For the institute, parse every source and compute:

1. **Per-file yield.** Any file returning **0 groups** is a flag:
   - junk (задолженности / ликвидация / адаптационный / график) → ignore;
   - otherwise a **missed scan or hard format with real groups** — this is
     exactly how physics lost its заочка/магистратура (`ЗZФ34-ФТО2401`) and how
     languages hides 31 scan files behind one parsable PDF. Run such files
     through the Surya pipeline.
2. **Unique parsed codes vs current data**, deduped on the canonical key
   (see `handling-mpgu-group-codes`):
   - **LOSE** (in data, not in sources): investigate each. Stale cohort removed
     from the site? Or a download/parse failure this run? Do not delete data to
     match a worse parse.
   - **GAIN** (in sources, not in data): candidate additions — but verify each
     has real lesson content before trusting it.

## Verify content, not just the name

Geography's "+10" included misreads with year `2101→2001` and only 4 lessons
each. The names looked new; the schedules exposed them. Always spot-check
lesson counts and a few subjects/teachers of GAIN groups before adding.

## Evidence to produce

State, per institute: `parsed_unique=N data=M | GAIN=[...] LOSE=[...]`, plus the
list of zero-yield files with TEXT/SCAN classification. Only then claim a
verdict (complete / missing X / needs Surya).

## Anti-patterns

- Declaring "complete" from the index number.
- Treating a 0-group file as "nothing there" without checking text vs scan.
- Replacing data wholesale with a fresh parse that has unexplained LOSEs.
