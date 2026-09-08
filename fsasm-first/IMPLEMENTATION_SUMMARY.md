# FS-ASM Milestone 1 - Implementation Summary

## Overview

This document summarizes the implementation of **FS-ASM Milestone 1** - a deterministic File System as State Machine runtime built with Mistral Workflows orchestration.

## What Was Built

### Core Architecture

The implementation follows the **FS-ASM** (File System as State Machine) pattern with clear separation of concerns:

- **Domain Core** (`src/fsasm/`): Pure Python + Pydantic models for state, plans, tasks, verification, and transitions
- **Persistence** (`src/fsasm/persistence.py`): Filesystem JSON with atomic writes
- **Workflow Orchestration** (`src/workflows/fsasm_milestone_one.py`): Mistral Workflows-based deterministic control flow
- **Activities**: Filesystem I/O and heavy operations delegated to activities

### Domain Models (Pydantic)

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `GoalInput` | Workflow input | `goal: str`, `run_id: str \| None` |
| `Plan` | Execution plan | `plan_id: str`, `run_id: str`, `tasks: list[ChildTask]` |
| `ChildTask` | Atomic task unit | `task_id: str`, `sequence: int`, `status: TaskStatus`, `dependencies: list[str]` |
| `VerificationSpec` | Verification rules | `type: str`, `expected: str` |
| `VerificationResult` | Verification outcome | `status: PASS \| FAIL`, `checks: list[VerificationCheck]` |
| `EvidenceRecord` | Persistent evidence | `evidence_id: str`, `run_id: str`, `kind: str`, `payload: dict` |
| `RunState` | Runtime state | `run_id: str`, `status: RunStatus`, `plan: Plan \| None` |

### Status Enums

**RunStatus:**
- `CREATED` → `PLANNED` → `RUNNING` → `PASSED` \| `FAILED` \| `NEEDS_HUMAN`

**TaskStatus:**
- `PENDING` → `READY` → `RUNNING` → `PASSED` \| `FAILED` \| `BLOCKED` \| `NEEDS_HUMAN`

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
RunState Transition: CREATED → PLANNED (via transition_run())
    ↓
Persist Evidence Activity (pre-verification: plan, state)
    ↓
Final Verification Activity (with all evidence records)
    ↓
Persist Final State Activity (create verification evidence, transition to PASSED/FAILED)
    ↓
Return Structured Result
```

### Filesystem Layout

```
runtime/
└── runs/
    └── <run_id>/
        ├── state.json          # RunState persistence
        ├── plan.json           # Plan persistence
        ├── evidence/
        │   └── <evidence_id>.json  # EvidenceRecord files
        └── run.log.jsonl       # Append-only run log
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

## Key Implementation Details

### 1. Stub Planner

The `PlannerStub` creates exactly 3 deterministic tasks for any goal:

```python
TASK-001: Inspect and prepare input
TASK-002: Perform core action  
TASK-003: Verify and finalize result
```

No LLM calls are made in Milestone 1.

### 2. State Transitions

Explicit transition validation with `transition_run()`:

```python
# In fsasm_milestone_one.py
# RunState is created with CREATED status
state = RunState(
    run_id=run_id,
    goal=goal_input.goal,
    status=RunStatus.CREATED,  # Always starts as CREATED
    ...
)

# Then transition to PLANNED via explicit function
transition_run(state, RunStatus.PLANNED)
```

**Critical Fix:** RunState is now **always created as CREATED**, and transitions to PLANNED happen **exclusively** through `transition_run()`. This ensures proper state machine semantics where state changes only occur through explicit transition functions.

Illegal transitions raise `TransitionError`.

### 3. Evidence Validation & Verification Flow

**Critical Fix:** The verifier now **FAILs** when evidence list is empty:

```python
# In verifier.py
if evidence_records is not None and len(evidence_records) > 0:
    checks.append(VerificationCheck(
        check_name="Evidence records exist",
        passed=True,
        message=f"Found {len(evidence_records)} evidence records",
    ))
else:
    checks.append(VerificationCheck(
        check_name="Evidence records exist", 
        passed=False,
        message="No evidence records provided or list is empty",
    ))
```

**Verification Flow Fix:** Implemented a single coherent verification flow:

```
1. persist_evidence_activity -> creates pre-verification evidence (plan, state)
2. verify_run_activity -> FINAL verification with all evidence records
3. persist_final_state_activity -> 
   a. creates verification evidence with actual PASS/FAIL status
   b. transitions RUNNING -> PASSED/FAILED
   c. saves final state
```

This ensures **EvidenceRecords never document FAIL when the final run ends with PASS**. This was a critical inconsistency that has been resolved.

### 4. Atomic Persistence

All mutable state writes use atomic file operations:

```python
# Write to temp file
fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
with os.fdopen(fd, "w") as f:
    json.dump(data, f)
    f.flush()
    os.fsync(f.fileno())
# Atomic rename
os.replace(temp_path, path)
```

### 5. Mistral Workflows Integration

- Workflow code is **deterministic**
- Filesystem I/O belongs in **activities**
- No direct `open()`, network calls, or environment lookups in workflow logic
- Uses `@workflow.define` decorator pattern
- Imports wrapped in `workflow.unsafe.imports_passed_through()` for sandbox compatibility

---

## Test Coverage

