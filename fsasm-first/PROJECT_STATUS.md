# FS-ASM — CURRENT PROJECT STATUS

**Snapshot date:** 2026-09-16. **Verified integration baseline before documentation PRs:** `Fsasm-experimental` @ `6e43b852ab4de6eb8856e04fddda1fdd10c3f987`. A dated SHA is a historical reference, not a claim of live HEAD. On every session verify branch, HEAD, refs, PRs and CI before relying on version-specific information.

## What is authoritative

This is the **single current project-status entry point**. Long-term intent: [`docs/CURRENT_FSASM_MODEL.md`](docs/CURRENT_FSASM_MODEL.md). Stable implementation constraints: [`AGENTS.md`](AGENTS.md). Document roles and precedence: [`docs/DOCUMENTATION_MAP.md`](docs/DOCUMENTATION_MAP.md). Branch rules: [`docs/BRANCH_POLICY.md`](docs/BRANCH_POLICY.md). Implementation and test claims require source, merged PRs and CI at an identified SHA. [`CURRENT_DEVELOPMENT_ANCHOR.md`](CURRENT_DEVELOPMENT_ANCHOR.md) preserves dated history with superseded instructions; do **not** execute its old LLMC-pause, old next-action or pending-S3 text as current direction.

## Verified branch and documentation state (2026-09-16)

| Branch | Observed SHA before documentation refresh | Role |
| --- | --- | --- |
| `Fsasm-experimental` | `6e43b852ab4de6eb8856e04fddda1fdd10c3f987` | Active integration and source for short-lived task branches. Later docs PRs move HEAD; re-check it. |
| `main` | `a9f8ab6640acfda21c31675a03ba53d094f2909f` | GitHub default, older divergent runtime and LLMC benchmark; no implicit merge or reset. |
| `__noop_check__` | `30a6e56935b7238b471f7f21365c21679693de20` | Legacy technical branch; removal requires a separate ancestry/reference check and explicit approval. |

These were the three persistent refs after user cleanup and before temporary documentation PRs. A short-lived `docs/*` ref may appear while its PR is open; check the live branch inventory instead of treating this table as a live API. Deleted refs: `Fsasm-llmc-testingbranch`, `vibe/f2-retry-state-consistency-b6d6c2` and `vibe/worker-activity-name-collision-b6d6c2`. Do not describe these deleted branches as currently frozen/present. Their removal did not delete the LLMC benchmark on `main` or Git history.

