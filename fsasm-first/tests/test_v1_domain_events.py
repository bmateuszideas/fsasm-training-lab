"""T05 — Czysty Domain Core i jedno zastosowanie zdarzeń.

Proves the v1 Domain Core contract (architecture §11, §30, §33):
- ``apply_event`` returns a new state and never mutates its input.
- The same state+event always yields the same result (determinism).
- At most one active Child Task per run.
- Only the Domain Core grants PASS, retry and gate transitions.
- A model "I am done" without a verification event + accepted evidence cannot
  produce PASS.
- Bad identity, illegal transition, exceeded limit and a model PASS attempt
  are rejected before any state change.
- ``revision`` is intentionally untouched (T06 increments it on commit).

The matrices moved to ``fsasm.domain`` are the single authority; the imperative
M4 ``transitions.py`` re-uses them (one set of rules, not two).
"""

import copy

import pytest
from pydantic import ValidationError as PydanticValidationError

from fsasm.domain import (
    EvidenceAccepted,
    HumanGateDecisionApplied,
    RunCompleted,
    RunFailed,
    RunPlanned,
    RunStarted,
    RUN_ALLOWED_TRANSITIONS,
    TASK_ALLOWED_TRANSITIONS,
    TaskActivated,
    TaskEscalated,
    TaskRetried,
    TaskVerificationFailed,
    TaskVerificationPassed,
    apply_event,
)
from fsasm.errors import InvalidTransitionError, RetryExhaustedError
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


def _task(task_id: str, sequence: int, deps: list[str] | None = None) -> ChildTask:
    return ChildTask(
        task_id=task_id,
        sequence=sequence,
        title=f"Title {task_id}",
        description=f"Desc {task_id}",
        dependencies=list(deps) if deps else [],
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
    )


def _plan(run_id: str, n: int = 2) -> Plan:
    tasks = [
        _task(f"TASK-{i}", i, deps=[f"TASK-{i - 1}"] if i > 1 else [])
        for i in range(1, n + 1)
    ]
    return Plan(plan_id=f"plan-{run_id}", run_id=run_id, goal="g", tasks=tasks)


def _planned_state(run_id: str = "r", n: int = 2) -> RunState:
    plan = _plan(run_id, n)
    # tasks start PENDING; mark READY so they can be activated.
    for t in plan.tasks:
        t.status = TaskStatus.READY
    state = RunState(run_id=run_id, goal="g", status=RunStatus.RUNNING, plan=plan)
    return state


def _running_state(run_id: str = "r", n: int = 2) -> RunState:
    """A state with TASK-1 active (RUNNING, attempt 1)."""
    state = _planned_state(run_id, n)
    state = apply_event(state, TaskActivated(run_id=run_id, task_id="TASK-1"))
    return state


# =============================================================================
# Immutability + determinism
# =============================================================================


class TestPurityAndDeterminism:
    def test_input_state_is_not_mutated(self):
        s = _planned_state()
        snapshot = copy.deepcopy(s)
        apply_event(s, TaskActivated(run_id="r", task_id="TASK-1"))
        assert s == snapshot, "apply_event must not mutate its input state"

    def test_input_task_object_is_not_mutated(self):
        s = _planned_state()
        original_task_status = s.plan.tasks[0].status
        original_attempt = s.plan.tasks[0].attempt
        apply_event(s, TaskActivated(run_id="r", task_id="TASK-1"))
        assert s.plan.tasks[0].status == original_task_status
        assert s.plan.tasks[0].attempt == original_attempt

    def test_same_state_and_event_yield_equal_result(self):
        base = _planned_state()
        s1 = copy.deepcopy(base)
        s2 = copy.deepcopy(base)
        r1 = apply_event(s1, TaskActivated(run_id="r", task_id="TASK-1"))
        r2 = apply_event(s2, TaskActivated(run_id="r", task_id="TASK-1"))
        assert r1 == r2, "same state+event must yield equal result"

    def test_result_is_a_new_object(self):
        s = _planned_state()
        nxt = apply_event(s, TaskActivated(run_id="r", task_id="TASK-1"))
        assert nxt is not s
        assert nxt.plan is not s.plan

    def test_events_are_immutable(self):
        ev = TaskActivated(run_id="r", task_id="TASK-1")
        with pytest.raises((PydanticValidationError, Exception)):
            ev.task_id = "TASK-2"  # type: ignore[misc]

    def test_revision_is_not_changed_by_apply_event(self):
        s = _planned_state()
        s.revision = 4
        nxt = apply_event(s, TaskActivated(run_id="r", task_id="TASK-1"))
        assert nxt.revision == 4, "T06 increments revision on commit, not apply_event"


