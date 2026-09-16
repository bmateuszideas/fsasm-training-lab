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

1. **Human Gate audit EvidenceRecord IDs**
   - Current audit evidence IDs should be checked for uniqueness across repeated Human Gate decisions on the same run/task.
   - A repeated `RETRY_ONCE` must never overwrite an earlier audit record.
   - Prefer deterministic uniqueness based on attempt or gate sequence.

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

### Task S3 — Human Gate audit payload completeness

- **Scope:** Preserve explicit `attempt` and `max_attempts` before and after a human-authorized decision where applicable, so the audit trail is reconstructable without chat history.
- **Completion criterion:** Each Human Gate audit evidence payload contains the attempt counter and max_attempts at decision time; repeated decisions remain reconstructable from evidence alone.
- **Regression test:** A test that performs a `RETRY_ONCE` decision and asserts the audit payload records `attempt` and `max_attempts` before and after the authorized retry.

### Task S4 — Stale M4 comments/docstrings alignment

- **Scope:** Align any remaining comments/docstrings that describe the older ordering (`persist -> set max_attempts` or initial `PLANNED -> RUNNING` inside initial persistence) with the implemented ordering: `set authoritative max_attempts -> persist PLANNED -> prepare execution -> RUNNING`.
- **Completion criterion:** No comment/docstring contradicts the implemented ordering; `make check` and `lint-workflows` are clean.
- **Regression test:** No behavioral test; verification is by grep/manual review that comments match code, plus `make check`.

---

## 13. Current stop point (updated 2026-09-16)

> **FS-ASM runtime development has resumed at `6cb17d6`. LLMC is deferred and not integrated. M4 stabilization is in progress: Task S0 (worker activity-name collision) is done; the next atomic task is S2 (initial M4 run log / persistence ordering consistency, which has a preexisting failing test). M5 has NOT been started and is not to be started until M4 stabilization is complete and explicitly authorized.**
