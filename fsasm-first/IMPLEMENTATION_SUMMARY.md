# FS-ASM Implementation Summary - Milestone 1, 2, 3 & 4

## Overview

This document summarizes the implementation of **FS-ASM Milestone 1** (deterministic stub planner), **Milestone 2** (real Mistral Planner integration), **Milestone 3** (Executor + execution verification for ONE eligible ChildTask), and **Milestone 4** (Bounded Retry + Human Gate).

## Status

- **Milestone 1**: CLOSED \u2705
- **Milestone 2**: CLOSED \u2705
- **Milestone 3**: CLOSED \u2705
- **Milestone 4**: CLOSED \u2705

## What Was Built

### Core Architecture

The implementation follows the **FS-ASM** (File System as State Machine) pattern with clear separation of concerns:

- **Domain Core** (`src/fsasm/`): Pure Python + Pydantic models for state, plans, tasks, verification, and transitions
- **Persistence** (`src/fsasm/persistence.py`): Filesystem JSON with atomic writes
- **Workflow Orchestration** (`src/workflows/fsasm_milestone_one.py`, `fsasm_milestone_two.py`, `fsasm_milestone_three.py`): Mistral Workflows-based deterministic control flow
- **Activities**: Filesystem I/O, model calls, and heavy operations delegated to activities

### Domain Models (Pydantic)

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `GoalInput` | Workflow input | `goal: str`, `run_id: str \| None` |
| `PlannerBackend` | Backend enum | `STUB`, `MISTRAL` |
| `PlannerConfig` | Backend configuration | `backend`, `model_name`, `prompt_version` |
| `PlannerProposal` | LLM semantic proposal | `tasks: list[TaskProposal]` (no runtime fields) |
| `TaskProposal` | Task semantic proposal | `title`, `description`, `dependencies: list[int]` (sequence numbers) |
| `PlannerMetadata` | Observability metadata | `provider`, `requested_model`, `resolved_model`, `model_version`, `prompt_version`, `template_hash`, `rendered_hash`, `model_call_count`, `planner_invocation_count`, `input_tokens`, `output_tokens`, `total_tokens`, `provider_request_id`, `run_id` |
| `PlannerOutput` | Complete planner output | `proposal`, `plan`, `metadata` |
| `Plan` | Execution plan | `plan_id: str`, `run_id: str`, `goal: str`, `tasks: list[ChildTask]` |
| `ChildTask` | Atomic task unit | `task_id: str`, `sequence: int`, `status: TaskStatus`, `dependencies: list[str]` |
| `VerificationSpec` | Verification rules | `type: VerificationType`, `expected: str` |
| `VerificationResult` | Verification outcome | `status: PASS \| FAIL`, `checks: list[VerificationCheck]` |
| `EvidenceRecord` | Persistent evidence | `evidence_id: str`, `run_id: str`, `kind: str`, `payload: dict` |
| `RunState` | Runtime state | `run_id: str`, `status: RunStatus`, `plan: Plan \| None` |
| `ExecutorBackend` | Executor backend enum | `STUB`, `LOCAL`, `MISTRAL` |
| `ExecutorConfig` | Executor configuration | `backend`, `model_name`, `max_tokens`, `temperature` |
| `ExecutorMetadata` | Executor observability | `run_id`, `task_id`, `provider`, `model_call_count`, `executor_invocation_count`, `input_tokens`, `output_tokens`, `total_tokens`, `provider_request_id` |
| `ExecutorOutput` | Executor result (CLAIM/RESULT) | `task_id`, `run_id`, `result`, `metadata: ExecutorMetadata` |

### Status Enums

**RunStatus:**
- `CREATED` \u2192 `PLANNED` \u2192 `RUNNING` \u2192 `PASSED` \| `FAILED` \| `NEEDS_HUMAN`

**TaskStatus:**
- `PENDING` \u2192 `READY` \u2192 `RUNNING` \u2192 `PASSED` \| `FAILED` \| `BLOCKED` \| `NEEDS_HUMAN`

---

## Milestone 1 - Deterministic Stub Planner

### Workflow Control Flow

```
Workflow Entry Point
    \u2193
create/normalize GoalInput
    \u2193
Planner Stub Activity (deterministic, creates exactly 3 tasks)
    \u2193
Validate Plan (Pydantic + domain rules)
    \u2193
Persist Plan & State Activity (RunState created as CREATED)
    \u2193
RunState Transition: CREATED \u2192 PLANNED (via transition_run() in activity)
    \u2193
Persist Evidence Activity (pre-verification: plan, state)
    \u2193
Final Verification Activity (with all evidence records)
    \u2193
Persist Final State Activity (create verification evidence, transition to PASSED/FAILED)
    \u2193
Return Structured Result
```

