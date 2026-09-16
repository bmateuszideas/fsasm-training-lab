# FS-ASM — CURRENT PROJECT STATUS

**Snapshot date:** 2026-09-16. **Latest verified active integration HEAD at this status update:** `Fsasm-experimental` @ `dbc73b74905064b5586325c207d70d5b7685aa19` (merged PR #17). This is a dated reference, not a claim that HEAD remains unchanged. Recheck live branches, HEAD, refs, PRs, source and CI every new session.

## What is authoritative

This file is the **single current project-status entry point**. Long-term intent: [`docs/CURRENT_FSASM_MODEL.md`](docs/CURRENT_FSASM_MODEL.md). Stable engineering rules: [`AGENTS.md`](AGENTS.md). Document roles and precedence: [`docs/DOCUMENTATION_MAP.md`](docs/DOCUMENTATION_MAP.md). Branch procedure: [`docs/BRANCH_POLICY.md`](docs/BRANCH_POLICY.md). Root `.vibe/skills/fsasm-vibe-coding/` provides optional external coding-agent methodology, **not** project status, work authorization or runtime features. Implementation claims require source, merged PRs and actual tests/CI at a pinned commit. [`CURRENT_DEVELOPMENT_ANCHOR.md`](CURRENT_DEVELOPMENT_ANCHOR.md) preserves dated history containing superseded instructions; do not execute its old LLMC-pause, old next-action or pending-S3 text.

## Verified branch and documentation state (2026-09-16)

| Branch | Verified historical reference | Role |
| --- | --- | --- |
| `Fsasm-experimental` | `dbc73b74905064b5586325c207d70d5b7685aa19` after PR #17 | Active integration and starting point for short-lived task branches; check live HEAD before using. |
| `main` | `a9f8ab6640acfda21c31675a03ba53d094f2909f` at previous inspection | GitHub default, older divergent runtime and LLMC benchmark; no implicit merge or reset. |
| `__noop_check__` | `30a6e56935b7238b471f7f21365c21679693de20` at previous inspection | Legacy technical branch; removal requires separate ancestry/reference check and explicit approval. |

The three persistent refs above were confirmed after user cleanup and before this documentation task. Short-lived task/docs branches may appear during PRs; this table is not a live branch API. Deleted refs include `Fsasm-llmc-testingbranch` and old `vibe/*` branches. Do not describe deleted refs as present or frozen. Deleting refs did not remove Git history or the LLMC benchmark on `main`.

**Documentation governance:** [PR #14](https://github.com/bmateuszideas/fsasm-training-lab/pull/14) merged the root agent entry, READMEs, status, documentation map and branch policy; policy follow-up `6e43b85` synchronized the reduced branch inventory. [PR #15](https://github.com/bmateuszideas/fsasm-training-lab/pull/15) refreshed status, and [PR #16](https://github.com/bmateuszideas/fsasm-training-lab/pull/16) corrected the next action. These completed documentation PRs are **not future tasks**.

**Verification references:** [CI run 35122809983](https://github.com/bmateuszideas/fsasm-training-lab/actions/runs/35122809983) passed for the earlier docs baseline `6e43b85`. The earlier M4 baseline `603fc607439b44e46b26d8c3a2114b34ba7c458c` had 299 passed, 3 skipped, 0 failed. The later F8 PR CI is recorded below. Documentation-only CI does not prove crash recovery, complete task execution or real coding; verify the exact candidate SHA before any merge.

## Approved direction and actual capability

- M1 **CLOSED**; M2 **CLOSED**; M3 **CLOSED**.
- M4 **IMPLEMENTED; STABILIZATION OPEN — NOT CLOSED**. Bounded retries and durable Human Gate have worker-level tests. The remaining stabilization contracts are listed below.
- M5 **NOT STARTED**. Do not start without the agreed M4 acceptance and explicit user authorization.
- LLMC **DEFERRED**. Research material persists on `main`; no adoption, integration or new benchmark is authorized by this status.
- M4 executes **one ChildTask**, possibly with retries, through a deterministic **STUB Executor**. A successful tested workflow path does not prove autonomous coding, independent artifact verification, complete plan execution or crash recovery.
- New runtime tasks start on short-lived branches from the **live** `Fsasm-experimental` HEAD and use focused PRs back to `Fsasm-experimental`. No implicit synchronization of `main`, branch deletion or archive cleanup.

## M4 stabilization queue — one atomic issue per PR

| Item | Meaning | Verified status |
| --- | --- | --- |
| S0 | Standard-worker activity-name collisions | DONE — merged PR #7 |
| F2 | Normal-path retry consistency of `state.json` / `plan.json` | DONE — merged PR #8; **not** F3 transactionality |
| S2 | Initial PLANNED persistence / log ordering | DONE — merged PR #9 |
| S1 | Distinct audit IDs for repeated RETRY_ONCE | DONE — merged PR #10; narrow F6 subset |
| CI-01 | Correct PR SHA checkout and test-code lint | DONE — merged PR #12 |
| S3 | Human Gate audit before/after values | DONE — merged PR #13 |
| DOC-01 | Context-entry documents and branch inventory | DONE — merged PR #14, policy follow-up and status PRs #15/#16 |
| F8 | Finalizer verifies authoritative run/task, checks and evidence before PASS | **DONE — independently reviewed and merged PR #17** |
| S4 | Stale M4 comments/docstrings | OPEN |
| F3 | Crash-consistent multi-file snapshot and recovery | OPEN |
| F4 | Explicit new-run creation vs reuse/resumption of `run_id` | OPEN |
| F5 | Safe identifiers in filesystem paths | **IMPLEMENTED \u2014 READY FOR EXTERNAL REVIEW** (task branch `task/f5-filesystem-path-safety`, PR pending) |
| F6/F7 | Remaining evidence/gate identity and duplicate/stale/multiple signal handling | OPEN beyond S1 |

The OPEN items are previously documented findings/risks, **not** proof that every reproducer was rerun in this session. Verify a selected issue against current source/tests before code edits; no single skill, review or model summary can silently authorize its implementation.

**F8 completion evidence (2026-09-16):** [PR #17](https://github.com/bmateuszideas/fsasm-training-lab/pull/17) merged into `Fsasm-experimental` at `dbc73b74905064b5586325c207d70d5b7685aa19` from reviewed task head `32cd58346b4d8d71cc0216aa54a341992508dd39`. The finalizer now rejects contradictory verification/run/task identity, inconsistent authoritative execution context (run, plan task, attempt and active task), foreign evidence and malformed PASS (empty/failed checks or missing evidence) before side effects; tests explicitly cover serialization-independent task/plan objects and error types. [PR CI run 35130458954](https://github.com/bmateuszideas/fsasm-training-lab/actions/runs/35130458954) completed successfully, reporting 314 passed, 3 skipped, 0 failed with five successful jobs. These facts establish the **reviewed F8 consistency fix**, not real coding verification, multi-file crash atomicity, F4/F5 path/run identity safety or full M4 closure. The original PR description contains older draft SHA/test counts; use the reviewed head and actual CI above.

**F5 implementation evidence (2026-09-16):** Implemented on task branch `task/f5-filesystem-path-safety` from integration base `Fsasm-experimental` @ `7e0df5a816e2a3511602e98470be14cd282a63ea`. The persistence layer (`src/fsasm/persistence.py`) now enforces a centralized filesystem-identifier policy (`_validate_identifier`) at the persistence boundary for every run_id- and evidence_id-derived path, raising a new explicit domain exception `fsasm.errors.InvalidIdentifierError` before any identifier-derived filesystem side effect. The policy accepts existing generated UUIDs and conventional FS-ASM IDs (ASCII letters, digits, `-`, `_`) and rejects empty/whitespace, `/` and `\` separators, absolute/drive/UNC input, `.`/`..`, null bytes and control characters, identifiers over 200 chars (leaving room for the `.json` suffix), and Windows-reserved names. Path containment (`_ensure_contained`) verifies resolved paths stay within their authorized root (`runs_dir` / run dir / evidence dir) and rejects existing symlinks at the run-directory, evidence-directory and destination-file levels so an operation cannot follow a pre-existing link into another run or an external location \u2014 run isolation holds even when a symlink target stays inside `runs_dir`. Validation is wired into all save/load/path/existence/cleanup entry points (`save_plan`, `save_run_state`, `save_evidence`, `save_verification_result`, `save_run_log_entry`, `load_plan`, `load_run_state`, `load_evidence`, `load_all_evidence`, `load_run_log`, `run_exists`, `cleanup_run`). `get_all_run_ids` iterates the trusted operator-configured `runs_dir` and is out of F5's untrusted-identifier scope.

Tested security scenarios (new `tests/test_f5_filesystem_path_safety.py`, 224 tests): valid UUID and conventional FS-ASM IDs round-trip; pre-fix reproduction confirmed 202 unsafe-input failures (e.g. `save_run_state("../outside")` wrote outside the run dir); post-fix all unsafe run/evidence IDs are rejected before writes and reads with `InvalidIdentifierError`; `cleanup_run("../outside")` cannot delete an external sentinel directory; run-directory symlinks (`runs/run-alias -> runs/run-real`) are rejected on save/load/exists/cleanup with the origin run unchanged; evidence-directory symlinks to outside and to another run's evidence dir are rejected; state/evidence destination-file symlinks to outside are rejected; rejected operations leave external sentinels and trees untouched; identifiers over 200 chars and Windows-reserved names (CON/PRN/AUX/NUL/COM1/LPT1) are rejected; empty/whitespace evidence IDs are rejected by the `EvidenceRecord` model at construction (recorded as already-protected). Full suite: 538 passed, 3 skipped, 0 failed; `make check` (ruff + mypy + semgrep) and `git diff --check` pass.

**F5 limitation:** the containment+symlink checks validate paths before each operation but are not a TOCTOU-hardened sandbox against arbitrary concurrent filesystem modification (e.g. an attacker replacing a directory with a symlink between the check and the write). The configured runtime root is assumed trusted (operator-selected); F5 addresses untrusted identifiers and unsafe identifier-derived paths, not run-ID reuse (F4), multi-file transactional writes (F3), or configuration permissions. F5 is **IMPLEMENTED \u2014 READY FOR EXTERNAL REVIEW**, not DONE; M4 remains OPEN pending external review and merge.

## NEXT ACTION — no new runtime task approved by this file

**F8 has been merged and is DONE; M4 is still OPEN.** Select **one** of S4, F3, F4, F5 or F6/F7, verify its failure mechanism in current code and agree on bounded scope/reproducer/acceptance criteria with the user **before** implementation. No other stabilization item is currently authorized by this status alone. Do not begin M5, reactivate LLMC, synchronize `main` or remove `__noop_check__` as an automatic next step. Adding a Vibe process skill is a separate documentation/tooling change, not M4 completion.

## Fresh-agent entry and handoff

1. Read root `AGENTS.md` and this file; verify live HEAD, branch, PRs and CI. Treat pinned baselines as historical if branches moved.
2. Read `docs/CURRENT_FSASM_MODEL.md` for intent, `AGENTS.md` for stable implementation rules, `docs/DOCUMENTATION_MAP.md` for authority and `docs/BRANCH_POLICY.md` for branch workflow. The M1 bootstrap in `AGENTS.md` is historical where superseded by accepted milestones/current scope.
3. Inspect only code and tests relevant to the explicitly selected atomic issue. Previous reviews, skill instructions and old chats are leads or methodology, not authority to start another task. Report conflicts rather than silently resolving them.
4. Record base SHA, scope, changed files, exact commands/results, CI and unresolved items in the task PR. Only update this page for real status changes. A task-specific handoff belongs in its PR or task branch, not a competing global status document.

## Preservation

Historical documents in `stare dokumenty rozwojowe fsasm/` remain intact. LLMC benchmark remains on `main`; deleted LLMC branch names are not active refs. The earlier anchor is retained in Git history ([snapshot](https://github.com/bmateuszideas/fsasm-training-lab/blob/603fc607439b44e46b26d8c3a2114b34ba7c458c/fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md)). A model's past conversation must never be the only record of project state or approved decisions.
