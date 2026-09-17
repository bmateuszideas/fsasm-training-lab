"""Regression test for S1: Human Gate EvidenceRecord ID uniqueness.

The confirmed defect S1:

``validate_and_apply_human_decision_activity`` builds the RETRY_ONCE audit
``evidence_id`` as ``evidence-human-gate-retry-{run_id}-{task_id}``. That
identifier does not include the attempt number or any Human Gate sequence, so
two consecutive ``RETRY_ONCE`` decisions on the same run/task receive the same
``evidence_id``. Because persistence stores evidence under a path derived from
``evidence_id``, the second write overwrites the first audit record.

This test performs two real consecutive ``RETRY_ONCE`` decisions through the
worker and verifies, via ``RuntimePersistence.load_all_evidence(...)`` and the
actual file contents, that both audit records survive as distinct files with
distinct identifiers and preserved per-decision content. A third ``ABORT``
signal only closes the workflow.

Persistence is isolated to ``tmp_path`` via monkeypatch of
``RuntimePersistence`` in the workflow module (and the executor/planner
modules that the activities import), so the global ``./runtime`` is never
touched or cleaned up.
"""

import asyncio
import json
from datetime import timedelta

import pytest

from fsasm.models import RunStatus, TaskStatus
from fsasm.persistence import RuntimePersistence
import workflows.fsasm_milestone_four as m4_module
import fsasm.executor_activities as exec_module
import fsasm.planner_activities as plan_module
from workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    HumanDecisionSignal,
    HumanDecisionAction,
    create_input_activity,
    validate_config_activity,
    persist_initial_state_activity,
    set_task_max_attempts_activity,
    find_next_ready_task_activity,
    prepare_task_activity,
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    finalize_task_activity,
    check_retry_budget_activity,
    persist_failure_state_activity,
    persist_retry_state_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    persist_final_m4_state_activity,
    persist_human_gate_rejections_activity,
)
from fsasm.planner_activities import plan_activity


_M4_ACTIVITIES = [
    create_input_activity,
    validate_config_activity,
    plan_activity,
    persist_initial_state_activity,
    set_task_max_attempts_activity,
    find_next_ready_task_activity,
    prepare_task_activity,
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    finalize_task_activity,
    check_retry_budget_activity,
    persist_failure_state_activity,
    persist_retry_state_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    persist_final_m4_state_activity,
    persist_human_gate_rejections_activity,
]