### Deterministic Verifier Checks

The verifier performs the following checks:

1. \u2705 Valid `Plan` exists
2. \u2705 Contains exactly 3 `ChildTask` instances
3. \u2705 Task IDs are unique
4. \u2705 Dependency references point to valid tasks
5. \u2705 State and plan share the same `run_id`
6. \u2705 **Evidence records exist and are non-empty** (critical fix)
7. \u2705 Final workflow result is unambiguously `PASS` or `FAIL`

---

## Milestone 2 - Real Mistral Planner

### Key Features

- **Structured Output**: LLM returns only semantic `PlannerProposal` with `TaskProposal` (no runtime-owned fields)
- **Deterministic Assembler**: `assemble_plan()` assigns all runtime fields (run_id, plan_id, task_id, sequence, status, etc.)
- **Single Model Call**: Exactly one model call per planning operation, both proposal and token usage from same response
- **Explicit Backend**: No silent fallback - `WorkflowInput` requires explicit `planner_backend` (STUB or MISTRAL)
- **Dependency Validation**: Strict validation `1 <= dep_seq < current_task_sequence` prevents 0, self-dependency, future dependencies, cycles
- **Observability**: Full metadata with provider, model, prompt version, hashes, token usage, provider_request_id

---

## Milestone 3 - Executor + Execution Verification

### Key Features

- **Executor Stub**: Deterministic stub executor that produces `ExecutorOutput` (CLAIM/RESULT) with 0 model API calls
- **ExecutorOutput is separate from Evidence**: Executor produces claims, which are converted to EvidenceRecord with provenance validation
- **Provenance Validation**: Before converting ExecutorOutput to EvidenceRecord, validate:
  - `executor_output.task_id == expected_task_id`
  - `executor_output.metadata.task_id == expected_task_id`
  - `executor_output.metadata.run_id == expected_run_id`
- **Evidence Conversion**: Deterministic conversion of ExecutorOutput to EvidenceRecord(s):
  - If `task.expected_evidence` is empty: create one fallback evidence with kind `executor_output`
  - Otherwise: create one EvidenceRecord per declared expected evidence kind
  - Uses deterministic safe IDs (ordinal counters) while keeping original evidence kind as data
- **Task-Level Verification**: Verifies task execution using:
  - authoritative `run_id`
  - `ChildTask`
  - `list[EvidenceRecord]`
  - Evidence must match BOTH: `evidence.run_id == authoritative run_id` AND `evidence.task_id == task.task_id`
  - Requires ALL declared expected evidence kinds to be present
- **State Persistence**: All state transitions persisted to filesystem:
  - `prepare_task_activity`: Sets task RUNNING, active_task_id, persists state + plan
  - `finalize_task_activity`: Sets task PASSED/FAILED, clears active_task_id, persists evidence + verification result

### Workflow Control Flow (M3)

```
Workflow Entry Point
    \u2193
Validate configuration (executor_backend must be STUB for M3)
    \u2193
Create/normalize input
    \u2193
Planner activity (Mistral or Stub backend)
    \u2193
Persist initial state (PLANNED \u2192 RUNNING)
    \u2193
Find first eligible task (PENDING \u2192 READY)
    \u2193
Prepare task (READY \u2192 RUNNING, set active_task_id, persist state)
    \u2193
Execute task (produces ExecutorOutput)
    \u2193
Validate ExecutorOutput provenance
    \u2193
Convert ExecutorOutput to EvidenceRecord(s)
    \u2193
Verify task execution
    \u2193
Finalize task (PASSED/FAILED, clear active_task_id, persist)
    \u2193
Persist final state
    \u2193
Return structured result
```

### Key Invariants Proven by M3

- **Exactly ONE task is executed**
- **After execution**: executed task = PASSED or FAILED, other tasks remain PENDING
- **RunState remains RUNNING** (not transitioned to PASSED/FAILED)
- **All state transitions use transition API**
- **Evidence is separate from ExecutorOutput**
- **Verifier receives EvidenceRecord, not ExecutorOutput**
- **ExecutorOutput provenance validated before evidence conversion**
- **Evidence must match both run_id AND task_id**
- **All expected evidence kinds must be present**

### M3 Evidence Model

For deterministic M3 stub execution:
- Evidence is runtime-captured deterministic stub evidence
- NOT yet independent real-world proof
- Future real Executors should provide independently observable evidence (test output, filesystem state, diffs, tool output, etc.)

---

## Test Results

```
260 passed, 3 skipped, 634 warnings
make check: All checks passed! (ruff, mypy, semgrep)
```

