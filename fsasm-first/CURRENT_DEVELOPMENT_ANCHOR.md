# FS-ASM Development Anchor

**Date:** 2026-09-16  
**Branch:** `Fsasm-experimental`  
**Code baseline:** `6cb17d62eb91813d147960533ea0ee1e9efc5d0d` (HEAD of `Fsasm-experimental`)  
**Previous baseline:** `c47f35602d812122fa40320a144880306cf7851d` (M4 implementation pause, 2026-09-09)  
**Status:** DEVELOPMENT RESUMED — M4 STABILIZATION

This file is an explicit restart anchor for future humans and AI coding agents.

Do not reconstruct the current project state from memory, chat history, or old summaries. Start from this file, the Git history, `AGENTS.md`, and the repository itself.

---

## 0. Approved decision (2026-09-16): resume FS-ASM, LLMC deferred

On 2026-09-16 the user approved resuming FS-ASM implementation after the context-efficiency experiments.

Approved decisions:

- **LLMC is set aside.** It is NOT integrated with the FS-ASM runtime now. Do not treat LLMC as a runtime dependency or a current architectural component.
- **No new context-efficiency benchmarks are launched.** The LLMC experiment (see section 6) is concluded as an experiment, not as an adoption.
- **M4 is stabilized first.** Before any new milestone work, close the known M4 stabilization items.
- **After M4 is closed, M5 starts as a minimal Context Builder** based initially on ordinary search and targeted reads. M5 is the next milestone after M4 stabilization.
- **Do NOT start M5 in the current work cycle.** M5 begins only after M4 stabilization is complete and explicitly authorized.

The distinction between "experiment concluded" and "M4 concluded" is explicit:

- The **LLMC experiment** is concluded (research/evaluation phase ended). This does not imply M4 is concluded.
- **M4** is implemented but not yet closed; it still has known stabilization items (see section 4 and the queue below).

The historical context below (sections 1–11) is preserved unchanged as the prior baseline record. The new stabilization queue follows.

---

## 1. Why development is paused here

The current FS-ASM runtime implementation has reached the end of the Milestone 4 development cycle, but further coding is intentionally paused before starting the next milestone.

The reason is not a failure of the FS-ASM runtime itself. The immediate bottleneck is **context acquisition for AI coding agents working in a growing repository**.

During the recent M4 implementation/review loop, a very large fraction of model usage was spent repeatedly reading, rediscovering, and reprocessing repository context rather than writing or reasoning about the actual code change. The repository is now large enough that letting a fresh coding model explore it naively is becoming expensive, slow, and increasingly unreliable.

This is directly related to the original motivation for FS-ASM: project state and relevant context should not have to live entirely inside an LLM context window.

Therefore the next work is **not M5 implementation yet**. The next work is to test a more efficient repository-context mechanism so that future FS-ASM development does not repeatedly pay the cost of reconstructing the same codebase context.

---

## 2. Current implementation baseline

The authoritative code baseline at this pause is:

`c47f35602d812122fa40320a144880306cf7851d`

Milestone status at this baseline:

- M1 — CLOSED
- M2 — CLOSED
- M3 — CLOSED
- M4 — **IMPLEMENTED — READY FOR EXTERNAL REVIEW**

The last reported local validation for `c47f356` was:

- 291 tests passed
- 3 tests skipped
- `make check` passed
- `git diff --check` passed

The `Fsasm-experimental` branch must be treated as the source of truth for this work.

---

## 3. What M4 currently proves

The M4 implementation now contains the core bounded-retry and durable Human Gate behavior that was being built and reviewed:

- execution attempts are explicitly counted;
- retry budget is bounded through `task.max_attempts`;
- failure is persisted before retry/escalation decisions;
- task and run enter durable `NEEDS_HUMAN` before the workflow waits;
- Human Gate uses Mistral Workflows signal/wait behavior;
- decisions are typed as `RETRY_ONCE` or `ABORT`;
- `RETRY_ONCE` authorizes exactly one additional execution attempt;
- a second failure after `RETRY_ONCE` requires a new Human Gate decision;
- a signal arriving after persisted `NEEDS_HUMAN` but before `wait_condition()` is preserved;
- initial durable state is `PLANNED` with the authoritative retry budget already persisted;
- `PLANNED -> RUNNING` occurs when execution is prepared;
- worker-level regression tests exercise the Human Gate and retry paths.

