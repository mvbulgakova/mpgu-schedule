---
name: publishing-schedule-data
description: Use when committing parsed MPGU groups to the data branch — writes group files via GitStorage, keeps meta/index.json counts in sync with actual files, and follows the commit/push conventions for the data worktree.
---

# Publishing Schedule Data

## Overview

The data lives on the `data` branch, checked out as a worktree at `.data-wt/`.
Group JSON, the per-institute manifest, and `meta/index.json` must stay
consistent.

**Core principle:** what ships must be internally consistent — file count ==
manifest groups == index `groups_count`. A stale index misreports the result.

## Write procedure

1. Use `GitStorage(ROOT)` (`scraper/storage/git_storage.py`) — `read_schedule`
   / `write_schedule` handle the manifest + per-group files. Preserve manifest
   fields other than `groups`; bump `updated_at`.
2. Run `sanitize_groups` (homoglyphs, drop-empties) on the final list before
   writing.
3. **Sync `meta/index.json`:** set each touched institute's `groups_count` to
   the ACTUAL file count (`glob institutes/<id>/groups/*.json`), bump
   `generated_at`. Don't hand-maintain counts — read them from disk.
4. Drop any group with 0 lessons.

## Commit / push conventions

- Work in `.data-wt/` (the `data` branch worktree); code/config changes go on
  the feature branch instead.
- Commit message: `data(<institute>): <what changed and why>` with the
  before→after count and "existing untouched" / "replaced N" note.
- Push: `git push origin data`, retry on network error with backoff (2s/4s/8s/16s).
- Verify after: `git status` clean, file count matches the index.

## Self-check before declaring done

```
files = glob(institutes/<id>/groups/*.json)
assert len(files) == index[<id>].groups_count == len(manifest.groups)
```

State the before→after counts and that working tree is clean + pushed.

## Anti-patterns

- Editing `groups_count` by hand or leaving it stale (biology said 35, had 34).
- Committing data changes onto the feature/code branch (keep `data` separate).
- Claiming "pushed" without confirming HEAD == origin/data.
