# FS-ASM — CURRENT PROJECT STATUS

**Snapshot date:** 2026-09-16. **Verified pre-update integration baseline:** `Fsasm-experimental` @ `6e43b852ab4de6eb8856e04fddda1fdd10c3f987`. This is a dated snapshot; a status-only PR and later work will move the branch. On every new session, check actual branch/HEAD, current refs, open PRs and CI before trusting version-specific claims.

## What is authoritative

This is the **single current project-status entry point**. Long-term intent: [`docs/CURRENT_FSASM_MODEL.md`](docs/CURRENT_FSASM_MODEL.md). Stable implementation constraints: [`AGENTS.md`](AGENTS.md). Document roles and precedence: [`docs/DOCUMENTATION_MAP.md`](docs/DOCUMENTATION_MAP.md). Branch rules: [`docs/BRANCH_POLICY.md`](docs/BRANCH_POLICY.md). Implementation and test claims require source, merged PRs and CI at an identified SHA. [`CURRENT_DEVELOPMENT_ANCHOR.md`](CURRENT_DEVELOPMENT_ANCHOR.md) preserves dated history with superseded instructions; do **not** execute its old LLMC-pause, old next-action or pending-S3 text as current direction.

## Verified branch and documentation state (2026-09-16)

| Branch | Observed SHA | Role |
| --- | --- | --- |
| `Fsasm-experimental` | `6e43b852ab4de6eb8856e04fddda1fdd10c3f987` | Active integration and source for short-lived task branches. This was HEAD before the present status-only update. |
| `main` | `a9f8ab6640acfda21c31675a03ba53d094f2909f` | GitHub default, older divergent runtime and LLMC benchmark; no implicit merge or reset. |
| `__noop_check__` | `30a6e56935b7238b471f7f21365c21679693de20` | Legacy technical branch; removal requires a separate ancestry/reference check and explicit approval. |

The three branches above were the persistent refs verified before creating this temporary documentation PR. A short-lived `docs/*` ref may additionally exist while its PR is open. Deleted branches: `Fsasm-llmc-testingbranch`, `vibe/f2-retry-state-consistency-b6d6c2`, `vibe/worker-activity-name-collision-b6d6c2`; do not describe them as present/frozen refs. Removing those branch names did **not** delete the LLMC benchmark on `main` or Git history. Check actual GitHub refs rather than treating this dated table as live inventory.

