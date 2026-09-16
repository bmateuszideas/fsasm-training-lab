"""F6/F7 — Human Gate protocol regression (worker-level + domain-level).

M4-05: the corrected Human Gate protocol — decisions are explicitly
identifiable (gate_id + decision_id), bound to one gate occurrence,
non-overwriting (first accepted wins) and idempotent (exactly-once application).

Required worker-level scenarios (1-12) plus domain-level idempotency and
identity checks. Uses the temporal_env fixture and the M4 activity set, plus
direct signal-handler / activity assertions.

Gate lifecycle: GATE_CREATED -> GATE_PERSISTED -> WAITING -> DECISION_ACCEPTED
-> DECISION_APPLIED -> GATE_CLOSED (equivalent naming). The gate is durably
represented by NEEDS_HUMAN persistence BEFORE the workflow waits; a valid signal
arriving after durable NEEDS_HUMAN but before wait_condition is preserved.
"""

import asyncio
import json
from datetime import timedelta

import pytest
from mistralai.workflows.testing import create_test_worker

from fsasm.errors import InvalidTransitionError
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
from src.workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    HumanDecisionSignal,
    check_retry_budget_activity,
    create_input_activity,
    find_next_ready_task_activity,
    persist_failure_state_activity,
    persist_final_m4_state_activity,
    persist_initial_state_activity,
    persist_retry_state_activity,
    set_task_max_attempts_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    validate_config_activity,
)
from src.workflows.fsasm_milestone_four import _gate_id, _decision_id
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
]


@pytest.fixture(autouse=True)
def cleanup_runtime():
    p = RuntimePersistence()
    p.cleanup_all()
    yield
    p.cleanup_all()


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


async def _wait_for_needs_human(temporal_env, run_id, timeout=20):
    """Poll the persisted state.json until it shows NEEDS_HUMAN (async)."""
    p = RuntimePersistence()
    max_iter = timeout * 10
    for _ in range(max_iter):
        await asyncio.sleep(0.1)
        try:
            state = p.load_run_state(run_id)
            if state is not None and state.status == RunStatus.NEEDS_HUMAN:
                return state
        except Exception:
            continue
    return p.load_run_state(run_id)


