"""T07 — Activity adapter and start_new/resume foundation contract.

Proves the v1 mutation path (architecture §11, §14, §15) and the activity state
contract (T07):
- ``start_new`` reserves a NEW run and writes the initial snapshot (revision 0);
  it refuses to overwrite an existing run or a mismatched plan.
- ``resume`` loads and validates the approved snapshot and returns its revision;
  it does not promise to reconcile real tool effects.
- ``start_new`` and ``resume`` have disjoint contracts: a new run cannot be
  started over an existing run_id, and resume cannot create a run.
- Each semantic change goes through load → apply_event → commit_snapshot via
  ``StateRepository.advance``.
- An **outdated activity** (stale ``expected_revision``) is rejected and does
  NOT overwrite newer state.
- Technical retry activity does NOT increment ``task_attempt``: only a
  ``TaskActivated`` event does.
"""

import copy

import pytest

from fsasm.domain import (
    EvidenceAccepted,
    TaskActivated,
    TaskVerificationFailed,
)
from fsasm.errors import PersistenceError, RunAlreadyExistsError
from fsasm.models import (
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence
from fsasm.runtime_lifecycle import RuntimeLifecycle
from fsasm.state_repository import StateRepository, StaleRevisionError


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


def _ready_state(run_id: str = "r", n: int = 2) -> RunState:
    plan = _plan(run_id, n)
    for t in plan.tasks:
        t.status = TaskStatus.READY
    return RunState(run_id=run_id, goal="g", status=RunStatus.RUNNING, plan=plan)


@pytest.fixture
def lifecycle(tmp_path):
    persistence = RuntimePersistence(runtime_dir=tmp_path / "runtime")
    repo = StateRepository(persistence)
    return RuntimeLifecycle(repo)


# =============================================================================
# start_new / resume disjoint contracts
# =============================================================================


class TestStartNew:
    def test_start_new_reserves_run_and_writes_revision_zero(self, lifecycle):
        plan = _plan("r")
        state = lifecycle.start_new("r", "g", plan)
        assert state.revision == 0
        assert lifecycle.repository.load("r").run_id == "r"
        assert lifecycle.repository.load("r").plan is not None

    def test_start_new_refuses_existing_run(self, lifecycle):
        lifecycle.start_new("r", "g", _plan("r"))
        with pytest.raises(RunAlreadyExistsError):
            lifecycle.start_new("r", "different-goal", _plan("r"))

    def test_start_new_refuses_mismatched_plan_run_id(self, lifecycle):
        with pytest.raises(PersistenceError, match="does not match"):
            lifecycle.start_new("r", "g", _plan("OTHER"))

    def test_start_new_does_not_overwrite_existing_evidence(self, lifecycle, tmp_path):
        lifecycle.start_new("r", "g", _plan("r"))
        # simulate some evidence existing from the first run
        ev_dir = lifecycle.repository.persistence._get_evidence_dir("r")
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "evidence-x.json").write_text('{"id": "x"}', encoding="utf-8")
        with pytest.raises(RunAlreadyExistsError):
            lifecycle.start_new("r", "new-goal", _plan("r"))
        # evidence from the first run survives (no overwrite)
        assert (ev_dir / "evidence-x.json").exists()


class TestResume:
    def test_resume_loads_approved_snapshot_and_revision(self, lifecycle):
        plan = _plan("r")
        lifecycle.start_new("r", "g", plan)
        state, revision = lifecycle.resume("r")
        assert state.run_id == "r"
        assert revision == 0

    def test_resume_after_advance_returns_new_revision(self, lifecycle):
        plan = _plan("r")
        lifecycle.start_new("r", "g", plan)
        # mark tasks READY in the snapshot via a direct commit
        s0, rev = lifecycle.resume("r")
        ready = _ready_state("r")
        ready.revision = rev
        # commit the READY state as revision 1
        lifecycle.repository.commit_snapshot("r", rev, ready)
        state, revision = lifecycle.resume("r")
        assert revision == 1
        assert state.plan.tasks[0].status == TaskStatus.READY

    def test_resume_uninitialized_run_fails_closed(self, lifecycle):
        with pytest.raises(PersistenceError, match="is not initialized"):
            lifecycle.resume("ghost")


class TestDisjointContracts:
    def test_start_new_then_resume_round_trip(self, lifecycle):
        plan = _plan("r")
        lifecycle.start_new("r", "g", plan)
        state, revision = lifecycle.resume("r")
        assert revision == 0
        assert state.plan.run_id == "r"

    def test_resume_does_not_create_a_run(self, lifecycle):
        # resume on a non-existent run must not create it
        with pytest.raises(PersistenceError):
            lifecycle.resume("never-existed")
        assert not lifecycle.repository.is_run_initialized("never-existed")


# =============================================================================
# Activity adapter: load → apply_event → commit_snapshot
# =============================================================================


@pytest.fixture
def running_run(lifecycle):
    """A run initialized with READY tasks, ready to advance via events."""
    plan = _plan("r")
    lifecycle.start_new("r", "g", plan)
    s0, rev = lifecycle.resume("r")
    ready = _ready_state("r")
    ready.revision = rev
    lifecycle.repository.commit_snapshot("r", rev, ready)
    return lifecycle


