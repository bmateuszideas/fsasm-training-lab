---
name: fsasm-vibe-coding
description: Use for explicitly authorized FS-ASM repository coding, review, debugging and task-scoped handoffs; follow the approved runtime v1 architecture and verified Git status.
user-invocable: true
---

# FS-ASM Vibe Code Web — development process

This is a **process skill for the external Vibe coding agent**. It is NOT the FS-ASM runtime, its local Executor, an implementation request, a new architecture, or an approval mechanism. The project source of truth is stored in GitHub because the Vibe Web chat cannot receive user-uploaded files directly into its sandbox.

## Mandatory entry order

1. Read the root `AGENTS.md` and the **entire** `fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`, including sections XIX–XX. This is the ONLY approved architecture. Its SHA-256 must match `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`. Do not use `CURRENT_FSASM_MODEL.md` or this skill as substitutes.
2. Read `fsasm-first/docs/DEPLOYMENT_DECISIONS.md` for subsequent user-approved hybrid/Mistral data-sharing decisions; these supplement the original without changing it.
3. Read `fsasm-first/PROJECT_STATUS.md`, `fsasm-first/docs/DOCUMENTATION_MAP.md` and `fsasm-first/docs/BRANCH_POLICY.md`. Verify actual `Fsasm-experimental` HEAD, PRs and CI live, because dated reports can be stale.
4. Read the user's explicitly approved atomic task, relevant code/tests and `references/fsasm-implementation.md`. For actual Mistral Workflows SDK changes, read `fsasm-first/.agents/skills/workflows/SKILL.md` and targeted reference pages before editing. Run commands from `fsasm-first/`.

If the canonical document is missing or the hash differs, stop architecture changes and report it. Never fabricate a reconstruction from earlier conversation text. `CURRENT_DEVELOPMENT_ANCHOR.md` and `IMPLEMENTATION_SUMMARY.md` are historical references; they are not live startup instructions.

## Optional targeted references

- `references/fsasm-implementation.md`: runtime/domain invariants and migration boundaries.
- `references/large-code-planning.md`: multi-file changes within an approved scope.
- `references/systematic-debugging.md`: reproduce an observed issue.
- `references/code-review.md`: repository-grounded self-review; not independent approval.
- `references/session-handoff.md`: task-specific handoff at context boundary.

Choose only what the task requires. Do not dump every historical conversation or skill reference into model context.

## Coding conduct

When a task is explicitly approved: inspect exact baseline and required contracts; write a short plan; change ONLY the bounded task; inspect diff; run targeted tests and, for runtime modifications where appropriate, full `uv run pytest`, `make check` and `git diff --check`; document actual results and known limits. Fix ordinary failures within the approved task without repeated permission prompts. Keep runtime data out of Git and tests in isolated temporary workspaces. Do not claim real-model success from scripted fixtures.

Develop from current `Fsasm-experimental` on a short task branch, PR back to that integration line, and await external review/approval for merge. Do not update `main`, delete branches, force-push, close M4, launch M5/LLMC, or silently extend architecture. PR #20 is merged as of 17 September but G3–G5 and M4 closure remain separate. Later Git may supersede this sentence; check it.

The approved profile is hybrid Workflows: worker/workspace/local ~7B on the user's laptop, cloud orchestrator permitted. The user accepts clear-text workflow data and telemetry to Mistral. Do not impose encryption/telemetry shutdown as a new privacy gate, but do protect API credentials and executable tool permissions. Real local model integration happens **only after** the complete stub-tested runtime is moved to the laptop; Vibe Web cannot access that local model.

A coding PR is `IMPLEMENTED — READY FOR EXTERNAL REVIEW` only after the stated checks; a green test or model declaration cannot mark a milestone CLOSED. Report SHA, changed paths, tests with their limitations and the next unresolved decision. Stop at the task boundary.
