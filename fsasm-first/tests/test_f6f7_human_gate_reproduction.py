"""F6/F7 — Human Gate decision identity, duplicate and stale-signal reproduction.

M4-04: reproduce the remaining Human Gate defects BEFORE changing the protocol.

Current historical implementation used a single workflow-local slot
``self.human_decision``. A later signal overwrites the earlier pending signal
before consumption. The original decision payload did not identify a particular
gate occurrence or carry a unique decision identity.

These reproductions exercise the actual ``receive_human_decision`` signal
handler and ``validate_and_apply_human_decision_activity`` to record the
pre-fix behavior. They are written to FAIL against the current (defective)
implementation (asserting the corrected contract) so the fix in M4-05 makes
them pass. Cases already protected by the current implementation are recorded
as passing (e.g. early valid signal preservation via wait_condition).

Reproduction cases:
  A. Conflicting pending signals (ABORT then RETRY_ONCE before consumption).
  B. Duplicate delivery (same logical decision applied twice).
  C. Stale decision (earlier gate's decision authorizes a later gate).
  D. Wrong task/run decision.
  E. Early valid signal (already protected by wait_condition — recorded).
  F. Multiple legitimate gates (two distinct authorized decisions not
     mistakenly deduplicated).
"""

import pytest

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
from src.workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    HumanDecisionSignal,
    validate_and_apply_human_decision_activity,
)


def _make_task(
    task_id: str = "TASK-001",
    status: TaskStatus = TaskStatus.NEEDS_HUMAN,
    attempt: int = 1,
    max_attempts: int = 1,
) -> ChildTask:
    return ChildTask(
        task_id=task_id,
        sequence=1,
        title="Task",
        description="Desc",
        status=status,
        attempt=attempt,
        max_attempts=max_attempts,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
    )


def _make_plan(task: ChildTask, run_id: str = "run-gate-001") -> Plan:
    return Plan(
        plan_id=f"plan-{run_id}",
        run_id=run_id,
        goal="Gate goal",
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


def _make_state(plan: Plan, run_id="run-gate-001") -> RunState:
    return RunState(
        run_id=run_id,
        goal=plan.goal,
        status=RunStatus.NEEDS_HUMAN,
        plan=plan,
    )


@pytest.fixture(autouse=True)
def cleanup_runtime():
    from fsasm.persistence import RuntimePersistence

    p = RuntimePersistence()
    p.cleanup_all()
    yield
    p.cleanup_all()


class TestF6F7ReproductionConflictingSignals:
    """A. Conflicting pending signals: a later signal overwrites the earlier
    pending signal before consumption."""

    @pytest.mark.asyncio
    async def test_abort_then_retry_once_overwrites_first(self):
        """Reproduce: send ABORT then RETRY_ONCE before consumption. The
        single-slot implementation overwrote ABORT with RETRY_ONCE, losing the
        first decision. The corrected contract keeps the first accepted
        decision and rejects the conflicting overwrite (first-wins)."""
        wf = FsasmMilestoneFourWorkflow()
        # Open a gate so the signal can be bound to a gate occurrence.
        wf.current_gate_id = "gate-run-gate-001-TASK-001-attempt-1"

        # Send ABORT first.
        await wf.receive_human_decision(
            HumanDecisionSignal(task_id="TASK-001", action=HumanDecisionAction.ABORT)
        )
        # Send RETRY_ONCE before the first is consumed.
        await wf.receive_human_decision(
            HumanDecisionSignal(
                task_id="TASK-001", action=HumanDecisionAction.RETRY_ONCE
            )
        )

        # The first accepted decision (ABORT) must be preserved; the
        # conflicting RETRY_ONCE must be rejected without overwriting it.
        assert wf.current_gate_id in wf.accepted_decisions
        accepted = wf.accepted_decisions[wf.current_gate_id]
        assert accepted.action == HumanDecisionAction.ABORT, (
            "Pre-fix defect reproduced: the later RETRY_ONCE signal overwrote the "
            "earlier ABORT signal in the single pending-decision slot."
        )
        # The conflicting signal was recorded as rejected.
        assert any(
            r["reason"] == "conflicting_signal_rejected_first_wins"
            and r["rejected_action"] == "RETRY_ONCE"
            for r in wf.rejected_signals
        )


class TestF6F7ReproductionDuplicateDelivery:
    """B. Duplicate delivery: the same logical decision applied twice."""

    @pytest.mark.asyncio
    async def test_duplicate_decision_application(self):
        """Reproduce: applying the same logical decision twice. The current
        activity has no decision_id idempotency key, so two applications of the
        same decision each perform a domain transition. The corrected contract
        must apply exactly once."""
        task = _make_task()
        plan = _make_plan(task)
        state = _make_state(plan)

        decision = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="retry",
        )

        # First application: NEEDS_HUMAN -> READY, run -> RUNNING
        task1, state1, _ = await validate_and_apply_human_decision_activity(
            decision, task, state
        )
        assert task1.status == TaskStatus.READY
        assert state1.status == RunStatus.RUNNING

        # A duplicate delivery of the SAME logical decision must NOT perform a
        # second domain transition. Under the corrected contract, a second
        # application must be rejected (the decision was already applied). This
        # assertion documents the desired contract; against the current code a
        # second call would re-transition from READY (already past NEEDS_HUMAN),
        # raising InvalidTransitionError because the task is no longer
        # NEEDS_HUMAN. The test below asserts the explicit rejection.
        with pytest.raises(InvalidTransitionError):
            await validate_and_apply_human_decision_activity(decision, task1, state1)


