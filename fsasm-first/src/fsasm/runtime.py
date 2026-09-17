"""FS-ASM Runtime v1 (T10) \u2014 deterministic whole-plan E2E on the stub.

This is the single target execution path that drives the whole plan (not just
TASK-001) through the new Domain Core (``apply_event``) and Scheduler
(``schedule``), using controlled stub executor/verifier results and the
authoritative State Repository. It has NO real tools and makes NO model calls;
it proves that a 1-, 3- or N-task plan reaches a terminal state (PASSED,
BLOCKED, or NEEDS_HUMAN) deterministically, with each Child Task going through
its own finalization and a plan-level "verify" task never replacing the
Verification Plane (architecture \u00a716\u2013\u00a718, \u00a730; canonical TODO T10).

The loop is:
    schedule(state) -> NEXT_TASK | ALL_COMPLETE | BLOCKED | WAITING_ON_GATE
    NEXT_TASK: TaskReadied (PENDING->READY) -> TaskActivated (READY->RUNNING)
               -> execute(stub) -> verify(stub) -> EvidenceAccepted
               -> TaskVerificationPassed | TaskVerificationFailed
               -> on FAIL: TaskRetried (if budget) else TaskEscalated (gate)
    repeat until terminal.

The Domain Core alone grants PASS/retry/gate; the runtime only orchestrates
events and a controlled stub outcome. The State Repository commits each
accepted event through ``advance`` so the on-disk snapshot is the authority.

M1\u2013M4 are unchanged; this is a parallel v1 path. The temporal Workflows
wrapper is added later; T10 establishes the deterministic execution path and
proves whole-plan termination on controlled stub results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from fsasm.domain import (
    DomainEvent,
    EvidenceAccepted,
    HumanDecisionAction,
    HumanGateDecisionApplied,
    RunFailed,
    RunStarted,
    TaskActivated,
    TaskEscalated,
    TaskReadied,
    TaskRetried,
    TaskVerificationFailed,
    TaskVerificationPassed,
)
from fsasm.models import ChildTask, RunState, RunStatus, TaskStatus
from fsasm.scheduler import ScheduleOutcome, schedule
from fsasm.state_repository import StateRepository


class RuntimeTerminated(Exception):
    """Raised when the runtime reaches a terminal state with no further step."""

    def __init__(self, state: RunState, reason: str) -> None:
        self.state = state
        self.reason = reason
        super().__init__(reason)


@dataclass
class StubExecutor:
    """Controlled stub executor producing a deterministic claim per attempt.

    ``should_pass(task_id, attempt)`` decides whether the attempt's claim is
    treated as a verification PASS. It never grants PASS itself; it produces a
    claim that the controlled verifier maps to a PASS/FAIL evidence decision.
    """

    should_pass: Callable[[str, int], bool] = staticmethod(
        lambda task_id, attempt: True
    )

    def execute(self, task_id: str, attempt: int) -> str:
        """Return a deterministic claim for an attempt."""
        return "PASS" if self.should_pass(task_id, attempt) else "FAIL"


@dataclass
class StubVerifier:
    """Controlled verifier mapping a claim to a PASS/FAIL evidence decision.

    The verifier never grants the domain PASS; it produces an
    ``accepted_evidence_refs`` list and a ``passed`` boolean that the runtime
    feeds to the Domain Core, which alone grants the transition.
    """

    def verify(
        self, run_id: str, task_id: str, attempt: int, claim: str
    ) -> tuple[bool, list[str]]:
        passed = claim == "PASS"
        evidence_id = f"evidence-{run_id}-{task_id}-attempt-{attempt}-stub"
        return passed, [evidence_id] if passed else []


@dataclass
class RuntimeOutcome:
    """Final outcome of a deterministic v1 run."""

    state: RunState
    status: RunStatus
    reason: str
    events: list[DomainEvent] = field(default_factory=list)


def run_plan(
    state: RunState,
    repository: StateRepository,
    executor: StubExecutor | None = None,
    verifier: StubVerifier | None = None,
    max_iterations: int = 1000,
) -> RuntimeOutcome:
    """Drive the whole plan to a terminal state on controlled stub results.

    Each semantic change is one event applied through ``advance``
    (load -> apply_event -> commit), so the on-disk snapshot is the authority
    and revision increments once per accepted event. The Domain Core alone
    grants PASS/retry/gate; this function only orchestrates events and the
    controlled stub outcome.

    Args:
        state: The initial authoritative RunState (PLANNED or RUNNING).
        repository: The StateRepository used to commit each accepted event.
        executor: Controlled stub executor (default: always PASS).
        verifier: Controlled stub verifier (default: maps claim to evidence).
        max_iterations: Safety cap against an accidental infinite loop.

    Returns:
        RuntimeOutcome with the final state, run status and reason.

    Raises:
        RuntimeTerminated: if the loop exceeds max_iterations (a bug, not a
            domain outcome).
    """
    executor = executor or StubExecutor()
    verifier = verifier or StubVerifier()
    run_id = state.run_id
    events: list[DomainEvent] = []

    current = state
    if current.status is RunStatus.PLANNED:
        current = _step(
            repository, run_id, current.revision, RunStarted(run_id=run_id), events
        )
    if current.status is not RunStatus.RUNNING:
        return RuntimeOutcome(
            current, current.status, f"initial status {current.status.value}"
        )
    if current.plan is None:
        raise RuntimeTerminated(current, "run has no plan to drive")

    for _ in range(max_iterations):
        result = schedule(current)
        if result.outcome is ScheduleOutcome.ALL_COMPLETE:
            return RuntimeOutcome(
                current, current.status, "all required tasks complete"
            )
        if result.outcome is ScheduleOutcome.BUSY:
            return RuntimeOutcome(
                current, current.status, "run busy with an active task"
            )
        if result.outcome is ScheduleOutcome.WAITING_ON_GATE:
            return RuntimeOutcome(current, current.status, "waiting on human gate")
        if result.outcome is ScheduleOutcome.BLOCKED:
            current = _step(
                repository, run_id, current.revision, RunFailed(run_id=run_id), events
            )
            return RuntimeOutcome(current, current.status, "plan blocked")
        if result.outcome is not ScheduleOutcome.NEXT_TASK or result.task is None:
            current = _step(
                repository, run_id, current.revision, RunFailed(run_id=run_id), events
            )
            return RuntimeOutcome(current, current.status, "no eligible task")

        task_id = result.task.task_id
        candidate = _find_task_in(current, task_id)
        if candidate.status is TaskStatus.PENDING:
            current = _step(
                repository,
                run_id,
                current.revision,
                TaskReadied(run_id=run_id, task_id=task_id),
                events,
            )
        current = _step(
            repository,
            run_id,
            current.revision,
            TaskActivated(run_id=run_id, task_id=task_id),
            events,
        )

        active = _find_task_in(current, task_id)
        attempt = active.attempt
        claim = executor.execute(task_id, attempt)
        passed, evidence_refs = verifier.verify(run_id, task_id, attempt, claim)

        if passed and evidence_refs:
            current = _step(
                repository,
                run_id,
                current.revision,
                EvidenceAccepted(
                    run_id=run_id, task_id=task_id, evidence_refs=evidence_refs
                ),
                events,
            )
            current = _step(
                repository,
                run_id,
                current.revision,
                TaskVerificationPassed(
                    run_id=run_id, task_id=task_id, verification_passed=True
                ),
                events,
            )
        else:
            current = _step(
                repository,
                run_id,
                current.revision,
                TaskVerificationFailed(
                    run_id=run_id, task_id=task_id, verification_passed=False
                ),
                events,
            )
            failed_task = _find_task_in(current, task_id)
            if failed_task.can_retry():
                current = _step(
                    repository,
                    run_id,
                    current.revision,
                    TaskRetried(run_id=run_id, task_id=task_id),
                    events,
                )
            else:
                current = _step(
                    repository,
                    run_id,
                    current.revision,
                    TaskEscalated(
                        run_id=run_id, task_id=task_id, attempt=failed_task.attempt
                    ),
                    events,
                )
                return RuntimeOutcome(
                    current, current.status, "retry exhausted -> human gate"
                )

    raise RuntimeTerminated(current, f"exceeded max_iterations={max_iterations}")


def apply_human_gate(
    state: RunState,
    repository: StateRepository,
    gate_id: str,
    task_id: str,
    decision_id: str,
    attempt: int,
    action: HumanDecisionAction,
    new_max_attempts: int | None = None,
) -> tuple[RunState, list[DomainEvent]]:
    """Apply a human gate decision and resume the run.

    For T10 stub E2E, ABORT terminates; RETRY_ONCE grants one more attempt and
    the run continues. Returns the post-decision state and the events applied.
    """
    events: list[DomainEvent] = []
    decision = HumanGateDecisionApplied(
        run_id=state.run_id,
        task_id=task_id,
        gate_id=gate_id,
        decision_id=decision_id,
        attempt=attempt,
        action=action,
        new_max_attempts=new_max_attempts,
    )
    current = _step(repository, state.run_id, state.revision, decision, events)
    return current, events


def _step(
    repository: StateRepository,
    run_id: str,
    expected_revision: int,
    event: DomainEvent,
    events: list[DomainEvent],
) -> RunState:
    """Apply one event through the repository (load -> apply_event -> commit)."""
    events.append(event)
    return repository.advance(run_id, expected_revision, event)


def _find_task_in(state: RunState, task_id: str) -> ChildTask:
    """Return the task with ``task_id`` from the run's plan.

    ``run_plan`` is reached only after a non-None plan guard, but ``current`` is
    reassigned inside the loop, so mypy cannot carry the narrowing. This helper
    makes the non-None plan explicit for the type checker and the reader.
    """
    assert state.plan is not None, "run_plan requires a plan to drive"
    return next(t for t in state.plan.tasks if t.task_id == task_id)


__all__ = [
    "RuntimeOutcome",
    "RuntimeTerminated",
    "StubExecutor",
    "StubVerifier",
    "apply_human_gate",
    "run_plan",
]
