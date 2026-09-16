"""Regression test for F8: finalizer contract.

The confirmed defect F8:

``finalize_task_activity`` accepts a ``VerificationResult`` reporting
``status = PASS`` and transitions the ``ChildTask`` to ``PASSED`` without
validating the verification result's identity, internal checks or associated
evidence. A contradictory PASS (foreign run_id/task_id, a failed check, an
empty checks list, or empty/foreign evidence) is silently accepted as a valid
PASS, mutating task/state and persisting invalid data.

The hardening contract (before accepting a PASS):
- ``VerificationResult.run_id`` matches the authoritative ``RunState.run_id``
- ``VerificationResult.task_id`` matches the task being finalized
- ``RunState.status`` is RUNNING
- ``RunState.plan`` exists
- the task belongs to the authoritative plan
- the authoritative plan task is RUNNING and its attempt equals the supplied
  task's attempt (the task and plan task are separate objects after the
  activity serialization boundary, so they are compared by value, not by
  shared object identity)
- ``RunState.active_task_id`` identifies the task being finalized
- a PASS contains at least one ``VerificationCheck`` and every check passed
  (an empty checks list must NOT pass via ``all([])``)
- a PASS requires nonempty task execution evidence
- every ``EvidenceRecord`` belongs to the authoritative run and task

Invalid or contradictory input fails closed through an explicit
``fsasm.errors.ValidationError`` BEFORE any side effect (no task/state
mutation, no persistence). Where a domain transition exception is the
intentional expected cause, that exact exception is asserted instead.

Persistence is isolated to ``tmp_path`` via monkeypatch of
``RuntimePersistence`` in the executor-activities module, so the global
``./runtime`` is never touched or cleaned up.
"""

import json

import pytest

from fsasm.errors import ValidationError
from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationCheck,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence
import fsasm.executor_activities as exec_module
from fsasm.executor_activities import finalize_task_activity


@pytest.fixture()
def isolated_runtime(tmp_path, monkeypatch):
    """Redirect executor-activities persistence to an isolated tmp_path.

    ``finalize_task_activity`` instantiates ``RuntimePersistence()`` itself,
    so the symbol is patched in the executor-activities module. The global
    ``./runtime`` is never touched or cleaned up.
    """
    runtime_dir = tmp_path / "runtime"
    original = RuntimePersistence

    class _RedirectingPersistence:
        """Delegating wrapper that points every instance at tmp_path."""

        def __init__(self, *args, **kwargs):
            kwargs.setdefault("runtime_dir", runtime_dir)
            self._inner = original(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(exec_module, "RuntimePersistence", _RedirectingPersistence)
    return {"runtime_dir": runtime_dir}


def _running_task(*, task_id: str = "TASK-001", attempt: int = 1) -> ChildTask:
    return ChildTask(
        task_id=task_id,
        sequence=1,
        title="Task 1",
        description="Desc 1",
        status=TaskStatus.RUNNING,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        attempt=attempt,
    )


def _plan(
    *,
    run_id: str = "test-f8-run",
    task_status: TaskStatus = TaskStatus.RUNNING,
    task_attempt: int = 1,
) -> Plan:
    """Authoritative plan. Its TASK-001 entry mirrors the supplied task's
    intended execution state, but is an independent object."""
    return Plan(
        plan_id="test-plan",
        run_id=run_id,
        goal="Test goal",
        tasks=[
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Task 1",
                description="Desc 1",
                status=task_status,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
                attempt=task_attempt,
            ),
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Task 2",
                description="Desc 2",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Task 3",
                description="Desc 3",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
        ],
    )


def _make_running_state(
    *,
    run_id: str = "test-f8-run",
    run_status: RunStatus = RunStatus.RUNNING,
    plan: Plan | None = None,
    active_task_id: str | None = "TASK-001",
    task_attempt: int = 1,
) -> tuple[RunState, ChildTask]:
    """Build a RunState plus an INDEPENDENT supplied task object.

    The supplied task and the plan task are separate objects (as they would be
    after the activity serialization boundary); they agree by value here.
    """
    task = _running_task(attempt=task_attempt)
    state = RunState(
        run_id=run_id,
        goal="Test goal",
        status=run_status,
        plan=plan
        if plan is not None
        else _plan(run_id=run_id, task_attempt=task_attempt),
        active_task_id=active_task_id,
        completed_task_ids=[],
        failed_task_ids=[],
    )
    return state, task


