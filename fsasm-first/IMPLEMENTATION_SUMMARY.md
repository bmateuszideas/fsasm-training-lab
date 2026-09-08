# FS-ASM Implementation Summary - Milestone 1 & 2

## Overview

This document summarizes the implementation of **FS-ASM Milestone 1** (deterministic stub planner) and **Milestone 2** (real Mistral Planner integration).

## Status

- **Milestone 1**: CLOSED ✅
- **Milestone 2**: CLOSED ✅

## What Was Built

### Core Architecture

The implementation follows the **FS-ASM** (File System as State Machine) pattern with clear separation of concerns:

- **Domain Core** (`src/fsasm/`): Pure Python + Pydantic models for state, plans, tasks, verification, and transitions
- **Persistence** (`src/fsasm/persistence.py`): Filesystem JSON with atomic writes
- **Workflow Orchestration** (`src/workflows/fsasm_milestone_one.py`, `fsasm_milestone_two.py`): Mistral Workflows-based deterministic control flow
- **Activities**: Filesystem I/O, model calls, and heavy operations delegated to activities

### Domain Models (Pydantic)

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `GoalInput` | Workflow input | `goal: str`, `run_id: str | None` |
| `PlannerBackend` | Backend enum | `STUB`, `MISTRAL` |
| `PlannerConfig` | Backend configuration | `backend`, `model_name`, `prompt_version` |
| `PlannerProposal` | LLM semantic proposal | `tasks: list[TaskProposal]` (no runtime fields) |
| `TaskProposal` | Task semantic proposal | `title`, `description`, `dependencies: list[int]` (sequence numbers) |
| `PlannerMetadata` | Observability metadata | `provider`, `requested_model`, `resolved_model`, `model_version`, `prompt_version`, `template_hash`, `rendered_hash`, `model_call_count`, `planner_invocation_count`, `input_tokens`, `output_tokens`, `total_tokens`, `provider_request_id`, `run_id` |
| `PlannerOutput` | Complete planner output | `proposal`, `plan`, `metadata` |
| `Plan` | Execution plan | `plan_id: str`, `run_id: str`, `goal: str`, `tasks: list[ChildTask]` |
| `ChildTask` | Atomic task unit | `task_id: str`, `sequence: int`, `status: TaskStatus`, `dependencies: list[str]` |
| `VerificationSpec` | Verification rules | `type: VerificationType`, `expected: str` |
| `VerificationResult` | Verification outcome | `status: PASS | FAIL`, `checks: list[VerificationCheck]` |
| `EvidenceRecord` | Persistent evidence | `evidence_id: str`, `run_id: str`, `kind: str`, `payload: dict` |
| `RunState` | Runtime state | `run_id: str`, `status: RunStatus`, `plan: Plan | None` |

### Status Enums

**RunStatus:**
- `CREATED` → `PLANNED` → `RUNNING` → `PASSED` | `FAILED` | `NEEDS_HUMAN`

**TaskStatus:**
- `PENDING` → `READY` → `RUNNING` → `PASSED` | `FAILED` | `BLOCKED` | `NEEDS_HUMAN`

---

## Milestone 1 - Deterministic Stub Planner

### Workflow Control Flow

```
Workflow Entry Point
    ↓
create/normalize GoalInput
    ↓
Planner Stub Activity (deterministic, creates exactly 3 tasks)
    ↓
Validate Plan (Pydantic + domain rules)
    ↓
Persist Plan & State Activity (RunState created as CREATED)
    ↓
RunState Transition: CREATED → PLANNED (via transition_run() in activity)
    ↓
Persist Evidence Activity (pre-verification: plan, state)
    ↓
Final Verification Activity (with all evidence records)
    ↓
Persist Final State Activity (create verification evidence, transition to PASSED/FAILED)
    ↓
Return Structured Result
```

### Deterministic Verifier Checks

The verifier performs the following checks:

1. ✅ Valid `Plan` exists
2. ✅ Contains exactly 3 `ChildTask` instances
3. ✅ Task IDs are unique
4. ✅ Dependency references point to valid tasks
5. ✅ State and plan share the same `run_id`
6. ✅ **Evidence records exist and are non-empty** (critical fix)
7. ✅ Final workflow result is unambiguously `PASS` or `FAIL`

---

## Milestone 2 - Real Mistral Planner

### Key Features

- **Structured Output**: LLM returns only semantic `PlannerProposal` with `TaskProposal` (no runtime-owned fields)
- **Deterministic Assembler**: `assemble_plan()` assigns all runtime fields (run_id, plan_id, task_id, sequence, status, etc.)
- **Single Model Call**: Exactly one model call per planning operation, both proposal and token usage from same response
- **Explicit Backend**: No silent fallback - `WorkflowInput` requires explicit `planner_backend` (STUB or MISTRAL)
- **Dependency Validation**: Strict validation `1 <= dep_seq < current_task_sequence` prevents 0, self-dependency, future dependencies, cycles
- **Observability**: Full metadata with provider, model, prompt version, hashes, token usage, provider_request_id

