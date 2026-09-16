"""Regression test for S1: Human Gate EvidenceRecord ID uniqueness.

Two consecutive `RETRY_ONCE` decisions on the same task must not overwrite each
other's audit `EvidenceRecord`. The pre-fix evidence_id was
`evidence-human-gate-retry-{run_id}-{task_id}` with no attempt/sequence, so the
second `RETRY_ONCE` overwrote the first audit file (same id => same path).

This test drives a real worker through three Human Gates:

    attempt 1 FAIL -> Gate #1 -> RETRY_ONCE -> attempt 2 FAIL
    attempt 2 FAIL -> Gate #2 -> RETRY_ONCE -> attempt 3 FAIL
    attempt 3 FAIL -> Gate #3 -> ABORT

and verifies BOTH `RETRY_ONCE` audit records survive on disk with distinct ids
and distinct contents. Persistence is isolated to `tmp_path` via monkeypatch of
`RuntimePersistence` in every activity module; the global `./runtime` is never
touched or cleaned.
"""

import asyncio
from datetime import timedelta

import pytest

from fsasm.persistence import RuntimePersistence
from fsasm.models import RunStatus, TaskStatus

import workflows.fsasm_milestone_four as m4_module
import fsasm.executor_activities as exec_module
import fsasm.planner_activities as plan_module

from workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    HumanDecisionSignal,
)
from fsasm.models import HumanDecisionAction


@pytest.fixture()
def isolated_runtime(tmp_path, monkeypatch):
    """Redirect ALL M4 persistence to an isolated tmp_path directory.

    The workflow activities instantiate `RuntimePersistence()` themselves, so
    the symbol is patched in every module that references it. The global
    `./runtime` is never touched or cleaned up.
    """
    runtime_dir = tmp_path / "runtime"
    original = RuntimePersistence

    def _factory(*args, **kwargs):
        kwargs.setdefault("runtime_dir", runtime_dir)
        return original(*args, **kwargs)

    monkeypatch.setattr(m4_module, "RuntimePersistence", _factory)
    monkeypatch.setattr(exec_module, "RuntimePersistence", _factory, raising=False)
    monkeypatch.setattr(plan_module, "RuntimePersistence", _factory, raising=False)
    return runtime_dir


_M4_ACTIVITIES = [
    m4_module.create_input_activity,
    m4_module.validate_config_activity,
    plan_module.plan_activity,
    m4_module.persist_initial_state_activity,
    m4_module.set_task_max_attempts_activity,
    m4_module.find_next_ready_task_activity,
    exec_module.prepare_task_activity,
    exec_module.execute_task_activity,
    exec_module.validate_executor_output_provenance_activity,
    exec_module.convert_executor_output_to_evidence_activity,
    exec_module.verify_task_execution_activity,
    exec_module.finalize_task_activity,
    m4_module.check_retry_budget_activity,
    m4_module.persist_failure_state_activity,
    m4_module.persist_retry_state_activity,
    m4_module.transition_to_needs_human_activity,
    m4_module.validate_and_apply_human_decision_activity,
    m4_module.persist_final_m4_state_activity,
]


def _read_log(runtime_dir, run_id):
    import json

    path = runtime_dir / "runs" / run_id / "run.log.jsonl"
    entries = []
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


async def _wait_for_needs_human(runtime_dir, run_id, expected_attempt, max_wait=10):
    """Deterministically wait for the durable NEEDS_HUMAN state at the given
    attempt by polling the persisted state (bounded, controlled). This is not a
    timing race against a transient value: NEEDS_HUMAN is a *terminal* gate
    state the workflow deliberately remains in until a signal arrives, so it is
    stable once persisted."""
    persistence = RuntimePersistence(runtime_dir=runtime_dir)
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
                and loaded_plan.tasks[0].max_attempts == expected_attempt
            ):
                return True
        except Exception:
            continue
    return False


