# Session Handoff

Use when a coding session approaches context limits, must stop, or a fresh agent will continue work. Enable continuation **without chat history** while avoiding a second global project-status document.

## Before handoff

1. Stop at a safe boundary; never intentionally leave syntax-broken committed files.
2. Run the smallest relevant verification and record real results.
3. Inspect `git status --short`, `git diff --stat`, current branch and HEAD.
4. Determine which work is committed, pushed or only present in the current sandbox.
5. Check the current task PR and `fsasm-first/PROJECT_STATUS.md` independently.

## Persist in the right place

Prefer the repository-defined task handoff location when one exists. Otherwise put a concise handoff **in the task PR description/comment or a task-branch-local `HANDOFF.md`**. Do not commit an evergreen root `HANDOFF.md` to `Fsasm-experimental`, append a new 'current stop point' to the historical anchor, or overwrite `PROJECT_STATUS.md` with temporary session notes. If writing a handoff file, commit/push it on the task branch when safe; an unpushed sandbox file will disappear after Vibe Code Web deprovisions the session.

Use this compact record:

```markdown
# Task handoff

## Objective and acceptance criteria

## Git and PR state
- integration branch and base SHA:
- task branch and HEAD SHA:
- PR URL/status:
- working tree:
- pushed commits:
- uncommitted files (NOT durable):

## Verified completed work
- files / behavior:

## Tests and evidence
- command, exact result and environment:
- actual CI link and status (or pending/not run):

## Current failure or blocker
- reproduction / first wrong value:
- observed vs hypothesized root cause:

## Remaining work (ordered)
1. ...

## Files and invariants that matter
- path: reason

## Do not redo / out of scope
- ...
```

Only include verified facts as facts; mark uncertain findings as hypotheses. Never claim a push, test, fix, merge or persisted state without checking it.

## New session

Read root `AGENTS.md`, the canonical `PROJECT_STATUS.md` and branch policy; inspect Git/PR/CI; read the handoff and verify its critical claims. Resume the **first remaining approved action** instead of re-planning the project or selecting another issue. If the handoff conflicts with current repo state, report the discrepancy before editing.