**Documentation governance:** PR [#14](https://github.com/bmateuszideas/fsasm-training-lab/pull/14) was merged into `Fsasm-experimental` at `e6a3bd3e9cd6174246218dc92e6787f68e3fd12f`. It established root `AGENTS.md`, refreshed both READMEs, and added this status file, the documentation map and branch policy. The subsequent commit `6e43b852ab4de6eb8856e04fddda1fdd10c3f987` synchronized branch policy with the reduced branch list. **These actions are DONE; the PR #14 documentation task is no longer NEXT.**

**Verification:** GitHub Actions [run 35122809983](https://github.com/bmateuszideas/fsasm-training-lab/actions/runs/35122809983) completed successfully for `6e43b852ab4de6eb8856e04fddda1fdd10c3f987`. The previously verified M4 baseline at `603fc607439b44e46b26d8c3a2114b34ba7c458c` reported **299 passed, 3 skipped, 0 failed** with Ruff, mypy and workflow lint passing. PR #14 and the branch-policy update changed documentation only; do not claim that the historical test count independently proves crash recovery or a real coding executor. Check the new PR's own CI before merging it.

## Approved direction and actual capability

- M1 **CLOSED**; M2 **CLOSED**; M3 **CLOSED**.
- M4 **IMPLEMENTED; STABILIZATION OPEN — NOT CLOSED**. Its bounded retry and durable Human Gate scenarios have worker-level tests, but outstanding contracts are listed below.
- M5 **NOT STARTED**. Do not start it without completion/review of M4 and explicit user authorization.
- LLMC **DEFERRED**: research material persists on `main`, but no adoption, integration or new benchmark is authorized in this work cycle. Its recorded benchmark has methodological limitations; it is not proof of a runtime Context Builder.
- Current M4 executes **one ChildTask** (possibly with retries); its Executor is a deterministic **STUB**. PASS here validates tested control-flow scenarios, not autonomous programming or independently verified code changes.
- Runtime work uses a new short-lived task branch based on the **current** `Fsasm-experimental` HEAD, with a focused PR targeting `Fsasm-experimental`. Do not modify `main`, merge divergent branches, or delete history as part of M4 work.

## M4 stabilization queue — one atomic issue per PR

| Item | Meaning | Verified status |
| --- | --- | --- |
| S0 | Standard-worker activity-name collisions | DONE — merged PR #7 |
| F2 | Normal-path retry consistency of `state.json` / `plan.json` | DONE — merged PR #8; **not** F3 transactionality |
| S2 | Initial PLANNED persistence / log ordering | DONE — merged PR #9 |
| S1 | Distinct audit IDs for repeated RETRY_ONCE | DONE — merged PR #10; only a narrow part of F6 |
| CI-01 | Check correct PR SHA and lint test code | DONE — merged PR #12 |
| S3 | Human Gate audit before/after values | DONE — merged PR #13 |
| DOC-01 | Context-entry documents and branch cleanup inventory | DONE — merged PR #14 and follow-up branch-policy commit `6e43b85`; this status refresh is a separate documentation-only PR |
| S4 | Stale M4 comments/docstrings | OPEN |
| F3 | Crash-consistent multi-file state snapshot and recovery | OPEN |
| F4 | Explicit run creation vs reuse/resumption of `run_id` | OPEN |
| F5 | Safe identifiers in filesystem paths | OPEN |
| F6/F7 | Remaining evidence/gate identity, stale/duplicate/multiple human signal semantics | OPEN beyond S1 |
| F8 | Finalizer checks authoritative run/task, verification checks and evidence before PASS | OPEN |

The open items are documented issues/risks from the 2026-09-16 reviews, **not** proof that each reproducer was rerun in the present session. Validate a selected issue against current source and tests before editing; do not silently close one from a model summary.

## NEXT ACTION — current work authorization

1. **Finish this one-file status-only PR**: review its diff, confirm CI for its exact HEAD, then merge into `Fsasm-experimental`. No runtime/test modifications; do not treat it as an M4 fix.
2. **After that merge**, select **one** outstanding M4 stabilization item with a bounded reproducer and acceptance criteria, then seek/record explicit authorization for that implementation. **F8 (finalizer contract)** is a proposed next candidate because an audit describes a false-PASS boundary, but selection and its fix are **not approved or implemented by this documentation update**. F3/F4/F5/F6/F7/S4 remain open regardless.
3. Do not begin M5 or reactivate LLMC. Do not automatically merge `main` and `Fsasm-experimental`, or remove `__noop_check__`.

## Fresh-agent entry and handoff

1. Read repository root `README.md` and this file; verify HEAD/branch/PRs/CI immediately. If this snapshot is stale, distinguish the documented historical baseline from current source.
2. Read `docs/CURRENT_FSASM_MODEL.md` for goal, `AGENTS.md` for stable rules, `docs/DOCUMENTATION_MAP.md` for precedence, and `docs/BRANCH_POLICY.md` for branch procedure. Original M1 bootstrap wording in `AGENTS.md` is historical where superseded by verified milestones and approved current scope.
3. Inspect **only** code and tests relevant to the selected atomic issue. Treat reviews and old chat summaries as leads, not executable instructions. Report rather than silently reconcile discrepancies.
4. Record base SHA, precise change, targeted/full tests, CI link and outstanding problems in the task PR. Update this short status page on status-changing PRs; do not append another competing 'current stop point' to the old anchor.

## Preservation

Historical documents in `stare dokumenty rozwojowe fsasm/` remain intact. The LLMC benchmark is on `main`; the removed LLMC branch name is not an active ref. The original anchor remains in Git history (e.g. [baseline snapshot](https://github.com/bmateuszideas/fsasm-training-lab/blob/603fc607439b44e46b26d8c3a2114b34ba7c458c/fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md)). A model's previous conversation must never be the only record of project state or a decision.