def _independent_state_and_task(state: RunState) -> tuple[RunState, ChildTask]:
    """Return JSON-round-tripped copies of state and the active task.

    This mimics the activity serialization boundary: the task passed to the
    finalizer and the plan task inside the state are independent objects that
    agree only by value, never by shared Python identity.
    """
    state_rt = RunState.model_validate_json(state.model_dump_json())
    task_rt = next(
        t for t in state_rt.plan.tasks if t.task_id == state_rt.active_task_id
    )
    return state_rt, task_rt


def _pass_result(*, run_id="test-f8-run", task_id="TASK-001", checks=None):
    return VerificationResult(
        run_id=run_id,
        task_id=task_id,
        status=VerificationResultStatus.PASS,
        checks=checks
        if checks is not None
        else [
            VerificationCheck(check_name="schema", passed=True, message="ok"),
        ],
        message="PASS",
    )


def _fail_result(*, run_id="test-f8-run", task_id="TASK-001"):
    return VerificationResult(
        run_id=run_id,
        task_id=task_id,
        status=VerificationResultStatus.FAIL,
        checks=[VerificationCheck(check_name="schema", passed=False, message="bad")],
        message="FAIL",
    )


def _evidence(*, run_id="test-f8-run", task_id="TASK-001", evidence_id="evidence-1"):
    return EvidenceRecord(
        evidence_id=evidence_id,
        run_id=run_id,
        task_id=task_id,
        kind="executor_output",
        source="executor_stub",
        payload={"result": "test"},
    )


def _persisted_state(runtime_dir, run_id):
    """Read the durable state.json for run_id, or return None if absent."""
    path = runtime_dir / "runs" / run_id / "state.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _persisted_plan(runtime_dir, run_id):
    path = runtime_dir / "runs" / run_id / "plan.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _assert_no_side_effects(
    runtime_dir, run_id, task, *, task_status=TaskStatus.RUNNING
):
    """Assert a rejected call left no in-memory mutation or durable writes."""
    assert task.status == task_status
    assert _persisted_state(runtime_dir, run_id) is None
    assert _persisted_plan(runtime_dir, run_id) is None


# ---------------------------------------------------------------------------
# Reproduction: contradictory input must be rejected (fails before the fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f8_a_contradictory_verification_identity(isolated_runtime):
    """A: a PASS result referring to another run/task is rejected.

    The original finalizer silently accepts a foreign PASS and transitions the
    task to PASSED. Expected after fix: explicit rejection via ValidationError;
    task remains RUNNING; no new persistence side effects.
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    foreign_pass = _pass_result(run_id="OTHER-RUN", task_id="OTHER-TASK")
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, foreign_pass, evidence)

    _assert_no_side_effects(runtime_dir, state.run_id, task)
    assert state.active_task_id == "TASK-001"
    assert state.completed_task_ids == []
    assert "TASK-001" not in state.failed_task_ids


@pytest.mark.asyncio
async def test_f8_b_pass_with_failed_check(isolated_runtime):
    """B: a PASS result containing a failed check is rejected."""
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    contradictory = _pass_result(
        checks=[
            VerificationCheck(check_name="ok", passed=True, message="ok"),
            VerificationCheck(check_name="bad", passed=False, message="failed"),
        ]
    )
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, contradictory, evidence)

    _assert_no_side_effects(runtime_dir, state.run_id, task)


@pytest.mark.asyncio
async def test_f8_c_pass_with_zero_checks(isolated_runtime):
    """C: a PASS result with zero checks is rejected (all([]) must not pass)."""
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    empty_pass = _pass_result(checks=[])
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, empty_pass, evidence)

    _assert_no_side_effects(runtime_dir, state.run_id, task)


@pytest.mark.asyncio
async def test_f8_d_pass_missing_evidence(isolated_runtime):
    """D: a PASS with no EvidenceRecords is rejected."""
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    good_pass = _pass_result()
    evidence: list[EvidenceRecord] = []

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, good_pass, evidence)

    _assert_no_side_effects(runtime_dir, state.run_id, task)


@pytest.mark.asyncio
async def test_f8_e_foreign_evidence(isolated_runtime):
    """E: at least one EvidenceRecord belonging to another run/task rejects.

    No partial persistence must occur.
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    good_pass = _pass_result()
    evidence = [
        _evidence(evidence_id="evidence-good"),
        _evidence(
            run_id="OTHER-RUN", task_id="OTHER-TASK", evidence_id="evidence-foreign"
        ),
    ]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, good_pass, evidence)

    _assert_no_side_effects(runtime_dir, state.run_id, task)
    evidence_dir = runtime_dir / "runs" / state.run_id / "evidence"
    if evidence_dir.exists():
        assert not any(evidence_dir.iterdir()), (
            "no evidence must be persisted on reject"
        )