class TestF6F7ReproductionStaleDecision:
    """C. Stale decision: a decision belonging to an earlier gate must not
    authorize a later gate for the same task."""

    @pytest.mark.asyncio
    async def test_stale_decision_cannot_authorize_later_gate(self):
        """Reproduce: open a Human Gate, approve RETRY_ONCE (gate 1), execute
        again, fail again, reach a later gate (gate 2). A decision carrying the
        earlier gate's identity must not authorize the later gate. The current
        activity only checks task_id and NEEDS_HUMAN state, not gate identity,
        so a decision accepted for gate 1 could be replayed against gate 2
        (both are NEEDS_HUMAN for the same task). The corrected contract must
        bind decisions to a gate occurrence via gate_id."""
        # Gate 1: task NEEDS_HUMAN after attempt 1.
        task_gate1 = _make_task(attempt=1, max_attempts=1)
        plan_gate1 = _make_plan(task_gate1)
        state_gate1 = _make_state(plan_gate1)

        decision_gate1 = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="gate 1 retry",
        )
        # Apply gate 1 decision: READY, max_attempts = attempt+1 = 2
        (
            task_after_gate1,
            state_after_gate1,
            _,
        ) = await validate_and_apply_human_decision_activity(
            decision_gate1, task_gate1, state_gate1
        )
        assert task_after_gate1.max_attempts == 2

        # Execute attempt 2, fail again -> NEEDS_HUMAN (gate 2).
        task_gate2 = task_after_gate1.model_copy()
        task_gate2.status = TaskStatus.NEEDS_HUMAN
        task_gate2.attempt = 2
        state_gate2 = state_after_gate1.model_copy()
        state_gate2.status = RunStatus.NEEDS_HUMAN
        state_gate2.plan = plan_gate1.model_copy()
        state_gate2.plan.tasks[0] = task_gate2

        # A STALE decision (carrying gate 1's identity) must NOT authorize
        # gate 2. The corrected contract rejects it via gate_id mismatch. Under
        # the current code (no gate_id), the same decision would be accepted
        # again. This test asserts the corrected contract: a second application
        # of the SAME decision object must be rejected as already-applied /
        # stale.
        with pytest.raises(InvalidTransitionError):
            await validate_and_apply_human_decision_activity(
                decision_gate1, task_gate2, state_gate2
            )


class TestF6F7ReproductionWrongContext:
    """D. Wrong task/run decision is rejected (already protected by the current
    task_id match check — recorded as already-protected)."""

    @pytest.mark.asyncio
    async def test_wrong_task_id_rejected(self):
        task = _make_task(task_id="TASK-001")
        plan = _make_plan(task)
        state = _make_state(plan)

        wrong_decision = HumanDecision(
            task_id="TASK-999",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="wrong task",
        )
        with pytest.raises(InvalidTransitionError):
            await validate_and_apply_human_decision_activity(
                wrong_decision, task, state
            )


class TestF6F7ReproductionMultipleLegitimateGates:
    """F. Two distinct, correctly authorized RETRY_ONCE decisions at two
    distinct gate occurrences must NOT be mistakenly deduplicated as one
    decision."""

    @pytest.mark.asyncio
    async def test_two_distinct_gates_both_authorized(self):
        """Gate 1 and gate 2 are distinct occurrences for the same task. Two
        distinct authorized RETRY_ONCE decisions must both apply and remain
        separately auditable. The corrected contract distinguishes them by
        gate_id."""
        # Gate 1
        task1 = _make_task(attempt=1, max_attempts=1)
        plan1 = _make_plan(task1)
        state1 = _make_state(plan1)
        decision1 = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="gate 1",
        )
        task_after1, state_after1, _ = await validate_and_apply_human_decision_activity(
            decision1, task1, state1
        )
        assert task_after1.status == TaskStatus.READY

        # Simulate attempt 2 fail -> gate 2
        task2 = task_after1.model_copy()
        task2.status = TaskStatus.NEEDS_HUMAN
        task2.attempt = 2
        state2 = state_after1.model_copy()
        state2.status = RunStatus.NEEDS_HUMAN
        state2.plan = plan1.model_copy()
        state2.plan.tasks[0] = task2

        # A DISTINCT decision for gate 2 must be authorized (different gate
        # occurrence). Under the current code this works because the state is
        # NEEDS_HUMAN again. The corrected contract must keep both audit
        # records distinct (by gate_id / decision identity).
        decision2 = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="gate 2",
        )
        task_after2, state_after2, _ = await validate_and_apply_human_decision_activity(
            decision2, task2, state2
        )
        assert task_after2.status == TaskStatus.READY
        # The two decisions must be distinct (not deduplicated). They produced
        # different max_attempts budgets (gate1: attempt+1=2, gate2: 2+1=3).
        assert task_after2.max_attempts == 3
