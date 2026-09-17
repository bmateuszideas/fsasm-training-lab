"""FS-ASM Domain Core (T05) — clean ``apply_event`` and one event path.

The Domain Core is the single authority over semantic state changes. It owns
the transition matrices and limits (moved here from ``transitions.py`` so there
is one set of rules, not two) and exposes a pure
``apply_event(current_state, validated_event) -> next_state`` with no I/O and no
mutation of its input.

Contract (architecture §11, §30, §33):
- ``apply_event`` returns a brand-new ``RunState``; the input is never mutated.
- The same ``state + event`` always yields the same result (determinism).
- Only the Domain Core grants PASS, retry and gate transitions; a model "I am
  done" can never produce PASS without a verification event carrying accepted
  evidence for the current attempt.
- Bad identity, illegal transition, exceeded limit and a model PASS attempt
  are rejected before any state change.
- At most one active Child Task per run.
- ``revision`` is intentionally untouched here; the State Repository (T06)
  increments it exactly once per accepted event on commit.

``transitions.py`` keeps the imperative M4 API (``transition_task`` etc.) and
re-uses these matrices so the milestone demonstrator is unchanged; the matrices
live once, in this module.
"""

from __future__ import annotations

import copy
from typing import Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fsasm.errors import InvalidTransitionError, RetryExhaustedError
from fsasm.models import (
    ChildTask,
    GateOccurrence,
    HumanDecisionAction,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    gate_id_for,
)

# =============================================================================
# TRANSITION MATRICES — the single authority (moved from transitions.py)
# =============================================================================

TASK_ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.READY, TaskStatus.BLOCKED},
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.BLOCKED},
    TaskStatus.RUNNING: {TaskStatus.PASSED, TaskStatus.FAILED, TaskStatus.BLOCKED},
    TaskStatus.PASSED: set(),
    TaskStatus.FAILED: {TaskStatus.READY, TaskStatus.NEEDS_HUMAN},
    TaskStatus.BLOCKED: {TaskStatus.READY},
    TaskStatus.NEEDS_HUMAN: set(),
}

RUN_ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.CREATED: {RunStatus.PLANNED},
    RunStatus.PLANNED: {RunStatus.RUNNING},
    RunStatus.RUNNING: {RunStatus.PASSED, RunStatus.FAILED, RunStatus.NEEDS_HUMAN},
    RunStatus.PASSED: set(),
    RunStatus.FAILED: set(),
    RunStatus.NEEDS_HUMAN: set(),
}

TASK_REQUIRES_VERIFICATION_PASS: set[tuple[TaskStatus, TaskStatus]] = {
    (TaskStatus.RUNNING, TaskStatus.PASSED),
}
TASK_REQUIRES_VERIFICATION_FAIL: set[tuple[TaskStatus, TaskStatus]] = {
    (TaskStatus.RUNNING, TaskStatus.FAILED),
}
TASK_REQUIRES_RETRY_CHECK: set[tuple[TaskStatus, TaskStatus]] = {
    (TaskStatus.FAILED, TaskStatus.READY),
    (TaskStatus.FAILED, TaskStatus.NEEDS_HUMAN),
}
RUN_REQUIRES_VERIFICATION_PASS: set[tuple[RunStatus, RunStatus]] = {
    (RunStatus.RUNNING, RunStatus.PASSED),
}


# =============================================================================
# DOMAIN EVENTS — explicit, immutable, identity-bound
# =============================================================================


