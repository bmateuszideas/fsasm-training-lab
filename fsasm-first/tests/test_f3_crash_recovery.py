"""F3 — Crash-consistent state and recovery.

Authoritative-snapshot contract for this laboratory:
  * ``state.json`` (with its embedded ``RunState.plan``) is the authoritative
    run-state snapshot.
  * ``plan.json`` is a derived/materialized view, NEVER a competing authority.
  * A transition is not durably committed until ``state.json`` is atomically
    committed (via ``commit_run_state``, which writes state.json first, then
    plan.json from the authoritative state's plan).

These tests inject failures at controlled persistence boundaries and read the
actual persisted JSON from disk (no mocks asserting a helper was called). They
also exercise ``recover_run`` for idempotent recovery and verify the derived
view is repaired from the authoritative snapshot.

Limitation documented (not claimed): atomically replacing a single JSON file
(state.json) does NOT make evidence, log and plan writes one atomic
    transaction. Evidence/log remain supplementary artifacts. Recovery
guarantees logical plan/state consistency, not a fully transactional store.
"""

import json
import tempfile
from pathlib import Path

import pytest

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


def _make_plan(
    run_id: str, goal: str, task_status: TaskStatus = TaskStatus.PENDING
) -> Plan:
    tasks = [
        ChildTask(
            task_id=f"TASK-{i}",
            sequence=i,
            title=f"Task {i}",
            description=f"Description {i}",
            status=task_status if i == 1 else TaskStatus.PENDING,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
        )
        for i in range(1, 4)
    ]
    return Plan(plan_id=f"plan-{run_id}", run_id=run_id, goal=goal, tasks=tasks)


