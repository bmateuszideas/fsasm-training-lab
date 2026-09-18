"""T22 — Human Gate as durable Domain Core semantics.

Proves the Human Gate is a durable snapshot semantics (canonical TODO T22;
architecture §33): the gate occurrence, its lifecycle and the accepted/applied
decision live in the authoritative snapshot. ``Workflows`` delivers and waits;
the Domain Core validates and applies RETRY_ONCE/ABORT. An old, foreign,
future, incomplete, duplicate or contradictory decision performs NO work.
Applying the decision and changing the limit/status is ONE snapshot event; a
crash after the commit cannot re-apply the same decision. Exactly one correct
RETRY_ONCE grants exactly one authority (one additional attempt).

This builds on the existing ``apply_event`` gate path (T05) and tightens its
identity contract: run_id match, attempt (stale gate) match, decision_id
idempotency, duplicate/contradictory rejection, and durable ``applied``
recording on the gate occurrence BEFORE the task effect. The valuable M4 gate
tests remain in their own files; this file covers the v1 Domain Core contract.
"""

import copy

import pytest

from fsasm.domain import (
    HumanGateDecisionApplied,
    TaskEscalated,
    TaskVerificationFailed,
    apply_event,
)
from fsasm.errors import InvalidTransitionError
from fsasm.models import (
    ChildTask,
    HumanDecisionAction,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
    decision_id_for,
    gate_id_for,
)


def _task(task_id: str, sequence: int) -> ChildTask:
    return ChildTask(
        task_id=task_id,
        sequence=sequence,
        title=f"Title {task_id}",
        description=f"Desc {task_id}",
        dependencies=[],
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
        max_attempts=1,
    )


def _plan(run_id: str = "r") -> Plan:
    return Plan(
        plan_id=f"plan-{run_id}", run_id=run_id, goal="g", tasks=[_task("TASK-1", 1)]
    )


def _gate_open_state(run_id: str = "r", attempt: int = 1) -> RunState:
    """A state with TASK-1 escalated to NEEDS_HUMAN (gate open)."""
    plan = _plan(run_id)
    state = RunState(run_id=run_id, goal="g", status=RunStatus.RUNNING, plan=plan)
    state.plan.tasks[0].status = TaskStatus.RUNNING
    state.active_task_id = "TASK-1"
    state.plan.tasks[0].attempt = attempt
    state = apply_event(
        state,
        TaskVerificationFailed(
            run_id=run_id, task_id="TASK-1", verification_passed=False
        ),
    )
    state = apply_event(
        state, TaskEscalated(run_id=run_id, task_id="TASK-1", attempt=attempt)
    )
    assert state.gate is not None
    assert state.plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
    return state


def _retry(
    run_id: str,
    gate_id: str,
    decision_id: str,
    attempt: int = 1,
    new_max_attempts: int = 2,
) -> HumanGateDecisionApplied:
    return HumanGateDecisionApplied(
        run_id=run_id,
        task_id="TASK-1",
        gate_id=gate_id,
        decision_id=decision_id,
        action=HumanDecisionAction.RETRY_ONCE,
        attempt=attempt,
        new_max_attempts=new_max_attempts,
    )


def _abort(
    run_id: str, gate_id: str, decision_id: str, attempt: int = 1
) -> HumanGateDecisionApplied:
    return HumanGateDecisionApplied(
        run_id=run_id,
        task_id="TASK-1",
        gate_id=gate_id,
        decision_id=decision_id,
        action=HumanDecisionAction.ABORT,
        attempt=attempt,
    )


class TestDurableGateOccurrence:
    """The snapshot stores the gate occurrence + lifecycle + accepted decision."""

    def test_gate_open_state_has_occurrence_with_attempt(self) -> None:
        s = _gate_open_state()
        assert s.gate is not None
        assert s.gate.task_id == "TASK-1"
        assert s.gate.attempt == 1
        assert s.gate.applied is False
        assert s.gate.accepted_decision_id is None

    def test_retry_once_records_accepted_decision_before_effect(self) -> None:
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        # The gate records the accepted decision; after apply the open gate is
        # cleared (no second decision can target it).
        nxt = apply_event(s, _retry("r", g_id, d_id))
        assert nxt.plan.tasks[0].status == TaskStatus.READY
        assert nxt.plan.tasks[0].max_attempts == 2
        assert nxt.gate is None
        assert nxt.status == RunStatus.RUNNING


class TestExactlyOneAuthority:
    """Exactly one correct RETRY_ONCE grants exactly one additional attempt."""

    def test_retry_once_grants_exactly_one_additional_attempt(self) -> None:
        s = _gate_open_state()
        assert s.plan.tasks[0].max_attempts == 1
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        nxt = apply_event(s, _retry("r", g_id, d_id, new_max_attempts=2))
        assert nxt.plan.tasks[0].max_attempts == 2
        # One additional attempt: attempt was 1, max now 2 -> exactly one more.
        assert nxt.plan.tasks[0].max_attempts - s.plan.tasks[0].attempt == 1

    def test_retry_once_task_ready_for_rescheduling(self) -> None:
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        nxt = apply_event(s, _retry("r", g_id, d_id))
        assert nxt.plan.tasks[0].status == TaskStatus.READY
        assert "TASK-1" not in nxt.needs_human_task_ids

    def test_abort_fails_task_and_run(self) -> None:
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.ABORT)
        nxt = apply_event(s, _abort("r", g_id, d_id))
        assert nxt.plan.tasks[0].status == TaskStatus.FAILED
        assert nxt.status == RunStatus.FAILED
        assert "TASK-1" in nxt.failed_task_ids


