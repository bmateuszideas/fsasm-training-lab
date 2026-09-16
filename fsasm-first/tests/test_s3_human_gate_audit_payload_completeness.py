"""Regression test for S3: Human Gate audit payload completeness.

The confirmed defect S3:

``validate_and_apply_human_decision_activity`` builds the Human Gate audit
``EvidenceRecord`` payload with incomplete/incorrect ``before``/``after``
fields for ``attempt`` and ``max_attempts``.

RETRY_ONCE payload (pre-fix):
- ``attempt_before`` present but ``attempt_after`` MISSING
- ``max_attempts_before`` set to ``task.attempt`` (reconstructed from the
  attempt number) instead of the real pre-transition ``max_attempts`` value
- ``max_attempts_after`` correct

ABORT payload (pre-fix):
- only flat ``attempt`` and ``max_attempts`` keys; all four
  ``attempt_before``/``attempt_after``/``max_attempts_before``/``max_attempts_after``
  fields MISSING

This test drives the activity directly with a ``NEEDS_HUMAN`` task where
``attempt != max_attempts`` (a contract-valid input: the activity only
validates statuses, not ``attempt == max_attempts``). That input exposes the
``max_attempts_before`` bug, because the buggy code sets it to ``task.attempt``
while the real pre-transition ``max_attempts`` is a different value.

The required audit contract for both decisions:

    action, reason, task_id
    attempt_before, attempt_after
    max_attempts_before, max_attempts_after
    task_status_before, task_status_after
    run_status_before, run_status_after

Persistence is isolated to ``tmp_path`` via monkeypatch of
``RuntimePersistence`` in the workflow module (and the executor/planner
modules that the activities import), so the global ``./runtime`` is never
touched or cleaned up.
"""

import pytest

