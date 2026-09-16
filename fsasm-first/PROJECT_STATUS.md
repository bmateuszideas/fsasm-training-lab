# FS-ASM — CURRENT PROJECT STATUS

**Snapshot date:** 2026-09-16. **Baseline verified:** `Fsasm-experimental` at `603fc607439b44e46b26d8c3a2114b34ba7c458c`. **This is a dated snapshot, not a promise that the branch HEAD never changes.** On entry, check the actual branch, HEAD, Git diff, PRs and CI before trusting any version-specific claim.

## Active decisions (as of this snapshot)

- Active integration branch: `Fsasm-experimental` (capital F). Implement changes on a short-lived task branch from its current HEAD; submit PR targeting `Fsasm-experimental`; do not push straight to `main` or merge branches automatically.
- `main` is the default branch but an older, diverged integration containing the LLMC benchmark. Do not treat it as the latest runtime. A later explicit release/integration decision is needed to bring the stabilized runtime to `main`.
- `Fsasm-llmc-testingbranch` is a frozen research baseline. LLMC is deferred, not a dependency, not adopted or rejected on the existing benchmark; no new LLMC work is authorized in this cycle.
- M1 CLOSED; M2 CLOSED; M3 CLOSED; M4 IMPLEMENTED, STABILIZATION OPEN — **not CLOSED**. M5 NOT STARTED and must not start until M4 has explicit approval.
- M4 normal test baseline: GitHub Actions for `603fc607` succeeded with **299 passed, 3 skipped, 0 failed**; Ruff, mypy and workflow lint jobs passed. This is evidence for tested scenarios, not proof of crash recovery or real coding.
- Only one ChildTask is executed in M4; Executor is a deterministic STUB. Do not describe the project as an autonomous coding agent or call a synthetic stub claim an independent execution proof.

## Open engineering queue (one atomic task and one PR at a time)

| Item | Scope | State |
| --- | --- | --- |
| S0 | Standard worker activity-name collision | DONE, merged PR #7 |
| F2 | Retry `state.json` / `plan.json` normal-path consistency | DONE, merged PR #8; NOT multi-file transactionality |
| S2 | Initial PLANNED persistence/log ordering | DONE, merged PR #9 |
| S1 | Repeated RETRY_ONCE audit evidence ID uniqueness | DONE, merged PR #10 (narrow F6 subset) |
| CI-01 | CI checkout actual SHA and Ruff tests | DONE, merged PR #12 |
| S3 | Human Gate audit before/after payload | DONE, merged PR #13 at baseline SHA |
| S4 | Stale M4 documentation/comments | OPEN |
| F3 | Crash-consistent multi-file state snapshot/recovery | OPEN |
| F4 | Reuse of run_id and explicit create vs resume | OPEN |
| F5 | Safe identifiers in filesystem paths | OPEN |
| F6/F7 | Complete evidence/gate identity and duplicate/stale human signal semantics | OPEN beyond S1 |
| F8 | Finalizer validates matching run/task, internal verification checks and evidence before PASS | OPEN |

These are known issues/risks from the 2026-09-16 audits, not proof that all reproducers have been run in the current session. Verify the current code and design a focused regression before marking any item DONE. Do not replace the backlog with newly invented milestone work.

## NEXT ACTION

**Documentation and branch governance only in PR `docs/context-source-of-truth-20260916`:** create clear entry points, hierarchy and branch policy; preserve history. This work is not an M4 stabilization fix and must not mark M4 closed. After review/merge, select exactly one outstanding M4 issue and implement with a focused regression. Do not begin M5, add LLMC, modify runtime behavior, or delete historical material as a side effect of documentation cleanup.

## Read order for an agent with zero chat context

1. Read repository `README.md` then this `PROJECT_STATUS.md` **first**; verify Git branch/HEAD and whether the snapshot is stale.
2. Read `docs/CURRENT_FSASM_MODEL.md` for long-term architectural intent, and `AGENTS.md` for invariant engineering rules. Its M1 bootstrap and "begin with M1" instructions describe the original historical start and **do not override the completed milestone status in this file**.
3. Read `docs/DOCUMENTATION_MAP.md` for the location, purpose and authority of every documentation category and `docs/BRANCH_POLICY.md` for branch rules.
4. Inspect actual implementation and relevant tests only for the selected atomic task. If documents conflict with code, record the discrepancy; do not silently change project decisions.
5. Consult `CURRENT_DEVELOPMENT_ANCHOR.md` as a **historical running record with mixed dated sections**, not an undated current command. Sections about a paused run at `c47f356`, pending S3 PR, or initiating LLMC are superseded by this dated snapshot and the actual merged history.
6. Before stopping, update this file's snapshot baseline and queue in the same PR as an actual status-changing task, linking the PR and exact verification. Avoid repeatedly editing long historical narratives.

## Facts, proposals, and verification

Do not confuse a proposal in a review, a reported local test, and a confirmed merged commit. Use the actual code, merged PR and check run as evidence for DONE. Do not assert that a task is DONE on a draft/unmerged branch. If the branch has moved after this snapshot, refresh it before changing code.

## Preservation

Historical materials in `stare dokumenty rozwojowe fsasm/` stay intact. LLMC benchmark artifacts remain research records on `main`; no automated merge or file removal. Previous anchor versions are preserved in Git history (baseline permalink: https://github.com/bmateuszideas/fsasm-training-lab/blob/603fc607439b44e46b26d8c3a2114b34ba7c458c/fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md). Never rely on chat history as the only source for an approved decision.
