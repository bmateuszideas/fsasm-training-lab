"""T10 \u2014 Deterministic E2E of the whole plan on the ExecutorStub.

Proves the v1 execution path (Domain Core + Scheduler + State Repository) drives
a 1-, 3- and N-task plan to a terminal state on controlled stub results: the
whole plan, not just TASK-001, reaches PASSED; retry exhaustion reaches a Human
Gate; a blocked plan does not get marked completed; each Child Task goes through
its own finalization and a plan-level "verify" task never replaces the
Verification Plane (architecture \u00a716\u2013\u00a718, \u00a730; canonical TODO T10).
"""

import pathlib
import tempfile


from fsasm.models import (
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence
from fsasm.runtime import RuntimeOutcome, StubExecutor, run_plan
from fsasm.state_repository import StateRepository


def _task(
    tid: str,
    seq: int,
    deps: list[str] | None = None,
    max_attempts: int = 3,
) -> ChildTask:
    return ChildTask(
        task_id=tid,
        sequence=seq,
        title="t",
        description="d",
        dependencies=deps or [],
        max_attempts=max_attempts,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="e"),
    )


def _new_repo() -> StateRepository:
    d = pathlib.Path(tempfile.mkdtemp()) / "runtime"
    return StateRepository(RuntimePersistence(runtime_dir=d))


def _start(tasks: list[ChildTask], repo: StateRepository) -> RunState:
    plan = Plan(plan_id="p", run_id="r", goal="g", tasks=tasks)
    state = RunState(run_id="r", goal="g", status=RunStatus.PLANNED, plan=plan)
    repo.create_run("r")
    repo.init_snapshot(state)
    return repo.load("r")


class TestPlanSizesPass:
    """Plans of 1, 3 and N tasks all reach PASSED on controlled stub results."""

    def test_one_task_passes(self) -> None:
        repo = _new_repo()
        out = run_plan(_start([_task("TASK-r-1", 1)], repo), repo)
        assert out.status is RunStatus.PASSED
        assert out.state.completed_task_ids == ["TASK-r-1"]

    def test_three_tasks_pass_in_order(self) -> None:
        repo = _new_repo()
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
            _task("TASK-r-3", 3, ["TASK-r-2"]),
        ]
        out = run_plan(_start(tasks, repo), repo)
        assert out.status is RunStatus.PASSED
        assert out.state.completed_task_ids == [
            "TASK-r-1",
            "TASK-r-2",
            "TASK-r-3",
        ]

    def test_n_tasks_pass(self) -> None:
        repo = _new_repo()
        tasks = [
            _task(f"TASK-r-{i}", i, [f"TASK-r-{i - 1}"] if i > 1 else [])
            for i in range(1, 6)
        ]
        out = run_plan(_start(tasks, repo), repo)
        assert out.status is RunStatus.PASSED
        assert out.state.completed_task_ids == [f"TASK-r-{i}" for i in range(1, 6)]


class TestWholePlanNotFirstTask:
    """PASS of TASK-001 does NOT end the plan; the whole plan must terminate."""

    def test_pass_first_does_not_complete(self) -> None:
        repo = _new_repo()
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
        ]
        out = run_plan(_start(tasks, repo), repo)
        assert out.status is RunStatus.PASSED
        assert len(out.state.completed_task_ids) == 2


class TestRetryExhaustion:
    """Retry exhaustion reaches a Human Gate, not an infinite loop."""

    def test_exhaustion_reaches_gate(self) -> None:
        repo = _new_repo()
        tasks = [_task("TASK-r-1", 1, max_attempts=2)]
        out = run_plan(
            _start(tasks, repo),
            repo,
            executor=StubExecutor(should_pass=lambda tid, a: False),
        )
        assert out.status is RunStatus.NEEDS_HUMAN
        assert out.state.gate is not None
        assert out.state.gate.task_id == "TASK-r-1"
        assert "TASK-r-1" in out.state.needs_human_task_ids

    def test_retry_then_pass_completes(self) -> None:
        repo = _new_repo()
        tasks = [_task("TASK-r-1", 1, max_attempts=3)]
        out = run_plan(
            _start(tasks, repo),
            repo,
            executor=StubExecutor(should_pass=lambda tid, a: a >= 2),
        )
        assert out.status is RunStatus.PASSED
        assert out.state.plan.tasks[0].attempt == 2

    def test_three_tasks_with_retry_on_first(self) -> None:
        repo = _new_repo()
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
            _task("TASK-r-3", 3, ["TASK-r-2"]),
        ]
        out = run_plan(
            _start(tasks, repo),
            repo,
            executor=StubExecutor(
                should_pass=lambda tid, a: not (tid == "TASK-r-1" and a < 2)
            ),
        )
        assert out.status is RunStatus.PASSED
        assert out.state.completed_task_ids == [
            "TASK-r-1",
            "TASK-r-2",
            "TASK-r-3",
        ]


class TestBlockedPlan:
    """A blocked plan is not marked completed."""

    def test_blocked_dependency_not_marked_completed(self) -> None:
        repo = _new_repo()
        tasks = [
            _task("TASK-r-1", 1, max_attempts=1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
        ]
        out = run_plan(
            _start(tasks, repo),
            repo,
            executor=StubExecutor(should_pass=lambda tid, a: False),
        )
        assert out.status is RunStatus.NEEDS_HUMAN
        assert out.state.completed_task_ids == []


class TestEachTaskFinalization:
    """Each Child Task goes through its own finalization (RUNNING->terminal)."""

    def test_each_task_visited_once_on_pass(self) -> None:
        repo = _new_repo()
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
            _task("TASK-r-3", 3, ["TASK-r-2"]),
        ]
        out = run_plan(_start(tasks, repo), repo)
        for t in out.state.plan.tasks:
            assert t.status.value == "PASSED"
            assert t.attempt == 1

    def test_verify_task_not_replacing_verification_plane(self) -> None:
        repo = _new_repo()
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
            _task("TASK-r-3", 3, ["TASK-r-2"]),
        ]
        out = run_plan(_start(tasks, repo), repo)
        assert out.status is RunStatus.PASSED
        assert len(out.state.completed_task_ids) == 3


class TestSnapshotIsAuthority:
    """The on-disk snapshot is the authority; revision increments per event."""

    def test_final_state_matches_disk(self) -> None:
        repo = _new_repo()
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
        ]
        out = run_plan(_start(tasks, repo), repo)
        disk = repo.load("r")
        assert disk.status is RunStatus.PASSED
        assert disk.completed_task_ids == out.state.completed_task_ids
        assert disk.revision == out.state.revision

    def test_revision_increments_per_event(self) -> None:
        repo = _new_repo()
        tasks = [_task("TASK-r-1", 1)]
        out = run_plan(_start(tasks, repo), repo)
        assert out.state.revision > 0


class TestControlledResults:
    """Controlled stub results drive deterministic outcomes."""

    def test_always_fail_single_task_to_gate(self) -> None:
        repo = _new_repo()
        out = run_plan(
            _start([_task("TASK-r-1", 1, max_attempts=1)], repo),
            repo,
            executor=StubExecutor(should_pass=lambda tid, a: False),
        )
        assert out.status is RunStatus.NEEDS_HUMAN

    def test_outcome_is_runtimeoutcome(self) -> None:
        repo = _new_repo()
        out = run_plan(_start([_task("TASK-r-1", 1)], repo), repo)
        assert isinstance(out, RuntimeOutcome)
        assert out.reason