Do not casually redesign these semantics when work resumes.

---

## 4. Known unfinished review / cleanup items

An independent GPT-6 review and the subsequent external review loop considered the core M4 behavior functionally sound, but some follow-up work was deliberately not spent on the exhausted coding instance.

These items are **known technical debt / review cleanup**, not forgotten work:

1. **Human Gate audit EvidenceRecord IDs** — DONE (S1, PR pending)
   - The `RETRY_ONCE` audit `evidence_id` in `validate_and_apply_human_decision_activity` was `evidence-human-gate-retry-{run_id}-{task_id}`, with no discriminator, so a consecutive `RETRY_ONCE` on the same run/task received the same id and overwrote the earlier audit record under a shared evidence path.
   - Fixed by appending the failing attempt: `evidence-human-gate-retry-{run_id}-{task_id}-attempt-{task.attempt}`. `RETRY_ONCE` does not reset `task.attempt`, so the attempt at decision time uniquely and deterministically identifies each consecutive `RETRY_ONCE` on the same run/task. The id is stable across replays of the same event and does not collide with the `ABORT` audit id (`evidence-human-gate-abort-...`). No random UUID or wall clock is used.
   - Regression test: `tests/test_s1_human_gate_evidence_uniqueness.py` (worker-level, isolated `tmp_path` persistence). It drives two consecutive `RETRY_ONCE` decisions through the real worker and proves both audit records survive as distinct files with distinct ids and preserved per-decision content, plus the closing `ABORT` and the attempt sequence 1→2→3.
   - Resolved scope (partial F6): uniqueness and non-overwrite of consecutive `RETRY_ONCE` audit records on the same run/task, and non-collision with the `ABORT` audit id. NOT resolved under F6: signal deduplication / idempotent re-application of the same Human Gate signal (that is the separate F7 scope) and audit payload completeness for the `attempt`/`max_attempts` before/after a decision (that is the separate S3 scope). F6 is therefore not marked DONE as a whole.

2. **Human Gate audit payload completeness**
   - Preserve explicit attempt and `max_attempts` before and after a human-authorized decision where applicable.
   - The audit trail should remain reconstructable without relying on chat history.

3. **Initial M4 run log consistency**
   - Verify that the initial `m4_run_started` log reports `PLANNED`, matching the actually persisted initial RunState.

4. **Stale M4 comments/docstrings**
   - Some text may still describe the older ordering (`persist -> set max_attempts` or initial `PLANNED -> RUNNING` inside initial persistence).
   - Documentation/comments should eventually be aligned with the implemented ordering:
     `set authoritative max_attempts -> persist PLANNED -> prepare execution -> RUNNING`.

These items should be re-verified against the actual code before editing. Do not blindly trust this list if the branch has moved.

They are not a reason to restart a broad M4 rewrite.

---

## 5. The new blocking engineering problem: repository context cost

The next problem to solve is how an AI coding agent should obtain repository context without repeatedly reading a large part of the repository.

Naive workflow:

```text
fresh coding agent
    -> list/search repository
    -> repeatedly open large files
    -> reconstruct architecture and dependencies
    -> consume a large context budget
    -> only then begin the actual task
```

This becomes worse as FS-ASM grows and directly recreates the historical problem that motivated FS-ASM in the first place.

A larger model context window postpones the failure mode but does not solve it: the project can fit, but repeatedly processing it can dominate cost and latency.

---

## 6. Immediate experiment: LLMC as a local repository-context engine

Before building a custom FS-ASM Context Builder, test the existing project:

`https://github.com/vmlinuzx/llmc`

The current reason for evaluating LLMC is that it already provides several mechanisms relevant to the FS-ASM problem:

- local-first repository indexing;
- Tree-Sitter parsing;
- symbol/function/class spans;
- SQLite-backed repository index;
- code skeletonization;
- structural relationships such as imports/calls/inheritance;
- precise symbol reads instead of whole-file reads;
- semantic/hybrid retrieval;
- MCP integration.

The experiment should be local and should initially avoid unnecessary LLM-based enrichment. The goal is to measure whether mostly mechanical repository context construction can substantially reduce the amount of code/context sent to the coding model.

