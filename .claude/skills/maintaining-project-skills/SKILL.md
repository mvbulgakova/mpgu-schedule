---
name: maintaining-project-skills
description: Use when adding, editing, or organising skills in THIS repo's .claude/skills/ — the house style for project skills, the project-vs-vendored split, the gitignore tracking requirement, turning a session lesson into a skill, and updating the vendored superpowers copy.
---

# Maintaining Project Skills

## Overview

This repo carries its own skills library under `.claude/skills/`. This skill is
the project-specific complement to the vendored `writing-skills` — that one
teaches the generic RED-GREEN-REFACTOR method for authoring a skill; THIS one
captures how we organise, name, ground, and ship skills here.

**Core principle:** a project skill earns its place by encoding a judgement
call we got wrong at least once. If it's mechanical (regex-enforceable) it
belongs in code; if it's a one-off, it belongs in a commit message, not a skill.

**REQUIRED BACKGROUND:** read `writing-skills` for the TDD-of-documentation
method before authoring anything non-trivial.

## Two families — keep them separate

- **Vendored (general engineering):** copied from obra/superpowers, MIT.
  Attribution and the update procedure live in `.claude/skills/_vendor/`.
  **Do not edit vendored skills in place** — local edits are lost on the next
  re-vendor and silently fork upstream. If you need different behaviour, write
  a new project skill that overrides/extends it.
- **Project (ours):** schedule/parsing skills, named for the domain
  (`*-mpgu-*`, `*-schedule-*`) so they're obvious in the list. These are the
  ones we maintain.

## House style for a project SKILL.md

Match the existing ones (`parsing-mpgu-schedules`, `handling-mpgu-group-codes`,
…). Every project skill has:

1. **Frontmatter** — `name` (kebab-case, == directory) and a `description` that
   starts "Use when …" and names concrete triggers. The description is the only
   thing the agent sees when deciding to invoke; make it match real situations.
2. **Overview + one bolded Core principle.**
3. **A procedure or decision** (numbered / table / decision tree).
4. **Anti-patterns grounded in real incidents.** Cite the actual failure: "the
   count looked fine but physics had lost its заочка", "geography +10 were
   misreads with 4 lessons each", "the overwrite bug deleted 56 history files".
   A rule without the scar that produced it gets rationalised away.

Keep it tight — these are reference cards, not narratives. Link sibling skills
by name rather than repeating their content.

## Turning a session lesson into a skill

1. Identify the judgement call and the failure that taught it.
2. Check it isn't already covered by an existing skill — extend that one
   instead of adding a near-duplicate.
3. If it's domain methodology, route it from `parsing-mpgu-schedules` (the entry
   skill) so it's discoverable in the pipeline.
4. Write the rule AND the anti-pattern with the concrete incident.
5. Verify (below), commit on the feature/code branch (never the `data` branch).

## The tracking gotcha (do not skip)

`.claude/` is gitignored except `.claude/skills/`. A skill that isn't committed
**will not load in fresh Claude Code web containers** — the whole point is lost.
After adding files, confirm they're tracked:

```
git check-ignore .claude/skills/<name>/SKILL.md   # must print nothing
git ls-files .claude/skills/<name>                # must list the file
```

`settings.local.json` stays ignored on purpose.

## Updating the vendored superpowers

Re-clone `obra/superpowers`, re-copy its `skills/` into `.claude/skills/`,
refresh `.claude/skills/_vendor/ATTRIBUTION.md`. Don't merge our project skills
into theirs and don't carry local edits across.

## Verify before shipping

- Frontmatter parses (`---`, `name`, `description`); `name` == directory.
- The skill appears in the loaded skills list with the intended description.
- For behaviour-changing skills, follow `writing-skills`: run a subagent against
  the pressure scenario without the skill (RED), then with it (GREEN).

## Anti-patterns

- Editing a vendored superpowers skill in place.
- A `description` that's a title ("Group codes") instead of triggers
  ("Use when reading/validating/deduping group codes …").
- A skill that's a story ("how I fixed pedagogy") rather than a reusable rule.
- Adding the file but forgetting it's gitignored, so it never loads on web.
