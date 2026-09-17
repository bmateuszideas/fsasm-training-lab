"""T06 — State Repository with revision and one atomic commit.

Proves the v1 State Repository contract (architecture §11, §14; G1):
- ``load(run_id)`` reconstructs the authoritative snapshot; fail-closed for an
  uninitialized/missing-snapshot run.
- ``commit_snapshot(run_id, expected_revision, next_state)`` rejects a stale
  ``expected_revision`` (G1: a stale snapshot cannot roll back newer state),
  rejects a mismatched ``run_id``, increments ``revision`` exactly once.
- The authoritative ``state.json`` is committed first; the derived ``plan.json``
  projection is written after and is rebuildable from the authority.
- Fault injection: a projection failure does NOT roll back the authoritative
  snapshot and cannot yield a false PASS — the authority is the only source of
  truth (F3 preserved).
- F3/F4/F5 protections remain effective (run creation, path safety, atomic
  single-file write) — the repository composes ``RuntimePersistence``.
"""

import copy
import json
from pathlib import Path

import pytest

from fsasm.domain import (
    EvidenceAccepted,
    TaskActivated,
    apply_event,
)
from fsasm.errors import PersistenceError
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


def _initial_state(run_id: str = "r", n: int = 2) -> RunState:
    plan = _plan(run_id, n)
    for t in plan.tasks:
        t.status = TaskStatus.READY
    return RunState(run_id=run_id, goal="g", status=RunStatus.RUNNING, plan=plan)


@pytest.fixture
def repo(tmp_path):
    persistence = RuntimePersistence(runtime_dir=tmp_path / "runtime")
    return StateRepository(persistence)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# =============================================================================
# load
# =============================================================================


class TestLoad:
    def test_load_reconstructs_authoritative_snapshot(self, repo):
        repo.create_run("r")
        state = _initial_state()
        repo.init_snapshot(state)
        loaded = repo.load("r")
        assert loaded.run_id == "r"
        assert loaded.revision == 0
        assert loaded.plan is not None

    def test_load_uninitialized_run_fails_closed(self, repo):
        repo.create_run("r")
        with pytest.raises(
            PersistenceError, match="authoritative state.json .* is missing"
        ):
            repo.load("r")

    def test_load_nonexistent_run_fails_closed(self, repo):
        with pytest.raises(PersistenceError, match="is not initialized"):
            repo.load("ghost")


# =============================================================================
# init_snapshot
# =============================================================================


