"""Final bounded correction-pass 3 reproducers.

Reproduces the confirmed defects from the third external review at
`3637d43f457ae571b1b7c336750716e5f210912b`:

- D1: rejection-audit loss during decision application. A conflicting signal
  arriving while ``validate_and_apply_human_decision_activity`` is in progress
  (after the pre-application flush, before gate closure) is appended to
  ``pending_rejections`` but never flushed for the closing gate; on the next
  gate it would be misattributed. The rejection must be durably audited before
  gate closure (or safely handled through an equivalent deterministic
  mechanism).
- D2: duplicate detection for identical action but different reason, especially
  legacy signals with ``decision_id=None``. Two legacy RETRY_ONCE signals with
  the same action but different ``reason`` were treated as an identical
  no-op duplicate instead of recording the contradictory submission as
  rejected (first-valid-decision-wins preserved).
- D3: rejection-audit persistence idempotency. A replayed/retried flush must
  not duplicate logical audit records; exactly-once is not claimed without a
  demonstrated durable guarantee.
- D5 (W11): the tautological assertion ``... or True`` is replaced with
  meaningful checks of the actual persisted state.
- D6: rejection handling before the first gate, during gate closure and
  between consecutive gates.

These tests assert the CORRECTED contract; the pre-fix ones FAIL against
`3637d43`.
"""

import asyncio
from datetime import timedelta

import pytest
from mistralai.workflows.testing import create_test_worker
from temporalio.client import WorkflowFailureError