### Architecture

```
GoalInput
    ↓
Planner Activity (backend-agnostic)
    ↓
plan_with_stub() OR plan_with_mistral()
    ↓
PlannerProposal (semantic, LLM output for Mistral)
    ↓
assemble_plan() (deterministic, same for both backends)
    ↓
Plan (runtime-owned, all fields assigned)
    ↓
PlannerOutput (proposal + plan + metadata)
```

### Planner Backend

**`PlannerBackend`**: Enum with two values:
- `STUB`: Deterministic stub planner (no API calls)
- `MISTRAL`: Real Mistral API planner

**`PlannerConfig`**: Configuration for the planner:
- `backend`: `PlannerBackend.STUB` or `PlannerBackend.MISTRAL`
- `model_name`: Model identifier (e.g., "mistral-large-latest")
- `prompt_version`: Template version used

### Planner Models

**`PlannerProposal`**: Semantic proposal from LLM (no runtime-owned fields):
- `tasks: list[TaskProposal]` - List of task proposals

**`TaskProposal`**: Individual task proposal:
- `title: str` - Task title
- `description: str` - Task description
- `dependencies: list[int]` - Dependency sequence numbers (proposal-local, not runtime task IDs)
- `verification_type: str` - Verification type
- `verification_expected: str` - Expected verification result
- `constraints: list[str]` - Task constraints
- `allowed_files: list[str]` - Allowed files for the task
- `expected_evidence: list[str]` - Expected evidence

**`PlannerMetadata`**: Complete observability metadata:
- `provider: str` - "stub" or "mistral"
- `requested_model: str | None` - Requested model name
- `resolved_model: str | None` - Actually resolved model name
- `model_version: str | None` - Model version if available
- `prompt_version: str` - Template version used
- `template_hash: str` - SHA256 of prompt template
- `rendered_hash: str` - SHA256 of rendered prompt (with goal)
- `model_call_count: int` - 0 for stub, 1 for mistral
- `planner_invocation_count: int` - Number of planner invocations
- `input_tokens: int | None` - Input tokens used
- `output_tokens: int | None` - Output tokens used
- `total_tokens: int | None` - Total tokens used
- `provider_request_id: str | None` - Provider-specific request ID (e.g., Mistral `response.id`)
- `run_id: str` - Traceability to the run

### Dependency Validation in assemble_plan()

The assembler validates that all dependencies satisfy: **`1 <= dep_seq < current_task_sequence`**

This prevents:
- ❌ `dep_seq = 0` (no task with sequence 0)
- ❌ Self-dependency (Task 2 → [2])
- ❌ Future dependency (Task 1 → [2])
- ❌ Dependencies beyond task count (dep_seq = 4 for 3 tasks)
- ❌ Cycles (automatically prevented by the rule)

All invalid dependencies raise `ValueError` with clear error message - **never KeyError**.

### Single Assembler

Both STUB and Mistral backends use **exactly the same** `assemble_plan()` function:
- Deterministic mapping from proposal-local sequence numbers to runtime task IDs
- All runtime-owned fields assigned by assembler, not by LLM
- Authoritative `Plan.goal` always comes from `GoalInput.goal`
- Runtime task IDs follow pattern: `TASK-001`, `TASK-002`, `TASK-003`, ...

---

## Workflow-Level Tests

Both Milestone 1 and Milestone 2 have real workflow-level tests using Mistral Workflows testing utilities:

| Workflow | Test | Backend | Status |
|----------|------|---------|--------|
| M1 | `test_workflow_level_execution_with_test_worker` | STUB | ✅ |
| M2 | `test_workflow_level_execution_with_test_worker` | STUB | ✅ |

Both tests use:
- `create_test_worker` to start a real worker
- `temporal_env.client.start_workflow(...)` to execute through the API
- `asyncio.wait_for(handle.result(), ...)` for result waiting
- All activities properly registered
- No paid API calls (STUB backend)

---

## Test Results

```
202 passed, 3 skipped, 388 warnings
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

---

## What's Next (Milestone 3)

The following are **NOT** implemented yet (per AGENTS.md scope):

- Executor + execution verification
- Bounded retry + Human Gate
- Context Builder / retrieval
- Local coding worker
- Model routing and fine-tuning

---

## Commit History

```
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

✅ **SATISFIED**: All deterministic control remains in code. Domain rules enforce all state transitions and validations. LLM provides semantic proposals only (PlannerProposal for Mistral, deterministic tasks for STUB). Both backends use the same deterministic assembler.