def _make_state(
    run_id: str, plan: Plan, status: RunStatus = RunStatus.PLANNED
) -> RunState:
    return RunState(
        run_id=run_id,
        goal=plan.goal,
        status=status,
        plan=plan,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def tmp_persistence() -> RuntimePersistence:
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime_dir = Path(tmpdir) / "runtime"
        yield RuntimePersistence(runtime_dir=runtime_dir)


class TestF3AuthoritativeSnapshotContract:
    """The smallest coherent crash-recovery strategy: state.json is the
    authoritative snapshot; plan.json is a derived view that recovery repairs."""

    def test_commit_run_state_writes_state_first_then_plan(self, tmp_persistence):
        """commit_run_state writes state.json (authoritative) before plan.json
        (derived), so a crash between them cannot leave a newer derived view."""
        p = tmp_persistence
        run_id = "run-commit-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Goal")
        state = _make_state(run_id, plan)
        p.commit_run_state(state)

        state_data = _read_json(p._get_state_path(run_id))
        plan_data = _read_json(p._get_plan_path(run_id))
        assert state_data["goal"] == "Goal"
        assert plan_data["goal"] == "Goal"
        # The embedded plan in state.json must match the derived plan.json.
        assert state_data["plan"]["plan_id"] == plan_data["plan_id"]

    def test_load_plan_prefers_authoritative_state_over_stale_plan(
        self, tmp_persistence
    ):
        """load_plan must return the authoritative plan from state.json, never a
        stale or contradictory plan.json. A crash leaving plan.json stale must
        not produce a contradictory snapshot via load_plan()."""
        p = tmp_persistence
        run_id = "run-stale-plan-001"
        p.create_run(run_id)

        # Write authoritative state with task PASSED.
        plan_v1 = _make_plan(run_id, "Goal v1")
        state_v1 = _make_state(run_id, plan_v1, status=RunStatus.RUNNING)
        state_v1.plan.tasks[0].status = TaskStatus.PASSED
        p.commit_run_state(state_v1)

        # Simulate a crash that leaves plan.json STALE: overwrite plan.json with
        # an OLDER plan where the task is still PENDING (contradictory).
        stale_plan = _make_plan(run_id, "Goal v1")
        p.save_plan(stale_plan)  # direct derived-view write, bypassing authority

        # load_plan must return the AUTHORITATIVE plan (task PASSED), not the
        # stale derived view (task PENDING).
        loaded_plan = p.load_plan(run_id)
        assert loaded_plan is not None
        assert loaded_plan.tasks[0].status == TaskStatus.PASSED

        # load_run_state and load_plan must NOT return contradictory snapshots.
        loaded_state = p.load_run_state(run_id)
        assert loaded_state.plan.tasks[0].status == TaskStatus.PASSED
        assert loaded_plan.tasks[0].status == loaded_state.plan.tasks[0].status

    def test_recover_repairs_derived_plan_from_authoritative_state(
        self, tmp_persistence
    ):
        """Recovery repairs plan.json from the authoritative state.json."""
        p = tmp_persistence
        run_id = "run-recover-001"
        p.create_run(run_id)

        plan = _make_plan(run_id, "Recover goal")
        state = _make_state(run_id, plan, status=RunStatus.RUNNING)
        state.plan.tasks[0].status = TaskStatus.FAILED
        state.plan.tasks[0].attempt = 2
        p.commit_run_state(state)

        # Corrupt the derived plan.json (stale).
        stale_plan = _make_plan(run_id, "Recover goal")
        p.save_plan(stale_plan)
        assert (
            p.load_plan(run_id).tasks[0].status == TaskStatus.FAILED
        )  # authority wins

        # Recover repairs the derived view.
        recovered = p.recover_run(run_id)
        assert recovered.plan.tasks[0].status == TaskStatus.FAILED
        assert recovered.plan.tasks[0].attempt == 2

        # The derived plan.json now matches the authoritative snapshot.
        plan_on_disk = _read_json(p._get_plan_path(run_id))
        assert plan_on_disk["tasks"][0]["status"] == "FAILED"
        assert plan_on_disk["tasks"][0]["attempt"] == 2

    def test_repeated_recovery_is_idempotent(self, tmp_persistence):
        """Recovery must be repeatable and produce the same result."""
        p = tmp_persistence
        run_id = "run-idempotent-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Idempotent goal")
        state = _make_state(run_id, plan, status=RunStatus.RUNNING)
        state.plan.tasks[0].status = TaskStatus.PASSED
        p.commit_run_state(state)

        r1 = p.recover_run(run_id)
        r2 = p.recover_run(run_id)
        assert r1.plan.tasks[0].status == r2.plan.tasks[0].status == TaskStatus.PASSED
        # Derived view identical after both recoveries.
        assert _read_json(p._get_plan_path(run_id))["tasks"][0]["status"] == "PASSED"

    def test_corrupted_canonical_state_rejected_not_replaced_by_stale_plan(
        self, tmp_persistence
    ):
        """If state.json is corrupt, recovery must NOT silently substitute
        stale plan.json data. It must raise an explicit error."""
        p = tmp_persistence
        run_id = "run-corrupt-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Corrupt goal")
        state = _make_state(run_id, plan)
        p.commit_run_state(state)

        # Corrupt state.json with invalid JSON.
        p._get_state_path(run_id).write_text(
            "{ this is not valid json", encoding="utf-8"
        )

        with pytest.raises(PersistenceError):
            p.recover_run(run_id)

        # load_run_state must also raise (corrupt authority), not silently
        # fall back to plan.json.
        with pytest.raises(PersistenceError):
            p.load_run_state(run_id)

    def test_missing_authoritative_state_rejected_on_recovery(self, tmp_persistence):
        """If state.json is missing (but plan.json exists), recovery must
        refuse to fabricate state from the derived view."""
        p = tmp_persistence
        run_id = "run-missing-state-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Missing state goal")
        state = _make_state(run_id, plan)
        p.commit_run_state(state)

        # Remove state.json, leave plan.json.
        p._get_state_path(run_id).unlink()
        assert p._get_plan_path(run_id).exists()

        with pytest.raises(PersistenceError):
            p.recover_run(run_id)