Do **not** integrate LLMC permanently into FS-ASM yet. First benchmark it as an external context provider.

---

## 7. First LLMC benchmark target

Use the current `fsasm-first` M4 implementation because its architecture and known review findings are already understood.

Useful benchmark questions/tasks include:

- Where is the durable Human Gate implemented?
- What controls the execution retry budget?
- Find every relevant path that can mutate `task.max_attempts`.
- Which tests prove `RETRY_ONCE` behavior?
- Which code transitions a run from `PLANNED` to `RUNNING`?
- What code and tests are relevant to repeated Human Gate decisions?

Measure at minimum:

- context/input tokens consumed by the coding model;
- number of files/spans read;
- time before the model begins actual task reasoning;
- whether the retrieved context contains the known relevant implementation/tests;
- whether review quality is comparable to the previous full-repository approach.

The purpose is empirical evaluation, not adoption by assumption.

---

## 8. Context architecture direction if the experiment succeeds

The intended conceptual split is:

```text
FS-ASM Runtime
    -> owns process state, transitions, retries, verification, evidence, Human Gates

Repository Context Provider
    -> finds the minimum code/project context needed for the current ChildTask

External documentation provider (for example Context7)
    -> provides current library/framework documentation when needed

LLM / Coding Executor
    -> performs the semantic/coding work on the bounded task and supplied context
```

The repository-context layer should be provider-agnostic. LLMC may become an adapter/provider, not a hard-coded architectural dependency.

A future interface can conceptually resemble:

```text
ContextProvider.get_context(task) -> bounded execution context
```

Do not implement this interface yet solely because it is written here. First complete the local LLMC experiment.

---

## 9. Cost discipline for future AI coding sessions

The M4 cycle exposed a second process issue: full-suite testing and verbose repository exploration can dominate token usage when an AI agent repeatedly reads command output.

Future coding agents should follow this policy unless a task specifically requires otherwise:

1. Inspect the smallest relevant subsystem first.
2. Run the smallest relevant targeted test(s) during implementation.
3. Use concise test output where possible (`-q`, short traceback, warnings suppressed unless relevant).
4. Expand to the subsystem test file after the focused tests pass.
5. Run the full repository suite once at a final milestone/review boundary, or when shared core changes make it necessary.
6. Do not repeatedly run the full suite after every small edit.
7. Do not recursively read the entire repository merely to "understand the project".

The objective is not to reduce verification quality. It is to avoid repeatedly paying for information that is already known or mechanically retrievable.

---

## 10. Resume protocol

When programming work resumes, a fresh AI agent should begin in this order:

1. Confirm the current branch and HEAD.
2. Read this file.
3. Read `AGENTS.md`.
4. Read `IMPLEMENTATION_SUMMARY.md` only as a handoff summary, then verify relevant claims against Git/code.
5. Check whether the LLMC/context-efficiency experiment has produced a documented result.
6. Re-verify the known M4 cleanup items against current code.
7. Do **not** start M5 until the user explicitly decides whether to adopt, reject, or postpone the repository-context solution.
8. If M4 cleanup is performed, keep it as a small focused patch. Do not reopen M1-M3 or redesign M4 without concrete repository evidence.

---

## 11. Current stop point in one sentence

> **FS-ASM runtime development is paused at `c47f356`: M4 core behavior is implemented and heavily tested, a small set of review/audit cleanup remains, and the immediate next task is to benchmark a local repository-context/RAG mechanism (starting with LLMC) so future AI coding does not spend most of its budget repeatedly reconstructing the codebase.**

---

## 12. M4 stabilization queue (added 2026-09-16)

This is the approved atomic queue for closing M4. Each item has a scope, a completion criterion, and a regression test. Do not start a broad architecture rebuild. Work on one item at a time, smallest correct change, preserving historical milestone semantics.

These items are derived from the 2026-09-09 audit (section 4) plus the worker-collision finding. Re-verify each against current code before editing.

### Task S0 — Standard worker activity-name collision (DONE 2026-09-16)