@pytest.mark.asyncio
async def test_two_consecutive_retry_once_keep_distinct_audit_records(
    isolated_runtime, temporal_env
):
    """S1: two consecutive RETRY_ONCE decisions keep distinct, non-overwritten
    Human Gate audit evidence records.

    Uses max_retries_per_task=0 (1 total attempt) and a stub executor that always
    fails, so each execution immediately exhausts its budget and escalates to the
    Human Gate.

    Sequence:
      attempt 1 FAIL -> Gate #1 -> RETRY_ONCE(reason A) -> attempt 2 FAIL
      attempt 2 FAIL -> Gate #2 -> RETRY_ONCE(reason B) -> attempt 3 FAIL
      attempt 3 FAIL -> Gate #3 -> ABORT (controlled test termination)
    """
    from mistralai.workflows.testing import create_test_worker

    runtime_dir = isolated_runtime
    test_run_id = "test-s1-human-gate-evidence-uniqueness"

    async with create_test_worker(
        temporal_env,
        workflows=[FsasmMilestoneFourWorkflow],
        activities=_M4_ACTIVITIES,
    ):
        handle = await temporal_env.client.start_workflow(
            "fsasm-milestone-four",
            {
                "goal": "Test S1 human gate evidence uniqueness",
                "planner_backend": "stub",
                "executor_backend": "stub",
                "max_retries_per_task": 0,
                "stub_fail_first_n_attempts": 999,
                "run_id": test_run_id,
            },
            id=test_run_id,
            task_queue="test-task-queue",
            execution_timeout=timedelta(seconds=15),
        )

        # --- Gate #1 at attempt 1 ---
        gate1 = await _wait_for_needs_human(runtime_dir, test_run_id, expected_attempt=1)
        assert gate1, "Human Gate #1 (attempt=1) was not reached"

        await handle.signal(
            FsasmMilestoneFourWorkflow.receive_human_decision,
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.RETRY_ONCE,
                reason="First retry authorization",
            ),
        )

        # --- Gate #2 at attempt 2 ---
        gate2 = await _wait_for_needs_human(runtime_dir, test_run_id, expected_attempt=2)
        assert gate2, "Human Gate #2 (attempt=2) was not reached after RETRY_ONCE #1"

        # Capture the audit record written by Gate #1 BEFORE the second decision,
        # so we can prove the first record survives untouched after RETRY_ONCE #2.
        persistence = RuntimePersistence(runtime_dir=runtime_dir)
        evidence_after_gate1 = persistence.load_all_evidence(test_run_id)
        retry_after_gate1 = [
            e
            for e in evidence_after_gate1
            if e.kind == "human_gate_audit" and e.payload.get("action") == "RETRY_ONCE"
        ]

        await handle.signal(
            FsasmMilestoneFourWorkflow.receive_human_decision,
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.RETRY_ONCE,
                reason="Second retry authorization",
            ),
        )

        # --- Gate #3 at attempt 3 -> ABORT to terminate ---
        gate3 = await _wait_for_needs_human(runtime_dir, test_run_id, expected_attempt=3)
        assert gate3, "Human Gate #3 (attempt=3) was not reached after RETRY_ONCE #2"

        await handle.signal(
            FsasmMilestoneFourWorkflow.receive_human_decision,
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.ABORT,
                reason="Stop retrying",
            ),
        )

        result = await asyncio.wait_for(handle.result(), timeout=10)

    # --- Assertions on durable artifacts (read from disk, isolated tmp_path) ---
    persistence = RuntimePersistence(runtime_dir=runtime_dir)
    persisted_evidence = persistence.load_all_evidence(test_run_id)
    human_gate_audit = [e for e in persisted_evidence if e.kind == "human_gate_audit"]

    # 1. Exactly two RETRY_ONCE audit records.
    retry_audit = [
        e for e in human_gate_audit if e.payload.get("action") == "RETRY_ONCE"
    ]
    assert len(retry_audit) == 2, (
        f"expected exactly 2 RETRY_ONCE audit records, got {len(retry_audit)}; "
        f"evidence ids: {[e.evidence_id for e in retry_audit]}"
    )

    # 2. Both concern the same run_id and task_id.
    for e in retry_audit:
        assert e.run_id == test_run_id
        assert e.task_id == "TASK-001"

    # 3. Their evidence_id are different.
    ids = [e.evidence_id for e in retry_audit]
    assert len(set(ids)) == 2, f"RETRY_ONCE evidence ids collide: {ids}"

    # 4. Both files exist simultaneously (already guaranteed by load_all_evidence
    # returning both; assert explicitly).
    assert len(retry_audit) == 2

    # 5. The first record's content survives the second decision. Re-read the
    # record captured before the second decision and confirm it still matches a
    # record on disk now, with the first reason intact.
    first_reason = "First retry authorization"
    second_reason = "Second retry authorization"
    reasons_on_disk = sorted(e.payload.get("reason") for e in retry_audit)
    assert reasons_on_disk == sorted([first_reason, second_reason]), (
        f"expected both reasons preserved on disk, got {reasons_on_disk}"
    )

    # 6. Each record keeps its proper reason (cross-check ids against captured).
    if retry_after_gate1:
        first_id_on_disk_pre = retry_after_gate1[0].evidence_id
        matching_now = [
            e for e in retry_audit if e.evidence_id == first_id_on_disk_pre
        ]
        assert matching_now, (
            "first RETRY_ONCE audit record was overwritten/removed by the second"
        )
        assert matching_now[0].payload.get("reason") == first_reason, (
            "first record content changed after second decision"
        )

    # 7. The log contains two human_decision_retry_once entries.
    log_entries = _read_log(runtime_dir, test_run_id)
    retry_log = [
        e for e in log_entries if e.get("event") == "human_decision_retry_once"
    ]
    assert len(retry_log) == 2, (
        f"expected 2 human_decision_retry_once log entries, got {len(retry_log)}"
    )

    # 8. Execution attempts preserve the 1 -> 2 -> 3 sequence (from log attempts).
    retry_attempts = sorted(e.get("current_attempt") for e in retry_log)
    assert retry_attempts == [1, 2], f"unexpected retry attempt sequence: {retry_attempts}"

    # 9. Each RETRY_ONCE authorized exactly one additional attempt: attempt
    # went 1->2 (after gate #1) and 2->3 (after gate #2). max_attempts == attempt
    # at each gate (one more try authorized).
    for e in retry_audit:
        assert e.payload.get("max_attempts_after") == e.payload.get("attempt_before") + 1, (
            "RETRY_ONCE must authorize exactly one additional attempt"
        )

    # 10. The ABORT correctly closed the workflow (FAILED).
    abort_audit = [
        e for e in human_gate_audit if e.payload.get("action") == "ABORT"
    ]
    assert len(abort_audit) == 1
    assert isinstance(result, dict)
    assert result["status"] == "FAILED"
    assert result["human_gate_invoked"] is True
    assert result["success"] is False

    # 11. evidence_count in the workflow result matches the actual number of
    # persisted evidence records on disk (not a hard-coded constant).
    assert result["evidence_count"] == len(persisted_evidence), (
        f"result evidence_count {result['evidence_count']} != "
        f"actual persisted records {len(persisted_evidence)}"
    )
