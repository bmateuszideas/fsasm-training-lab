---
name: fsasm-vibe-coding
description: Use for substantial coding work in Vibe Code Web, especially FS-ASM milestones, multi-file changes, workflow/state-machine debugging, durable handoffs, and repository-grounded review.
user-invocable: true
---

# FS-ASM Vibe Coding

A single reusable **coding-process skill** for planning large changes, systematic debugging, durable session handoff, repository-grounded review and FS-ASM-specific implementation. This skill is NOT the FS-ASM runtime, the current task specification, a second status document, an approval mechanism or a replacement for the existing Mistral Workflows SDK skill.

## Repository contracts and current state come first

The repository is `bmateuszideas/fsasm-training-lab`; the active integration branch is currently named `Fsasm-experimental`. Check the actual repository and branch rather than trusting a cached SHA or historical snapshot. Source and test claims must be verified at the working commit.

Before any implementation or branch operation, read in order:

1. Repository root `AGENTS.md` (context-entry and authorization rules).
2. `fsasm-first/PROJECT_STATUS.md` (the **only current project-status entry point**); cross-check its dated claims against live Git, merged PRs, source and CI.
3. `fsasm-first/docs/BRANCH_POLICY.md` and `fsasm-first/docs/DOCUMENTATION_MAP.md`.
4. `fsasm-first/AGENTS.md` and the relevant parts of `fsasm-first/docs/CURRENT_FSASM_MODEL.md`.
5. The user's actual atomic task, acceptance criteria, relevant source and tests.
6. For Mistral Workflows implementation, the existing SDK guide: `fsasm-first/.agents/skills/workflows/SKILL.md`, plus its targeted references.

Run project commands from `fsasm-first/`. `CURRENT_DEVELOPMENT_ANCHOR.md` is a **historical** running record and its old LLMC-pause/next-action instructions are superseded. `IMPLEMENTATION_SUMMARY.md` is implementation history, not live status. Never silently resolve a conflict between current status, explicit authorization, code and tests; report it.

**Skill scope does not grant task authorization.** Do not select or implement a new backlog issue, merge/close a PR or milestone, start M5, reactivate LLMC, synchronize `main`, delete branches, or alter GitHub settings merely because this skill mentions the workflow. Explicit user instructions and repository contracts take precedence over generic advice here.

## Choose focused references (progressive disclosure)

- Large or multi-file change: `references/large-code-planning.md`.
- Failing test, broken workflow, regression or unexpected state: `references/systematic-debugging.md`.
- Approaching context/session end: `references/session-handoff.md`.
- Separate review of a commit/PR/milestone: `references/code-review.md`.
- Any FS-ASM implementation or repair: **also** `references/fsasm-implementation.md`.

For a multi-file FS-ASM task, normally read the FS-ASM implementation reference, then large-code planning; debugging and handoff are conditional. A self-review is not independent external review.

## Default implementation behavior

When the user has explicitly requested implementation with approved scope or acceptance criteria:

1. Inspect Git state and read the authoritative contracts.
2. Inspect only relevant code/tests and write a concise plan.
3. Implement a single bounded task, verify meaningful phases and inspect diffs.
4. Fix routine implementation/test failures autonomously without repeatedly asking whether to continue.
5. Stop only for a genuinely blocking ambiguity, missing authorization or unsafe operation that cannot be resolved from the task/contracts.
6. Run the verification appropriate to the actual scope. For runtime tasks use required focused tests, full pytest, `make check` and `git diff --check` unless the task contract says otherwise. For documentation-only work, validate paths, Markdown/references/diff and use applicable CI; do not claim tests were run if they were not.
7. Do not begin the next task or claim DONE merely because a model says work is finished.

## Repository truth beats agent memory

Verify important claims against actual files, Git history/diff, tests, persisted runtime artifacts and current documentation. Previous summaries and handoffs are leads, not authoritative truth. Never invent test results, commits, CI state or observed behavior.

## Editing and Git safety

Prefer precise edits, check diffs after bulk operations, never intentionally commit syntax-broken files, and preserve unrelated completed work. Check `git status --short`, `git diff --stat` and `git diff` before delivery. Start a short-lived task branch from the current `Fsasm-experimental` HEAD and target an atomic PR there when the user authorizes a change. Do not push broken intermediate states. Follow `BRANCH_POLICY.md`; do not merge your own implementation PR unless separately authorized.

## Completion and handoff

For an FS-ASM implementation PR, report `IMPLEMENTED — READY FOR EXTERNAL REVIEW`, with commit SHA, changed files, tests and actual CI status. This phrase is **not** approval to merge or to mark an issue/milestone CLOSED. For skill/documentation work, report the actual PR state without using implementation-completion claims.

Before a session ends or context degrades, persist a task-specific, factual handoff on its branch/PR and push it when needed. Do not create a competing global project-status file; after a new session starts, re-verify the handoff against Git. See `references/session-handoff.md`.