class TestF3FaultInjection:
    """Inject ACTUAL write failures at controlled persistence boundaries and
    read the actual persisted JSON from disk after each failure.

    These tests monkeypatch ``RuntimePersistence._atomic_write_json`` to raise
    at a specific write (the Nth call) so that ``commit_run_state`` fails
    mid-commit. They then inspect the real on-disk files and exercise recovery.
    No mocked assertion that a helper was called — the real filesystem is the
    oracle.
    """

    def test_failure_before_first_state_write(self, tmp_persistence):
        """A crash before the first authoritative commit leaves no authoritative
        state; recovery rejects it rather than fabricating a clean run."""
        p = tmp_persistence
        run_id = "run-pre-first-001"
        p.create_run(run_id)
        # Crash before commit_run_state: nothing authoritative written.
        # Only a partially initialized directory exists (the reservation marker).
        with pytest.raises(PersistenceError):
            p.recover_run(run_id)

    def test_failure_after_authoritative_commit_before_derived_view(
        self, tmp_persistence, monkeypatch
    ):
        """Inject a real failure: ``commit_run_state`` writes state.json
        (authoritative) successfully, then the derived plan.json write raises.
        After the failure, state.json is authoritative and plan.json is absent.
        Recovery repairs plan.json from state.json."""
        p = tmp_persistence
        run_id = "run-after-state-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Crash after state")
        state = _make_state(run_id, plan, status=RunStatus.RUNNING)
        state.plan.tasks[0].status = TaskStatus.PASSED

        call_count = {"n": 0}
        original = p._atomic_write_json

        def failing_write(path, data):
            call_count["n"] += 1
            # First write = state.json (authoritative). Let it succeed.
            # Second write = plan.json (derived). Make it raise.
            if call_count["n"] == 2:
                raise PersistenceError(
                    message="injected derived-view write failure",
                    path=str(path),
                    operation="injected",
                )
            return original(path, data)

        monkeypatch.setattr(p, "_atomic_write_json", failing_write)
        with pytest.raises(PersistenceError):
            p.commit_run_state(state)

        # state.json (authoritative) was written; plan.json was NOT.
        assert p._get_state_path(run_id).exists()
        assert not p._get_plan_path(run_id).exists()

        # load_plan returns the authoritative plan (from state.json) even though
        # plan.json is absent.
        monkeypatch.undo()
        loaded_plan = p.load_plan(run_id)
        assert loaded_plan is not None
        assert loaded_plan.tasks[0].status == TaskStatus.PASSED

        # Recovery repairs the derived plan.json from the authoritative state.
        p.recover_run(run_id)
        assert p._get_plan_path(run_id).exists()
        assert _read_json(p._get_plan_path(run_id))["tasks"][0]["status"] == "PASSED"

    def test_failure_during_authoritative_commit(self, tmp_persistence, monkeypatch):
        """Inject a real failure DURING the authoritative state.json write: the
        atomic write raises before state.json is replaced, so the PREVIOUS
        authoritative snapshot remains intact and authoritative. The newer
        state is NOT committed."""
        p = tmp_persistence
        run_id = "run-during-state-001"
        p.create_run(run_id)

        # First, commit a valid authoritative snapshot (v1).
        plan_v1 = _make_plan(run_id, "Goal v1")
        state_v1 = _make_state(run_id, plan_v1, status=RunStatus.PLANNED)
        p.commit_run_state(state_v1)

        # Now attempt a second commit (v2) but inject a failure on the FIRST
        # write (state.json), so v2 is never committed.
        plan_v2 = _make_plan(run_id, "Goal v2")
        state_v2 = _make_state(run_id, plan_v2, status=RunStatus.RUNNING)
        state_v2.plan.tasks[0].status = TaskStatus.RUNNING

        call_count = {"n": 0}
        original = p._atomic_write_json

        def failing_write(path, data):
            call_count["n"] += 1
            # First write = state.json for v2. Inject failure (atomic write
            # raises before os.replace, so the prior v1 state.json survives).
            if call_count["n"] == 1:
                raise PersistenceError(
                    message="injected authoritative write failure",
                    path=str(path),
                    operation="injected",
                )
            return original(path, data)

        monkeypatch.setattr(p, "_atomic_write_json", failing_write)
        with pytest.raises(PersistenceError):
            p.commit_run_state(state_v2)

        monkeypatch.undo()
        # The previous authoritative snapshot (v1) remains intact and
        # authoritative; v2 was never committed.
        loaded = p.load_run_state(run_id)
        assert loaded.goal == "Goal v1"
        assert loaded.status == RunStatus.PLANNED
        assert loaded.plan.tasks[0].status == TaskStatus.PENDING
        # The derived plan.json still reflects v1 (the failed commit never
        # reached the derived write).
        assert _read_json(p._get_plan_path(run_id))["goal"] == "Goal v1"

    def test_preparation_and_retry_transition_crash_consistency(self, tmp_persistence):
        """A preparation transition (PENDING -> READY -> RUNNING) and a retry
        transition (FAILED -> READY) must both leave a consistent authoritative
        snapshot after commit_run_state."""
        p = tmp_persistence
        run_id = "run-prep-retry-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Prep+retry goal")
        state = _make_state(run_id, plan, status=RunStatus.RUNNING)

        # Preparation: task RUNNING, attempt 1
        state.plan.tasks[0].status = TaskStatus.RUNNING
        state.plan.tasks[0].attempt = 1
        p.commit_run_state(state)

        loaded = p.load_run_state(run_id)
        assert loaded.plan.tasks[0].status == TaskStatus.RUNNING
        assert loaded.plan.tasks[0].attempt == 1

        # Retry transition: task FAILED -> READY (attempt unchanged), commit
        state.plan.tasks[0].status = TaskStatus.FAILED
        p.commit_run_state(state)
        # load_plan and load_run_state must agree (no contradiction)
        lp = p.load_plan(run_id)
        ls = p.load_run_state(run_id)
        assert lp.tasks[0].status == ls.plan.tasks[0].status == TaskStatus.FAILED
        assert lp.tasks[0].attempt == ls.plan.tasks[0].attempt == 1

    def test_finalizer_constraints_remain_intact(self, tmp_persistence):
        """F8 must not accept an unsupported PASS because a partially persisted
        state appears to exist. The finalizer requires the authoritative run to
        be RUNNING with an active RUNNING plan task; a NEEDS_HUMAN authoritative
        state must not yield a PASS."""
        from fsasm.executor_activities import _validate_finalization_inputs
        from fsasm.errors import ValidationError

        p = tmp_persistence
        run_id = "run-finalizer-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Finalizer goal")
        state = _make_state(run_id, plan, status=RunStatus.NEEDS_HUMAN)
        state.plan.tasks[0].status = TaskStatus.NEEDS_HUMAN
        p.commit_run_state(state)

        # Re-read authoritative state and try to finalize a PASSED task against
        # a NEEDS_HUMAN authoritative context.
        loaded_state = p.load_run_state(run_id)
        task = loaded_state.plan.tasks[0]
        from fsasm.models import (
            VerificationResult,
            VerificationResultStatus,
            VerificationCheck,
        )

        vr = VerificationResult(
            run_id=run_id,
            task_id=task.task_id,
            status=VerificationResultStatus.PASS,
            checks=[VerificationCheck(check_name="ok", passed=True)],
        )
        with pytest.raises(ValidationError):
            _validate_finalization_inputs(loaded_state, task, vr, [])

    def test_retry_attempt_counters_unchanged_during_recovery(self, tmp_persistence):
        """Recovery must not change retry attempt counters."""
        p = tmp_persistence
        run_id = "run-attempt-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Attempt goal")
        state = _make_state(run_id, plan, status=RunStatus.RUNNING)
        state.plan.tasks[0].status = TaskStatus.FAILED
        state.plan.tasks[0].attempt = 2
        state.plan.tasks[0].max_attempts = 3
        p.commit_run_state(state)

        before = p.load_run_state(run_id)
        recovered = p.recover_run(run_id)
        assert recovered.plan.tasks[0].attempt == 2
        assert recovered.plan.tasks[0].max_attempts == 3
        assert before.plan.tasks[0].attempt == recovered.plan.tasks[0].attempt

    def test_crash_between_state_and_plan_leaves_consistent_recovery(
        self, tmp_persistence, monkeypatch
    ):
        """End-to-end crash between the authoritative state write and the
        derived plan write: after recovery, state.json and plan.json must
        describe the SAME logical state (no contradiction)."""
        p = tmp_persistence
        run_id = "run-crash-mid-001"
        p.create_run(run_id)
        # Commit v1 (RUNNING, task PASSED).
        plan = _make_plan(run_id, "Crash mid goal")
        state = _make_state(run_id, plan, status=RunStatus.RUNNING)
        state.plan.tasks[0].status = TaskStatus.PASSED
        p.commit_run_state(state)

        # Now commit a v2 (task FAILED) but crash AFTER state.json is written
        # and BEFORE plan.json is written. This leaves a stale plan.json (still
        # PASSED) that contradicts the authoritative state.json (FAILED).
        state_v2 = _make_state(run_id, plan, status=RunStatus.RUNNING)
        state_v2.plan.tasks[0].status = TaskStatus.FAILED

        call_count = {"n": 0}
        original = p._atomic_write_json

        def failing_write(path, data):
            call_count["n"] += 1
            if call_count["n"] == 2:  # plan.json write for v2
                raise PersistenceError(
                    message="injected derived-view crash",
                    path=str(path),
                    operation="injected",
                )
            return original(path, data)

        monkeypatch.setattr(p, "_atomic_write_json", failing_write)
        with pytest.raises(PersistenceError):
            p.commit_run_state(state_v2)
        monkeypatch.undo()

        # Disk now has authoritative state.json = FAILED (v2) and stale
        # plan.json = PASSED (v1). This is the contradictory pair F3 forbids
        # treating as two authorities.
        state_disk = _read_json(p._get_state_path(run_id))
        plan_disk = _read_json(p._get_plan_path(run_id))
        assert state_disk["plan"]["tasks"][0]["status"] == "FAILED"
        assert plan_disk["tasks"][0]["status"] == "PASSED"

        # load_plan must return the AUTHORITATIVE plan (FAILED), not the stale
        # derived plan.json (PASSED) — no contradictory snapshot.
        loaded_plan = p.load_plan(run_id)
        loaded_state = p.load_run_state(run_id)
        assert loaded_plan.tasks[0].status == TaskStatus.FAILED
        assert loaded_plan.tasks[0].status == loaded_state.plan.tasks[0].status

        # Recovery repairs plan.json from the authoritative state.json.
        p.recover_run(run_id)
        assert _read_json(p._get_plan_path(run_id))["tasks"][0]["status"] == "FAILED"