### Unit Tests (157 passed)

| Test File | Coverage |
|-----------|----------|
| `test_models.py` | Pydantic validation, model creation |
| `test_transitions.py` | Legal/illegal state transitions |
| `test_persistence.py` | Atomic save/load, file operations |
| `test_planner_stub.py` | Deterministic 3-task plan generation |
| `test_verifier.py` | All verification checks, PASS/FAIL cases |
| `test_fsasm_workflow.py` | Workflow integration, file system verification, **workflow-level test** |

### Key Test Scenarios

1. **Input Validation**: Blank goals rejected, minimal input accepted
2. **Plan Validation**: Exactly 3 tasks, unique IDs, valid dependencies
3. **State Transitions**: Legal transitions allowed, illegal blocked
4. **Persistence**: Atomic writes, save/load roundtrip
5. **Evidence**: Records persisted separately from state
6. **End-to-End**: All required files created and validated
7. **Workflow-Level Test**: Real worker execution via `create_test_worker` and `start_workflow` API

### Workflow-Level Integration Test

```python
@pytest.mark.asyncio
async def test_workflow_level_execution_with_test_worker(self, temporal_env):
    """
    Real workflow-level test using Mistral Workflows testing utilities.
    Uses create_test_worker to start a real worker and execute via API.
    """
    async with create_test_worker(
        temporal_env,
        workflows=[FsasmMilestoneOneWorkflow],
        activities=[create_input_activity, plan_activity, ...],
    ):
        handle = await temporal_env.client.start_workflow(
            "fsasm-milestone-one",
            {"goal": "Test workflow level execution"},
            id="test-fsasm-workflow-level",
            task_queue="test-task-queue",
            execution_timeout=timedelta(seconds=10),
        )
        result = await asyncio.wait_for(handle.result(), timeout=15)
        assert result["status"] == "PASSED"
        assert result["task_count"] == 3
        assert result["evidence_count"] > 0
```

This test follows the pattern from `.agents/skills/workflows/references/guides/testing.md` and uses the proper Mistral Workflows testing utilities rather than calling `workflow.run()` directly.

---

## Definition of Done - Milestone 1

All **14 criteria** from AGENTS.md are satisfied:

- ✅ 1. Goal can be submitted to FS-ASM workflow
- ✅ 2. Deterministic planner creates exactly 3 ChildTasks
- ✅ 3. All input/output models are Pydantic validated
- ✅ 4. RunState persisted to JSON
- ✅ 5. plan.json persisted separately
- ✅ 6. At least one EvidenceRecord persisted separately
- ✅ 7. Verification returns explicit PASS or FAIL
- ✅ 8. RunState cannot become PASSED without verification PASS
- ✅ 9. Runtime writes are atomic where state is mutable
- ✅ 10. Unit tests pass (157 passed)
- ✅ 11. Workflow-level test passes (using create_test_worker)
- ✅ 12. make check passes (ruff, mypy, semgrep)
- ✅ 13. No Mistral API key required for tests
- ✅ 14. hello-world workflow remains untouched

---

## Files Modified

```
fsasm-first/src/workflows/fsasm_milestone_one.py | +6 -12 (imports in sandbox pass-through, verification flow)
fsasm-first/src/fsasm/verifier.py                | +18 -2  (evidence validation fix)
fsasm-first/src/workflows/fsasm_milestone_one.py | +53 -44 (single coherent verification flow)
fsasm-first/tests/conftest.py                   | +11   (testing fixtures)
fsasm-first/tests/test_fsasm_workflow.py         | +163 -88 (workflow-level integration test)
fsasm-first/tests/test_verifier.py               | +16 -2  (evidence validation tests)
```

## Quality Checks

```bash
# All pass
uv run pytest tests/                    # 157 passed
make check                             # ruff, mypy, semgrep all pass
```

---

## What's Next (Milestone 2+)

The following are **NOT** implemented yet (per AGENTS.md scope):

- Real Mistral Planner (LLM-based planning)
- Executor + execution verification
- Bounded retry + Human Gate
- Context Builder / retrieval
- Local coding worker
- Model routing and fine-tuning

---

## Commit History

```
e0a38a0 feat: add real Mistral Workflows integration test using create_test_worker
bdf160d fix: resolve verification/evidence inconsistency with single coherent flow
12c0be2 fix: ensure RunState is created as CREATED and transitions to PLANNED via transition_run()
6777d85 docs: add implementation summary for Milestone 1
e9f8588 feat: add Mistral Workflows integration test with evidence validation
```

### Recent Fixes Summary

| Commit | Fix | Details |
|--------|-----|---------|
| `bdf160d` | Verification/Evidence Inconsistency | Single coherent flow: pre-verification evidence → final verification → verification evidence with correct status |
| `12c0be2` | CREATED → PLANNED Transition | RunState always created as CREATED, transition via `transition_run()` only |
| `e0a38a0` | Workflow-Level Test | Added real integration test using `create_test_worker` and `start_workflow` API |

---

## Core Invariant Preserved

> **The LLM may propose, interpret, generate and request actions. It must not be the sole authority for deterministic state, permissions, verification, retry limits or completion.**

✅ **SATISFIED**: All deterministic control remains in code. No LLM calls in Milestone 1. Domain rules enforce all state transitions and validations.