- **Scope:** The standard worker's autodiscovery (`entrypoints.worker` -> `get_all_temporal_activities()`) collected two different activities that shared the same `name=` despite different contracts, so building a `temporalio.worker.Worker` raised `ValueError: More than one activity named fsasm-plan`. Seven M1 activity names collided with M2 / `planner_activities`. The smallest correct change was to prefix the seven M1 activity names with `m1-` (e.g. `fsasm-plan` -> `fsasm-m1-plan`), because the colliding pairs have different arguments/return types/behavior and must remain separate. No duplicates were removed merely by name.
- **Completion criterion:** `get_all_temporal_activities()` collected via the standard autodiscovery path yields all-unique names, and a `temporalio.worker.Worker` can be built from that full list without `ValueError`.
- **Regression test:** `tests/test_worker_activity_name_collision.py` reproduces the standard worker path (autodiscovery + `get_all_temporal_activities()`) and builds a `temporalio.worker.Worker` exactly like the production worker. Reverting any of the seven M1 names re-triggers `ValueError: More than one activity named ...` in this test.
- **Status:** DONE on branch `vibe/worker-activity-name-collision-b6d6c2`. M1–M4 workflow scenarios and hello-world remain contract-conformant. The preexisting M4 `test_initial_persistence_ordering_worker_level` failure is unrelated to this change (see Task S2).

### Task S1 — Human Gate audit EvidenceRecord ID uniqueness

- **Scope:** Verify that Human Gate audit `EvidenceRecord` IDs are unique across repeated decisions on the same run/task. A repeated `RETRY_ONCE` must never overwrite an earlier audit record. Prefer deterministic uniqueness based on attempt or gate sequence.
- **Completion criterion:** Every Human Gate decision produces a distinct, deterministic evidence ID even when `RETRY_ONCE` is applied more than once to the same task; no audit record is overwritten.
- **Regression test:** A worker-level test that drives two consecutive `RETRY_ONCE` decisions on the same task and asserts two distinct evidence records with non-overlapping IDs and contents.

### Task S2 — Initial M4 run log / persistence ordering consistency (preexisting failure)

- **Scope:** Verify that the initial `m4_run_started` log reports `PLANNED`, matching the actually persisted initial `RunState`, and that the initial durable state observed by the worker-level test is `PLANNED` with `active_task_id=None`, all tasks `PENDING`, and authoritative `max_attempts=3`. As of `6cb17d6`, `tests/test_fsasm_milestone_four.py::TestInitialPersistenceOrdering::test_initial_persistence_ordering_worker_level` fails on the clean baseline (preexisting, unrelated to S0). This item closes that failure.
- **Completion criterion:** `test_initial_persistence_ordering_worker_level` passes, and the implemented ordering (`set authoritative max_attempts -> persist PLANNED -> prepare execution -> RUNNING`) is consistent with logs and comments.
- **Regression test:** The existing `test_initial_persistence_ordering_worker_level` plus a focused assertion that the initial `m4_run_started` log entry reports `PLANNED`.

### Task S3 — Human Gate audit payload completeness (DONE 2026-09-16)

- **Scope:** Preserve explicit `attempt` and `max_attempts` before and after a human-authorized decision where applicable, so the audit trail is reconstructable without chat history.
- **Completion criterion:** Each Human Gate audit evidence payload contains the attempt counter and max_attempts at decision time; repeated decisions remain reconstructable from evidence alone.
- **Regression test:** A test that performs a `RETRY_ONCE` decision and asserts the audit payload records `attempt` and `max_attempts` before and after the authorized retry.
- **Defect found:** In `validate_and_apply_human_decision_activity` (`src/workflows/fsasm_milestone_four.py`), the `RETRY_ONCE` audit payload was missing `attempt_after` and set `max_attempts_before` to `task.attempt` (reconstructed from the attempt number) instead of the real pre-transition `max_attempts` value. The `ABORT` audit payload carried only flat `attempt` and `max_attempts` keys and was missing all four `attempt_before`/`attempt_after`/`max_attempts_before`/`max_attempts_after` fields.
- **Minimal production fix:** Before applying any transition, the activity now captures a local snapshot of `attempt`, `max_attempts`, `task.status`, and `run.status` from the actual objects; after applying the existing transitions (semantics unchanged), it reads the real post-transition values and builds the audit payload from both snapshots. Both `RETRY_ONCE` and `ABORT` payloads now carry the full contract: `action`, `reason`, `task_id`, `attempt_before`, `attempt_after`, `max_attempts_before`, `max_attempts_after`, `task_status_before`, `task_status_after`, `run_status_before`, `run_status_after`, `active_task_id`. No transition semantics, models, evidence id scheme, or audit system changed.
- **Status:** DONE on branch `vibe/s3-human-gate-audit-payload` (draft PR, not merged). Resolves ONLY S3; does NOT resolve S4, F3, F4, F5, F6/F7, F8. M4 as a whole is NOT closed.