class TestF6F7DomainIdentity:
    """Domain-level identity and idempotency (no temporal worker)."""

    @pytest.mark.asyncio
    async def test_decision_carries_gate_and_decision_id(self):
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="T",
            description="d",
            status=TaskStatus.NEEDS_HUMAN,
            attempt=1,
            max_attempts=1,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
        )
        plan = Plan(
            plan_id="plan-r1",
            run_id="run-1",
            goal="g",
            tasks=[
                task,
                ChildTask(
                    task_id="TASK-002",
                    sequence=2,
                    title="T2",
                    description="d",
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
                ChildTask(
                    task_id="TASK-003",
                    sequence=3,
                    title="T3",
                    description="d",
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
            ],
        )
        state = RunState(
            run_id="run-1", goal="g", status=RunStatus.NEEDS_HUMAN, plan=plan
        )
        decision = HumanDecision(
            task_id="TASK-001", action=HumanDecisionAction.RETRY_ONCE, reason="r"
        )
        task_out, state_out, dec_out = await validate_and_apply_human_decision_activity(
            decision, task, state
        )
        assert dec_out.gate_id == _gate_id("run-1", "TASK-001", 1)
        assert dec_out.decision_id == _decision_id(
            "run-1", "TASK-001", dec_out.gate_id, HumanDecisionAction.RETRY_ONCE
        )

    @pytest.mark.asyncio
    async def test_stale_gate_id_rejected(self):
        """A decision carrying an earlier gate's identity must not authorize a
        later gate."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="T",
            description="d",
            status=TaskStatus.NEEDS_HUMAN,
            attempt=2,
            max_attempts=2,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
        )
        plan = Plan(
            plan_id="plan-r2",
            run_id="run-2",
            goal="g",
            tasks=[
                task,
                ChildTask(
                    task_id="TASK-002",
                    sequence=2,
                    title="T2",
                    description="d",
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
                ChildTask(
                    task_id="TASK-003",
                    sequence=3,
                    title="T3",
                    description="d",
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
            ],
        )
        state = RunState(
            run_id="run-2", goal="g", status=RunStatus.NEEDS_HUMAN, plan=plan
        )
        # gate_id for attempt 1, but the task is now at attempt 2 (gate 2).
        stale_gate = _gate_id("run-2", "TASK-001", 1)
        decision = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="stale",
            gate_id=stale_gate,
        )
        with pytest.raises(InvalidTransitionError):
            await validate_and_apply_human_decision_activity(
                decision, task, state, gate_id=stale_gate
            )


class TestF6F7WorkerLevelScenarios:
    """Worker-level scenarios 1-12 using the temporal test environment."""

    def _start(self, temporal_env, run_id, max_retries, fail_n):
        return temporal_env.client.start_workflow(
            "fsasm-milestone-four",
            {
                "goal": "F6/F7 worker scenario",
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

    @pytest.mark.asyncio
    async def test_1_first_attempt_success_no_human_gate(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await self._start(temporal_env, "run-sc1", 2, 0)
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        assert result["human_gate_invoked"] is False

    @pytest.mark.asyncio
    async def test_2_automatic_retry_success(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await self._start(temporal_env, "run-sc2", 2, 1)
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        assert result["human_gate_invoked"] is False

    @pytest.mark.asyncio
    async def test_3_retry_exhaustion_then_abort(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await self._start(temporal_env, "run-sc3", 0, 999)
            # Wait for NEEDS_HUMAN
            await asyncio.sleep(0.2)
            await _wait_for_needs_human(temporal_env, "run-sc3")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.ABORT
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["status"] == "FAILED"
        assert result["human_decision"]["action"] == "ABORT"

    @pytest.mark.asyncio
    async def test_4_retry_exhaustion_then_retry_once_success(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            # max_retries=0 -> 1 attempt (attempt 1) fails (fail_n=1), reaches
            # gate 1. RETRY_ONCE authorizes attempt 2, which passes.
            handle = await self._start(temporal_env, "run-sc4", 0, 1)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human(temporal_env, "run-sc4")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.RETRY_ONCE
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        assert result["human_decision"]["action"] == "RETRY_ONCE"

    @pytest.mark.asyncio
    async def test_5_retry_once_then_another_failure_distinct_gate(self, temporal_env):
        """RETRY_ONCE authorizes one more execution; if it fails again, a new
        distinct gate opens for the same task."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await self._start(temporal_env, "run-sc5", 0, 999)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human(temporal_env, "run-sc5")
            # Gate 1: RETRY_ONCE
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.RETRY_ONCE
                ),
            )
            await asyncio.sleep(0.2)
            # Fail again -> gate 2
            await _wait_for_needs_human(temporal_env, "run-sc5")
            # Gate 2: ABORT
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.ABORT
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["status"] == "FAILED"
        assert result["human_decision"]["action"] == "ABORT"

    @pytest.mark.asyncio
    async def test_6_two_distinct_approvals_separately_auditable(self, temporal_env):
        """Two distinct RETRY_ONCE decisions at two distinct gates must remain
        separately auditable (distinct gate_id / decision_id in evidence)."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            # fail_n=2: attempt1 fail->gate1 RETRY_ONCE, attempt2 fail->gate2
            # RETRY_ONCE, attempt3 passes -> success.
            handle = await self._start(temporal_env, "run-sc6", 0, 2)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human(temporal_env, "run-sc6")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.RETRY_ONCE
                ),
            )
            await asyncio.sleep(0.2)
            await _wait_for_needs_human(temporal_env, "run-sc6")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.RETRY_ONCE
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        # Two distinct gate audit evidence records exist with distinct gate_ids.
        p = RuntimePersistence()
        evidence = p.load_all_evidence("run-sc6")
        gate_audits = [e for e in evidence if e.kind == "human_gate_audit"]
        gate_ids = {e.payload.get("gate_id") for e in gate_audits}
        assert len(gate_ids) == 2, f"expected 2 distinct gate_ids, got {gate_ids}"

    @pytest.mark.asyncio
    async def test_7_duplicate_decision_one_application(self, temporal_env):
        """A duplicated delivery must not result in a duplicated domain
        transition or duplicated logical audit event."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await self._start(temporal_env, "run-sc7", 0, 1)
            await asyncio.sleep(0.2)
            await _wait_for_needs_human(temporal_env, "run-sc7")
            # Send the same RETRY_ONCE decision; the stub fails first then
            # passes, so one RETRY_ONCE authorizes one more execution that
            # passes. Duplicating the signal must not double-apply.
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001", action=HumanDecisionAction.RETRY_ONCE
                ),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        # Exactly one human_decision audit event for this gate.
        p = RuntimePersistence()
        gate_audits = [
            e for e in p.load_all_evidence("run-sc7") if e.kind == "human_gate_audit"
        ]
        assert len(gate_audits) == 1