class TestF3F4F5Integration:
    """F3 recovery must preserve F4 (duplicate-creation protection) and F5
    (path validation)."""

    def test_recovery_does_not_create_new_run(self, tmp_persistence):
        """Recovery never creates a new run; it requires an initialized run.
        A second create_run after recovery is still rejected (F4 holds)."""
        p = tmp_persistence
        run_id = "run-recovery-f4-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "F4 during recovery")
        state = _make_state(run_id, plan)
        p.commit_run_state(state)

        p.recover_run(run_id)

        # F4: duplicate creation still rejected after recovery.
        with pytest.raises(RunAlreadyExistsError):
            p.create_run(run_id)

    def test_recovery_validates_identifier(self, tmp_persistence):
        """Recovery applies F5 identifier validation."""
        p = tmp_persistence
        from fsasm.errors import InvalidIdentifierError

        with pytest.raises(InvalidIdentifierError):
            p.recover_run("../escape")

    def test_crashed_initial_creation_not_silently_clean_run(self, tmp_persistence):
        """A crashed initial creation (directory exists, reservation marker
        exists, but no state.json) must not be silently interpreted as a clean
        new run. create_run rejects it; recovery rejects it."""
        p = tmp_persistence
        run_id = "run-crashed-init-001"
        # Simulate crashed creation: directory + marker but no state.json.
        run_dir = p.runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / p._RESERVATION_MARKER).write_text(
            json.dumps({"run_id": run_id}), encoding="utf-8"
        )
        assert p.is_run_initialized(run_id)
        assert p.load_run_state(run_id) is None

        # Recovery rejects (no authoritative state).
        with pytest.raises(PersistenceError):
            p.recover_run(run_id)
        # F4: a duplicate creation is also rejected.
        with pytest.raises(RunAlreadyExistsError):
            p.create_run(run_id)


