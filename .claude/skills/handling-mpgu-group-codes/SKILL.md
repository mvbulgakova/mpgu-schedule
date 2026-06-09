---
name: handling-mpgu-group-codes
description: Use when reading, validating, normalising, or deduplicating MPGU group codes (e.g. ВОП40-ПФК2501) — covers homoglyphs, the canonical code regex, the digit↔letter confusion, and per-column majority voting against VLM misreads.
---

# Handling MPGU Group Codes

## Overview

A code looks like `БОИ34-ИОВ2503`: `[2-3 letters][2 digits]-[2-4 letters][4
digits]`, sometimes with a trailing human label (`(103) п/г 2`).

**Core principle:** the code is the identity. Normalise it consistently and
dedupe on the canonical form, but never invent or "fix" a code into a different
group.

## Homoglyphs are real on MPGU sources

MPGU codes genuinely contain Latin look-alikes (`БVИ34`, `ЗZФ34`, `БOЭ63` with
Latin O). Two distinct problems:

1. **Letter↔letter (Latin in a Cyrillic slot):** handled by `fix_homoglyphs`
   in `scraper/normalizer/schedule_normalizer.py`. Apply it before matching.
2. **Digit↔Cyrillic-letter inside the numeric slots** (VLM misreads `3→З`,
   `0→О`, `4→Ч`): e.g. `БВПЗ9-ПДЛ2509` should be `БВП39`. Fix ONLY the numeric
   positions — never the letter prefix (`БОП40` must not become `Б0П40`). See
   `_CODE_TOLERANT_RE` / `_code` in `surya_column_parser.py`.
3. **Space before the year** on language-faculty scans (`ММК 2501`): allow an
   optional space in the regex and strip it.

## Canonical key for dedup

```python
CODE = re.compile(r'[А-ЯA-Z]{2,3}\s?\d{2}-?[А-ЯA-Z]{2,4}\s?\d{4}')
key = lambda n: re.sub(r'[\s-]', '', CODE.search(fix_homoglyphs(n)).group(0))
```

Dedupe groups on this key. Merge schedules of same-key groups (do not drop the
human label — `(103) п/г 2` distinguishes subgroups that share a code prefix).

## Majority voting (Surya pipeline)

A scanned column read once can misread the code. The same column position holds
the same group across all pages of a file, so collect every per-position read
and take the **most common** valid code. This is what turned 20 noisy pedagogy
reads into 40 stable groups. Position-based voting beats code-based grouping
because a single misread otherwise spawns a phantom group.

## Anti-patterns

- **Dropping a group because its code didn't match the strict regex.** First
  try the tolerant path (homoglyph + digit + space). Only then discard.
- **Trusting a single VLM read.** Without voting, `РЯЦ2401` and `РЯЦ2301` can
  both collapse to one misread, or a neighbouring institute's code can leak in
  (the recurring `ВОП40-ПФК2501` contaminant). Verify against the source.
- **"Correcting" `БVИ34` to `БИИ34`.** The V is on the real schedule. Keep it.