# =============================================================================
# One active task
# =============================================================================


class TestOneActiveTask:
    def test_second_activation_rejected(self):
        s = _running_state()
        with pytest.raises(InvalidTransitionError, match="already active"):
            apply_event(s, TaskActivated(run_id="r", task_id="TASK-2"))

    def test_activation_sets_active_task_id(self):
        s = _running_state()
        assert s.active_task_id == "TASK-1"

    def test_pass_clears_active_task_id(self):
        s = _running_state()
        s = apply_event(
            s, EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev1"])
        )
        s = apply_event(
            s,
            TaskVerificationPassed(
                run_id="r", task_id="TASK-1", verification_passed=True
            ),
        )
        assert s.active_task_id is None

    def test_fail_clears_active_task_id(self):
        s = _running_state()
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        assert s.active_task_id is None


# =============================================================================
# Exclusive Domain Core control over PASS
# =============================================================================


class TestExclusivePassControl:
    def test_pass_without_evidence_rejected(self):
        s = _running_state()
        with pytest.raises(
            InvalidTransitionError, match="accepted evidence for the current attempt"
        ):
            apply_event(
                s,
                TaskVerificationPassed(
                    run_id="r", task_id="TASK-1", verification_passed=True
                ),
            )

    def test_pass_with_verification_false_rejected(self):
        s = _running_state()
        s = apply_event(
            s, EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev1"])
        )
        with pytest.raises(InvalidTransitionError, match="verification_passed=True"):
            apply_event(
                s,
                TaskVerificationPassed(
                    run_id="r", task_id="TASK-1", verification_passed=False
                ),
            )

    def test_pass_requires_accepted_evidence_first(self):
        s = _running_state()
        nxt = apply_event(
            s,
            EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev-diff"]),
        )
        nxt = apply_event(
            nxt,
            TaskVerificationPassed(
                run_id="r", task_id="TASK-1", verification_passed=True
            ),
        )
        assert nxt.plan.tasks[0].status == TaskStatus.PASSED
        assert "TASK-1" in nxt.completed_task_ids

    def test_new_activation_clears_stale_evidence(self):
        s = _running_state()
        s = apply_event(
            s, EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev1"])
        )
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        s = apply_event(s, TaskRetried(run_id="r", task_id="TASK-1"))
        s = apply_event(s, TaskActivated(run_id="r", task_id="TASK-1"))
        assert s.plan.tasks[0].accepted_evidence_refs == [], (
            "stale evidence cleared on new attempt"
        )

    def test_pass_on_stale_evidence_of_old_attempt_blocked(self):
        s = _running_state()
        s = apply_event(
            s, EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev1"])
        )
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        s = apply_event(s, TaskRetried(run_id="r", task_id="TASK-1"))
        s = apply_event(s, TaskActivated(run_id="r", task_id="TASK-1"))
        with pytest.raises(InvalidTransitionError, match="accepted evidence"):
            apply_event(
                s,
                TaskVerificationPassed(
                    run_id="r", task_id="TASK-1", verification_passed=True
                ),
            )


# =============================================================================
# Retry + escalation + gate (Domain Core owns the decision)
# =============================================================================