# ---------------------------------------------------------------------------
# Authoritative execution-context validation (independent objects)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f8_run_not_running_rejected(isolated_runtime):
    """The authoritative RunState.status must be RUNNING to finalize a task.

    Uses independent task and plan objects (JSON-round-tripped).
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state(run_status=RunStatus.PLANNED)
    state_rt, task_rt = _independent_state_and_task(state)
    good_pass = _pass_result()
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state_rt, task_rt, good_pass, evidence)

    _assert_no_side_effects(runtime_dir, state_rt.run_id, task_rt)


@pytest.mark.asyncio
async def test_f8_absent_plan_rejected(isolated_runtime):
    """RunState must have an authoritative plan to finalize a task."""
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    state.plan = None
    good_pass = _pass_result()
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, good_pass, evidence)

    _assert_no_side_effects(runtime_dir, state.run_id, task)


@pytest.mark.asyncio
async def test_f8_plan_task_not_running_rejected(isolated_runtime):
    """The authoritative plan task must be RUNNING for finalization.

    The supplied task is RUNNING but the plan task is not, exposing a
    contradictory execution context across the serialization boundary.
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    # Plan task is FAILED while the supplied task claims RUNNING.
    plan = _plan(task_status=TaskStatus.FAILED, task_attempt=1)
    state, task = _make_running_state(plan=plan)
    state_rt, task_rt = _independent_state_and_task(state)
    # Force the supplied task to RUNNING while plan task stays FAILED.
    task_rt = ChildTask(
        task_id="TASK-001",
        sequence=1,
        title="Task 1",
        description="Desc 1",
        status=TaskStatus.RUNNING,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        attempt=1,
    )
    good_pass = _pass_result()
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state_rt, task_rt, good_pass, evidence)

    _assert_no_side_effects(runtime_dir, state_rt.run_id, task_rt)