---

## Files Modified

### Milestone 1
- `src/fsasm/models.py` - Core domain models
- `src/fsasm/planner.py` - Stub planner
- `src/fsasm/verifier.py` - Deterministic verifier
- `src/fsasm/persistence.py` - Filesystem persistence
- `src/fsasm/transitions.py` - State transition functions
- `src/workflows/fsasm_milestone_one.py` - M1 workflow
- `tests/test_fsasm_workflow.py` - M1 workflow-level test with create_test_worker

### Milestone 2
- `src/fsasm/models.py` - PlannerProposal, TaskProposal, PlannerMetadata, PlannerConfig, PlannerOutput
- `src/fsasm/planner.py` - assemble_plan(), async PlannerStub
- `src/fsasm/planner_activities.py` - plan_with_stub(), plan_with_mistral(), prompt templates
- `src/fsasm/transitions.py` - transition_run(), transition_task() in activities
- `src/fsasm/errors.py` - ConfigurationError
- `src/workflows/fsasm_milestone_two.py` - M2 workflow with explicit backend
- `tests/test_fsasm_milestone_two.py` - M2 workflow tests + workflow-level test with create_test_worker
- `tests/test_planner_activities.py` - Assembler tests + dependency validation tests
- `tests/test_mistral_planner.py` - Mistral activity unit tests (mocked)
- `tests/test_mistral_live.py` - Live smoke tests (opt-in only)
- `Makefile` - Added test target, expanded check scope

### Milestone 4
- `src/workflows/fsasm_milestone_four.py` - M4 workflow with bounded retry + Human Gate
- `src/fsasm/executor_activities.py` - New activities:
  - `check_retry_budget_activity` - Check if task can retry
  - `transition_to_needs_human_activity` - Transition task to NEEDS_HUMAN with logging
- `tests/test_fsasm_milestone_four.py` - M4 workflow tests including WorkflowInput validation, activity tests, retry logic tests, Human Gate tests, RunStatus transition tests

### Milestone 3
- `src/fsasm/models.py` - ExecutorBackend, ExecutorConfig, ExecutorMetadata, ExecutorOutput
- `src/fsasm/executor.py` - ExecutorStub with deterministic execution
- `src/fsasm/executor_activities.py` - All executor activities:
  - `execute_task_activity` - Execute task with STUB backend
  - `validate_executor_output_provenance_activity` - Provenance validation
  - `convert_executor_output_to_evidence_activity` - Convert to EvidenceRecord(s)
  - `verify_task_execution_activity` - Task-level verification
  - `prepare_task_activity` - Prepare task (RUNNING status, persist)
  - `finalize_task_activity` - Finalize task (PASSED/FAILED, persist)
- `src/fsasm/errors.py` - ProvenanceValidationError
- `src/workflows/fsasm_milestone_three.py` - M3 workflow
- `tests/test_executor.py` - Executor models and stub tests (19 tests)
- `tests/test_executor_activities.py` - Executor activity tests including RUNNING SEMANTICS regression tests (21 tests)
- `tests/test_fsasm_milestone_three.py` - M3 workflow tests + workflow-level test with create_test_worker including REAL WORKER EVIDENCE COUNT verification (22 tests)

---

## What M3 Proves

Milestone 3 proves the complete execution path for ONE eligible ChildTask:

**PENDING -> READY -> RUNNING -> PASSED/FAILED**

With the following invariants:
- Exactly ONE task is executed per workflow run
- After execution: executed task = PASSED or FAILED, remaining tasks remain PENDING
- RunState remains RUNNING (not transitioned to PASSED/FAILED)
- All state transitions use the transition API
- Evidence is separate from ExecutorOutput
- Verifier receives EvidenceRecord, not ExecutorOutput
- Executor never authorizes its own PASS
- Verification checks: run_id match, task_id match, expected evidence kinds, VerificationSpec.expected
- Complete provenance validation: executor_output.task_id, executor_output.run_id, metadata.task_id, metadata.run_id
- Safe evidence IDs: deterministic ordinal-only (no LLM content embedded)
- Durable state correctness: state.json and plan.json always agree
---

## What's Next (Milestone 5)

The following are **NOT** implemented yet (per AGENTS.md scope):

- Context Builder / retrieval
- Local coding worker
- Model routing and fine-tuning

**Explicit statement**: Retries and Human Gate are implemented in Milestone 4. M3 proves exactly ONE task execution with PENDING -> READY -> RUNNING -> PASSED/FAILED path. M4 extends this with bounded retry and Human Gate escalation.

---

## Milestone 4 Implementation

### Key Features