class _DomainEvent(BaseModel):
    """Base for all domain events. Events are immutable and identity-bound."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(..., description="The run this event applies to.")

    @field_validator("run_id")
    @classmethod
    def _run_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("event run_id cannot be empty")
        return v.strip()


class RunPlanned(_DomainEvent):
    """A plan was compiled and attached to a newly created run (CREATED→PLANNED)."""

    plan: Plan


class RunStarted(_DomainEvent):
    """The run began executing its plan (PLANNED→RUNNING)."""


class TaskActivated(_DomainEvent):
    """A scheduled task began an execution attempt (READY→RUNNING).

    Increments ``attempt`` exactly once and sets ``active_task_id``. Rejected if
    another task is already active, preserving the one-active-task invariant.
    Clears the previous attempt's accepted evidence refs so stale evidence
    cannot authorize the new attempt.
    """

    task_id: str


class TaskBlocked(_DomainEvent):
    """A task was blocked (PENDING/READY/RUNNING→BLOCKED)."""

    task_id: str


class TaskUnblocked(_DomainEvent):
    """A blocked task became ready again (BLOCKED→READY)."""

    task_id: str


class EvidenceAccepted(_DomainEvent):
    """The Verifier accepted evidence for the current attempt of a task.

    Records ``accepted_evidence_refs`` on the task for the CURRENT attempt
    only. Evidence must exist (be accepted) before a PASS event; this event does
    not grant PASS. The refs supplied replace the current attempt's refs.
    """

    task_id: str
    evidence_refs: list[str] = Field(default_factory=list)


class TaskVerificationPassed(_DomainEvent):
    """The Domain Core approved PASS for a task (RUNNING→PASSED).

    Requires a real verification PASS plus non-empty accepted evidence refs for
    the current attempt. A model "I am done" without this event cannot PASS.
    Clears ``active_task_id`` and records the task in ``completed_task_ids``;
    if all required tasks are complete, the run transitions to PASSED.
    """

    task_id: str
    verification_passed: bool = Field(..., description="Must be True for PASS.")


class TaskVerificationFailed(_DomainEvent):
    """A task's verification failed (RUNNING→FAILED).

    Requires a real verification FAIL. The Domain Core then owns the next
    decision: retry if budget remains, escalate to Human Gate if exhausted.
    This single event path means a model cannot self-grant retry or gate.
    """

    task_id: str
    verification_passed: bool = Field(..., description="Must be False for FAIL.")


class TaskRetried(_DomainEvent):
    """A failed task was scheduled for another attempt (FAILED→READY).

    Rejected if the retry budget is exhausted; exhaustion must route to the
    Human Gate via ``TaskEscalated`` instead.
    """

    task_id: str


class TaskEscalated(_DomainEvent):
    """Retry budget exhausted: the task escalates to a Human Gate.

    (FAILED→NEEDS_HUMAN.) Opens a gate occurrence recorded in the snapshot.
    Rejected if budget still remains — the Domain Core, not the model, decides
    when escalation is reached.
    """

    task_id: str
    attempt: int = Field(..., ge=1, description="The attempt that exhausted budget.")


class HumanGateDecisionApplied(_DomainEvent):
    """A validated human decision is applied to a gate (NEEDS_HUMAN→…).

    RETRY_ONCE: task NEEDS_HUMAN→READY with ``max_attempts = attempt + 1``,
    run NEEDS_HUMAN→RUNNING. ABORT: task NEEDS_HUMAN→FAILED, run
    NEEDS_HUMAN→FAILED. Identity (run/task/gate/decision) is validated; a stale
    or foreign decision is rejected before any effect.
    """

    task_id: str
    gate_id: str
    decision_id: str
    action: HumanDecisionAction
    attempt: int = Field(..., ge=1)
    new_max_attempts: int | None = Field(
        default=None, ge=1, description="For RETRY_ONCE: attempt + 1."
    )


class RunCompleted(_DomainEvent):
    """The run reached PASSED after all required tasks passed (RUNNING→PASSED)."""

    verification_passed: bool = Field(..., description="Must be True for run PASS.")


class RunFailed(_DomainEvent):
    """The run failed (RUNNING→FAILED)."""


DomainEvent = Union[
    RunPlanned,
    RunStarted,
    TaskActivated,
    TaskBlocked,
    TaskUnblocked,
    EvidenceAccepted,
    TaskVerificationPassed,
    TaskVerificationFailed,
    TaskRetried,
    TaskEscalated,
    HumanGateDecisionApplied,
    RunCompleted,
    RunFailed,
]


# =============================================================================
# apply_event — pure, no I/O, no input mutation
# =============================================================================


def apply_event(current_state: RunState, event: DomainEvent) -> RunState:
    """Apply a validated domain event to a state, returning a NEW state.

    The input ``current_state`` is never mutated (a deep copy is produced). The
    same ``current_state + event`` always yields an equal result. Raises
    ``InvalidTransitionError`` / ``RetryExhaustedError`` for bad identity,
    illegal transition, exceeded limit, or a model attempt to grant PASS.
    """
    _validate_identity(current_state, event)
    next_state = copy.deepcopy(current_state)
    _apply(next_state, event)
    return next_state


def _validate_identity(state: RunState, event: DomainEvent) -> None:
    if event.run_id != state.run_id:
        raise InvalidTransitionError(
            from_status=state.status.value,
            to_status=state.status.value,
            entity_type="RunState",
            entity_id=state.run_id,
            reason=(
                f"event run_id {event.run_id!r} does not match state run_id "
                f"{state.run_id!r}"
            ),
        )
    task_event = getattr(event, "task_id", None)
    if task_event is not None:
        if state.plan is None:
            raise InvalidTransitionError(
                from_status=state.status.value,
                to_status=state.status.value,
                entity_type="RunState",
                entity_id=state.run_id,
                reason="task event requires a plan",
            )
        if not any(t.task_id == task_event for t in state.plan.tasks):
            raise InvalidTransitionError(
                from_status=state.status.value,
                to_status=state.status.value,
                entity_type="ChildTask",
                entity_id=task_event,
                reason=f"task_id {task_event!r} not in plan",
            )


def _find_task(state: RunState, task_id: str) -> ChildTask:
    assert state.plan is not None
    for t in state.plan.tasks:
        if t.task_id == task_id:
            return t
    raise AssertionError("unreachable: identity validated above")


def _check_task_transition(task: ChildTask, target: TaskStatus) -> None:
    allowed = TASK_ALLOWED_TRANSITIONS.get(task.status, set())
    if target not in allowed:
        raise InvalidTransitionError(
            from_status=task.status.value,
            to_status=target.value,
            entity_type="ChildTask",
            entity_id=task.task_id,
            reason=f"{task.status.value} cannot transition to {target.value}",
        )


def _check_run_transition(state: RunState, target: RunStatus) -> None:
    allowed = RUN_ALLOWED_TRANSITIONS.get(state.status, set())
    if target not in allowed:
        raise InvalidTransitionError(
            from_status=state.status.value,
            to_status=target.value,
            entity_type="RunState",
            entity_id=state.run_id,
            reason=f"{state.status.value} cannot transition to {target.value}",
        )


def _all_required_tasks_complete(state: RunState) -> bool:
    if state.plan is None:
        return False
    done = set(state.completed_task_ids)
    return all(t.task_id in done for t in state.plan.tasks)


def _apply(state: RunState, event: DomainEvent) -> None:
    if isinstance(event, RunPlanned):
        _check_run_transition(state, RunStatus.PLANNED)
        if state.run_id != event.plan.run_id:
            raise InvalidTransitionError(
                from_status=state.status.value,
                to_status=RunStatus.PLANNED.value,
                entity_type="RunState",
                entity_id=state.run_id,
                reason="plan run_id does not match run",
            )
        state.plan = event.plan
        state.status = RunStatus.PLANNED
        return

    if isinstance(event, RunStarted):
        _check_run_transition(state, RunStatus.RUNNING)
        state.status = RunStatus.RUNNING
        return

    if isinstance(event, TaskActivated):
        task = _find_task(state, event.task_id)
        _check_task_transition(task, TaskStatus.RUNNING)
        if state.active_task_id is not None and state.active_task_id != event.task_id:
            raise InvalidTransitionError(
                from_status=task.status.value,
                to_status=TaskStatus.RUNNING.value,
                entity_type="RunState",
                entity_id=state.run_id,
                reason=(f"another task {state.active_task_id!r} is already active"),
            )
        task.attempt += 1
        task.accepted_evidence_refs = []
        task.status = TaskStatus.RUNNING
        state.active_task_id = event.task_id
        if state.status == RunStatus.PLANNED:
            state.status = RunStatus.RUNNING
        return

    if isinstance(event, TaskBlocked):
        task = _find_task(state, event.task_id)
        _check_task_transition(task, TaskStatus.BLOCKED)
        task.status = TaskStatus.BLOCKED
        return

    if isinstance(event, TaskUnblocked):
        task = _find_task(state, event.task_id)
        _check_task_transition(task, TaskStatus.READY)
        task.status = TaskStatus.READY
        return

    if isinstance(event, EvidenceAccepted):
        task = _find_task(state, event.task_id)
        task.accepted_evidence_refs = list(event.evidence_refs)
        return

    if isinstance(event, TaskVerificationPassed):
        if event.verification_passed is not True:
            raise InvalidTransitionError(
                from_status=TaskStatus.RUNNING.value,
                to_status=TaskStatus.PASSED.value,
                entity_type="ChildTask",
                entity_id=event.task_id,
                reason="PASS requires verification_passed=True",
            )
        task = _find_task(state, event.task_id)
        _check_task_transition(task, TaskStatus.PASSED)
        # F8 / §30: PASS requires accepted evidence for the CURRENT attempt.
        if not task.accepted_evidence_refs:
            raise InvalidTransitionError(
                from_status=TaskStatus.RUNNING.value,
                to_status=TaskStatus.PASSED.value,
                entity_type="ChildTask",
                entity_id=event.task_id,
                reason="PASS requires accepted evidence for the current attempt",
            )
        task.status = TaskStatus.PASSED
        if event.task_id not in state.completed_task_ids:
            state.completed_task_ids.append(event.task_id)
        if state.active_task_id == event.task_id:
            state.active_task_id = None
        if _all_required_tasks_complete(state):
            _check_run_transition(state, RunStatus.PASSED)
            state.status = RunStatus.PASSED
        return

    if isinstance(event, TaskVerificationFailed):
        if event.verification_passed is not False:
            raise InvalidTransitionError(
                from_status=TaskStatus.RUNNING.value,
                to_status=TaskStatus.FAILED.value,
                entity_type="ChildTask",
                entity_id=event.task_id,
                reason="FAIL requires verification_passed=False",
            )
        task = _find_task(state, event.task_id)
        _check_task_transition(task, TaskStatus.FAILED)
        task.status = TaskStatus.FAILED
        if state.active_task_id == event.task_id:
            state.active_task_id = None
        return

    if isinstance(event, TaskRetried):
        task = _find_task(state, event.task_id)
        _check_task_transition(task, TaskStatus.READY)
        if (TaskStatus.FAILED, TaskStatus.READY) in TASK_REQUIRES_RETRY_CHECK:
            if not task.can_retry():
                raise RetryExhaustedError(
                    task_id=task.task_id,
                    max_attempts=task.max_attempts,
                    current_attempt=task.attempt,
                )
        task.status = TaskStatus.READY
        return

    if isinstance(event, TaskEscalated):
        task = _find_task(state, event.task_id)
        _check_task_transition(task, TaskStatus.NEEDS_HUMAN)
        if (TaskStatus.FAILED, TaskStatus.NEEDS_HUMAN) in TASK_REQUIRES_RETRY_CHECK:
            if task.can_retry():
                raise InvalidTransitionError(
                    from_status=TaskStatus.FAILED.value,
                    to_status=TaskStatus.NEEDS_HUMAN.value,
                    entity_type="ChildTask",
                    entity_id=task.task_id,
                    reason="retry budget remains — escalate only when exhausted",
                )
        task.status = TaskStatus.NEEDS_HUMAN
        if event.task_id not in state.needs_human_task_ids:
            state.needs_human_task_ids.append(event.task_id)
        g_id = gate_id_for(state.run_id, event.task_id, event.attempt)
        state.gate = GateOccurrence(
            gate_id=g_id,
            task_id=event.task_id,
            attempt=event.attempt,
        )
        if state.active_task_id == event.task_id:
            state.active_task_id = None
        if state.status == RunStatus.RUNNING:
            _check_run_transition(state, RunStatus.NEEDS_HUMAN)
            state.status = RunStatus.NEEDS_HUMAN
        return

    if isinstance(event, HumanGateDecisionApplied):
        task = _find_task(state, event.task_id)
        if task.status != TaskStatus.NEEDS_HUMAN:
            raise InvalidTransitionError(
                from_status=task.status.value,
                to_status=task.status.value,
                entity_type="ChildTask",
                entity_id=event.task_id,
                reason="human decision applies only to a NEEDS_HUMAN task",
            )
        if state.gate is None or state.gate.gate_id != event.gate_id:
            raise InvalidTransitionError(
                from_status=task.status.value,
                to_status=task.status.value,
                entity_type="ChildTask",
                entity_id=event.task_id,
                reason=f"gate {event.gate_id!r} is not the open gate",
            )
        if event.action is HumanDecisionAction.RETRY_ONCE:
            if event.new_max_attempts is None:
                raise InvalidTransitionError(
                    from_status=TaskStatus.NEEDS_HUMAN.value,
                    to_status=TaskStatus.READY.value,
                    entity_type="ChildTask",
                    entity_id=event.task_id,
                    reason="RETRY_ONCE requires new_max_attempts",
                )
            task.status = TaskStatus.READY
            task.max_attempts = event.new_max_attempts
            if event.task_id in state.needs_human_task_ids:
                state.needs_human_task_ids.remove(event.task_id)
            state.gate = None
            if state.status == RunStatus.NEEDS_HUMAN:
                # Human-authorized: the gate decision is the authority that
                # leaves NEEDS_HUMAN, bypassing the normal run matrix (mirrors
                # M4 apply_human_authorized_run_transition).
                state.status = RunStatus.RUNNING
        elif event.action is HumanDecisionAction.ABORT:
            task.status = TaskStatus.FAILED
            if event.task_id not in state.failed_task_ids:
                state.failed_task_ids.append(event.task_id)
            if event.task_id in state.needs_human_task_ids:
                state.needs_human_task_ids.remove(event.task_id)
            state.gate = None
            if state.status == RunStatus.NEEDS_HUMAN:
                state.status = RunStatus.FAILED
        return

    if isinstance(event, RunCompleted):
        if event.verification_passed is not True:
            raise InvalidTransitionError(
                from_status=state.status.value,
                to_status=RunStatus.PASSED.value,
                entity_type="RunState",
                entity_id=state.run_id,
                reason="run PASS requires verification_passed=True",
            )
        _check_run_transition(state, RunStatus.PASSED)
        state.status = RunStatus.PASSED
        return

    if isinstance(event, RunFailed):
        _check_run_transition(state, RunStatus.FAILED)
        state.status = RunStatus.FAILED
        return

    raise TypeError(f"unsupported domain event: {type(event).__name__}")
