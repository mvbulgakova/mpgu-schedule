---
name: safe-schedule-data-merges
description: Use when writing parsed groups into the data branch for an MPGU institute — chooses additive-no-loss merge (default) vs full replace (only for garbage-named institutes), and guards against the wholesale-overwrite bug that deletes existing groups.
---

# Safe Schedule Data Merges

## Overview

**Core principle:** never lose an existing good group. Default to additive merge
keyed on the canonical code; replace only when the existing data is garbage and
cannot be joined on.

## Two modes

### Additive (default — history, math, social, geography, physics)

1. Load existing `institutes/<id>/groups/*.json`, key each on the canonical code.
2. Add only parsed groups whose key is NOT already present.
3. Existing groups stay byte-for-byte untouched.

This guaranteed history 56→62, math 22→33, social 26→53, geography 21→31,
physics 16→19 with **zero losses**.

### Replace (only when existing names are garbage)

Use when the current data has no usable codes to merge on — e.g. pedagogy had
"304 ГРУППА", "I, II, III, IV курсы"; preschool had 2 stale groups. Then:

1. Confirm the new set is a SUPERSET of (or strictly better than) the old —
   check the old groups' codes appear in the new set, so replacement loses
   nothing real.
2. Delete old group files, write the new set.

## Hard guard: the overwrite bug

A merge helper that deletes files for groups "not in the new set" will silently
wipe the institute if the new keying is wrong (this happened — 56 history files
deleted, only 53 written back, caught by checking file count after). Therefore:

- After writing, **assert the file count** equals `len(existing-kept) + len(added)`
  (additive) or `len(new)` (replace). If it dropped, restore (`git checkout --`)
  and find the keying bug.
- Re-key with the SAME canonical function used for the diff, including
  homoglyph normalisation — a mismatched key collapses distinct groups.

## form / degree

Derive per source: filenames (`ochno-zaochnoe`/`zfo`/`mag`) via
`infer_form_degree`, or from the code letters when filenames are opaque
(nextcloud IDs): 1st letter М→master, С→specialist, else bachelor; 2nd letter
О→full_time, З→correspondence, В→part_time, У→part_time. Prefer filename when
descriptive.

## Anti-patterns

- Merge-by-code that uses a different/looser key than the audit diff.
- Replacing 52 imperfect-but-present groups with 20 cleaner ones without first
  confirming the 20 don't drop real cohorts.
