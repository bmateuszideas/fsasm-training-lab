"""Regression test for F2: state.json / plan.json consistency after retry persistence.

The confirmed defect F2: `persist_retry_state_activity` updated the separate
`plan` argument but wrote `state` (carrying `state.plan`) and `plan`
independently. In the real worker, activity arguments cross the serialization
boundary, so `state.plan` and the `plan` argument are independent objects.
Updating only `plan` left `state.json` (which embeds `state.plan`) stale
relative to `plan.json`:

    state.json: state.plan.tasks[TASK-001].status = FAILED
    plan.json:  tasks[TASK-001].status = READY

A plain in-process activity call shares references and hides the bug. This
test forces an independent serialization round-trip (Pydantic JSON) before
calling the activity - exactly what Temporal's worker produces - so the
defect is observable in the persisted files.
"""

import pydantic
import pytest

from fsasm.models import (
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence
from fsasm.transitions import transition_task

import workflows.fsasm_milestone_four as m4_module
from workflows.fsasm_milestone_four import persist_retry_state_activity


def _roundtrip(obj):
    """Independent copy via JSON round-trip, as Temporal argument serialization."""
    return pydantic.TypeAdapter(type(obj)).validate_json(obj.model_dump_json())


def _build_failed_state(run_id: str):
    """A run state with TASK-001 already FAILED (attempt=1, max_attempts=3)."""
    t1 = ChildTask(
        task_id="TASK-001",
        sequence=1,
        title="Task 1",
        description="First task",
        status=TaskStatus.FAILED,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        dependencies=[],
        max_attempts=3,
        attempt=1,
    )
    t2 = ChildTask(
        task_id="TASK-002",
        sequence=2,
        title="Task 2",
        description="Second task",
        status=TaskStatus.PENDING,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        dependencies=["TASK-001"],
        max_attempts=3,
    )
    t3 = ChildTask(
        task_id="TASK-003",
        sequence=3,
        title="Task 3",
        description="Third task",
        status=TaskStatus.PENDING,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        dependencies=["TASK-002"],
        max_attempts=3,
    )
    plan = Plan(
        plan_id="plan-f2",
        run_id=run_id,
        goal="Test goal",
        tasks=[t1, t2, t3],
    )
    state = RunState(
        run_id=run_id,
        goal="Test goal",
        status=RunStatus.RUNNING,
        plan=plan,
        active_task_id="TASK-001",
        completed_task_ids=[],
        failed_task_ids=["TASK-001"],
    )
    return state, plan, t1


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    """Redirect persistence to an isolated tmp_path directory.

    The activity under test instantiates ``RuntimePersistence()`` itself, so we
    monkeypatch the ``RuntimePersistence`` symbol in the workflow module to a
    factory that always points at this test's ``tmp_path``. This never touches
    the global ``./runtime`` directory or any real run data.
    """
    runtime_dir = tmp_path / "runtime"

    def _factory(*args, **kwargs):
        kwargs.setdefault("runtime_dir", runtime_dir)
        return RuntimePersistence(*args, **kwargs)

    monkeypatch.setattr(m4_module, "RuntimePersistence", _factory)
    yield runtime_dir


@pytest.mark.asyncio
async def test_persist_retry_state_keeps_state_json_and_plan_json_consistent(
    _isolated_runtime,
):
    """F2: state.json.plan and plan.json must agree after retry persistence.

    Arguments are forced through an independent JSON round-trip so that
    `state.plan` and the `plan` arg are NOT the same object, matching the real
    worker. The test reads the persisted files, not the returned objects.
    """
    run_id = "f2-regression"
    state, plan, task = _build_failed_state(run_id)

    # Independent copies, as the worker would deliver to the activity.
    state_indep = _roundtrip(state)
    plan_indep = _roundtrip(plan)
    task_indep = _roundtrip(task)

    # Prove independence; otherwise the test would not exercise F2.
    assert state_indep.plan is not plan_indep
    assert state_indep.plan.tasks[0] is not plan_indep.tasks[0]
    assert state_indep.plan.tasks[0].status == TaskStatus.FAILED
    assert plan_indep.tasks[0].status == TaskStatus.FAILED

    # FAILED -> READY on the independent task copy (does NOT increment attempt).
    task_indep = transition_task(task_indep, TaskStatus.READY)
    assert task_indep.attempt == 1
    assert state_indep.plan.tasks[0].status == TaskStatus.FAILED
    assert plan_indep.tasks[0].status == TaskStatus.FAILED

    out_state, out_plan = await persist_retry_state_activity(
        state_indep, plan_indep, task_indep, "retry"
    )

    # Read back what was actually persisted, from the same isolated directory.
    persistence = RuntimePersistence(runtime_dir=_isolated_runtime)
    loaded_state = persistence.load_run_state(run_id)
    loaded_plan = persistence.load_plan(run_id)
    assert loaded_state is not None
    assert loaded_plan is not None

    s_task = loaded_state.plan.tasks[0]
    p_task = loaded_plan.tasks[0]

    # Required by F2: both files agree on status/attempt/max_attempts.
    assert s_task.status == TaskStatus.READY
    assert p_task.status == TaskStatus.READY
    assert s_task.attempt == p_task.attempt == 1
    assert s_task.max_attempts == p_task.max_attempts == 3

    # The returned objects must also be consistent (single source of truth).
    assert out_state.plan is not None
    assert out_plan is not None
    assert out_state.plan.tasks[0].status == TaskStatus.READY
    assert out_plan.tasks[0].status == TaskStatus.READY
    assert out_state.plan.tasks[0].attempt == out_plan.tasks[0].attempt == 1

    # Other tasks untouched.
    assert loaded_plan.tasks[1].status == TaskStatus.PENDING
    assert loaded_plan.tasks[2].status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_persist_retry_state_does_not_increment_attempt(
    _isolated_runtime,
):
    """F2 invariants: FAILED->READY does not increment attempt; the next
    READY->RUNNING increments exactly once."""
    run_id = "f2-attempt"
    state, plan, task = _build_failed_state(run_id)

    state_indep = _roundtrip(state)
    plan_indep = _roundtrip(plan)
    task_indep = _roundtrip(task)

    task_indep = transition_task(task_indep, TaskStatus.READY)
    assert task_indep.attempt == 1

    await persist_retry_state_activity(state_indep, plan_indep, task_indep, "retry")

    # Reload and simulate the next READY -> RUNNING transition on the persisted
    # authoritative task. It must increment attempt exactly once.
    persistence = RuntimePersistence(runtime_dir=_isolated_runtime)
    loaded_state = persistence.load_run_state(run_id)
    loaded_plan = persistence.load_plan(run_id)
    assert loaded_state is not None and loaded_plan is not None

    persisted_task = loaded_plan.tasks[0]
    assert persisted_task.status == TaskStatus.READY
    assert persisted_task.attempt == 1

    next_task = transition_task(persisted_task, TaskStatus.RUNNING)
    assert next_task.attempt == 2, (
        f"READY->RUNNING must increment attempt exactly once; got {next_task.attempt}"
    )