class TestRetryAndEscalation:
    def test_retry_allowed_when_budget_remains(self):
        s = _running_state()  # attempt=1, max_attempts default 3
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        nxt = apply_event(s, TaskRetried(run_id="r", task_id="TASK-1"))
        assert nxt.plan.tasks[0].status == TaskStatus.READY

    def test_retry_rejected_when_budget_exhausted(self):
        s = _running_state()
        s.plan.tasks[0].max_attempts = 1  # attempt 1 already used
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        with pytest.raises(RetryExhaustedError):
            apply_event(s, TaskRetried(run_id="r", task_id="TASK-1"))

    def test_escalation_rejected_when_budget_remains(self):
        s = _running_state()
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        with pytest.raises(InvalidTransitionError, match="budget remains"):
            apply_event(s, TaskEscalated(run_id="r", task_id="TASK-1", attempt=1))

    def test_escalation_opens_gate_in_snapshot(self):
        s = _running_state()
        s.plan.tasks[0].max_attempts = 1
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        nxt = apply_event(s, TaskEscalated(run_id="r", task_id="TASK-1", attempt=1))
        assert nxt.plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
        assert "TASK-1" in nxt.needs_human_task_ids
        assert nxt.gate is not None
        assert nxt.gate.task_id == "TASK-1"
        assert nxt.status == RunStatus.NEEDS_HUMAN

    def test_retry_once_grants_exactly_one_more_attempt(self):
        s = _running_state()
        s.plan.tasks[0].max_attempts = 1
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        s = apply_event(s, TaskEscalated(run_id="r", task_id="TASK-1", attempt=1))
        g_id = gate_id_for("r", "TASK-1", 1)
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.RETRY_ONCE)
        nxt = apply_event(
            s,
            HumanGateDecisionApplied(
                run_id="r",
                task_id="TASK-1",
                gate_id=g_id,
                decision_id=d_id,
                action=HumanDecisionAction.RETRY_ONCE,
                attempt=1,
                new_max_attempts=2,
            ),
        )
        t = nxt.plan.tasks[0]
        assert t.status == TaskStatus.READY
        assert t.max_attempts == 2
        assert nxt.gate is None
        assert nxt.status == RunStatus.RUNNING

    def test_abort_fails_task_and_run(self):
        s = _running_state()
        s.plan.tasks[0].max_attempts = 1
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        s = apply_event(s, TaskEscalated(run_id="r", task_id="TASK-1", attempt=1))
        g_id = gate_id_for("r", "TASK-1", 1)
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.ABORT)
        nxt = apply_event(
            s,
            HumanGateDecisionApplied(
                run_id="r",
                task_id="TASK-1",
                gate_id=g_id,
                decision_id=d_id,
                action=HumanDecisionAction.ABORT,
                attempt=1,
            ),
        )
        assert nxt.plan.tasks[0].status == TaskStatus.FAILED
        assert "TASK-1" in nxt.failed_task_ids
        assert nxt.status == RunStatus.FAILED