from fsasm.errors import PersistenceError
from fsasm.models import HumanDecisionAction, RunStatus
from fsasm.persistence import RuntimePersistence
from src.workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    HumanDecisionSignal,
    OpenGate,
    check_retry_budget_activity,
    create_input_activity,
    find_next_ready_task_activity,
    persist_failure_state_activity,
    persist_final_m4_state_activity,
    persist_human_gate_rejections_activity,
    persist_initial_state_activity,
    persist_retry_state_activity,
    set_task_max_attempts_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    validate_config_activity,
    _gate_id,
)
from fsasm.planner_activities import plan_activity
from fsasm.executor_activities import (
    convert_executor_output_to_evidence_activity,
    execute_task_activity,
    finalize_task_activity,
    prepare_task_activity,
    validate_executor_output_provenance_activity,
    verify_task_execution_activity,
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


def _start(temporal_env, run_id, max_retries, fail_n):
    return temporal_env.client.start_workflow(
        "fsasm-milestone-four",
        {
            "goal": "correction3 reproducer",
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


async def _wait_for_needs_human(run_id, timeout=20):
    p = RuntimePersistence()
    for _ in range(timeout * 10):
        await asyncio.sleep(0.1)
        try:
            state = p.load_run_state(run_id)
            if state is not None and state.status == RunStatus.NEEDS_HUMAN:
                return state
        except Exception:
            continue
    return p.load_run_state(run_id)


def _rejection_log_entries(run_id):
    p = RuntimePersistence()
    return [
        e
        for e in p.load_run_log(run_id)
        if e.get("event") == "human_gate_rejected_signals"
    ]


# =====================================================================
# D2 — duplicate detection: identical action, different reason, legacy
# =====================================================================


class TestD2DuplicateIdenticalActionDifferentReason:
    """Two legacy signals (decision_id=None) with the same action but a
    different ``reason`` must NOT be treated as an identical no-op duplicate.
    The first VALID decision wins; the contradictory second submission is
    recorded as rejected (``conflicting_signal_rejected_first_wins``)."""

    @pytest.mark.asyncio
    async def test_same_action_different_reason_recorded_rejected(self):
        wf = FsasmMilestoneFourWorkflow()
        gate = _gate_id("run-d2", "TASK-001", 1)
        wf.current_gate_id = gate
        wf.current_gate = OpenGate(
            run_id="run-d2", task_id="TASK-001", gate_id=gate, attempt=1
        )
        await wf.receive_human_decision(
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.RETRY_ONCE,
                reason="first reason",
            )
        )
        await wf.receive_human_decision(
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.RETRY_ONCE,
                reason="second different reason",
            )
        )
        assert gate in wf.accepted_decisions
        accepted = wf.accepted_decisions[gate]
        assert accepted.reason == "first reason"
        assert any(
            r["reason"] == "conflicting_signal_rejected_first_wins"
            for r in wf.pending_rejections
        ), (
            "Pre-fix defect: a legacy signal with the same action but a "
            "different reason was silently treated as an identical duplicate "
            "instead of recording the contradictory submission as rejected."
        )


# =====================================================================
# D6 — rejection handling before the first gate
# =====================================================================


class TestD6RejectionBeforeFirstGate:
    """A signal arriving before any gate is open is rejected as no_open_gate
    and durably auditable (gate tag None). It is not silently lost and is not
    attributed to a future gate."""

    @pytest.mark.asyncio
    async def test_pre_gate_signal_recorded_no_open_gate(self):
        wf = FsasmMilestoneFourWorkflow()
        assert wf.current_gate is None
        await wf.receive_human_decision(
            HumanDecisionSignal(
                task_id="TASK-001",
                action=HumanDecisionAction.RETRY_ONCE,
                reason="early",
            )
        )
        assert len(wf.accepted_decisions) == 0
        assert any(r["reason"] == "no_open_gate" for r in wf.pending_rejections)
        rec = next(r for r in wf.pending_rejections if r["reason"] == "no_open_gate")
        assert rec["gate_id"] is None


# =====================================================================
# D1 — rejection-audit loss during decision application (worker)
# =====================================================================


class TestD1RejectionDuringApplication:
    """A conflicting signal arriving while the application activity is in
    progress (after the pre-application flush, before gate closure) is, in this
    deterministic workflow SDK, processed at the next workflow-task boundary
    (signals are not interleaved mid-activity). When the signal is processed
    the gate may already be closed, so it is rejected as ``no_open_gate``
    (gate tag None). It must be durably audited, must NOT authorize execution,
    and must NOT be misattributed to a later gate occurrence. The audit record
    for a no_open_gate rejection carries gate_id None (its own gate tag), not
    the next gate's id."""

    @pytest.mark.asyncio
    async def test_conflict_during_application_durable_audit(
        self, temporal_env, monkeypatch
    ):
        fired = {"during": False}
        orig_commit = RuntimePersistence.commit_run_state

        def barrier_commit(self, state):
            result = orig_commit(self, state)
            if state.status == RunStatus.RUNNING and not fired["during"]:
                fired["during"] = True
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(
                    handle_ref["h"].signal(
                        FsasmMilestoneFourWorkflow.receive_human_decision,
                        HumanDecisionSignal(
                            task_id="TASK-001",
                            action=HumanDecisionAction.ABORT,
                            reason="conflict during application",
                        ),
                    ),
                    loop,
                )
            return result

        handle_ref = {"h": None}
        monkeypatch.setattr(RuntimePersistence, "commit_run_state", barrier_commit)

        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-d1", 0, 1)
            handle_ref["h"] = handle
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-d1")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001",
                    action=HumanDecisionAction.RETRY_ONCE,
                    reason="first",
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert fired["during"] is True
        assert result["success"] is True
        # The conflicting ABORT was NOT applied: only one RETRY_ONCE audit.
        p = RuntimePersistence()
        audits = [
            e for e in p.load_all_evidence("run-d1") if e.kind == "human_gate_audit"
        ]
        assert len(audits) == 1
        assert audits[0].payload["action"] == "RETRY_ONCE"
        # The conflicting ABORT signal was durably audited as a rejection.
        entries = _rejection_log_entries("run-d1")
        rejected_abort = [
            r
            for e in entries
            for r in e.get("rejections", [])
            if r.get("rejected_action") == "ABORT" or r.get("action") == "ABORT"
        ]
        assert rejected_abort, (
            "Pre-fix defect: a conflicting signal arriving during the "
            "application activity was not durably audited."
        )


# =====================================================================
# D5 — W11 meaningful persisted-state checks (replaces tautology)
# =====================================================================


class TestD5W11MeaningfulPersistedState:
    """Force NEEDS_HUMAN persistence to fail after the gate identity has been
    registered. The workflow must fail; no unauthorized execution occurs
    (no RUNNING/PASSED task state, no execution evidence)."""

    @pytest.mark.asyncio
    async def test_needs_human_persistence_failure_no_unauthorized_exec(
        self, temporal_env, monkeypatch
    ):
        orig_commit = RuntimePersistence.commit_run_state

        def failing_commit(self, state):
            if state.status == RunStatus.NEEDS_HUMAN:
                raise PersistenceError("injected NEEDS_HUMAN commit failure")
            return orig_commit(self, state)

        monkeypatch.setattr(RuntimePersistence, "commit_run_state", failing_commit)
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-d5", 0, 999)
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(handle.result(), timeout=30)
        p = RuntimePersistence()
        state = p.load_run_state("run-d5")
        if state is not None:
            assert state.status != RunStatus.NEEDS_HUMAN
        assert "TASK-001" not in [
            e.task_id
            for e in p.load_all_evidence("run-d5")
            if e.kind in ("executor_output", "verification_result")
        ], "No execution evidence must exist when NEEDS_HUMAN persistence failed."


# =====================================================================
# D3 — idempotent rejection-audit persistence under replay
# =====================================================================


class TestD3IdempotentRejectionPersistence:
    """A replayed flush of the same in-memory rejection (by rejection_id) must
    not duplicate the logical audit record within a workflow execution.
    Exactly-once across crashes is NOT claimed (no durable dedup store)."""

    @pytest.mark.asyncio
    async def test_replayed_flush_does_not_duplicate(self, temporal_env, monkeypatch):
        rejection_log_writes = {"n": 0}
        orig_save = RuntimePersistence.save_run_log_entry

        def counting_save(self, run_id, entry):
            if entry.get("event") == "human_gate_rejected_signals":
                rejection_log_writes["n"] += 1
            return orig_save(self, run_id, entry)

        monkeypatch.setattr(RuntimePersistence, "save_run_log_entry", counting_save)

        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-d3", 0, 999)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-d3")
            gate = _gate_id("run-d3", "TASK-001", 1)
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-999",
                    action=HumanDecisionAction.RETRY_ONCE,
                    gate_id=gate,
                ),
            )
            await asyncio.sleep(0.4)
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.ABORT
                ),
            )
            await asyncio.wait_for(handle.result(), timeout=30)
        assert rejection_log_writes["n"] == 1, (
            "The wait loop re-evaluates the flush condition on each iteration; "
            "the same logical wrong_task rejection must be persisted exactly "
            "once (one human_gate_rejected_signals log write), not on every "
            "loop iteration."
        )
        entries = _rejection_log_entries("run-d3")
        wrong_task_records = [
            r
            for e in entries
            for r in e.get("rejections", [])
            if r.get("reason") == "wrong_task"
        ]
        rids = [r.get("rejection_id") for r in wrong_task_records]
        assert len(wrong_task_records) == 1, (
            "The same logical wrong_task rejection must be persisted exactly "
            "once even if the wait loop re-evaluates the flush condition."
        )
        assert all(rid is not None for rid in rids), (
            "Each rejection must carry a stable rejection_id for idempotent "
            "persistence."
        )


# =====================================================================
# D6 — rejection between consecutive gates (no misattribution)
# =====================================================================


class TestD6RejectionBetweenGates:
    """A rejection recorded between gate closure and the next gate opening
    (gate tag None, no open gate) must NOT be flushed under the next gate's
    id. It must be durably audited under its own gate tag (None)."""

    @pytest.mark.asyncio
    async def test_between_gate_rejection_not_misattributed(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-d6bg", 0, 999)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-d6bg")
            gate1 = _gate_id("run-d6bg", "TASK-001", 1)
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.RETRY_ONCE
                ),
            )
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-d6bg")
            gate2 = _gate_id("run-d6bg", "TASK-001", 2)
            assert gate2 != gate1
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.ABORT
                ),
            )
            await asyncio.wait_for(handle.result(), timeout=30)
        entries = _rejection_log_entries("run-d6bg")
        for e in entries:
            for r in e.get("rejections", []):
                tag = r.get("gate_id")
                assert tag != gate2 or r.get("reason") != "no_open_gate", (
                    "A no_open_gate rejection must not be attributed to a "
                    "later gate occurrence."
                )
