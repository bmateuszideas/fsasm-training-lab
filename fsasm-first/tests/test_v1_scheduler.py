"""T09 \u2014 Scheduler of the whole plan and Parent/run aggregation.

Tests that the Scheduler deterministically selects a qualifying Child Task
after dependencies are met, maintains at most one active task, distinguishes
"no ready task" cases (completion vs. blockage vs. gate vs. busy), and computes
Parent/run from ALL required Child Tasks so PASS of TASK-001 does not end a
multi-task plan (architecture \u00a718; canonical TODO T09).
"""

from fsasm.models import (
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.scheduler import (
    ScheduleOutcome,
    all_required_tasks_complete,
    schedule,
)


def _task(
    tid: str,
    seq: int,
    deps: list[str] | None = None,
    status: TaskStatus = TaskStatus.PENDING,
    attempt: int = 0,
    max_attempts: int = 3,
) -> ChildTask:
    return ChildTask(
        task_id=tid,
        sequence=seq,
        title="t",
        description="d",
        dependencies=deps or [],
        status=status,
        attempt=attempt,
        max_attempts=max_attempts,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="e"),
    )


def _state(
    tasks: list[ChildTask],
    *,
    status: RunStatus = RunStatus.RUNNING,
    completed: list[str] | None = None,
    failed: list[str] | None = None,
    needs_human: list[str] | None = None,
    active_task_id: str | None = None,
) -> RunState:
    plan = Plan(plan_id="p", run_id="r", goal="g", tasks=tasks)
    return RunState(
        run_id="r",
        goal="g",
        status=status,
        plan=plan,
        completed_task_ids=completed or [],
        failed_task_ids=failed or [],
        needs_human_task_ids=needs_human or [],
        active_task_id=active_task_id,
    )


def _linear3() -> list[ChildTask]:
    return [
        _task("TASK-r-1", 1),
        _task("TASK-r-2", 2, ["TASK-r-1"]),
        _task("TASK-r-3", 3, ["TASK-r-2"]),
    ]


def _mark_passed(state: RunState, task_id: str) -> None:
    for t in state.plan.tasks:
        if t.task_id == task_id:
            t.status = TaskStatus.PASSED


class TestSelectsQualifyingTask:
    """Deterministically select a task once dependencies are met."""

    def test_first_task_no_deps_selected(self) -> None:
        res = schedule(_state(_linear3()))
        assert res.has_next
        assert res.task.task_id == "TASK-r-1"

    def test_second_task_after_first_passed(self) -> None:
        st = _state(_linear3(), completed=["TASK-r-1"])
        _mark_passed(st, "TASK-r-1")
        res = schedule(st)
        assert res.has_next
        assert res.task.task_id == "TASK-r-2"

    def test_third_task_after_second_passed(self) -> None:
        st = _state(_linear3(), completed=["TASK-r-1", "TASK-r-2"])
        _mark_passed(st, "TASK-r-1")
        _mark_passed(st, "TASK-r-2")
        res = schedule(st)
        assert res.has_next
        assert res.task.task_id == "TASK-r-3"

    def test_deterministic_lowest_sequence(self) -> None:
        tasks = [
            _task("TASK-r-3", 3),
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2),
        ]
        res = schedule(_state(tasks))
        assert res.task.task_id == "TASK-r-1"

    def test_diamond_selects_independent_roots(self) -> None:
        tasks = [
            _task("A", 1),
            _task("B", 2),
            _task("C", 3, ["A", "B"]),
        ]
        st = _state(tasks)
        first = schedule(st)
        assert first.task.task_id == "A"
        st.active_task_id = None
        st.completed_task_ids = ["A"]
        _mark_passed(st, "A")
        second = schedule(st)
        assert second.task.task_id == "B"


class TestOneActiveTask:
    """At most one active Child Task per run."""

    def test_busy_when_active_task_set(self) -> None:
        res = schedule(_state(_linear3(), active_task_id="TASK-r-1"))
        assert res.outcome is ScheduleOutcome.BUSY
        assert res.task is None

    def test_does_not_return_second_while_first_running(self) -> None:
        st = _state(_linear3(), active_task_id="TASK-r-1", completed=["TASK-r-1"])
        res = schedule(st)
        assert res.outcome is ScheduleOutcome.BUSY