### Task S4 — Stale M4 comments/docstrings alignment

- **Scope:** Align any remaining comments/docstrings that describe the older ordering (`persist -> set max_attempts` or initial `PLANNED -> RUNNING` inside initial persistence) with the implemented ordering: `set authoritative max_attempts -> persist PLANNED -> prepare execution -> RUNNING`.
- **Completion criterion:** No comment/docstring contradicts the implemented ordering; `make check` and `lint-workflows` are clean.
- **Regression test:** No behavioral test; verification is by grep/manual review that comments match code, plus `make check`.

---

## 13. Current stop point (updated 2026-09-16)

> **FS-ASM runtime development has resumed at `6cb17d6`. LLMC is deferred and not integrated. M4 stabilization is in progress: Task S0 (worker activity-name collision) is done; Task F2 (retry state.json/plan.json consistency) is done; Task S2 (initial persistence ordering & run log consistency) is done; Task S1 (Human Gate audit EvidenceRecord ID uniqueness) is done; Task S3 (Human Gate audit payload completeness) is done; the next atomic tasks are the remaining open items in the queue below. M5 has NOT been started and is not to be started until M4 stabilization is complete and explicitly authorized.**

**Merged stabilization history:** S0 — merged PR #7; F2 — merged PR #8; S2 — merged PR #9 (HEAD `e4a93ef`); CI fix (task CI-01) — merged PR #12 (HEAD `7322cc7`). S1 is on branch `vibe/s1-human-gate-evidence-uniqueness-9726de` (draft PR, not merged). S3 is on branch `vibe/s3-human-gate-audit-payload` (draft PR, not merged). M4 as a whole is NOT closed.

---

## 14. M4 stabilization queue — extended with F-audit findings (added 2026-09-16)

The original S0–S4 queue (section 12) is preserved unchanged. This section extends it with the confirmed F-audit findings and marks completed work. Identification is more important than renumbering, so the original S1–S4 numbers are kept and the new items get explicit identifiers.

### Task S0 — Standard worker activity-name collision (DONE 2026-09-16)

See section 12 for the full record. DONE on branch `vibe/worker-activity-name-collision-b6d6c2`, merged into `Fsasm-experimental` at `0414d69`.

### Task F2-STATE-CONSISTENCY — Retry state.json / plan.json consistency (DONE 2026-09-16)

- **Scope:** `persist_retry_state_activity` in `src/workflows/fsasm_milestone_four.py` updated the separate `plan` argument but wrote `state` (embedding `state.plan`) and `plan` independently. In the real worker, activity arguments cross the serialization boundary, so `state.plan` and the `plan` arg are independent objects; updating only `plan` left `state.json` (`state.plan.tasks[*].status = FAILED`) stale relative to `plan.json` (`tasks[*].status = READY`) after a `FAILED -> READY` retry transition. Fix: a single authoritative source of truth inside the activity. The activity now reconciles both to one object (`state.plan` when present, else `plan`), updates that object's task, sets `state.plan` and the returned `plan` to the same object, and persists both from that single source. No file write is skipped; retry semantics are unchanged.
- **Invariants preserved:** `attempt` increments only on `READY -> RUNNING`; `FAILED -> READY` does not increment; `max_attempts` remains authoritative; Human Gate and `RETRY_ONCE` behavior unchanged.
- **Completion criterion:** After `persist_retry_state_activity` under independent (serialized) arguments, `state.json.plan.tasks[T].{status,attempt,max_attempts} == plan.json.tasks[T].{status,attempt,max_attempts}`, and the returned objects are consistent. The next `READY -> RUNNING` increments `attempt` exactly once.
- **Regression test:** `tests/test_f2_retry_state_consistency.py` forces an independent JSON round-trip of activity arguments (as Temporal does), calls the real activity, and reads back the persisted `state.json` and `plan.json`. This test fails on the unpatched code (`FAILED == READY`) and passes after the fix.
- **Status:** DONE on branch `vibe/f2-retry-state-consistency-b6d6c2`. Resolves ONLY F2; does not resolve F3 (multi-file snapshot transactionality).

