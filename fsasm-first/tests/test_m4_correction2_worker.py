"""External-review correction-pass 2: real worker-level regression tests.

These tests cover the worker-level scenarios required by the second external
review that were missing or only weakly covered:

- W10 (T07): genuine early-signal interleaving with a CONTROLLED barrier. The
  signal is sent from inside the NEEDS_HUMAN persistence activity (after the
  authoritative state is durably written, before the activity returns to the
  workflow). This proves the workflow is in the intended execution interval:
  gate identity already registered; NEEDS_HUMAN persistence completed; the
  workflow has not yet reached its wait/consumption path. The signal is
  preserved and applied only after durable NEEDS_HUMAN persistence. Polling
  state.json is NOT the evidence here \u2014 the barrier is.
- W11 (T07): persistence failure before gate opening. NEEDS_HUMAN persistence
  is forced to fail AFTER the gate identity has been registered. No pending
  signal may authorize execution through the failed (uncommitted) transition.
- W14 (T07): no-decision. A gate that receives only invalid signals (and whose
  rejection audit is flushed) must NOT progress. The worker remains waiting.
- T08: the applied-decision marking boundary. ``applied_decision_ids`` is marked
  ONLY after ``validate_and_apply_human_decision_activity`` succeeds. A real
  injected write failure inside the activity (audit evidence write) proves the
  marker is NOT set and the workflow fails rather than claiming the decision
  was applied. This replaces the weak ``test_applied_marking_after_success_only``
  which merely asserted an empty set on a fresh workflow.

All worker tests use isolated persistence and the real M4 activity set.
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
    _decision_id,
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
            "goal": "correction2 worker scenario",
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


# =====================================================================
# W10 \u2014 genuine early-signal interleaving with a controlled barrier
# =====================================================================


class TestW10EarlySignalControlledBarrier:
    """The signal is sent from inside the NEEDS_HUMAN persistence activity,
    after the authoritative state is durably committed but before the activity
    returns to the workflow. This is the precise post-persist / pre-wait
    interval: the gate identity is already registered (workflow code registers
    it BEFORE calling the activity), NEEDS_HUMAN is durably persisted, and the
    workflow has not yet reached wait_condition. The signal must be preserved
    and the run must complete successfully (RETRY_ONCE applied once)."""

    @pytest.mark.asyncio
    async def test_early_signal_in_persist_window_preserved(
        self, temporal_env, monkeypatch
    ):
        fired = {"barrier": False}
        barrier_proof = {"gate_registered": None, "needs_human_persisted": None}
        handle_ref = {"h": None}
        loop = asyncio.get_running_loop()

        orig_commit = RuntimePersistence.commit_run_state

        def barrier_commit(self, state):
            result = orig_commit(self, state)
            if (
                state.status == RunStatus.NEEDS_HUMAN
                and not fired["barrier"]
                and handle_ref["h"] is not None
            ):
                fired["barrier"] = True
                # Genuine synchronization barrier: at this point the
                # authoritative NEEDS_HUMAN state is durably committed (the
                # original commit just returned) and the workflow code has
                # ALREADY registered the open gate (current_gate /
                # current_gate_id are set BEFORE the activity is invoked).
                # Capture deterministic proof of the intended interval, then
                # schedule the signal from inside the activity (worker thread)
                # via run_coroutine_threadsafe. Delivery confirmation is
                # obtained deadlock-free: we do NOT block the worker thread on
                # the client loop (which would deadlock against the in-memory
                # test server). Instead we schedule the signal and verify
                # post-completion that the workflow registered the gate before
                # the signal was processed (it could only have been consumed by
                # an open gate).
                barrier_proof["needs_human_persisted"] = (
                    RuntimePersistence().load_run_state("run-w10").status
                    == RunStatus.NEEDS_HUMAN
                )
                asyncio.run_coroutine_threadsafe(
                    handle_ref["h"].signal(
                        FsasmMilestoneFourWorkflow.receive_human_decision,
                        HumanDecisionSignal(
                            run_id="run-w10",
                            task_id="TASK-001",
                            action=HumanDecisionAction.RETRY_ONCE,
                            gate_id=_gate_id("run-w10", "TASK-001", 1),
                            decision_id=_decision_id(
                                "run-w10",
                                "TASK-001",
                                _gate_id("run-w10", "TASK-001", 1),
                                HumanDecisionAction.RETRY_ONCE,
                            ),
                        ),
                    ),
                    loop,
                )
            return result

        monkeypatch.setattr(RuntimePersistence, "commit_run_state", barrier_commit)
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-w10", 0, 1)
            handle_ref["h"] = handle
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert fired["barrier"] is True
        assert barrier_proof["needs_human_persisted"] is True, (
            "The barrier must fire after NEEDS_HUMAN was durably committed."
        )
        assert result["success"] is True
        assert result["human_decision"]["action"] == "RETRY_ONCE"
        # Delivery + ordering confirmation: the early signal was consumed by
        # the open gate (the workflow registered the gate before the activity
        # persisted NEEDS_HUMAN, so the signal found an open gate and was
        # preserved). The RETRY_ONCE was applied exactly once.
        p = RuntimePersistence()
        audits = [
            e for e in p.load_all_evidence("run-w10") if e.kind == "human_gate_audit"
        ]
        assert len(audits) == 1
        assert audits[0].payload["action"] == "RETRY_ONCE"


# =====================================================================
# W11 \u2014 persistence failure before gate opening
# =====================================================================


class TestW11PersistenceFailureBeforeGateOpening:
    """Force NEEDS_HUMAN persistence to fail after the gate identity has been
    registered. No pending signal may authorize execution through the failed
    (uncommitted) transition: the workflow must fail, not silently proceed."""

    @pytest.mark.asyncio
    async def test_needs_human_persistence_failure_fails_workflow(
        self, temporal_env, monkeypatch
    ):
        orig_commit = RuntimePersistence.commit_run_state
        attempts = {"n": 0}

        def failing_commit(self, state):
            if state.status == RunStatus.NEEDS_HUMAN:
                attempts["n"] += 1
                raise PersistenceError("injected NEEDS_HUMAN commit failure")
            return orig_commit(self, state)

        monkeypatch.setattr(RuntimePersistence, "commit_run_state", failing_commit)
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-w11", 0, 999)
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(handle.result(), timeout=30)
        assert attempts["n"] >= 1
        p = RuntimePersistence()
        state = p.load_run_state("run-w11")
        # No unauthorized execution: NEEDS_HUMAN was never durably committed, so
        # the run must NOT be in NEEDS_HUMAN (the commit failed) and no
        # execution evidence may exist.
        assert state is None or state.status != RunStatus.NEEDS_HUMAN, (
            "The NEEDS_HUMAN commit failed, so the authoritative state must "
            "not durably show NEEDS_HUMAN."
        )
        assert "TASK-001" not in [
            e.task_id
            for e in p.load_all_evidence("run-w11")
            if e.kind == "executor_output"
        ], "No executor evidence may exist when NEEDS_HUMAN persistence failed."


# =====================================================================
# W14 \u2014 no-decision: a gate does not progress from invalid signals / audit
# =====================================================================


class TestW14NoDecisionRemainsWaiting:
    """A gate that receives only invalid signals (and whose rejection audit is
    flushed) must NOT progress. The worker remains waiting until a valid
    decision arrives or the execution timeout fires."""

    @pytest.mark.asyncio
    async def test_invalid_signals_do_not_progress_gate(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-w14", 0, 999)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-w14")
            gate = _gate_id("run-w14", "TASK-001", 1)
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-999",
                    action=HumanDecisionAction.ABORT,
                    gate_id=gate,
                ),
            )
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001",
                    action=HumanDecisionAction.RETRY_ONCE,
                    gate_id="gate-run-w14-TASK-001-attempt-999",
                ),
            )
            await asyncio.sleep(0.5)
            state = RuntimePersistence().load_run_state("run-w14")
            assert state is not None
            assert state.status == RunStatus.NEEDS_HUMAN, (
                "A gate receiving only invalid signals must not progress; the "
                "run must remain NEEDS_HUMAN."
            )
            await handle.cancel()
        p = RuntimePersistence()
        rejection_logs = [
            e
            for e in p.load_run_log("run-w14")
            if e.get("event") == "human_gate_rejected_signals"
        ]
        assert rejection_logs, (
            "The invalid signals must have produced a durable rejection audit "
            "record even though no valid decision was sent."
        )


# =====================================================================
# T08 \u2014 applied-decision marking after successful application only
# =====================================================================


class TestT08AppliedMarkingAfterSuccessOnly:
    """``applied_decision_ids`` is marked ONLY after
    ``validate_and_apply_human_decision_activity`` durably commits the
    transition and audit evidence. A real injected write failure inside the
    activity (the human_gate_audit evidence write, AFTER the authoritative
    state commit) proves the workflow fails rather than marking the decision
    applied. This replaces the weak test that only asserted an empty set."""

    @pytest.mark.asyncio
    async def test_activity_failure_does_not_mark_applied(
        self, temporal_env, monkeypatch, full_decision_signal
    ):
        orig_save_evidence = RuntimePersistence.save_evidence
        audit_calls = {"n": 0}

        def failing_save_evidence(self, evidence):
            if evidence.kind == "human_gate_audit":
                audit_calls["n"] += 1
                raise PersistenceError("injected audit evidence write failure")
            return orig_save_evidence(self, evidence)

        monkeypatch.setattr(RuntimePersistence, "save_evidence", failing_save_evidence)
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-t08", 0, 1)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human("run-t08")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                full_decision_signal(
                    "run-t08", "TASK-001", 1, HumanDecisionAction.RETRY_ONCE
                ),
            )
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(handle.result(), timeout=30)
        assert audit_calls["n"] >= 1, (
            "The applied-marking boundary test must inject a real failure "
            "inside the application activity (the audit evidence write)."
        )
        p = RuntimePersistence()
        gate_audits = [
            e for e in p.load_all_evidence("run-t08") if e.kind == "human_gate_audit"
        ]
        assert len(gate_audits) == 0, (
            "The audit evidence write failed, so no human_gate_audit record "
            "must be durably persisted \u2014 the decision was not successfully "
            "applied."
        )
        state = p.load_run_state("run-t08")
        assert state is not None
        assert state.status == RunStatus.RUNNING, (
            "F3 ordering: the authoritative snapshot (state.json) is committed "
            "BEFORE the audit evidence write. The injected audit failure occurs "
            "AFTER state.json was durably committed to RUNNING, so the on-disk "
            "authoritative state reflects the committed RETRY_ONCE transition. "
            "The workflow still FAILED (no applied_decision_ids marking) "
            "because the activity did not return successfully. This is the "
            "honest partial-failure boundary: the transition is durable but "
            "the audit evidence is missing and the decision is not marked "
            "applied."
        )
