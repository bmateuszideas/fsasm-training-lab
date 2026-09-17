"""F4 — Run identity and safe new-run creation.

Separates *creating* a new run from *accessing* or *resuming* an existing run.

Pre-fix (before ``create_run``): the same valid ``run_id`` could silently
initialize two different runs, overwriting existing state, plan, evidence and
log history. These tests reproduce that defect against the persistence
boundary and assert the corrected identity contract.

The authoritative run-creation boundary is ``RuntimePersistence.create_run``,
which atomically reserves the run directory using exclusive creation. M1-M4
creation activities call this boundary before their first ``save_plan`` /
``save_run_state``.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from fsasm.errors import InvalidIdentifierError, RunAlreadyExistsError
from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence


def _make_plan(run_id: str, goal: str) -> Plan:
    tasks = [
        ChildTask(
            task_id=f"TASK-{i}",
            sequence=i,
            title=f"Task {i}",
            description=f"Description {i}",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
        )
        for i in range(1, 4)
    ]
    return Plan(plan_id=f"plan-{run_id}", run_id=run_id, goal=goal, tasks=tasks)


def _make_state(plan: Plan) -> RunState:
    return RunState(
        run_id=plan.run_id,
        goal=plan.goal,
        status=RunStatus.PLANNED,
        plan=plan,
    )


@pytest.fixture
def tmp_persistence() -> RuntimePersistence:
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime_dir = Path(tmpdir) / "runtime"
        yield RuntimePersistence(runtime_dir=runtime_dir)


class TestF4PreFixReproduction:
    """Reproduce the pre-F4 silent-overwrite defect.

    Before ``create_run`` existed, calling ``save_plan`` + ``save_run_state``
    twice with the same ``run_id`` (but a different goal) silently overwrote the
    first run's authoritative state and plan, mixing unrelated event histories.
    """

    @pytest.mark.asyncio
    async def test_pre_fix_silent_overwrite_reproduction(self, tmp_persistence):
        """Reproduce: same run_id, different goal -> existing state overwritten.

        This documents the pre-F4 defect mechanism. Under the corrected contract
        the second creation must be rejected by ``create_run`` before any write,
        leaving the first run's state, plan, evidence and log intact.
        """
        p = tmp_persistence
        run_id = "run-reuse-001"

        # First creation: goal A
        p.create_run(run_id)
        plan_a = _make_plan(run_id, "Goal A")
        state_a = _make_state(plan_a)
        p.save_plan(plan_a)
        p.save_run_state(state_a)
        p.save_evidence(
            EvidenceRecord(
                evidence_id=f"evidence-proposal-{run_id}",
                run_id=run_id,
                task_id=None,
                kind="planner_proposal",
                source="test",
                payload={"goal": "Goal A"},
            )
        )

        # Attempt a second creation with the SAME run_id but a different goal.
        # Under the corrected contract this must raise RunAlreadyExistsError.
        with pytest.raises(RunAlreadyExistsError) as exc:
            p.create_run(run_id)
        assert exc.value.run_id == run_id

        # Existing state, plan, evidence must remain unchanged after rejection.
        loaded_state = p.load_run_state(run_id)
        loaded_plan = p.load_plan(run_id)
        assert loaded_state is not None
        assert loaded_state.goal == "Goal A"
        assert loaded_plan is not None
        assert loaded_plan.goal == "Goal A"
        evidence = p.load_all_evidence(run_id)
        assert len(evidence) == 1
        assert evidence[0].payload["goal"] == "Goal A"


class TestF4SafeNewRunCreation:
    """Authoritative run-identity contract via ``create_run``."""

    def test_fresh_generated_id_accepted(self, tmp_persistence):
        p = tmp_persistence
        run_id = "run-generated-uuid-1234"
        run_dir = p.create_run(run_id)
        assert run_dir.exists()
        assert p.is_run_initialized(run_id)
        assert p.run_exists(run_id)

    def test_fresh_explicit_id_accepted(self, tmp_persistence):
        p = tmp_persistence
        run_id = "run-explicit-abc"
        p.create_run(run_id)
        assert p.is_run_initialized(run_id)

    def test_duplicate_id_different_goal_rejected(self, tmp_persistence):
        p = tmp_persistence
        run_id = "run-dup-001"
        p.create_run(run_id)
        plan_a = _make_plan(run_id, "Goal A")
        p.save_plan(plan_a)
        p.save_run_state(_make_state(plan_a))

        with pytest.raises(RunAlreadyExistsError):
            p.create_run(run_id)

        # State/plan preserved
        assert p.load_plan(run_id).goal == "Goal A"
        assert p.load_run_state(run_id).goal == "Goal A"

    def test_duplicate_id_same_goal_rejected(self, tmp_persistence):
        """A duplicate request must not silently create another logical run
        merely because its goal matches (idempotency: creation is not
        idempotent; a second creation is always rejected regardless of goal)."""
        p = tmp_persistence
        run_id = "run-dup-same-goal"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Goal X")
        p.save_plan(plan)
        p.save_run_state(_make_state(plan))

        with pytest.raises(RunAlreadyExistsError):
            p.create_run(run_id)

        assert p.load_plan(run_id).goal == "Goal X"

    def test_existing_state_plan_evidence_log_preserved_after_rejection(
        self, tmp_persistence
    ):
        p = tmp_persistence
        run_id = "run-preserve-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Preserve goal")
        state = _make_state(plan)
        p.save_plan(plan)
        p.save_run_state(state)
        p.save_evidence(
            EvidenceRecord(
                evidence_id="evidence-keep-1",
                run_id=run_id,
                task_id="TASK-1",
                kind="test_result",
                source="test",
                payload={"kept": True},
            )
        )
        p.save_run_log_entry(run_id, {"event": "run_created", "run_id": run_id})

        with pytest.raises(RunAlreadyExistsError):
            p.create_run(run_id)

        assert p.load_plan(run_id).goal == "Preserve goal"
        assert p.load_run_state(run_id).status == RunStatus.PLANNED
        assert len(p.load_all_evidence(run_id)) == 1
        log = p.load_run_log(run_id)
        assert len(log) == 1
        assert log[0]["event"] == "run_created"

    def test_partially_initialized_directory_not_silently_reused(self, tmp_persistence):
        """A directory that exists but lacks the reservation marker is a
        partially initialized or foreign directory, not a legitimately created
        run. ``create_run`` must still reject it (the directory exists), and
        ``is_run_initialized`` must return False."""
        p = tmp_persistence
        run_id = "run-partial-001"
        # Manually create a directory WITHOUT the reservation marker,
        # simulating a crashed/partial initialization.
        run_dir = p.runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text('{"incomplete": true}')

        # It is NOT a legitimately initialized run.
        assert not p.is_run_initialized(run_id)
        # create_run rejects it because the directory already exists.
        with pytest.raises(RunAlreadyExistsError):
            p.create_run(run_id)
        # The partially initialized content is not deleted by the rejection.
        assert (run_dir / "state.json").exists()

    def test_concurrent_local_creation_only_one_succeeds(self, tmp_persistence):
        """Two concurrent local creation attempts for the same ID cannot both
        succeed. ``mkdir(exist_ok=False)`` is the race-free exclusive boundary."""
        p = tmp_persistence
        run_id = "run-race-001"

        results = []

        def attempt():
            try:
                p.create_run(run_id)
                results.append("ok")
            except RunAlreadyExistsError:
                results.append("rejected")

        # Run two attempts concurrently in threads (mkdir is atomic locally).
        threads = [asyncio.to_thread(attempt) for _ in range(2)]

        async def run_threads():
            await asyncio.gather(*threads)

        asyncio.run(run_threads())

        assert results.count("ok") == 1
        assert results.count("rejected") == 1

    def test_normal_internal_persistence_continues_working(self, tmp_persistence):
        """``create_run`` is the creation boundary only. Subsequent normal
        internal writes (save_plan/save_run_state) to an established run must
        continue to work and are NOT rejected."""
        p = tmp_persistence
        run_id = "run-normal-001"
        p.create_run(run_id)

        # Multiple legitimate updates
        for attempt in range(3):
            plan = _make_plan(run_id, f"Goal update {attempt}")
            state = _make_state(plan)
            state.status = RunStatus.PLANNED
            p.save_plan(plan)
            p.save_run_state(state)

        assert p.load_run_state(run_id).goal == "Goal update 2"
        assert p.load_plan(run_id).goal == "Goal update 2"

    def test_unsafe_identifier_rejected_by_create_run(self, tmp_persistence):
        """F5 identifier validation remains effective at the creation boundary."""
        p = tmp_persistence
        with pytest.raises(InvalidIdentifierError):
            p.create_run("../escape-attempt")
        with pytest.raises(InvalidIdentifierError):
            p.create_run("run/with/slash")

    def test_resume_and_create_are_separate_concepts(self, tmp_persistence):
        """An existing run cannot be implicitly reinitialized. Resume is a
        distinct concept; if full resume is unsupported, the system rejects an
        unsupported resume rather than quietly starting over. Here we verify
        that loading an existing run does not re-run creation, and that a second
        ``create_run`` is rejected."""
        p = tmp_persistence
        run_id = "run-resume-001"
        p.create_run(run_id)
        plan = _make_plan(run_id, "Resume goal")
        p.save_plan(plan)
        p.save_run_state(_make_state(plan))

        # Loading is access, not creation.
        loaded = p.load_run_state(run_id)
        assert loaded is not None
        assert loaded.goal == "Resume goal"

        # A second creation (which would be an implicit resume-as-new) is rejected.
        with pytest.raises(RunAlreadyExistsError):
            p.create_run(run_id)


class TestF4WorkflowCreationPaths:
    """M1-M4 initial creation paths behave consistently: each calls
    ``create_run`` before its first save, so a duplicate run_id is rejected at
    the creation activity boundary."""

    @pytest.mark.asyncio
    async def test_m3_creation_activity_rejects_duplicate(self):
        from src.workflows import fsasm_milestone_three as m3
        from fsasm.models import ExecutorBackend, PlannerBackend

        persistence = RuntimePersistence()
        persistence.cleanup_all()

        input1 = m3.WorkflowInput(
            goal="Goal A",
            run_id="run-m3-dup",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
        )
        result1 = await m3.FsasmMilestoneThreeWorkflow().run(input1)
        assert result1["run_id"] == "run-m3-dup"

        # Second run with same run_id must fail at the creation activity.
        input2 = m3.WorkflowInput(
            goal="Goal B",
            run_id="run-m3-dup",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
        )
        with pytest.raises(RunAlreadyExistsError):
            await m3.FsasmMilestoneThreeWorkflow().run(input2)

        # First run's state preserved
        loaded = persistence.load_run_state("run-m3-dup")
        assert loaded is not None
        assert loaded.goal == "Goal A"

    @pytest.mark.asyncio
    async def test_m2_creation_activity_rejects_duplicate(self):
        from src.workflows import fsasm_milestone_two as m2
        from fsasm.models import PlannerBackend

        persistence = RuntimePersistence()
        persistence.cleanup_all()

        input1 = m2.WorkflowInput(
            goal="Goal A",
            run_id="run-m2-dup",
            planner_backend=PlannerBackend.STUB,
        )
        result1 = await m2.FsasmMilestoneTwoWorkflow().run(input1)
        assert result1["run_id"] == "run-m2-dup"

        input2 = m2.WorkflowInput(
            goal="Goal B",
            run_id="run-m2-dup",
            planner_backend=PlannerBackend.STUB,
        )
        with pytest.raises(RunAlreadyExistsError):
            await m2.FsasmMilestoneTwoWorkflow().run(input2)

        loaded = persistence.load_run_state("run-m2-dup")
        assert loaded is not None
        assert loaded.goal == "Goal A"

    @pytest.mark.asyncio
    async def test_m1_creation_activity_rejects_duplicate(self):
        from src.workflows import fsasm_milestone_one as m1

        persistence = RuntimePersistence()
        persistence.cleanup_all()

        input1 = m1.WorkflowInput(goal="Goal A", run_id="run-m1-dup")
        result1 = await m1.FsasmMilestoneOneWorkflow().run(input1)
        assert result1["run_id"] == "run-m1-dup"

        input2 = m1.WorkflowInput(goal="Goal B", run_id="run-m1-dup")
        with pytest.raises(RunAlreadyExistsError):
            await m1.FsasmMilestoneOneWorkflow().run(input2)

        loaded = persistence.load_run_state("run-m1-dup")
        assert loaded is not None
        assert loaded.goal == "Goal A"
