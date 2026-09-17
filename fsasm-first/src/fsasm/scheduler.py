"""FS-ASM Scheduler (T09) \u2014 deterministic whole-plan scheduling.

The Scheduler is a pure query over the authoritative ``RunState`` (architecture
\u00a718). It does NOT mutate state, grant PASS, persist, or apply events: those
belong to the Domain Core (``apply_event``) and the State Repository. Its only
job is to answer "what should run next?" so the workflow can emit a
``TaskActivated`` event through the one event path.

Contract (architecture \u00a718):
- At most one active Child Task per run. If one is already active, the run is
  busy and there is no new candidate.
- A task is eligible once ALL its dependencies are PASSED. The scheduler picks
  the lowest-``sequence`` eligible task deterministically (sequence, then
  ``task_id`` tie-break) so the same state always yields the same candidate.
- "No ready task" is not a single answer: the scheduler distinguishes
  ``ALL_COMPLETE`` (run finished), ``BLOCKED`` (no eligible task and not all
  done \u2014 a dependency is in a non-PASSED terminal/needs_human state or the
  remaining graph is inconsistent), and ``WAITING_ON_GATE`` (the run is at a
  Human Gate). A genuine cycle is structural corruption caught earlier by the
  Task Compiler (T08) and the Plan cycle validator; the scheduler reports it
  as ``BLOCKED`` rather than silently looping.
- Parent/run completion is computed from ALL required Child Tasks; PASS of
  ``TASK-001`` does NOT end a multi-task plan.
- The scheduler never claims PASS; it only identifies the next task.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from fsasm.models import ChildTask, RunState, RunStatus, TaskStatus


class ScheduleOutcome(str, Enum):
    """Why the scheduler returned (or did not return) a candidate task."""

    NEXT_TASK = "NEXT_TASK"
    ALL_COMPLETE = "ALL_COMPLETE"
    BLOCKED = "BLOCKED"
    WAITING_ON_GATE = "WAITING_GATE"
    BUSY = "BUSY"


class ScheduleResult(BaseModel):
    """The scheduler's answer: a candidate task plus the outcome reason.

    ``task`` is set only when ``outcome == NEXT_TASK``; otherwise it is ``None``
    and the caller must inspect ``outcome`` to decide whether to stop, wait,
    escalate, or treat the plan as blocked.
    """

    outcome: ScheduleOutcome = Field(..., description="Why this result was returned.")
    task: ChildTask | None = Field(
        default=None,
        description="The next candidate task, set only for NEXT_TASK.",
    )

    @property
    def has_next(self) -> bool:
        return self.outcome is ScheduleOutcome.NEXT_TASK and self.task is not None

    @property
    def is_complete(self) -> bool:
        return self.outcome is ScheduleOutcome.ALL_COMPLETE


def _dependencies_satisfied(task: ChildTask, completed: set[str]) -> bool:
    return all(dep in completed for dep in task.dependencies)


def _has_unsatisfiable_dependency(
    task: ChildTask,
    by_id: dict[str, ChildTask],
    completed: set[str],
    failed: set[str],
    needs_human: set[str],
) -> bool:
    """A dependency is in a non-PASSED terminal/needs_human state.

    If a dependency is FAILED and not retryable, or NEEDS_HUMAN, the dependent
    task can never become eligible \u2014 the plan is blocked.
    """
    for dep_id in task.dependencies:
        if dep_id in completed:
            continue
        dep = by_id.get(dep_id)
        if dep is None:
            return True
        if dep.status is TaskStatus.NEEDS_HUMAN or dep_id in needs_human:
            return True
        if dep.status is TaskStatus.FAILED and not dep.can_retry():
            return True
    return False


def all_required_tasks_complete(state: RunState) -> bool:
    """Parent/run completion requires ALL Child Tasks to be PASSED.

    The run's own ``completed_task_ids`` is the authority; this query mirrors
    the Domain Core's ``_all_required_tasks_complete`` so the scheduler can
    answer without applying events. PASS of one task does NOT complete a
    multi-task plan.
    """
    if state.plan is None:
        return False
    done = set(state.completed_task_ids)
    return all(t.task_id in done for t in state.plan.tasks)


def schedule(state: RunState) -> ScheduleResult:
    """Select the next qualifying Child Task, or explain why there is none.

    Pure query: reads ``state`` only, returns a ``ScheduleResult``. The caller
    (workflow) emits ``TaskActivated`` via the Domain Core to actually move the
    task from READY to RUNNING; the scheduler does not grant that transition.

    Args:
        state: The authoritative RunState snapshot (plan + Task Register).

    Returns:
        ``ScheduleResult`` with ``outcome`` and, for ``NEXT_TASK``, the
        candidate ``ChildTask`` (lowest sequence, deterministic tie-break).
    """
    if state.plan is None:
        return ScheduleResult(outcome=ScheduleOutcome.BLOCKED)

    if state.active_task_id is not None:
        return ScheduleResult(outcome=ScheduleOutcome.BUSY)

    if state.status is RunStatus.NEEDS_HUMAN:
        return ScheduleResult(outcome=ScheduleOutcome.WAITING_ON_GATE)

    if state.status in (RunStatus.PASSED, RunStatus.FAILED):
        return ScheduleResult(outcome=ScheduleOutcome.ALL_COMPLETE)

    completed = set(state.completed_task_ids)
    failed = set(state.failed_task_ids)
    needs_human = set(state.needs_human_task_ids)
    by_id: dict[str, ChildTask] = {t.task_id: t for t in state.plan.tasks}

    if all_required_tasks_complete(state):
        return ScheduleResult(outcome=ScheduleOutcome.ALL_COMPLETE)

    # A task is eligible to be activated once its dependencies are PASSED.
    # Both PENDING (needs TaskReadied first) and READY (already readied, e.g.
    # after a retry FAILED->READY) tasks with satisfied deps qualify; the run
    # emits TaskReadied only for PENDING candidates. Deterministic sequence,
    # then task_id tie-break.
    candidates = [
        t
        for t in state.plan.tasks
        if t.status in (TaskStatus.PENDING, TaskStatus.READY)
        and _dependencies_satisfied(t, completed)
    ]
    if candidates:
        candidates.sort(key=lambda t: (t.sequence, t.task_id))
        return ScheduleResult(outcome=ScheduleOutcome.NEXT_TASK, task=candidates[0])

    blocked = [
        t
        for t in state.plan.tasks
        if t.status is TaskStatus.PENDING
        and _has_unsatisfiable_dependency(t, by_id, completed, failed, needs_human)
    ]
    if blocked:
        return ScheduleResult(outcome=ScheduleOutcome.BLOCKED)

    remaining = [
        t
        for t in state.plan.tasks
        if t.task_id not in completed
        and t.task_id not in failed
        and t.task_id not in needs_human
    ]
    if not remaining:
        return ScheduleResult(outcome=ScheduleOutcome.ALL_COMPLETE)

    return ScheduleResult(outcome=ScheduleOutcome.BLOCKED)
