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
Persist Plan & State Activity
    ↓
RunState Transition: CREATED → PLANNED
    ↓
Verification Activity (deterministic checks)
    ↓
Persist Evidence Activity
    ↓
Re-run Verification with Evidence Records
    ↓
Persist Final State & Log Activity
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
if state.status == RunStatus.CREATED:
    transition_run(state, RunStatus.PLANNED)
```

Illegal transitions raise `TransitionError`.

### 3. Evidence Validation

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

---

## Test Coverage

### Unit Tests (156 passed)

| Test File | Coverage |
|-----------|----------|
| `test_models.py` | Pydantic validation, model creation |
| `test_transitions.py` | Legal/illegal state transitions |
| `test_persistence.py` | Atomic save/load, file operations |
| `test_planner_stub.py` | Deterministic 3-task plan generation |
| `test_verifier.py` | All verification checks, PASS/FAIL cases |
| `test_fsasm_workflow.py` | Workflow integration, file system verification |

### Key Test Scenarios

1. **Input Validation**: Blank goals rejected, minimal input accepted
2. **Plan Validation**: Exactly 3 tasks, unique IDs, valid dependencies
3. **State Transitions**: Legal transitions allowed, illegal blocked
4. **Persistence**: Atomic writes, save/load roundtrip
5. **Evidence**: Records persisted separately from state
6. **End-to-End**: All required files created and validated

### Integration Test

```python
@pytest.mark.asyncio
async def test_end_to_end_files_created(self, workflow_module):
    """Test that workflow creates all required files"""
    result = await workflow.run(input_data)
    
    # Verify state.json
    assert state_path.exists()
    assert state_data["run_id"] == result["run_id"]
    
    # Verify plan.json  
    assert plan_path.exists()
    assert len(plan_data["tasks"]) == 3
    
    # Verify evidence/*.json
    assert len(evidence_files) > 0
    
    # Verify run.log.jsonl
    assert run_log_path.exists()
```

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
- ✅ 10. Unit tests pass (156 passed)
- ✅ 11. Workflow-level test passes
- ✅ 12. make check passes (ruff, mypy, semgrep)
- ✅ 13. No Mistral API key required for tests
- ✅ 14. hello-world workflow remains untouched

---

## Files Modified

```
fsasm-first/src/fsasm/verifier.py                | +18 -2  (evidence validation fix)
fsasm-first/src/workflows/fsasm_milestone_one.py |  +8   (state transition + re-verification)
fsasm-first/tests/test_fsasm_workflow.py         | +163 -88 (integration tests)
fsasm-first/tests/test_verifier.py               | +16 -2  (evidence validation tests)
```

## Quality Checks

```bash
# All pass
uv run pytest tests/                    # 156 passed
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
e9f8588 feat: add Mistral Workflows integration test with evidence validation
```

Changes:
- Add end-to-end test for state.json, plan.json, evidence/*.json
- Fix verifier to FAIL when evidence list is empty
- Add transition_run() call: CREATED → PLANNED
- Re-run verification with actual evidence records
- Update tests to match new behavior

---

## Core Invariant Preserved

> **The LLM may propose, interpret, generate and request actions. It must not be the sole authority for deterministic state, permissions, verification, retry limits or completion.**

✅ **SATISFIED**: All deterministic control remains in code. No LLM calls in Milestone 1. Domain rules enforce all state transitions and validations.