### Task S2-INIT-PERSISTENCE-ORDERING — Initial persistence ordering & run log consistency (DONE 2026-09-16)

- **Scope:** Two confirmed problems. (A) `persist_initial_state_activity` persisted the initial `RunState` as `PLANNED` but wrote the `m4_run_started` log entry with `status=RunStatus.RUNNING.value`, contradicting the actually persisted initial state. (B) The preexisting `tests/test_fsasm_milestone_four.py::TestInitialPersistenceOrdering::test_initial_persistence_ordering_worker_level` tried to observe the transient `PLANNED` state by polling `state.json` every 100 ms; the workflow transitions `PLANNED -> RUNNING` very quickly during `prepare_task_activity`, so missing `PLANNED` in the poll is a race and does NOT prove it was never persisted. That test also called `RuntimePersistence().cleanup_all()` on the global `./runtime`, which is unsafe for test isolation.
- **Minimal production fix:** `m4_run_started` now reports the actually persisted status (`state.status.value`, i.e. `PLANNED`) instead of a hard-coded `RUNNING`. The state machine is unchanged: the initial snapshot is still `PLANNED`, `active_task_id=None`, all tasks `PENDING`, and the `PLANNED -> RUNNING` transition still happens later in `prepare_task_activity`. Ordering `set authoritative max_attempts -> persist PLANNED -> prepare execution -> RUNNING` is unchanged; only the log value and the two directly related comments were corrected.
- **Test method:** The old race-based, `cleanup_all()`-using worker-level test was removed. The deterministic replacement is `tests/test_s2_initial_persistence_ordering.py`. It does not poll the transient state. It (1) runs the real worker and reads the append-only `run.log.jsonl` after completion to prove the durable `m4_run_started` entry reports `PLANNED` and is the first event, (2) confirms the final run transitioned to `RUNNING` (so `PLANNED -> RUNNING` happened after init), and (3) drives `persist_initial_state_activity` directly with independently JSON-round-tripped arguments (mimicking the worker serialization boundary, not shared Python references) and reads back the durable `state.json` and `plan.json` to prove `PLANNED`, `active_task_id=None`, all tasks `PENDING`, `max_attempts=3`, and `state.json.plan == plan.json` at initialization. Persistence is isolated to `tmp_path` via monkeypatch of `RuntimePersistence` in every activity module; the global `./runtime` is never touched.
- **Invariants preserved:** initial state `PLANNED`; `active_task_id=None`; all tasks `PENDING`; `max_attempts = max_retries_per_task + 1 = 3`; `PLANNED -> RUNNING` happens only during task preparation; retry/Human Gate/`RETRY_ONCE` semantics and counters unchanged.
- **Completion criterion:** The deterministic S2 test passes; `m4_run_started` reports `PLANNED`; `state.json.plan == plan.json` at init; the workflow still completes the success scenario. The preexisting failing test no longer exists (replaced deterministically), and the full suite is green.
- **Regression test:** `tests/test_s2_initial_persistence_ordering.py`. Fails on the unpatched code (`m4_run_started.status == RUNNING`) and passes after the fix.
- **Status:** DONE on branch `vibe/s2-initial-persistence-ordering-b6d6c2`. Resolves ONLY S2; does NOT resolve F3 (proving correct init ordering is not a transactional multi-file write), and does not touch S1/S3/S4/F4/F5/F6/F7/F8.

### Task S1-HUMAN-GATE-EVIDENCE-UNIQUENESS — Human Gate audit EvidenceRecord ID uniqueness (DONE 2026-09-16)