**Documentation governance:** PR [#14](https://github.com/bmateuszideas/fsasm-training-lab/pull/14) merged at `e6a3bd3e9cd6174246218dc92e6787f68e3fd12f`, establishing root `AGENTS.md`, both updated READMEs, this status file, documentation map and branch policy. Commit `6e43b852ab4de6eb8856e04fddda1fdd10c3f987` synchronized branch policy with the reduced branch list. PR [#15](https://github.com/bmateuszideas/fsasm-training-lab/pull/15) merged the subsequent status refresh at `aadcd4651451395937dddd49cafb7f3a69f27611`. **Documentation and branch-inventory cleanup are completed; neither PR is a future task.**

**Verification:** [CI run 35122809983](https://github.com/bmateuszideas/fsasm-training-lab/actions/runs/35122809983) completed successfully for `6e43b85`, and [CI run 35124088669](https://github.com/bmateuszideas/fsasm-training-lab/actions/runs/35124088669) completed successfully for PR #15 candidate `0264bd1b1f69047c8374c3cd8ad94bf3be18df83`. The older, independently identified M4 baseline `603fc607439b44e46b26d8c3a2114b34ba7c458c` reported **299 passed, 3 skipped, 0 failed** with Ruff, mypy and workflow lint passing. Documentation-only CI does not prove crash recovery, complete task execution or actual coding. Check the exact current candidate HEAD's CI before any future merge.

## Approved direction and actual capability

- M1 **CLOSED**; M2 **CLOSED**; M3 **CLOSED**.
- M4 **IMPLEMENTED; STABILIZATION OPEN — NOT CLOSED**. Its bounded retry and durable Human Gate scenarios have worker-level tests, but outstanding contracts are listed below.
- M5 **NOT STARTED**. Do not start it without completion/review of M4 and explicit user authorization.
- LLMC **DEFERRED**: research material persists on `main`, but no adoption, integration or new benchmark is authorized in this work cycle. Existing benchmark has methodological limitations and is not a runtime Context Builder.
- M4 executes **one ChildTask** (possibly with retries); its Executor is a deterministic **STUB**. PASS validates tested control-flow scenarios, not autonomous coding or independently verified code changes.
- Runtime work starts on a new short-lived task branch from the **current** `Fsasm-experimental` HEAD, with a focused PR targeting `Fsasm-experimental`. No implicit `main` merge or archive deletion.

## M4 stabilization queue — one atomic issue per PR

| Item | Meaning | Verified status |
| --- | --- | --- |
| S0 | Standard-worker activity-name collisions | DONE — merged PR #7 |
| F2 | Normal-path retry consistency of `state.json` / `plan.json` | DONE — merged PR #8; **not** F3 transactionality |
| S2 | Initial PLANNED persistence / log ordering | DONE — merged PR #9 |
| S1 | Distinct audit IDs for repeated RETRY_ONCE | DONE — merged PR #10; narrow F6 subset |
| CI-01 | Correct PR SHA checkout and test-code lint | DONE — merged PR #12 |
| S3 | Human Gate audit before/after values | DONE — merged PR #13 |
| DOC-01 | Context-entry documents and branch inventory | DONE — merged PR #14, policy commit `6e43b85`, status refresh PR #15 |
| S4 | Stale M4 comments/docstrings | OPEN |
| F3 | Crash-consistent multi-file snapshot and recovery | OPEN |
| F4 | Explicit new-run creation vs reuse/resumption of `run_id` | OPEN |
| F5 | Safe identifiers in filesystem paths | OPEN |
| F6/F7 | Remaining evidence/gate identity and duplicate/stale/multiple signal handling | OPEN beyond S1 |
| F8 | Finalizer verifies authoritative run/task, checks and evidence before PASS | IMPLEMENTED — READY FOR EXTERNAL REVIEW (draft PR; not merged) |

The open items are documented issues/risks from the 2026-09-16 reviews, **not** proof that every reproducer was rerun in the present session. Verify the selected issue against current source/tests before modifying code. Do not declare an item DONE from a model summary alone.

**F8 verification (2026-09-16):** Implemented on branch `task/f8-finalizer-contract` from `Fsasm-experimental` HEAD `d6548b73af284a05e02f2c178bdc1d85006f7dfc`; PR [#17](https://github.com/bmateuszideas/fsasm-training-lab/pull/17) is **under external review** (draft PR, not merged). `finalize_task_activity` now validates verification identity (`run_id`/`task_id`), authoritative execution context (`RunState.status == RUNNING`, plan exists, task belongs to plan, plan task is RUNNING and its attempt equals the supplied task's attempt — compared by value across the serialization boundary), active-task context, evidence ownership, and (for PASS) nonempty all-passed checks + nonempty evidence before any side effect; invalid input fails closed via `ValidationError` with no state mutation or persistence. The redundant identity comparison that cannot fail after selecting a plan task by the same `task_id` was removed. Negative tests assert the specific `fsasm.errors.ValidationError` (and the exact domain exception where one is intentionally expected). Reproducer `tests/test_f8_finalizer_contract.py` (15 tests, independent task/plan objects via JSON round-trip) fails on the unpatched finalizer and passes after the fix. Local: `uv run pytest` → 314 passed, 3 skipped, 0 failed; `make check` clean; `git diff --check` clean. F8 is **IMPLEMENTED — READY FOR EXTERNAL REVIEW**; pending external review/acceptance and CI at the PR head. Not DONE; M4 is NOT CLOSED.

## NEXT ACTION — stable post-documentation work scope

**F8 (finalizer contract) is IMPLEMENTED — READY FOR EXTERNAL REVIEW on PR [#17](https://github.com/bmateuszideas/fsasm-training-lab/pull/17) (draft, not merged; branch `task/f8-finalizer-contract`).** F8 is NOT DONE and M4 is NOT CLOSED until external review/acceptance and the PR merges. The remaining M4 stabilization items — S4, F3, F4, F5, F6/F7 — are still OPEN; no other item is in progress. Do not begin M5, reactivate LLMC, automatically synchronize `main` or remove `__noop_check__`. The next decision after F8 is reviewed is to select ONE of the remaining open items, verify its failure mechanism in current code, define a bounded reproducer and acceptance criteria, and explicitly authorize its implementation.

## Fresh-agent entry and handoff

1. Read root `README.md` and this file; verify live HEAD/branch/PRs/CI. Treat pinned historical baselines as historical if the branch has moved.
2. Read `docs/CURRENT_FSASM_MODEL.md` for intent, `AGENTS.md` for stable rules, `docs/DOCUMENTATION_MAP.md` for authority and `docs/BRANCH_POLICY.md` for workflow. Original M1 bootstrap wording in `AGENTS.md` is historical where superseded by verified milestones and approved current scope.
3. Inspect only source and tests relevant to the selected atomic issue. Treat reviews and old chats as leads, not instructions. Report conflicts rather than silently resolving them.
4. Record base SHA, precise change, tests/CI and outstanding issues in the task PR. Update this short page for status-changing work; do not append competing 'current stop points' to the old anchor.

## Preservation

Historical documents in `stare dokumenty rozwojowe fsasm/` remain intact. LLMC benchmark is on `main`; removed LLMC branch name is not an active ref. Previous anchor remains in Git history ([baseline snapshot](https://github.com/bmateuszideas/fsasm-training-lab/blob/603fc607439b44e46b26d8c3a2114b34ba7c458c/fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md)). A model's previous conversation must never be the only record of project state or approved decision.