- **Bounded Retry**: Tasks can retry up to `max_retries_per_task` times (configurable, default=2)
- **Human Gate**: When retry budget is exhausted, tasks transition to `NEEDS_HUMAN` status
- **Retry Loop**: FAILED -> READY (retry) -> RUNNING -> FAILED/NEEDS_HUMAN
- **State Persistence**: All retry attempts and Human Gate invocations are persisted
- **Workflow Configuration**: `max_retries_per_task` parameter controls retry behavior

### Workflow Control Flow (M4)

```
Workflow Entry Point
    \u2193
Validate configuration (executor_backend must be STUB for M4)
    \u2193
Create/normalize input
    \u2193
Planner activity (Mistral or Stub backend)
    \u2193
Persist initial state (PLANNED \u2192 RUNNING)
    \u2193
Find first eligible task (PENDING \u2192 READY)
    \u2193
Prepare task (READY \u2192 RUNNING, set active_task_id, persist state)
    \u2193
Execute task (produces ExecutorOutput)
    \u2193
Validate ExecutorOutput provenance
    \u2193
Convert ExecutorOutput to EvidenceRecord(s)
    \u2193
Verify task execution
    \u2193
If PASS: Finalize task (PASSED, clear active_task_id, persist)
    \u2193
If FAIL: Check retry budget
        \u251c\u2500\u2500 Can retry: Transition to READY, increment attempt, loop back
        \u2514\u2500\u2500 Exhausted: Transition to NEEDS_HUMAN (Human Gate)
    \u2193
Persist final state
    \u2193
Return structured result
```

### Key Invariants Proven by M4

- **Bounded retry**: Tasks can retry at most `max_retries_per_task` times
- **Human Gate escalation**: When retry budget exhausted, task transitions to NEEDS_HUMAN
- **NEEDS_HUMAN is terminal**: No outgoing transitions from NEEDS_HUMAN
- **RunState reflects Human Gate**: If any task is NEEDS_HUMAN, RunState becomes NEEDS_HUMAN
- **Evidence preserved**: All retry attempts and Human Gate decisions are logged
- **Atomic state updates**: State and plan always agree, persisted atomically

### M4 Evidence Model

- Retry attempts are logged with attempt number and reason
- Human Gate invocation creates evidence with reason
- Final execution summary includes retry count and Human Gate status

---

## Commit History

```
# M4 Commit Chain
[NEW] Implement Milestone 4 - Bounded Retry + Human Gate

# M3 Commit Chain
4e8927e fix: address remaining 3 M3 audit issues - RUNNING SEMANTICS, ACTIVITY SERIALIZATION/EVIDENCE COUNT, DOMAIN VERIFIER BOUNDARY
9fb3c95 fix: address remaining 4 M3 audit issues - required backends, .gitignore, VerificationSpec satisfaction, duplicate persistence fix
2cfb696 fix: address all 10 M3 audit issues - plan staleness, safe evidence IDs, VerificationSpec check, provenance, fallback, retries, dependencies, transition API, config consistency, runtime .gitignore
79251fa feat: implement Milestone 3 - Executor + execution verification for ONE eligible ChildTask

# M2 Commit Chain
fc8addf fix: restore M2 workflow-level test, fix Makefile duplicate test target, fix UTF-8 in live tests, update IMPLEMENTATION_SUMMARY.md
a845ffc fix: final M2 cleanup - remove duplicate test, update Makefile .PHONY, remove direct-run live workflow test, update IMPLEMENTATION_SUMMARY.md
7c7a6c5 fix: M2 fix-pass - address all acceptance criteria
2ff50b1 feat: implement Milestone 2 - Real Mistral Planner integration
2ec832f docs: update IMPLEMENTATION_SUMMARY.md with recent fixes
e0a38a0 feat: add real Mistral Workflows integration test using create_test_worker
bdf160d fix: resolve verification/evidence inconsistency with single coherent flow
12c0be2 fix: ensure RunState is created as CREATED and transitions to PLANNED via transition_run()
6777d85 docs: add implementation summary for Milestone 1
e9f8588 feat: add Mistral Workflows integration test with evidence validation
5f6fdff feat: Complete FS-ASM Milestone 1 implementation
```

---

## Core Invariant Preserved

> **The LLM may propose, interpret, generate and request actions. It must not be the sole authority for deterministic state, permissions, verification, retry limits or completion.**

\u2705 **SATISFIED**: All deterministic control remains in code. Domain rules enforce all state transitions and validations. LLM provides semantic proposals only (PlannerProposal for Mistral, deterministic tasks for STUB). Both backends use the same deterministic assembler. Executor produces claims that are validated and converted to evidence - the verifier receives EvidenceRecord, not ExecutorOutput.