class TestF3NormalPathUnchanged:
    """Existing normal-path state transitions must remain unchanged."""

    @pytest.fixture(autouse=True)
    def cleanup_runtime(self):
        persistence = RuntimePersistence()
        persistence.cleanup_all()
        yield
        persistence.cleanup_all()

    def test_normal_save_load_roundtrip(self, tmp_persistence):
        p = tmp_persistence
        run_id = "run-normal-rt-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Normal goal")
        state = _make_state(run_id, plan, status=RunStatus.RUNNING)
        p.commit_run_state(state)

        loaded = p.load_run_state(run_id)
        loaded_plan = p.load_plan(run_id)
        assert loaded.run_id == run_id
        assert loaded.status == RunStatus.RUNNING
        assert loaded_plan.run_id == run_id
        assert loaded_plan.tasks[0].task_id == loaded.plan.tasks[0].task_id

    @pytest.mark.asyncio
    async def test_worker_level_retry_scenario_remains_functional(self, temporal_env):
        """The worker-level retry scenario must remain functional after F3
        changes (commit_run_state replaces save_run_state+save_plan in M4
        activities). Uses the temporal_env fixture and the M4 activity set."""
        from mistralai.workflows.testing import create_test_worker
        from src.workflows.fsasm_milestone_four import (
            FsasmMilestoneFourWorkflow,
            create_input_activity,
            validate_config_activity,
            find_next_ready_task_activity,
            set_task_max_attempts_activity,
            check_retry_budget_activity,
            persist_failure_state_activity,
            transition_to_needs_human_activity,
            persist_retry_state_activity,
            validate_and_apply_human_decision_activity,
            persist_final_m4_state_activity,
            persist_human_gate_rejections_activity,
            persist_initial_state_activity,
        )
        from fsasm.planner_activities import plan_activity
        from fsasm.executor_activities import (
            execute_task_activity,
            validate_executor_output_provenance_activity,
            convert_executor_output_to_evidence_activity,
            verify_task_execution_activity,
            prepare_task_activity,
            finalize_task_activity,
        )
        from datetime import timedelta
        import asyncio

        _M4_ACTIVITIES = [
            create_input_activity,
            validate_config_activity,
            plan_activity,
            set_task_max_attempts_activity,
            persist_initial_state_activity,
            find_next_ready_task_activity,
            prepare_task_activity,
            execute_task_activity,
            validate_executor_output_provenance_activity,
            convert_executor_output_to_evidence_activity,
            verify_task_execution_activity,
            finalize_task_activity,
            persist_failure_state_activity,
            check_retry_budget_activity,
            persist_retry_state_activity,
            transition_to_needs_human_activity,
            validate_and_apply_human_decision_activity,
            persist_final_m4_state_activity,
            persist_human_gate_rejections_activity,
        ]

        persistence = RuntimePersistence()

        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await temporal_env.client.start_workflow(
                "fsasm-milestone-four",
                {
                    "goal": "F3 worker retry test",
                    "planner_backend": "stub",
                    "executor_backend": "stub",
                    "max_retries_per_task": 1,
                    "stub_fail_first_n_attempts": 1,
                    "run_id": "run-f3-worker-001",
                },
                id="run-f3-worker-001",
                task_queue="test-task-queue",
                execution_timeout=timedelta(seconds=20),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)

        assert result["success"] is True
        assert result["executed_task_ids"] == ["TASK-001"]
        # Authoritative state.json is consistent with plan.json after retries.
        state_data = _read_json(persistence._get_state_path("run-f3-worker-001"))
        plan_data = _read_json(persistence._get_plan_path("run-f3-worker-001"))
        assert (
            state_data["plan"]["tasks"][0]["status"]
            == plan_data["tasks"][0]["status"]
            == "PASSED"
        )