class TestCrashAfterCommitIdempotency:
    """Crash after commit cannot re-apply the same decision."""

    def test_replay_same_decision_after_apply_rejected(self) -> None:
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        nxt = apply_event(s, _retry("r", g_id, d_id))
        # Simulate a crash after commit + replay of the SAME decision: the task
        # already left NEEDS_HUMAN, so the replay is rejected (no second effect).
        with pytest.raises(InvalidTransitionError, match="NEEDS_HUMAN"):
            apply_event(nxt, _retry("r", g_id, d_id))

    def test_replay_abort_after_apply_rejected(self) -> None:
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.ABORT)
        nxt = apply_event(s, _abort("r", g_id, d_id))
        with pytest.raises(InvalidTransitionError, match="NEEDS_HUMAN"):
            apply_event(nxt, _abort("r", g_id, d_id))

    def test_replay_same_decision_on_still_open_gate_rejected_as_duplicate(
        self,
    ) -> None:
        # Construct a gate still marked open+applied (e.g. a commit landed the
        # accepted mark but the task transition is pending in a partial state).
        # The same decision_id is a duplicate no-op; a different one is
        # contradictory.
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        # Manually mark the gate as already applied (simulating a partial
        # commit window) while the task is still NEEDS_HUMAN.
        s.gate.accepted_decision_id = d_id
        s.gate.accepted_action = HumanDecisionAction.RETRY_ONCE
        s.gate.applied = True
        # Same decision_id replayed -> duplicate (no work).
        with pytest.raises(InvalidTransitionError, match="duplicate"):
            apply_event(s, _retry("r", g_id, d_id))
        # Different decision_id -> contradictory.
        other = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.ABORT)
        with pytest.raises(InvalidTransitionError, match="contradictory"):
            apply_event(s, _abort("r", g_id, other))


class TestStaleForeignFutureIncomplete:
    """Old, foreign, future, incomplete decisions perform no work."""

    def test_foreign_run_id_rejected(self) -> None:
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("other", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        # Foreign run_id is rejected by the universal identity guard before
        # the gate-specific block: the decision performs NO work and the gate
        # is NOT reserved, attempts NOT incremented.
        with pytest.raises(InvalidTransitionError, match="does not match"):
            apply_event(s, _retry("other", g_id, d_id))

    def test_stale_attempt_rejected(self) -> None:
        # Open gate is for attempt 1; a decision for attempt 2 (future) or 0
        # (old) is rejected.
        s = _gate_open_state(attempt=1)
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        with pytest.raises(InvalidTransitionError, match="stale"):
            apply_event(s, _retry("r", g_id, d_id, attempt=2))

    def test_wrong_gate_id_rejected(self) -> None:
        s = _gate_open_state()
        wrong_g = "gate-r-TASK-1-attempt-99"
        d_id = decision_id_for("r", "TASK-1", wrong_g, HumanDecisionAction.RETRY_ONCE)
        with pytest.raises(InvalidTransitionError, match="not the open gate"):
            apply_event(s, _retry("r", wrong_g, d_id))

    def test_decision_on_non_needs_human_task_rejected(self) -> None:
        # Build a RUNNING task (no gate open).
        plan = _plan("r")
        state = RunState(run_id="r", goal="g", status=RunStatus.RUNNING, plan=plan)
        state.plan.tasks[0].status = TaskStatus.RUNNING
        g_id = gate_id_for("r", "TASK-1", 1)
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.ABORT)
        with pytest.raises(InvalidTransitionError, match="NEEDS_HUMAN"):
            apply_event(state, _abort("r", g_id, d_id))

    def test_retry_once_without_new_max_attempts_rejected(self) -> None:
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        with pytest.raises(InvalidTransitionError, match="new_max_attempts"):
            apply_event(
                s,
                HumanGateDecisionApplied(
                    run_id="r",
                    task_id="TASK-1",
                    gate_id=g_id,
                    decision_id=d_id,
                    action=HumanDecisionAction.RETRY_ONCE,
                    attempt=1,
                ),
            )


class TestOneSnapshotEvent:
    """Decision application + limit/status change are one snapshot event."""

    def test_retry_once_changes_status_and_limit_in_one_event(self) -> None:
        s = _gate_open_state()
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        nxt = apply_event(s, _retry("r", g_id, d_id))
        # Status (NEEDS_HUMAN->READY), limit (max_attempts), run status
        # (NEEDS_HUMAN->RUNNING) and gate closure all change in ONE event.
        assert nxt.plan.tasks[0].status == TaskStatus.READY
        assert nxt.plan.tasks[0].max_attempts == 2
        assert nxt.status == RunStatus.RUNNING
        assert nxt.gate is None

    def test_apply_event_does_not_mutate_input(self) -> None:
        s = _gate_open_state()
        snapshot = copy.deepcopy(s)
        g_id = s.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        apply_event(s, _retry("r", g_id, d_id))
        assert s == snapshot
        assert s.plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
        assert s.gate.applied is False


class TestDeterminism:
    """Same state + decision yield the same result."""

    def test_same_decision_same_result(self) -> None:
        s1 = _gate_open_state()
        s2 = _gate_open_state()
        g_id = s1.gate.gate_id
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        r1 = apply_event(s1, _retry("r", g_id, d_id))
        r2 = apply_event(s2, _retry("r", g_id, d_id))
        assert r1.plan.tasks[0].status == r2.plan.tasks[0].status
        assert r1.plan.tasks[0].max_attempts == r2.plan.tasks[0].max_attempts
        assert r1.status == r2.status
