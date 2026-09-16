# Large Code Planning & Chunking

Use for large codebases, multi-file changes, refactors, or tasks likely to consume substantial context.

## Principles

- Plan before editing.
- Search before reading.
- Read enough to understand authoritative contracts and dependency boundaries.
- Break work into verifiable phases.
- Maintain a compact progress checkpoint.
- Verify each phase.
- Keep the repository syntactically valid.
- Continue autonomously when an approved brief already exists.

## Reconnaissance

Start with low-cost repository inspection:

```bash
pwd
git status --short
find . -maxdepth 2 -type f | sort | head -200
```

Locate relevant symbols and behavior with `rg`, `grep`, `find`, or equivalent tools before opening unrelated files.

Read the full file when it is an authoritative contract and partial reading risks misunderstanding it. Do not use file size alone as the criterion.

Inspect project commands in `pyproject.toml`, `Makefile`, `package.json`, or equivalent files.

## Written plan

Use a compact plan:

```markdown
## Task
[objective]

### Scope
- create:
- modify:
- delete:

### Phases
1. [phase] — [files] — [verification]
2. [phase] — [files] — [verification]

### Risks
- ...

### Out of scope
- ...
```

If the user requested planning only, stop after the plan.

If implementation was requested and an approved brief/acceptance criteria already exist, do not stop for routine plan approval.

## Chunked execution

For each phase:

1. read only what is needed
2. make precise edits
3. run focused verification
4. inspect the diff
5. update the progress checkpoint
6. continue while acceptance criteria remain unmet

Use bulk replacement only for demonstrably mechanical transformations, and inspect the resulting diff.

## Context management

After each meaningful phase, retain:

- what changed
- why
- tests run
- failures
- important invariants
- next action

Use Git state rather than repeatedly reconstructing work from memory.

When the session becomes long, switch to the handoff procedure before context becomes unreliable.

## Final verification

Before completion:

1. run the requested/full test suite
2. run required lint/type/format checks
3. run `git diff --check` when appropriate
4. review diff/stat
5. verify claimed tests/files actually exist
6. check acceptance criteria against repository state