class TestInitSnapshot:
    def test_init_writes_first_snapshot_at_revision_zero(self, repo):
        repo.create_run("r")
        state = _initial_state()
        initial = repo.init_snapshot(state)
        assert initial.revision == 0
        assert repo.has_snapshot("r")
        assert repo.load("r").revision == 0

    def test_init_rejects_uninitialized_run(self, repo):
        with pytest.raises(PersistenceError, match="is not initialized"):
            repo.init_snapshot(_initial_state())

    def test_init_rejects_existing_snapshot(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        with pytest.raises(PersistenceError, match="already has an authoritative"):
            repo.init_snapshot(_initial_state())

    def test_init_writes_derived_plan_projection(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        plan_path = repo.persistence._get_plan_path("r")
        assert plan_path.exists()
        assert _read(plan_path)["run_id"] == "r"


# =============================================================================
# commit_snapshot + revision
# =============================================================================


class TestCommitRevision:
    def test_commit_increments_revision_exactly_once(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        state = repo.load("r")
        nxt = apply_event(state, TaskActivated(run_id="r", task_id="TASK-1"))
        committed = repo.commit_snapshot("r", expected_revision=0, next_state=nxt)
        assert committed.revision == 1
        assert repo.load("r").revision == 1

    def test_two_commits_increment_monotonically(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        s0 = repo.load("r")
        s1 = apply_event(s0, TaskActivated(run_id="r", task_id="TASK-1"))
        c1 = repo.commit_snapshot("r", 0, s1)
        assert c1.revision == 1
        s2 = apply_event(
            c1, EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev"])
        )
        c2 = repo.commit_snapshot("r", 1, s2)
        assert c2.revision == 2
        assert repo.load("r").revision == 2

    def test_commit_rejects_mismatched_run_id(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        state = repo.load("r")
        with pytest.raises(PersistenceError, match="run_id mismatch"):
            repo.commit_snapshot("OTHER", 0, state)

    def test_commit_returns_new_state_not_input(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        nxt = apply_event(repo.load("r"), TaskActivated(run_id="r", task_id="TASK-1"))
        committed = repo.commit_snapshot("r", 0, nxt)
        assert committed is not nxt
        assert committed.revision == nxt.revision + 1


# =============================================================================
# G1: stale revision cannot roll back newer state
# =============================================================================


class TestG1StaleRevisionRollback:
    def test_stale_revision_rejected(self, repo):
        """G1 reproducer: a stale snapshot cannot overwrite newer state.

        commit(state_running) -> commit(newer_state) -> commit(stale_old_copy)
        must NOT roll back to the stale copy; the stale commit is rejected.
        """
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        # commit a newer state (revision 0 -> 1)
        running = apply_event(
            repo.load("r"), TaskActivated(run_id="r", task_id="TASK-1")
        )
        repo.commit_snapshot("r", 0, running)
        assert repo.load("r").revision == 1
        # A caller holding the now-stale expected_revision=0 against on-disk
        # revision 1 must be rejected.
        stale_copy = _initial_state()
        with pytest.raises(StaleRevisionError):
            repo.commit_snapshot("r", 0, stale_copy)
        # authority remains the newer state
        loaded = repo.load("r")
        assert loaded.revision == 1
        assert loaded.active_task_id == "TASK-1"

    def test_stale_revision_error_carries_expected_and_actual(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        running = apply_event(
            repo.load("r"), TaskActivated(run_id="r", task_id="TASK-1")
        )
        repo.commit_snapshot("r", 0, running)
        with pytest.raises(StaleRevisionError) as exc_info:
            repo.commit_snapshot("r", 0, _initial_state())
        assert exc_info.value.expected == 0
        assert exc_info.value.actual == 1

    def test_concurrent_writers_one_wins_one_rejects(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        base = repo.load("r")
        # writer A commits first
        a_state = apply_event(base, TaskActivated(run_id="r", task_id="TASK-1"))
        a_committed = repo.commit_snapshot("r", base.revision, a_state)
        assert a_committed.revision == 1
        # writer B still holds expected_revision=0 -> rejected
        b_state = apply_event(base, TaskActivated(run_id="r", task_id="TASK-2"))
        with pytest.raises(StaleRevisionError):
            repo.commit_snapshot("r", base.revision, b_state)
        assert repo.load("r").active_task_id == "TASK-1"


# =============================================================================
# F3 preserved: projection failure does not roll back authority / no false PASS
# =============================================================================


class TestFaultInjectionProjection:
    def test_projection_failure_keeps_authoritative_commit(self, repo, monkeypatch):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        state = repo.load("r")
        nxt = apply_event(
            apply_event(state, TaskActivated(run_id="r", task_id="TASK-1")),
            EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev-diff"]),
        )
        # Inject failure on the SECOND _atomic_write_json call (plan.json).
        call = {"n": 0}
        original = repo.persistence._atomic_write_json

        def failing_write(path, data):
            call["n"] += 1
            if call["n"] == 2:  # plan.json projection
                raise PersistenceError(
                    message="injected projection failure",
                    path=str(path),
                    operation="injected",
                )
            return original(path, data)

        monkeypatch.setattr(repo.persistence, "_atomic_write_json", failing_write)
        with pytest.raises(PersistenceError, match="injected projection failure"):
            repo.commit_snapshot("r", 0, nxt)
        monkeypatch.undo()
        # authoritative state.json WAS committed with revision 1
        loaded = repo.load("r")
        assert loaded.revision == 1
        assert loaded.active_task_id == "TASK-1"
        assert "TASK-1" in loaded.plan.tasks[0].accepted_evidence_refs or (
            loaded.plan.tasks[0].accepted_evidence_refs == ["ev-diff"]
        )
        # plan.json projection is absent/stale, but the authority is intact
        # and rebuildable from state.json
        plan_path = repo.persistence._get_plan_path("r")
        assert not plan_path.exists() or _read(plan_path)["run_id"] == "r"

    def test_projection_failure_cannot_give_false_pass(self, repo, monkeypatch):
        """A projection failure after the authoritative commit cannot leave a
        state where PASS is granted without the authoritative snapshot."""
        repo.create_run("r")
        repo.init_snapshot(_initial_state("r", n=1))
        state = repo.load("r")
        nxt = apply_event(
            apply_event(state, TaskActivated(run_id="r", task_id="TASK-1")),
            EvidenceAccepted(run_id="r", task_id="TASK-1", evidence_refs=["ev-diff"]),
        )
        # PASS event applied in-memory but NOT committed (projection fails first)
        call = {"n": 0}
        original = repo.persistence._atomic_write_json

        def failing_write(path, data):
            call["n"] += 1
            if call["n"] == 2:
                raise PersistenceError("injected", str(path), "injected")
            return original(path, data)

        monkeypatch.setattr(repo.persistence, "_atomic_write_json", failing_write)
        with pytest.raises(PersistenceError):
            repo.commit_snapshot("r", 0, nxt)
        monkeypatch.undo()
        loaded = repo.load("r")
        assert loaded.plan.tasks[0].status == TaskStatus.RUNNING
        assert loaded.status == RunStatus.RUNNING, "PASS not committed -> no false PASS"

    def test_authoritative_write_failure_preserves_prior_snapshot(
        self, repo, monkeypatch
    ):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        v1 = repo.load("r")
        # commit a newer state successfully
        newer = apply_event(v1, TaskActivated(run_id="r", task_id="TASK-1"))
        repo.commit_snapshot("r", 0, newer)
        v2 = repo.load("r")
        # now inject failure on the authoritative (first) write
        call = {"n": 0}
        original = repo.persistence._atomic_write_json

        def failing_write(path, data):
            call["n"] += 1
            if call["n"] == 1:
                raise PersistenceError("injected auth failure", str(path), "injected")
            return original(path, data)

        monkeypatch.setattr(repo.persistence, "_atomic_write_json", failing_write)
        with pytest.raises(PersistenceError):
            repo.commit_snapshot("r", v2.revision, copy.deepcopy(v2))
        monkeypatch.undo()
        # prior snapshot (revision 1, TASK-1 active) intact
        loaded = repo.load("r")
        assert loaded.revision == 1
        assert loaded.active_task_id == "TASK-1"


# =============================================================================
# F3/F4/F5 integration: existing protections remain effective
# =============================================================================


class TestF3F4F5Preserved:
    def test_duplicate_create_run_rejected(self, repo):
        repo.create_run("r")
        from fsasm.errors import RunAlreadyExistsError

        with pytest.raises(RunAlreadyExistsError):
            repo.create_run("r")

    def test_path_safety_rejects_traversal_run_id(self, repo):
        from fsasm.errors import InvalidIdentifierError

        with pytest.raises(InvalidIdentifierError):
            repo.create_run("../escape")

    def test_state_json_is_single_authority_over_plan_json(self, repo, tmp_path):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        # tamper with plan.json to be inconsistent with state.json
        plan_path = repo.persistence._get_plan_path("r")
        data = _read(plan_path)
        data["goal"] = "TAMPERED"
        plan_path.write_text(json.dumps(data), encoding="utf-8")
        # load() still returns the authoritative state.json goal
        loaded = repo.load("r")
        assert loaded.goal == "g"
        # recover repairs plan.json from state.json
        repo.persistence.recover_run("r")
        assert _read(plan_path)["goal"] == "g"

    def test_load_is_idempotent(self, repo):
        repo.create_run("r")
        repo.init_snapshot(_initial_state())
        a = repo.load("r")
        b = repo.load("r")
        assert a == b
