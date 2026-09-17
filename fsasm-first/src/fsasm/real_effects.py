"""FS-ASM Runtime v1 (T14) — deterministic real-effects E2E.

Drives the whole plan through REAL isolated effects produced by the Tool
Broker, independent verification by the :class:`ArtifactVerifier`, evidence
persistence BEFORE the snapshot accepts refs, and Domain Core commit through
the authoritative State Repository. There is no LLM and no stub claim-as-PASS:
the controlled executor modifies a real fixture via the Broker, the Verifier
reads the actual artifact and runs a real ``run_checks`` check, evidence is
persisted, and only the Domain Core grants PASS. The whole plan — not just
TASK-001 — reaches a terminal state; PASS cannot come from stub text alone
(architecture §16–§18, §29, §30; canonical TODO T14; Gate D).

The loop mirrors :func:`fsasm.runtime.run_plan` but swaps the stub
executor/verifier for the real Broker/ArtifactVerifier path and persists
evidence. The T10 stub path in ``runtime.py`` is unchanged (parallel v1 path).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from fsasm.domain import (
    DomainEvent,
    EvidenceAccepted,
    RunFailed,
    RunStarted,
    TaskActivated,
    TaskEscalated,
    TaskReadied,
    TaskRetried,
    TaskVerificationFailed,
    TaskVerificationPassed,
)
from fsasm.models import (
    ChildTask,
    CheckKind,
    RunState,
    RunStatus,
    TaskStatus,
    ToolObservation,
)
from fsasm.scheduler import ScheduleOutcome, schedule
from fsasm.state_repository import StateRepository
from fsasm.tool_broker import ToolBroker
from fsasm.verifier import ArtifactVerifier, VerifyRequest


@dataclass
class ToolEffectSpec:
    """One controlled effect the executor applies for a task attempt.

    ``patch`` is the new content to write to ``artifact_path`` via the Broker;
    ``check_args`` are the trailing args for a ``CUSTOM`` ``run_checks`` call
    that verifies the effect (e.g. ``["python", "assert_effect.py"]``). The
    executor never claims PASS; it produces a real patch + a real check
    observation that the :class:`ArtifactVerifier` inspects.
    """

    artifact_path: str
    new_content: str
    allowed_files: list[str]
    check_kind: CheckKind = CheckKind.CUSTOM
    check_args: list[str] = field(default_factory=list)


@dataclass
class ControlledToolExecutor:
    """Controlled executor that applies a real effect via the Tool Broker.

    ``spec_for(task_id, attempt)`` returns the :class:`ToolEffectSpec` to apply
    (or ``None`` to simulate an executor that produces no effect — a "DONE"
    claim without a real change, which must FAIL verification). The executor
    uses the Broker to patch the fixture then run the check; it returns the
    two observations (patch + check) bound to the attempt, never granting PASS.
    """

    broker: ToolBroker
    spec_for: Callable[[str, int], ToolEffectSpec | None]

    def execute(
        self, run_id: str, task_id: str, attempt: int, step: int
    ) -> tuple[ToolObservation, ToolObservation] | None:
        """Apply the real effect and return (patch_obs, check_obs), or None.

        ``None`` means the executor produced no effect (a "DONE" claim with no
        change); the driver then runs only the check (if any) or treats the
        attempt as having no artifact to verify.
        """
        spec = self.spec_for(task_id, attempt)
        if spec is None:
            return None
        patch = self.broker.apply_patch(
            run_id,
            task_id,
            attempt,
            step,
            spec.artifact_path,
            spec.new_content,
            allowed_files=spec.allowed_files,
        )
        check = self.broker.run_checks(
            run_id,
            task_id,
            attempt,
            step + 1,
            spec.check_kind,
            spec.check_args,
        )
        return patch, check


@dataclass
class RealEffectsOutcome:
    """Final outcome of a real-effects v1 run."""

    state: RunState
    status: RunStatus
    reason: str
    events: list[DomainEvent] = field(default_factory=list)


def run_plan_real(
    state: RunState,
    repository: StateRepository,
    broker: ToolBroker,
    verifier: ArtifactVerifier,
    executor: ControlledToolExecutor,
    max_iterations: int = 1000,
) -> RealEffectsOutcome:
    """Drive the whole plan to a terminal state on REAL isolated effects.

    Each task attempt: the controlled executor patches the fixture and runs a
    real check via the Broker; the :class:`ArtifactVerifier` reads the actual
    artifact and check observation, producing evidence bound to the attempt;
    evidence is persisted through ``save_evidence`` BEFORE the snapshot accepts
    refs; the Domain Core grants PASS only with ``verification_passed=True`` and
    non-empty current-attempt evidence refs. The Scheduler then advances to
    the next task. PASS cannot come from stub text alone — it requires a real
    artifact + a passing check of the current attempt.

    Args:
        state: The initial authoritative RunState (PLANNED or RUNNING).
        repository: The StateRepository used to commit each accepted event.
        broker: The ToolBroker executing real isolated file/check effects.
        verifier: The ArtifactVerifier reading the real artifact + check.
        executor: The ControlledToolExecutor applying effects per attempt.
        max_iterations: Safety cap against an accidental infinite loop.

    Returns:
        RealEffectsOutcome with the final state, run status and reason.
    """
    run_id = state.run_id
    events: list[DomainEvent] = []
    current = state
    if current.status is RunStatus.PLANNED:
        current = _step(
            repository, run_id, current.revision, RunStarted(run_id=run_id), events
        )
    if current.status is not RunStatus.RUNNING:
        return RealEffectsOutcome(
            current, current.status, f"initial status {current.status.value}"
        )
    if current.plan is None:
        return RealEffectsOutcome(current, current.status, "run has no plan")
    for _ in range(max_iterations):
        result = schedule(current)
        if result.outcome is ScheduleOutcome.ALL_COMPLETE:
            return RealEffectsOutcome(
                current, current.status, "all required tasks complete"
            )
        if result.outcome is ScheduleOutcome.BUSY:
            return RealEffectsOutcome(
                current, current.status, "run busy with an active task"
            )
        if result.outcome is ScheduleOutcome.WAITING_ON_GATE:
            return RealEffectsOutcome(current, current.status, "waiting on human gate")
        if result.outcome is ScheduleOutcome.BLOCKED:
            current = _step(
                repository, run_id, current.revision, RunFailed(run_id=run_id), events
            )
            return RealEffectsOutcome(current, current.status, "plan blocked")
        if result.outcome is not ScheduleOutcome.NEXT_TASK or result.task is None:
            current = _step(
                repository, run_id, current.revision, RunFailed(run_id=run_id), events
            )
            return RealEffectsOutcome(current, current.status, "no eligible task")
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
        # Resolve the controlled effect spec ONCE per attempt. The executor's
        # ``execute`` re-resolves the spec internally; resolving it here too would
        # triple the call (and could misbehave if ``spec_for`` had side effects).
        spec = executor.spec_for(task_id, attempt)
        # Real effect: patch + check via the Broker. step 1 = patch, step 2 = check.
        outcome = executor.execute(run_id, task_id, attempt, 1)
        if outcome is None:
            # No effect produced: the executor claimed DONE without a change.
            # Build a verification against a (likely absent/wrong) artifact with
            # no patch observation; the ArtifactVerifier will FAIL it (G2).
            patch_obs_id = f"op-{run_id}-{task_id}-attempt-{attempt}-step-1"
            check_obs = broker.run_checks(
                run_id, task_id, attempt, 2, CheckKind.CUSTOM, ["python", "-c", "pass"]
            )
            artifact_path = (
                spec.artifact_path if spec is not None else _artifact_path_for(task_id)
            )
            verify_req = VerifyRequest(
                run_id=run_id,
                task_id=task_id,
                attempt=attempt,
                artifact_path=artifact_path,
                patch_observation_id=patch_obs_id,
                check_observation_id=check_obs.operation_id,
                check_observation=check_obs,
            )
        else:
            patch_obs, check_obs = outcome
            artifact_path = (
                spec.artifact_path if spec is not None else _artifact_path_for(task_id)
            )
            verify_req = VerifyRequest(
                run_id=run_id,
                task_id=task_id,
                attempt=attempt,
                artifact_path=artifact_path,
                patch_observation_id=patch_obs.operation_id,
                check_observation_id=check_obs.operation_id,
                check_observation=check_obs,
            )
        result_v, evidence_records = verifier.verify(verify_req)
        # Persist evidence BEFORE the snapshot accepts refs (architecture §30,
        # T13). Evidence is written to disk first; only then EvidenceAccepted
        # records the refs in the authoritative snapshot.
        for ev in evidence_records:
            repository.persistence.save_evidence(ev)
        if result_v.status.value == "PASS" and result_v.evidence_refs:
            current = _step(
                repository,
                run_id,
                current.revision,
                EvidenceAccepted(
                    run_id=run_id, task_id=task_id, evidence_refs=result_v.evidence_refs
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
                return RealEffectsOutcome(
                    current, current.status, "retry exhausted -> human gate"
                )
    return RealEffectsOutcome(current, current.status, "max iterations reached")


def _artifact_path_for(task_id: str) -> str:
    """Default artifact path guess for a no-effect attempt (will not exist)."""
    return f"artifact_{task_id}.py"


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
    """Return the task with ``task_id`` from the run's plan."""
    assert state.plan is not None, "run_plan_real requires a plan to drive"
    return next(t for t in state.plan.tasks if t.task_id == task_id)


__all__ = [
    "ControlledToolExecutor",
    "RealEffectsOutcome",
    "ToolEffectSpec",
    "run_plan_real",
]