@pytest.mark.asyncio
async def test_f8_plan_task_attempt_mismatch_rejected(isolated_runtime):
    """The authoritative plan task attempt must equal the supplied task attempt.

    Both are RUNNING, but the attempt counters disagree.
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    # Plan task attempt = 2, supplied task attempt = 1 (independent objects).
    plan = _plan(task_status=TaskStatus.RUNNING, task_attempt=2)
    state, _ = _make_running_state(plan=plan, task_attempt=1)
    state_rt = RunState.model_validate_json(state.model_dump_json())
    task_rt = _running_task(attempt=1)  # supplied task: attempt=1, plan task: attempt=2
    good_pass = _pass_result()
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state_rt, task_rt, good_pass, evidence)

    _assert_no_side_effects(runtime_dir, state_rt.run_id, task_rt)


@pytest.mark.asyncio
async def test_f8_task_not_in_plan_rejected(isolated_runtime):
    """The supplied task must belong to the authoritative plan."""
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    # Replace the supplied task with one not present in the plan.
    foreign_task = _running_task(task_id="TASK-999", attempt=1)
    good_pass = _pass_result(task_id="TASK-999")
    evidence = [_evidence(task_id="TASK-999")]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, foreign_task, good_pass, evidence)

    _assert_no_side_effects(runtime_dir, state.run_id, foreign_task)


# ---------------------------------------------------------------------------
# Positive cases: valid PASS / valid FAIL (independent objects)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f8_f_valid_pass(isolated_runtime):
    """F: a correctly identified RUNNING task receives a consistent PASS.

    Uses independent task and plan objects (JSON-round-tripped). task becomes
    PASSED; completed_task_ids contains it exactly once; failed_task_ids does
    not; active_task_id becomes None; RunState stays RUNNING; state.json and
    plan.json agree.
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    state_rt, task_rt = _independent_state_and_task(state)
    good_pass = _pass_result()
    evidence = [_evidence()]

    updated_state, updated_task = await finalize_task_activity(
        state_rt, task_rt, good_pass, evidence
    )

    assert updated_task.status == TaskStatus.PASSED
    assert updated_state.completed_task_ids.count("TASK-001") == 1
    assert "TASK-001" not in updated_state.failed_task_ids
    assert updated_state.active_task_id is None
    assert updated_state.status == RunStatus.RUNNING
    assert updated_state.plan.tasks[0].status == TaskStatus.PASSED

    persisted_state = _persisted_state(runtime_dir, state_rt.run_id)
    persisted_plan = _persisted_plan(runtime_dir, state_rt.run_id)
    assert persisted_state is not None
    assert persisted_plan is not None
    assert persisted_state["status"] == "RUNNING"
    assert persisted_state["completed_task_ids"] == ["TASK-001"]
    assert persisted_state["active_task_id"] is None
    assert persisted_plan["tasks"][0]["status"] == "PASSED"
    assert (
        persisted_plan["tasks"][0]["status"]
        == persisted_state["plan"]["tasks"][0]["status"]
    )


@pytest.mark.asyncio
async def test_f8_g_valid_fail(isolated_runtime):
    """G: a correctly identified task receives a valid FAIL result.

    Preserves the existing failure transition and persistence behavior.
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    state_rt, task_rt = _independent_state_and_task(state)
    fail = _fail_result()
    evidence: list[EvidenceRecord] = []

    updated_state, updated_task = await finalize_task_activity(
        state_rt, task_rt, fail, evidence
    )

    assert updated_task.status == TaskStatus.FAILED
    assert "TASK-001" in updated_state.failed_task_ids
    assert "TASK-001" not in updated_state.completed_task_ids
    assert updated_state.active_task_id is None
    assert updated_state.status == RunStatus.RUNNING
    assert updated_state.plan.tasks[0].status == TaskStatus.FAILED

    persisted_state = _persisted_state(runtime_dir, state_rt.run_id)
    assert persisted_state is not None
    assert persisted_state["failed_task_ids"] == ["TASK-001"]


@pytest.mark.asyncio
async def test_f8_g2_fail_with_contradictory_identity(isolated_runtime):
    """A FAIL result referring to another run/task is also rejected.

    Identity contradiction must be rejected even on the FAIL path, rather
    than persisting a result for another run or task.
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    foreign_fail = _fail_result(run_id="OTHER-RUN", task_id="OTHER-TASK")

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, foreign_fail, [])

    _assert_no_side_effects(runtime_dir, state.run_id, task)


@pytest.mark.asyncio
async def test_f8_task_not_running_rejected(isolated_runtime):
    """The task must be RUNNING to be finalized as PASSED."""
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state()
    task.status = TaskStatus.PENDING
    good_pass = _pass_result()
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, good_pass, evidence)

    _assert_no_side_effects(
        runtime_dir, state.run_id, task, task_status=TaskStatus.PENDING
    )


@pytest.mark.asyncio
async def test_f8_task_not_active_in_run_rejected(isolated_runtime):
    """RunState.active_task_id must identify the task being finalized."""
    runtime_dir = isolated_runtime["runtime_dir"]
    state, task = _make_running_state(active_task_id="TASK-002")
    good_pass = _pass_result()
    evidence = [_evidence()]

    with pytest.raises(ValidationError):
        await finalize_task_activity(state, task, good_pass, evidence)

    _assert_no_side_effects(runtime_dir, state.run_id, task)