@pytest.fixture()
def isolated_runtime(tmp_path, monkeypatch):
    """Redirect ALL M4 persistence to an isolated tmp_path directory.

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


def _read_log(runtime_dir, run_id):
    path = runtime_dir / "runs" / run_id / "run.log.jsonl"
    entries = []
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


async def _await_gate(persistence, run_id, expected_attempt, expected_max_attempts):
    """Poll the persisted state for a Human Gate at a given attempt.

    Returns once the run and TASK-001 are durably NEEDS_HUMAN with the expected
    attempt/max_attempts, or raises after a bounded timeout. Controlled
    synchronization on durable state, not a fixed delay.
    """
    max_wait = 10
    for _ in range(max_wait * 10):
        await asyncio.sleep(0.1)
        try:
            loaded_state = persistence.load_run_state(run_id)
            loaded_plan = persistence.load_plan(run_id)
            if (
                loaded_state is not None
                and loaded_state.status == RunStatus.NEEDS_HUMAN
                and loaded_plan is not None
                and loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
                and loaded_state.active_task_id is None
                and loaded_plan.tasks[0].attempt == expected_attempt
                and loaded_plan.tasks[0].max_attempts == expected_max_attempts
            ):
                return True
        except Exception:
            continue
    return False


@pytest.mark.asyncio
async def test_human_gate_evidence_id_uniqueness(isolated_runtime, temporal_env):
    """S1: two consecutive RETRY_ONCE decisions keep both audit records.

    Scenario (max_retries_per_task=0, stub_fail_first_n_attempts=999):

        attempt 1 FAIL -> Human Gate #1 -> RETRY_ONCE
        attempt 2 FAIL -> Human Gate #2 -> RETRY_ONCE
        attempt 3 FAIL -> Human Gate #3 -> ABORT

    The third ABORT only closes the workflow; the assertion target is the two
    RETRY_ONCE audit records.
    """
    from mistralai.workflows.testing import create_test_worker

    runtime_dir = isolated_runtime["runtime_dir"]
    persistence = RuntimePersistence(runtime_dir=runtime_dir)
    test_run_id = "test-s1-human-gate-evidence-uniqueness"

    async with create_test_worker(
        temporal_env,
        workflows=[FsasmMilestoneFourWorkflow],
        activities=_M4_ACTIVITIES,
    ):
        handle = await temporal_env.client.start_workflow(
            "fsasm-milestone-four",
            {
                "goal": "Test S1 Human Gate evidence uniqueness",
                "planner_backend": "stub",
                "executor_backend": "stub",
                "max_retries_per_task": 0,
                "stub_fail_first_n_attempts": 999,
                "run_id": test_run_id,
            },
            id=test_run_id,
            task_queue="test-task-queue",
            execution_timeout=timedelta(seconds=20),
        )

        # --- Human Gate #1: attempt 1 FAIL -> NEEDS_HUMAN (attempt=1, max=1)
        observed = await _await_gate(persistence, test_run_id, 1, 1)
        assert observed, "Human Gate #1 (NEEDS_HUMAN, attempt=1) was not observed"
        await handle.signal(
            FsasmMilestoneFourWorkflow.receive_human_decision,
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.RETRY_ONCE,
                reason="first retry reason",
            ),
        )

        # --- Human Gate #2: attempt 2 FAIL -> NEEDS_HUMAN (attempt=2, max=2)
        observed = await _await_gate(persistence, test_run_id, 2, 2)
        assert observed, "Human Gate #2 (NEEDS_HUMAN, attempt=2) was not observed"
        await handle.signal(
            FsasmMilestoneFourWorkflow.receive_human_decision,
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.RETRY_ONCE,
                reason="second retry reason",
            ),
        )

        # --- Human Gate #3: attempt 3 FAIL -> NEEDS_HUMAN (attempt=3, max=3)
        observed = await _await_gate(persistence, test_run_id, 3, 3)
        assert observed, "Human Gate #3 (NEEDS_HUMAN, attempt=3) was not observed"
        await handle.signal(
            FsasmMilestoneFourWorkflow.receive_human_decision,
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.ABORT,
                reason="abort after three attempts",
            ),
        )

        result = await asyncio.wait_for(handle.result(), timeout=15)

    # --- Assertion 7: the run log contains exactly two RETRY_ONCE decisions.
    log_entries = _read_log(runtime_dir, test_run_id)
    retry_once_log = [
        e for e in log_entries if e.get("event") == "human_decision_retry_once"
    ]
    assert len(retry_once_log) == 2, (
        f"expected two human_decision_retry_once log entries, got {len(retry_once_log)}"
    )

    # --- Assertion 8: execution attempts preserve the sequence 1 -> 2 -> 3.
    fail_entries = [e for e in log_entries if e.get("event") == "task_execution_failed"]
    fail_attempts = sorted(e["attempt"] for e in fail_entries)
    assert fail_attempts == [1, 2, 3], (
        f"execution attempts must be 1, 2, 3; got {fail_attempts}"
    )

    # --- Assertion 9 & 10: RETRY_ONCE authorizes exactly one more attempt and
    # the ABORT closes the workflow with FAILED.
    assert result["status"] == "FAILED"
    assert result["human_gate_invoked"] is True
    assert result["success"] is False
    assert "TASK-001" in result["failed_task_ids"]

    # Each RETRY_ONCE raised max_attempts by exactly one relative to its attempt.
    # Gate #1: attempt=1 -> max_attempts becomes 2; Gate #2: attempt=2 -> 3.
    assert retry_once_log[0]["current_attempt"] == 1
    assert retry_once_log[0]["new_max_attempts"] == 2
    assert retry_once_log[1]["current_attempt"] == 2
    assert retry_once_log[1]["new_max_attempts"] == 3

    # --- Load all evidence and isolate the two RETRY_ONCE audit records.
    all_evidence = persistence.load_all_evidence(test_run_id)
    retry_audits = [
        e
        for e in all_evidence
        if e.kind == "human_gate_audit" and e.payload.get("action") == "RETRY_ONCE"
    ]

    # --- Assertion 1: exactly two human_gate_audit RETRY_ONCE records.
    assert len(retry_audits) == 2, (
        f"expected exactly two RETRY_ONCE audit records, got {len(retry_audits)}"
    )

    # --- Assertion 2: both concern the same run_id and task_id.
    for e in retry_audits:
        assert e.run_id == test_run_id
        assert e.task_id == "TASK-001"

    # --- Assertion 3: their evidence_id are different.
    ids = {e.evidence_id for e in retry_audits}
    assert len(ids) == 2, f"expected two distinct evidence_ids, got {ids}"

    # --- Assertion 4: both files exist on disk simultaneously.
    evidence_dir = runtime_dir / "runs" / test_run_id / "evidence"
    for e in retry_audits:
        path = evidence_dir / f"{e.evidence_id}.json"
        assert path.exists(), f"evidence file {path} does not exist"

    # --- Assertion 6 & content checks: each record keeps its own reason, and
    # the records are keyed by the failing attempt (1 and 2 respectively).
    by_reason = {e.payload["reason"]: e for e in retry_audits}
    first = by_reason["first retry reason"]
    second = by_reason["second retry reason"]
    assert first.payload["reason"] == "first retry reason"
    assert second.payload["reason"] == "second retry reason"

    # The audit records the attempt at decision time (attempt_before). RETRY_ONCE
    # does not reset attempt, so this equals the failed attempt number.
    attempt_keys = sorted(
        [first.payload["attempt_before"], second.payload["attempt_before"]]
    )
    assert attempt_keys == [1, 2], (
        f"audit attempt_before must be 1 and 2, got {attempt_keys}"
    )

    # --- Assertion 5: the first record's content is unchanged after the second
    # decision. Re-read both directly from disk and confirm they are distinct
    # files with distinct content, and that the "first retry reason" content
    # was not overwritten by the second decision.
    first_path = evidence_dir / f"{first.evidence_id}.json"
    second_path = evidence_dir / f"{second.evidence_id}.json"
    with open(first_path, "r", encoding="utf-8") as f:
        first_on_disk = json.load(f)
    with open(second_path, "r", encoding="utf-8") as f:
        second_on_disk = json.load(f)
    assert first_on_disk["evidence_id"] == first.evidence_id
    assert first_on_disk["payload"]["reason"] == "first retry reason"
    assert second_on_disk["payload"]["reason"] == "second retry reason"
    assert first_on_disk["evidence_id"] != second_on_disk["evidence_id"]
    assert first_on_disk["payload"]["reason"] != second_on_disk["payload"]["reason"]

    # --- No collision with the ABORT audit identifier.
    abort_audits = [
        e
        for e in all_evidence
        if e.kind == "human_gate_audit" and e.payload.get("action") == "ABORT"
    ]
    assert len(abort_audits) == 1
    abort_id = abort_audits[0].evidence_id
    assert abort_id not in ids, (
        f"ABORT audit id collides with a RETRY_ONCE audit id: {abort_id}"
    )

    # --- evidence_count in the workflow result matches the actual on-disk count.
    actual_count = len(all_evidence)
    assert result["evidence_count"] == actual_count, (
        f"result.evidence_count={result['evidence_count']} != "
        f"actual persisted evidence={actual_count}"
    )
