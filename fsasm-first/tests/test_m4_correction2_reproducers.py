"""External-review correction-pass 2 reproducers.

Reproduces the confirmed defects from the second external review at
`094b6de7adaba1d1427cd58cb741c8beedc0baa3`:

- BLOCKER A (T01): wrong-task decision takeover. A signal with the CORRECT
  current ``gate_id`` but an INCORRECT ``task_id`` is accepted into
  ``accepted_decisions``; the wait releases and the activity rejects it too
  late, blocking a subsequent legitimate decision.
- BLOCKER B (T02): substring-based wrong-run acceptance. ``signal.run_id in
  self.current_gate_id`` is not equality; on run ``run-10`` a signal claiming
  ``run-1`` passes.
- BLOCKER C (T03): rejection audit loss while waiting and gate-1-to-gate-2
  audit duplication. Rejections are only persisted after a valid decision
  releases the wait; rejection-only waiting leaves no durable record. The
  shared ``rejected_signals`` list is never cleared, so gate-1 rejections are
  logged again under gate-2.

These tests assert the CORRECTED contract, so they FAIL against the pre-fix
code at `094b6de` and PASS after the fix.
"""

import asyncio
from datetime import timedelta

import pytest
from mistralai.workflows.testing import create_test_worker

from fsasm.models import HumanDecisionAction
from fsasm.persistence import RuntimePersistence
from src.workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    HumanDecisionSignal,
    OpenGate,
    _decision_id,
    _gate_id,
)
from src.workflows.fsasm_milestone_four import (
    create_input_activity,
    validate_config_activity,
    find_next_ready_task_activity,
    set_task_max_attempts_activity,
    check_retry_budget_activity,
    persist_failure_state_activity,
    transition_to_needs_human_activity,
    persist_retry_state_activity,
    validate_and_apply_human_decision_activity,
    persist_final_m4_state_activity,
    persist_human_gate_rejections_activity,
    persist_initial_state_activity,
)
from fsasm.planner_activities import plan_activity
from fsasm.executor_activities import (
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    prepare_task_activity,
    finalize_task_activity,
)

_M4_ACTIVITIES = [
    create_input_activity,
    validate_config_activity,
    plan_activity,
    set_task_max_attempts_activity,
    persist_initial_state_activity,
    find_next_ready_task_activity,
    prepare_task_activity,
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    finalize_task_activity,
    persist_failure_state_activity,
    check_retry_budget_activity,
    persist_retry_state_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    persist_final_m4_state_activity,
    persist_human_gate_rejections_activity,
]


@pytest.fixture(autouse=True)
def cleanup_runtime():
    p = RuntimePersistence()
    p.cleanup_all()
    yield
    p.cleanup_all()


async def _wait_for_needs_human(run_id, timeout=20):
    p = RuntimePersistence()
    for _ in range(timeout * 10):
        await asyncio.sleep(0.1)
        try:
            from fsasm.models import RunStatus

            state = p.load_run_state(run_id)
            if state is not None and state.status == RunStatus.NEEDS_HUMAN:
                return state
        except Exception:
            continue
    return p.load_run_state(run_id)


def _start(temporal_env, run_id, max_retries, fail_n):
    return temporal_env.client.start_workflow(
        "fsasm-milestone-four",
        {
            "goal": "T01/T02/T03 reproducer",
            "planner_backend": "stub",
            "executor_backend": "stub",
            "max_retries_per_task": max_retries,
            "stub_fail_first_n_attempts": fail_n,
            "run_id": run_id,
        },
        id=run_id,
        task_queue="test-task-queue",
        execution_timeout=timedelta(seconds=20),
    )


# =====================================================================
# BLOCKER A (T01) — wrong-task decision takeover
# =====================================================================