class TestNoReadyTaskDistinguished:
    """Distinguish completion, blockage, cycle/inconsistency and gate wait."""

    def test_all_complete(self) -> None:
        st = _state(_linear3(), completed=["TASK-r-1", "TASK-r-2", "TASK-r-3"])
        res = schedule(st)
        assert res.is_complete

    def test_blocked_by_failed_non_retryable_dependency(self) -> None:
        tasks = [
            _task("A", 1, status=TaskStatus.FAILED, attempt=3, max_attempts=3),
            _task("B", 2, ["A"]),
        ]
        st = _state(tasks, failed=["A"])
        res = schedule(st)
        assert res.outcome is ScheduleOutcome.BLOCKED

    def test_not_blocked_when_failed_still_retryable(self) -> None:
        tasks = [
            _task("A", 1, status=TaskStatus.FAILED, attempt=1, max_attempts=3),
            _task("B", 2, ["A"]),
        ]
        st = _state(tasks, failed=["A"])
        res = schedule(st)
        assert res.outcome is ScheduleOutcome.BLOCKED

    def test_waiting_on_gate(self) -> None:
        st = _state(
            _linear3(),
            status=RunStatus.NEEDS_HUMAN,
            needs_human=["TASK-r-1"],
        )
        res = schedule(st)
        assert res.outcome is ScheduleOutcome.WAITING_ON_GATE

    def test_no_plan_is_blocked(self) -> None:
        st = RunState(run_id="r", goal="g", status=RunStatus.RUNNING)
        res = schedule(st)
        assert res.outcome is ScheduleOutcome.BLOCKED


class TestParentRunAggregation:
    """Parent/run completion is computed from ALL required Child Tasks."""

    def test_pass_of_first_does_not_complete_plan(self) -> None:
        st = _state(_linear3(), completed=["TASK-r-1"])
        _mark_passed(st, "TASK-r-1")
        res = schedule(st)
        assert not res.is_complete
        assert res.has_next

    def test_all_required_complete_only_when_all_passed(self) -> None:
        st = _state(_linear3(), completed=["TASK-r-1", "TASK-r-2"])
        assert not all_required_tasks_complete(st)
        st3 = _state(_linear3(), completed=["TASK-r-1", "TASK-r-2", "TASK-r-3"])
        assert all_required_tasks_complete(st3)

    def test_no_plan_not_complete(self) -> None:
        st = RunState(run_id="r", goal="g", status=RunStatus.RUNNING)
        assert not all_required_tasks_complete(st)


class TestPlanSizes:
    """Plans of 1, 3 and N schedule correctly."""

    def test_one_task_plan(self) -> None:
        tasks = [_task("TASK-r-1", 1)]
        st = _state(tasks)
        res = schedule(st)
        assert res.has_next and res.task.task_id == "TASK-r-1"
        st_done = _state(tasks, completed=["TASK-r-1"])
        assert schedule(st_done).is_complete

    def test_n_task_linear(self) -> None:
        tasks = [
            _task(f"TASK-r-{i}", i, [f"TASK-r-{i - 1}"] if i > 1 else [])
            for i in range(1, 6)
        ]
        st = _state(tasks)
        assert schedule(st).task.task_id == "TASK-r-1"
        st_mid = _state(tasks, completed=["TASK-r-1", "TASK-r-2", "TASK-r-3"])
        for tid in ["TASK-r-1", "TASK-r-2", "TASK-r-3"]:
            _mark_passed(st_mid, tid)
        assert schedule(st_mid).task.task_id == "TASK-r-4"


class TestPurityAndDeterminism:
    """The scheduler is a pure query: no mutation, deterministic output."""

    def test_does_not_mutate_state(self) -> None:
        st = _state(_linear3())
        before_active = st.active_task_id
        before_completed = list(st.completed_task_ids)
        before_statuses = [t.status for t in st.plan.tasks]
        schedule(st)
        assert st.active_task_id == before_active
        assert st.completed_task_ids == before_completed
        assert [t.status for t in st.plan.tasks] == before_statuses

    def test_same_state_same_result(self) -> None:
        st1 = _state(_linear3(), completed=["TASK-r-1"])
        _mark_passed(st1, "TASK-r-1")
        st2 = _state(_linear3(), completed=["TASK-r-1"])
        _mark_passed(st2, "TASK-r-1")
        r1 = schedule(st1)
        r2 = schedule(st2)
        assert r1.outcome is r2.outcome
        assert (r1.task.task_id if r1.task else None) == (
            r2.task.task_id if r2.task else None
        )

    def test_scheduler_never_grants_pass(self) -> None:
        st = _state(_linear3(), completed=["TASK-r-1", "TASK-r-2", "TASK-r-3"])
        res = schedule(st)
        assert res.outcome is ScheduleOutcome.ALL_COMPLETE
        assert res.task is None


class TestResultProperties:
    """ScheduleResult convenience properties."""

    def test_has_next_true_only_with_task(self) -> None:
        res_next = schedule(_state(_linear3()))
        assert res_next.has_next
        res_busy = schedule(_state(_linear3(), active_task_id="TASK-r-1"))
        assert not res_busy.has_next

    def test_is_complete(self) -> None:
        st = _state(_linear3(), completed=["TASK-r-1", "TASK-r-2", "TASK-r-3"])
        assert schedule(st).is_complete
        st2 = _state(_linear3(), completed=["TASK-r-1"])
        assert not schedule(st2).is_complete
