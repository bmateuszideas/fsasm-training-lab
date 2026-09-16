# FS-ASM repository agent entry protocol

This root file only governs how to locate and verify context; the actual implementation contract is [`fsasm-first/AGENTS.md`](fsasm-first/AGENTS.md).

## Before any coding or branch operation

1. Read [`fsasm-first/PROJECT_STATUS.md`](fsasm-first/PROJECT_STATUS.md), then verify the actual remote branch, HEAD SHA, Git changes, PR state and CI. A dated snapshot may be stale.
2. Read [`fsasm-first/docs/BRANCH_POLICY.md`](fsasm-first/docs/BRANCH_POLICY.md) and [`fsasm-first/docs/DOCUMENTATION_MAP.md`](fsasm-first/docs/DOCUMENTATION_MAP.md).
3. For FS-ASM architecture read [`fsasm-first/docs/CURRENT_FSASM_MODEL.md`](fsasm-first/docs/CURRENT_FSASM_MODEL.md), then `fsasm-first/AGENTS.md` for stable rules. Its instructions to *begin with M1* are the original bootstrap and superseded by the verified milestone states in PROJECT_STATUS.
4. Only inspect code and tests relevant to the explicitly approved, atomic task. The long `CURRENT_DEVELOPMENT_ANCHOR.md` preserves historic paused-state/LLMC instructions and is NOT the current command source.
5. Do not start M5, adopt LLMC, merge `main`, touch frozen branches, delete branches or rewrite history as a consequence of 'cleanup'. Each requires explicit authorization and a separate reviewed change.
6. Every progress/closure claim must reference the changed commit, merged PR and actual test evidence. If you reach a context limit, leave a concise persisted handoff: branch/base SHA, atomic task, changes, tests and next action. A previous model summary is not authoritative.

Current repo working directory for runtime: `fsasm-first/`. Prefer a short-lived task branch from the latest `Fsasm-experimental` and a PR back to that branch. Never silently resolve discrepancies between docs and actual code; record and escalate them.
