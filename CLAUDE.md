# mpgu-schedule — agent guide

## Skills first

This repo uses a skills library under `.claude/skills/` (in the style of, and
partly vendored from, [obra/superpowers](https://github.com/obra/superpowers)).

**Before any non-trivial work, check whether a skill applies and invoke it.**
If there is even a ~1% chance a skill fits what you are doing, use it.

Two families:

- **General engineering discipline** (vendored from superpowers, MIT — see
  `.claude/skills/_vendor/ATTRIBUTION.md`): `brainstorming`, `writing-plans`,
  `executing-plans`, `test-driven-development`, `systematic-debugging`,
  `verification-before-completion`, `requesting-code-review`,
  `subagent-driven-development`, `using-git-worktrees`,
  `finishing-a-development-branch`, and the `using-superpowers` bootstrap.
  Start a conversation by following `using-superpowers`.

- **This project's schedule-parsing methodology** (original):
  - `parsing-mpgu-schedules` — entry point; routes to the rest.
  - `choosing-a-schedule-parser` — deterministic first, Surya only for scans.
  - `handling-mpgu-group-codes` — homoglyphs, code regex, majority voting.
  - `verifying-schedule-completeness` — source audit before claiming done.
  - `safe-schedule-data-merges` — additive-no-loss vs replace.
  - `publishing-schedule-data` — data branch, index sync, commit/push.

  For ANY task touching `institutes/*` schedule data, start with
  `parsing-mpgu-schedules`.

- **Maintaining the skills library itself:** `maintaining-project-skills`
  (house style, project-vs-vendored split, the gitignore tracking gotcha,
  turning a session lesson into a skill). Use it whenever you add or edit a
  skill here.

## Project shape

- **Scraper / parsers:** `scraper/parsers/` (`pdf_parser`, `excel_parser`,
  `gsheets_parser`, `surya_column_parser`), normaliser in
  `scraper/normalizer/`, storage in `scraper/storage/git_storage.py`,
  VLM reparse driver `scraper/reparse_vision.py` (`--surya`).
- **Data:** the `data` branch (worktree at `.data-wt/`) holds
  `institutes/<id>/groups/*.json`, `institutes/<id>/schedule.json`, and
  `meta/index.json`. Code/config changes go on the feature branch; data
  changes go on `data`.
- **App:** `app/` is the Android client that consumes the `data` branch.
- **CI branches are split, and it is not obvious.** The repo's default branch
  is `claude/migrate-mpgu-schedule-jj5gV`, not `main`. GitHub takes the
  *workflow file* (its `cron`, `timeout-minutes`, `workflow_dispatch` inputs)
  from the default branch, while each job checks out `ref: main` for the code
  it runs. So a change under `scraper/` takes effect as soon as it is on
  `main`, but a change under `.github/workflows/` does nothing until it is
  also pushed to the default branch — silently, with green-looking runs on
  the old definition. Check both when a workflow change seems to have no
  effect.

## Non-negotiables

- Clean, code-named groups; **no data loss**. A garbled code is worse than a
  missing group.
- Never trust a group count — diff parsed-unique against current data and
  explain every LOSE/GAIN before publishing (`verifying-schedule-completeness`).
- Keep `meta/index.json` counts equal to the actual files on disk.
- **Investigating a row means dumping the WHOLE row, every column, before
  reasoning about it** — never a hand-picked subset of fields you think
  matter. Print the header and the cells together and check they line up: on
  epk25 the competitive-list header is two `<TR>`s with `ROWSPAN=2` and a
  `COLSPAN=3` over «Количество баллов за каждое ВИ», so a naive
  `zip(headers, cells)` silently shifts everything right of it (14 headers vs
  16 cells) and you end up reading ИД as ПП. Verify with an arithmetic check
  the row must satisfy (ВИ1+ВИ2+ВИ3 = «Сумма баллов за ВИ»; + ИД = «Сумма
  конкурсных баллов»). Columns the parser ignores still matter to a
  diagnosis: ОВП, ПП and the two trailing unnamed columns exist and are only
  ever visible if you dump everything.