class TestBlockerAWrongTaskTakeover:
    """A wrong-task signal with the correct gate_id (or omitted gate_id)
    occupies the accepted-decision slot, blocking a later legitimate
    decision."""

    @pytest.mark.asyncio
    async def test_wrong_task_correct_gate_does_not_block_legit(
        self, temporal_env, full_decision_signal
    ):
        """W1: send RETRY_ONCE for TASK-999 with the CORRECT current gate_id,
        then send a legitimate RETRY_ONCE for TASK-001. The wrong-task signal
        must NOT occupy the slot; the legitimate decision must succeed."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-w1", 0, 1)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-w1")
            gate = _gate_id("run-w1", "TASK-001", 1)
            # Wrong task, CORRECT gate_id (full IDs: the wrong task uses the
            # open gate's gate_id but its own task_id/decision_id).
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    run_id="run-w1",
                    task_id="TASK-999",
                    action=HumanDecisionAction.RETRY_ONCE,
                    gate_id=gate,
                    decision_id=_decision_id(
                        "run-w1", "TASK-999", gate, HumanDecisionAction.RETRY_ONCE
                    ),
                ),
            )
            # Legitimate decision for TASK-001.
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                full_decision_signal(
                    "run-w1", "TASK-001", 1, HumanDecisionAction.RETRY_ONCE
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_wrong_task_omitted_gate_does_not_block_legit(
        self, temporal_env, full_decision_signal
    ):
        """W2: send a wrong-task signal WITHOUT an explicit gate_id, then send
        a legitimate decision. The wrong signal must not occupy the slot."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-w2", 0, 1)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-w2")
            # Wrong task, NO gate_id (legacy) -> rejected as incomplete_payload.
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-999", action=HumanDecisionAction.RETRY_ONCE
                ),
            )
            # Legitimate decision (full IDs for the open gate).
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                full_decision_signal(
                    "run-w2", "TASK-001", 1, HumanDecisionAction.RETRY_ONCE
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True


# =====================================================================
# BLOCKER B (T02) — substring-based wrong-run acceptance
# =====================================================================


class TestBlockerBSubstringRun:
    """``signal.run_id in self.current_gate_id`` is not equality: on run
    ``run-10`` a signal claiming ``run-1`` passes the substring check."""

    @pytest.mark.asyncio
    async def test_substring_run_rejected_at_handler(self):
        """Direct handler test: on run ``run-10`` (gate_id
        ``gate-run-10-TASK-001-attempt-1``), a signal claiming ``run-1`` with
        the correct gate_id must be rejected as wrong_run, NOT accepted into
        accepted_decisions. Pre-fix: the substring check
        ``'run-1' in 'gate-run-10-...'`` passes, so the signal is wrongly
        accepted."""
        wf = FsasmMilestoneFourWorkflow()
        gate = _gate_id("run-10", "TASK-001", 1)
        wf.current_gate_id = gate
        wf.current_gate = OpenGate(
            run_id="run-10",
            task_id="TASK-001",
            gate_id=gate,
            attempt=1,
        )
        await wf.receive_human_decision(
            HumanDecisionSignal(
                run_id="run-1",
                task_id="TASK-001",
                action=HumanDecisionAction.RETRY_ONCE,
                gate_id=gate,
                decision_id=_decision_id(
                    "run-1", "TASK-001", gate, HumanDecisionAction.RETRY_ONCE
                ),
            )
        )
        assert gate not in wf.accepted_decisions, (
            "Pre-fix defect: run-1 (a substring of run-10) was accepted as a "
            "decision for run-10 because the run check uses substring "
            "membership instead of exact equality."
        )
        assert any(r["reason"] == "wrong_run" for r in wf.pending_rejections)

    @pytest.mark.asyncio
    async def test_substring_run_collision_rejected_worker(
        self, temporal_env, full_decision_signal
    ):
        """W3 worker: current run ``run-10``, incoming signal claims ``run-1``
        with the correct explicit gate_id. The signal must be rejected (run-1
        is a substring of run-10's gate_id but not the same run); the
        legitimate decision then succeeds."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-10", 0, 1)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-10")
            gate = _gate_id("run-10", "TASK-001", 1)
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    run_id="run-1",
                    task_id="TASK-001",
                    action=HumanDecisionAction.RETRY_ONCE,
                    gate_id=gate,
                    decision_id=_decision_id(
                        "run-1", "TASK-001", gate, HumanDecisionAction.RETRY_ONCE
                    ),
                ),
            )
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                full_decision_signal(
                    "run-10", "TASK-001", 1, HumanDecisionAction.RETRY_ONCE
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        p = RuntimePersistence()
        logs = p.load_run_log("run-10")
        rejection_logs = [
            e for e in logs if e.get("event") == "human_gate_rejected_signals"
        ]
        assert rejection_logs
        assert any(
            any(r.get("reason") == "wrong_run" for r in e.get("rejections", []))
            for e in rejection_logs
        )

    @pytest.mark.asyncio
    async def test_substring_run_collision_omitted_gate_rejected(
        self, temporal_env, full_decision_signal
    ):
        """run-1 against run-10 with omitted gate_id (legacy). Must be
        rejected by exact run comparison, not substring. Under T03 the legacy
        payload is rejected as incomplete_payload; the legitimate full-ID
        decision then succeeds."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-10b", 0, 1)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-10b")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001",
                    action=HumanDecisionAction.RETRY_ONCE,
                    run_id="run-1",
                ),
            )
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                full_decision_signal(
                    "run-10b", "TASK-001", 1, HumanDecisionAction.RETRY_ONCE
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True


# =====================================================================
# BLOCKER C (T03) — rejection audit loss while waiting + duplication
# =====================================================================


class TestBlockerCRejectionAudit:
    """Rejections are only persisted after a valid decision; rejection-only
    waiting leaves no durable record. The shared list is never cleared, so
    gate-1 rejections leak to gate-2."""

    @pytest.mark.asyncio
    async def test_rejection_only_waiting_produces_durable_audit(self, temporal_env):
        """W4: open a gate, send ONE invalid signal, send NO valid decision.
        A rejection record must appear on disk while the workflow remains
        waiting."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-w4", 0, 999)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-w4")
            # Invalid signal: a complete-ID signal with a wrong gate_id
            # (full IDs so it is rejected as wrong_gate, not incomplete).
            wrong_gate = "gate-run-w4-TASK-001-attempt-999"
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    run_id="run-w4",
                    task_id="TASK-001",
                    action=HumanDecisionAction.ABORT,
                    gate_id=wrong_gate,
                    decision_id=_decision_id(
                        "run-w4", "TASK-001", wrong_gate, HumanDecisionAction.ABORT
                    ),
                ),
            )
            # Wait for the rejection to be durably persisted WITHOUT sending
            # a valid decision.
            p = RuntimePersistence()
            found = False
            for _ in range(150):
                await asyncio.sleep(0.1)
                logs = p.load_run_log("run-w4")
                for entry in logs:
                    if entry.get("event") == "human_gate_rejected_signals":
                        found = True
                        break
                if found:
                    break
        assert found, (
            "Pre-fix defect: rejection-only waiting produced no durable audit "
            "record because rejections are only flushed after a valid decision."
        )