from fsasm.models import (
    ChildTask,
    HumanDecision,
    HumanDecisionAction,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence
import workflows.fsasm_milestone_four as m4_module
import fsasm.executor_activities as exec_module
import fsasm.planner_activities as plan_module
from workflows.fsasm_milestone_four import (
    validate_and_apply_human_decision_activity,
)

# Audit payload fields required by the S3 contract.
_ATTEMPT_MAX_FIELDS = (
    "attempt_before",
    "attempt_after",
    "max_attempts_before",
    "max_attempts_after",
)
_STATUS_FIELDS = (
    "task_status_before",
    "task_status_after",
    "run_status_before",
    "run_status_after",
)


@pytest.fixture()
def isolated_runtime(tmp_path, monkeypatch):
    """Redirect M4 persistence to an isolated tmp_path directory.

    The workflow activities instantiate ``RuntimePersistence()`` themselves,
    so the symbol is patched in every module that references it. The global
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

    monkeypatch.setattr(m4_module, "RuntimePersistence", _RedirectingPersistence)
    monkeypatch.setattr(
        exec_module, "RuntimePersistence", _RedirectingPersistence, raising=False
    )
    monkeypatch.setattr(
        plan_module, "RuntimePersistence", _RedirectingPersistence, raising=False
    )
    return {"runtime_dir": runtime_dir}


def _make_gated_state(
    *,
    attempt: int,
    max_attempts: int,
    run_id: str = "test-s3-run",
    task_id: str = "TASK-001",
) -> tuple[ChildTask, RunState]:
    """Build a NEEDS_HUMAN task+state with explicit attempt/max_attempts.

    The activity's input contract only validates that task/run are
    NEEDS_HUMAN; it does NOT enforce ``attempt == max_attempts``. So a task
    with ``attempt != max_attempts`` is contract-valid input and is exactly
    what exposes the ``max_attempts_before`` reconstruction bug.
    """
    task = ChildTask(
        task_id=task_id,
        sequence=1,
        title="Test",
        description="Test",
        status=TaskStatus.NEEDS_HUMAN,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        attempt=attempt,
        max_attempts=max_attempts,
    )
    tasks = [
        task,
        ChildTask(
            task_id="TASK-002",
            sequence=2,
            title="Test 2",
            description="Test 2",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
        ),
        ChildTask(
            task_id="TASK-003",
            sequence=3,
            title="Test 3",
            description="Test 3",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
        ),
    ]
    state = RunState(
        run_id=run_id,
        goal="Test",
        status=RunStatus.NEEDS_HUMAN,
        plan=Plan(
            plan_id=f"plan-{run_id}",
            run_id=run_id,
            goal="Test",
            tasks=tasks,
        ),
        active_task_id=None,
        completed_task_ids=[],
        failed_task_ids=[task_id],
    )
    return task, state


def _load_audit(persistence, run_id, action):
    """Load the single human_gate_audit EvidenceRecord for ``action``."""
    all_evidence = persistence.load_all_evidence(run_id)
    audits = [
        e
        for e in all_evidence
        if e.kind == "human_gate_audit" and e.payload.get("action") == action
    ]
    assert len(audits) == 1, (
        f"expected exactly one {action} human_gate_audit record, got {len(audits)}"
    )
    return audits[0]


@pytest.mark.asyncio
async def test_s3_retry_once_audit_payload_completeness(isolated_runtime):
    """S3: RETRY_ONCE audit records real before/after attempt and max_attempts.

    Scenario (attempt != max_attempts to expose the reconstruction bug):
        BEFORE: attempt=4, max_attempts=5, status NEEDS_HUMAN
        DECISION: RETRY_ONCE
        AFTER: attempt=4 (unchanged), max_attempts=5 (attempt+1), status READY
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    persistence = RuntimePersistence(runtime_dir=runtime_dir)
    run_id = "test-s3-retry-once"

    attempt_before = 4
    max_attempts_before = 5
    task, state = _make_gated_state(
        attempt=attempt_before, max_attempts=max_attempts_before, run_id=run_id
    )

    decision = HumanDecision(
        task_id="TASK-001",
        action=HumanDecisionAction.RETRY_ONCE,
        reason="retry one more time",
    )

    (
        task_after,
        state_after,
        _applied,
    ) = await validate_and_apply_human_decision_activity(decision, task, state)

    expected_max_attempts_after = attempt_before + 1

    assert task_after.attempt == attempt_before, "RETRY_ONCE must not reset attempt"
    assert task_after.max_attempts == expected_max_attempts_after, (
        "RETRY_ONCE must set max_attempts = attempt_before + 1"
    )
    assert task_after.status == TaskStatus.READY
    assert state_after.status == RunStatus.RUNNING

    audit = _load_audit(persistence, run_id, "RETRY_ONCE")
    payload = audit.payload

    for field in _ATTEMPT_MAX_FIELDS:
        assert field in payload, f"RETRY_ONCE audit missing required field: {field}"
    for field in _STATUS_FIELDS:
        assert field in payload, f"RETRY_ONCE audit missing required field: {field}"

    assert payload["action"] == "RETRY_ONCE"
    assert payload["reason"] == "retry one more time"
    assert payload["task_id"] == "TASK-001"

    assert payload["attempt_before"] == attempt_before
    assert payload["attempt_after"] == attempt_before, (
        "RETRY_ONCE must preserve attempt_after == attempt_before"
    )
    assert payload["max_attempts_before"] == max_attempts_before, (
        "max_attempts_before must be the real pre-transition value (5), "
        "not reconstructed from attempt (4)"
    )
    assert payload["max_attempts_after"] == expected_max_attempts_after
    assert payload["max_attempts_after"] == attempt_before + 1

    assert payload["task_status_before"] == "NEEDS_HUMAN"
    assert payload["task_status_after"] == "READY"
    assert payload["run_status_before"] == "NEEDS_HUMAN"
    assert payload["run_status_after"] == "RUNNING"


@pytest.mark.asyncio
async def test_s3_abort_audit_payload_completeness(isolated_runtime):
    """S3: ABORT audit records real before/after attempt and max_attempts.

    Scenario:
        BEFORE: attempt=3, max_attempts=3, status NEEDS_HUMAN
        DECISION: ABORT
        AFTER: attempt=3 (unchanged), max_attempts=3 (unchanged), status FAILED
    """
    runtime_dir = isolated_runtime["runtime_dir"]
    persistence = RuntimePersistence(runtime_dir=runtime_dir)
    run_id = "test-s3-abort"

    attempt_before = 3
    max_attempts_before = 3
    task, state = _make_gated_state(
        attempt=attempt_before, max_attempts=max_attempts_before, run_id=run_id
    )

    decision = HumanDecision(
        task_id="TASK-001",
        action=HumanDecisionAction.ABORT,
        reason="aborting the run",
    )

    (
        task_after,
        state_after,
        _applied,
    ) = await validate_and_apply_human_decision_activity(decision, task, state)

    assert task_after.attempt == attempt_before, "ABORT must not change attempt"
    assert task_after.max_attempts == max_attempts_before, (
        "ABORT must not change max_attempts"
    )
    assert task_after.status == TaskStatus.FAILED
    assert state_after.status == RunStatus.FAILED
    assert state_after.active_task_id is None

    audit = _load_audit(persistence, run_id, "ABORT")
    payload = audit.payload

    for field in _ATTEMPT_MAX_FIELDS:
        assert field in payload, f"ABORT audit missing required field: {field}"
    for field in _STATUS_FIELDS:
        assert field in payload, f"ABORT audit missing required field: {field}"

    assert payload["action"] == "ABORT"
    assert payload["reason"] == "aborting the run"
    assert payload["task_id"] == "TASK-001"

    assert payload["attempt_before"] == attempt_before
    assert payload["attempt_after"] == attempt_before, (
        "ABORT must keep attempt_after == attempt_before"
    )
    assert payload["max_attempts_before"] == max_attempts_before
    assert payload["max_attempts_after"] == max_attempts_before, (
        "ABORT must keep max_attempts_after == max_attempts_before"
    )

    assert payload["task_status_before"] == "NEEDS_HUMAN"
    assert payload["task_status_after"] == "FAILED"
    assert payload["run_status_before"] == "NEEDS_HUMAN"
    assert payload["run_status_after"] == "FAILED"


@pytest.mark.asyncio
async def test_s3_disk_payload_matches_contract(isolated_runtime):
    """S3: the on-disk evidence JSON contains the complete payload.

    Reads the persisted JSON file directly (not just the loaded object) to
    confirm the durable record carries the full contract.
    """
    import json

    runtime_dir = isolated_runtime["runtime_dir"]
    persistence = RuntimePersistence(runtime_dir=runtime_dir)
    run_id = "test-s3-disk"

    attempt_before = 4
    max_attempts_before = 5
    task, state = _make_gated_state(
        attempt=attempt_before, max_attempts=max_attempts_before, run_id=run_id
    )

    decision = HumanDecision(
        task_id="TASK-001",
        action=HumanDecisionAction.RETRY_ONCE,
        reason="disk contract check",
    )

    await validate_and_apply_human_decision_activity(decision, task, state)

    audit = _load_audit(persistence, run_id, "RETRY_ONCE")
    evidence_path = (
        runtime_dir / "runs" / run_id / "evidence" / f"{audit.evidence_id}.json"
    )
    assert evidence_path.exists(), f"evidence file {evidence_path} does not exist"
    with open(evidence_path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    payload = on_disk["payload"]
    for field in _ATTEMPT_MAX_FIELDS + _STATUS_FIELDS:
        assert field in payload, f"on-disk payload missing required field: {field}"
    assert payload["attempt_before"] == attempt_before
    assert payload["attempt_after"] == attempt_before
    assert payload["max_attempts_before"] == max_attempts_before
    assert payload["max_attempts_after"] == attempt_before + 1