class TestGateIdentity:
    def test_decision_for_wrong_gate_rejected(self):
        s = _running_state()
        s.plan.tasks[0].max_attempts = 1
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        s = apply_event(s, TaskEscalated(run_id="r", task_id="TASK-1", attempt=1))
        wrong_g = "gate-r-TASK-1-attempt-99"
        d_id = decision_id_for("r", "TASK-1", wrong_g, HumanDecisionAction.RETRY_ONCE)
        with pytest.raises(InvalidTransitionError, match="not the open gate"):
            apply_event(
                s,
                HumanGateDecisionApplied(
                    run_id="r",
                    task_id="TASK-1",
                    gate_id=wrong_g,
                    decision_id=d_id,
                    action=HumanDecisionAction.RETRY_ONCE,
                    attempt=1,
                    new_max_attempts=2,
                ),
            )

    def test_decision_on_non_needs_human_task_rejected(self):
        s = _running_state()
        g_id = gate_id_for("r", "TASK-1", 1)
        d_id = decision_id_for("r", "TASK-1", g_id, HumanDecisionAction.ABORT)
        with pytest.raises(InvalidTransitionError, match="NEEDS_HUMAN"):
            apply_event(
                s,
                HumanGateDecisionApplied(
                    run_id="r",
                    task_id="TASK-1",
                    gate_id=g_id,
                    decision_id=d_id,
                    action=HumanDecisionAction.ABORT,
                    attempt=1,
                ),
            )

    def test_retry_once_without_new_max_attempts_rejected(self):
        s = _running_state()
        s.plan.tasks[0].max_attempts = 1
        s = apply_event(
            s,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        s = apply_event(s, TaskEscalated(run_id="r", task_id="TASK-1", attempt=1))
        g_id = gate_id_for("r", "TASK-1", 1)
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


# =============================================================================
# Bad identity + illegal transition rejection
# =============================================================================


class TestIdentityAndIllegalTransition:
    def test_foreign_run_id_rejected(self):
        s = _running_state()
        with pytest.raises(InvalidTransitionError, match="does not match state run_id"):
            apply_event(s, TaskActivated(run_id="OTHER", task_id="TASK-1"))

    def test_unknown_task_id_rejected(self):
        s = _running_state()
        with pytest.raises(InvalidTransitionError, match="not in plan"):
            apply_event(s, TaskActivated(run_id="r", task_id="GHOST"))

    def test_task_event_without_plan_rejected(self):
        s = RunState(run_id="r", goal="g")
        with pytest.raises(InvalidTransitionError, match="requires a plan"):
            apply_event(s, TaskActivated(run_id="r", task_id="TASK-1"))

    def test_pass_from_pending_rejected(self):
        s = _planned_state()
        with pytest.raises(InvalidTransitionError, match="cannot transition to"):
            apply_event(
                s,
                TaskVerificationPassed(
                    run_id="r", task_id="TASK-1", verification_passed=True
                ),
            )

    def test_activation_increments_attempt_exactly_once(self):
        s = _planned_state()
        nxt = apply_event(s, TaskActivated(run_id="r", task_id="TASK-1"))
        assert nxt.plan.tasks[0].attempt == 1
        nxt2 = apply_event(
            nxt,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        nxt2 = apply_event(nxt2, TaskRetried(run_id="r", task_id="TASK-1"))
        # FAILED->READY must NOT increment attempt
        assert nxt2.plan.tasks[0].attempt == 1
        nxt3 = apply_event(nxt2, TaskActivated(run_id="r", task_id="TASK-1"))
        assert nxt3.plan.tasks[0].attempt == 2


# =============================================================================
# Run lifecycle
# =============================================================================


class TestRunLifecycle:
    def test_plan_and_start(self):
        plan = _plan("r2", 2)
        s = RunState(run_id="r2", goal="g")
        s = apply_event(s, RunPlanned(run_id="r2", plan=plan))
        assert s.status == RunStatus.PLANNED
        assert s.plan is not None
        s = apply_event(s, RunStarted(run_id="r2"))
        assert s.status == RunStatus.RUNNING

    def test_plan_with_mismatched_run_id_rejected(self):
        plan = _plan("OTHER", 2)
        s = RunState(run_id="r2", goal="g")
        with pytest.raises(InvalidTransitionError, match="plan run_id does not match"):
            apply_event(s, RunPlanned(run_id="r2", plan=plan))

    def test_run_passes_when_all_tasks_complete(self):
        s = _running_state("r", n=1)
        s = apply_event(
            s, EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev1"])
        )
        s = apply_event(
            s,
            TaskVerificationPassed(
                run_id="r", task_id="TASK-1", verification_passed=True
            ),
        )
        assert s.status == RunStatus.PASSED

    def test_single_task_pass_does_not_complete_multi_task_run(self):
        s = _running_state("r", n=3)
        s = apply_event(
            s, EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev1"])
        )
        s = apply_event(
            s,
            TaskVerificationPassed(
                run_id="r", task_id="TASK-1", verification_passed=True
            ),
        )
        assert s.status == RunStatus.RUNNING, (
            "PASS of TASK-001 must not finish a multi-task plan"
        )
        assert "TASK-1" in s.completed_task_ids

    def test_run_completed_requires_verification_true(self):
        s = _running_state("r", n=1)
        with pytest.raises(InvalidTransitionError, match="verification_passed=True"):
            apply_event(s, RunCompleted(run_id="r", verification_passed=False))

    def test_run_failed_allowed_from_running(self):
        s = _running_state("r", n=1)
        s = apply_event(s, RunFailed(run_id="r"))
        assert s.status == RunStatus.FAILED


# =============================================================================
# Matrices live once (Domain Core is the authority)
# =============================================================================


class TestSingleAuthority:
    def test_domain_matrices_match_m4_imperative_api(self):
        from fsasm.transitions import (
            _TASK_ALLOWED_TRANSITIONS,
            _RUN_ALLOWED_TRANSITIONS,
        )

        assert _TASK_ALLOWED_TRANSITIONS is TASK_ALLOWED_TRANSITIONS
        assert _RUN_ALLOWED_TRANSITIONS is RUN_ALLOWED_TRANSITIONS

    def test_terminal_states_have_no_outgoing(self):
        for terminal in (TaskStatus.PASSED, TaskStatus.NEEDS_HUMAN):
            assert TASK_ALLOWED_TRANSITIONS[terminal] == set()