class TestAdvance:
    def test_advance_applies_event_and_increments_revision(self, running_run):
        lifecycle = running_run
        state, rev = lifecycle.resume("r")
        assert rev == 1
        committed = lifecycle.repository.advance(
            "r", rev, TaskActivated(run_id="r", task_id="TASK-1")
        )
        assert committed.revision == 2
        assert committed.active_task_id == "TASK-1"
        assert lifecycle.repository.load("r").revision == 2

    def test_advance_returns_committed_state(self, running_run):
        lifecycle = running_run
        state, rev = lifecycle.resume("r")
        committed = lifecycle.repository.advance(
            "r", rev, TaskActivated(run_id="r", task_id="TASK-1")
        )
        assert committed.active_task_id == "TASK-1"
        assert committed.revision == rev + 1


class TestOutdatedActivityRejected:
    def test_outdated_activity_does_not_overwrite_newer_state(self, running_run):
        """An activity holding a stale expected_revision must not overwrite a
        newer committed state (the core T07/G1 invariant)."""
        lifecycle = running_run
        state, rev = lifecycle.resume("r")
        # a newer commit lands first (TASK-1 activated -> revision 2)
        lifecycle.repository.advance(
            "r", rev, TaskActivated(run_id="r", task_id="TASK-1")
        )
        assert lifecycle.repository.load("r").revision == 2
        # the outdated activity still holds rev=1 -> rejected
        with pytest.raises(StaleRevisionError):
            lifecycle.repository.advance(
                "r", rev, TaskActivated(run_id="r", task_id="TASK-2")
            )
        # authority remains the newer state (TASK-1 active)
        loaded = lifecycle.repository.load("r")
        assert loaded.revision == 2
        assert loaded.active_task_id == "TASK-1"

    def test_outdated_activity_no_side_effect(self, running_run):
        lifecycle = running_run
        state, rev = lifecycle.resume("r")
        lifecycle.repository.advance(
            "r", rev, TaskActivated(run_id="r", task_id="TASK-1")
        )
        before = copy.deepcopy(lifecycle.repository.load("r"))
        with pytest.raises(StaleRevisionError):
            lifecycle.repository.advance(
                "r", rev, TaskActivated(run_id="r", task_id="TASK-2")
            )
        after = lifecycle.repository.load("r")
        assert after == before, "rejected advance must not change the snapshot"


class TestTechnicalRetryDoesNotIncrementAttempt:
    def test_technical_retry_event_keeps_attempt(self, running_run):
        """Technical retry activity does NOT increment task_attempt: only a
        TaskActivated event (a real execution attempt) does."""
        lifecycle = running_run
        state, rev = lifecycle.resume("r")
        # first real attempt
        s1 = lifecycle.repository.advance(
            "r", rev, TaskActivated(run_id="r", task_id="TASK-1")
        )
        assert s1.plan.tasks[0].attempt == 1
        # accept evidence (a technical/in-transit step, no new attempt)
        s2 = lifecycle.repository.advance(
            "r",
            s1.revision,
            EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev"]),
        )
        assert s2.plan.tasks[0].attempt == 1, "evidence step must not increment attempt"
        # verification failure (still attempt 1; retry decision is separate)
        s3 = lifecycle.repository.advance(
            "r",
            s2.revision,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        assert s3.plan.tasks[0].attempt == 1, "FAIL must not increment attempt"

    def test_only_task_activated_increments_attempt(self, running_run):
        from fsasm.domain import TaskRetried

        lifecycle = running_run
        state, rev = lifecycle.resume("r")
        s1 = lifecycle.repository.advance(
            "r", rev, TaskActivated(run_id="r", task_id="TASK-1")
        )
        assert s1.plan.tasks[0].attempt == 1
        s2 = lifecycle.repository.advance(
            "r",
            s1.revision,
            TaskVerificationFailed(
                run_id="r", task_id="TASK-1", verification_passed=False
            ),
        )
        s3 = lifecycle.repository.advance(
            "r", s2.revision, TaskRetried(run_id="r", task_id="TASK-1")
        )
        # FAILED->READY does NOT increment; only the next TaskActivated will
        assert s3.plan.tasks[0].attempt == 1
        s4 = lifecycle.repository.advance(
            "r", s3.revision, TaskActivated(run_id="r", task_id="TASK-1")
        )
        assert s4.plan.tasks[0].attempt == 2


# =============================================================================
# Determinism + resume round-trip after controlled restart (Gate C evidence)
# =============================================================================


class TestControlledRestart:
    def test_resume_returns_to_approved_snapshot_after_restart(self, lifecycle):
        """Gate C: a controlled restart (new process / fresh repository over the
        same on-disk state) returns to the approved snapshot."""
        plan = _plan("r")
        lifecycle.start_new("r", "g", plan)
        s0, rev = lifecycle.resume("r")
        ready = _ready_state("r")
        ready.revision = rev
        committed = lifecycle.repository.commit_snapshot("r", rev, ready)
        # "restart": build a fresh lifecycle over the SAME on-disk runtime dir
        fresh_persistence = RuntimePersistence(
            runtime_dir=lifecycle.repository.persistence.runtime_dir
        )
        fresh_repo = StateRepository(fresh_persistence)
        fresh_lifecycle = RuntimeLifecycle(fresh_repo)
        resumed, revision = fresh_lifecycle.resume("r")
        assert revision == 1
        assert resumed == committed

    def test_resume_is_idempotent(self, lifecycle):
        lifecycle.start_new("r", "g", _plan("r"))
        a, ra = lifecycle.resume("r")
        b, rb = lifecycle.resume("r")
        assert a == b and ra == rb