- **Scope / defect:** `validate_and_apply_human_decision_activity` in `src/workflows/fsasm_milestone_four.py` built the `RETRY_ONCE` audit `evidence_id` as `evidence-human-gate-retry-{run_id}-{task_id}` with no discriminator. Two consecutive `RETRY_ONCE` decisions on the same run/task received the same id, and because persistence stores evidence under a path derived from `evidence_id`, the second write overwrote the earlier audit record (the first decision's `reason` was lost).
- **Minimal production fix:** The `RETRY_ONCE` audit `evidence_id` now appends the failing attempt: `evidence-human-gate-retry-{run_id}-{task_id}-attempt-{task.attempt}`. `RETRY_ONCE` does not reset `task.attempt`, so the attempt at decision time equals the execution attempt that just failed and uniquely, deterministically identifies each consecutive `RETRY_ONCE` on the same run/task. The id is stable across replays of the same event, uses no random UUID or wall clock, and does not collide with the `ABORT` audit id (`evidence-human-gate-abort-{run_id}-{task_id}`). Other evidence category ids (`planner_proposal`, `m4_execution_summary`, per-attempt executor evidence, the `ABORT` audit) are unchanged.
- **Invariants preserved:** `RETRY_ONCE`/`ABORT`/`attempt`/`max_attempts` semantics unchanged; `attempt` increments only on `READY -> RUNNING`; `RETRY_ONCE` authorizes exactly one additional attempt; no change to other evidence category ids.
- **Reproduction:** Before the fix, the worker-level reproducer observed only one `RETRY_ONCE` audit record surviving on disk (the second overwrote the first, carrying the second decision's `reason`), confirming the collision.
- **Regression test:** `tests/test_s1_human_gate_evidence_uniqueness.py` (worker-level, isolated `tmp_path` persistence via monkeypatch of `RuntimePersistence` in every activity module; the global `./runtime` is never touched). It drives two consecutive `RETRY_ONCE` decisions through the real worker (`max_retries_per_task=0`, `stub_fail_first_n_attempts=999`) with controlled synchronization on durable `NEEDS_HUMAN` state keyed by attempt number, then a closing `ABORT`. It asserts: exactly two `human_gate_audit`/`RETRY_ONCE` records; same run_id/task_id; distinct `evidence_id`; both files exist; first record's content unchanged after the second decision (different `reason` values detect overwrite, not just name collision); each record keeps its own `reason`; two `human_decision_retry_once` log entries; attempts 1→2→3; each `RETRY_ONCE` authorizes exactly one more attempt; the `ABORT` closes the workflow with `FAILED`; no collision with the `ABORT` audit id; and `result.evidence_count == actual persisted evidence count`.
- **Resolved scope (partial F6):** uniqueness and non-overwrite of consecutive `RETRY_ONCE` audit records on the same run/task, and non-collision with the `ABORT` audit id.
- **NOT resolved (remain open):** F3 (multi-file transactionality); F4 (run_id reuse); F5 (path identifier validation); F7 (signal deduplication / idempotent re-application of the same Human Gate signal); F8 (finalizer contract); the remainder of F6 beyond the specific case solved here. F6 is NOT marked DONE as a whole. (S3 — audit payload completeness — is now done separately; see Task S3.)
- **Status:** DONE on branch `vibe/s1-human-gate-evidence-uniqueness-9726de`. Resolves ONLY S1 (and the corresponding narrow part of F6); does NOT resolve F3, F4, F5, F7, F8, or the rest of F6.

### Open backlog (separate atomic tasks, not started)

These items remain open and require their own atomic patches. They are NOT done.

- **S3 — Human Gate audit payload completeness** (DONE 2026-09-16, draft PR not merged). See section 12.
- **S4 — Stale M4 comments/docstrings alignment** (open). See section 12.
- **F3 — Multi-file snapshot transactionality** (open). `state.json` and `plan.json` consistency after an activity does NOT imply a transactional write of both files. A crash between the two writes can still leave them inconsistent. Separate atomic task; do not claim it is solved by F2.
- **F4 — run_id reuse** (open). Separate atomic task.
- **F5 — identifier validation in paths** (open). Separate atomic task.
- **F6/F7 — evidence and Human Gate identifier contracts** (open). Overlaps with S1/S3. S1 resolved only the narrow case of consecutive-`RETRY_ONCE` audit id uniqueness/non-overwrite and non-collision with the `ABORT` id; F6 as a whole and F7 (signal deduplication) remain open. Separate atomic task.
- **F8 — finalizer contract** (open). Separate atomic task.

The historical code baseline `c47f356` (section 2) is preserved as the historical M4 implementation commit; it is not changed by this stabilization work.
