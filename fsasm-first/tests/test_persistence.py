"""Tests for FS-ASM persistence layer."""

import tempfile
from pathlib import Path

import pytest

from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    GoalInput,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationCheck,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence, DEFAULT_RUNTIME_DIR


class TestRuntimePersistence:
    """Tests for RuntimePersistence class."""

    @pytest.fixture
    def temp_persistence(self) -> RuntimePersistence:
        """Create a temporary persistence instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            yield RuntimePersistence(runtime_dir=runtime_dir)

    @pytest.fixture
    def sample_plan(self) -> Plan:
        """Create a sample plan for testing."""
        tasks = [
            ChildTask(
                task_id=f"TASK-{i}",
                sequence=i,
                title=f"Task {i}",
                description=f"Description {i}",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            )
            for i in range(1, 4)
        ]
        return Plan(
            plan_id="plan-test-123",
            run_id="run-test-123",
            goal="Test goal",
            tasks=tasks,
        )

    @pytest.fixture
    def sample_state(self, sample_plan: Plan) -> RunState:
        """Create a sample run state for testing."""
        return RunState(
            run_id=sample_plan.run_id,
            goal=sample_plan.goal,
            status=RunStatus.PLANNED,
            plan=sample_plan,
        )

    @pytest.fixture
    def sample_evidence(self) -> EvidenceRecord:
        """Create a sample evidence record for testing."""
        return EvidenceRecord(
            evidence_id="evidence-test-123",
            run_id="run-test-123",
            task_id="TASK-1",
            kind="test_result",
            source="pytest",
            payload={"passed": True, "tests": 5},
        )

    @pytest.fixture
    def sample_verification_result(self) -> VerificationResult:
        """Create a sample verification result for testing."""
        return VerificationResult(
            run_id="run-test-123",
            task_id=None,
            status=VerificationResultStatus.PASS,
            checks=[
                VerificationCheck(
                    check_name="test_check",
                    passed=True,
                    message="All good",
                )
            ],
            message="Verification passed",
        )

    # =========================================================================
    # SAVE OPERATIONS
    # =========================================================================

    def test_save_and_load_plan(
        self, temp_persistence: RuntimePersistence, sample_plan: Plan
    ) -> None:
        """Test saving and loading a plan."""
        temp_persistence.save_plan(sample_plan)
        loaded = temp_persistence.load_plan(sample_plan.run_id)
        assert loaded is not None
        assert loaded.plan_id == sample_plan.plan_id
        assert loaded.run_id == sample_plan.run_id
        assert len(loaded.tasks) == 3

    def test_save_and_load_run_state(
        self, temp_persistence: RuntimePersistence, sample_state: RunState
    ) -> None:
        """Test saving and loading run state."""
        temp_persistence.save_run_state(sample_state)
        loaded = temp_persistence.load_run_state(sample_state.run_id)
        assert loaded is not None
        assert loaded.run_id == sample_state.run_id
        assert loaded.goal == sample_state.goal
        assert loaded.status == sample_state.status

    def test_save_and_load_evidence(
        self, temp_persistence: RuntimePersistence, sample_evidence: EvidenceRecord
    ) -> None:
        """Test saving and loading evidence."""
        temp_persistence.save_evidence(sample_evidence)
        loaded = temp_persistence.load_evidence(
            sample_evidence.run_id, sample_evidence.evidence_id
        )
        assert loaded is not None
        assert loaded.evidence_id == sample_evidence.evidence_id
        assert loaded.run_id == sample_evidence.run_id
        assert loaded.kind == sample_evidence.kind

    def test_save_verification_result_to_log(
        self,
        temp_persistence: RuntimePersistence,
        sample_verification_result: VerificationResult,
    ) -> None:
        """Test saving verification result to run log."""
        temp_persistence.save_verification_result(sample_verification_result)
        log_entries = temp_persistence.load_run_log(sample_verification_result.run_id)
        assert len(log_entries) > 0
        # Find the verification result entry
        found = False
        for entry in log_entries:
            if entry.get("status") == VerificationResultStatus.PASS.value:
                found = True
                break
        assert found

    def test_save_run_log_entry(self, temp_persistence: RuntimePersistence) -> None:
        """Test saving a generic run log entry."""
        run_id = "run-log-test"
        entry = {"event": "test_event", "data": "test_data"}
        temp_persistence.save_run_log_entry(run_id, entry)
        log_entries = temp_persistence.load_run_log(run_id)
        assert len(log_entries) == 1
        assert log_entries[0]["event"] == "test_event"

    # =========================================================================
    # LOAD OPERATIONS
    # =========================================================================

    def test_load_nonexistent_plan(self, temp_persistence: RuntimePersistence) -> None:
        """Test loading a non-existent plan returns None."""
        loaded = temp_persistence.load_plan("nonexistent")
        assert loaded is None

    def test_load_nonexistent_state(self, temp_persistence: RuntimePersistence) -> None:
        """Test loading a non-existent state returns None."""
        loaded = temp_persistence.load_run_state("nonexistent")
        assert loaded is None

    def test_load_nonexistent_evidence(
        self, temp_persistence: RuntimePersistence
    ) -> None:
        """Test loading a non-existent evidence returns None."""
        loaded = temp_persistence.load_evidence("run-123", "evidence-123")
        assert loaded is None

    def test_load_all_evidence(
        self, temp_persistence: RuntimePersistence, sample_evidence: EvidenceRecord
    ) -> None:
        """Test loading all evidence for a run."""
        # Save multiple evidence records
        for i in range(3):
            evidence = EvidenceRecord(
                evidence_id=f"evidence-{i}",
                run_id=sample_evidence.run_id,
                kind="test",
                source="test",
                payload={"index": i},
            )
            temp_persistence.save_evidence(evidence)

        all_evidence = temp_persistence.load_all_evidence(sample_evidence.run_id)
        assert len(all_evidence) == 3

    def test_load_empty_run_log(self, temp_persistence: RuntimePersistence) -> None:
        """Test loading an empty run log returns empty list."""
        log = temp_persistence.load_run_log("nonexistent")
        assert log == []

    # =========================================================================
    # UTILITY OPERATIONS
    # =========================================================================

    def test_run_exists(
        self, temp_persistence: RuntimePersistence, sample_state: RunState
    ) -> None:
        """Test run_exists check."""
        assert temp_persistence.run_exists(sample_state.run_id) is False
        temp_persistence.save_run_state(sample_state)
        assert temp_persistence.run_exists(sample_state.run_id) is True

    def test_get_all_run_ids(
        self, temp_persistence: RuntimePersistence, sample_state: RunState
    ) -> None:
        """Test getting all run IDs."""
        # Save multiple states
        for i in range(3):
            state = RunState(
                run_id=f"run-{i}",
                goal=f"Goal {i}",
            )
            temp_persistence.save_run_state(state)

        all_ids = temp_persistence.get_all_run_ids()
        assert len(all_ids) == 3
        assert "run-0" in all_ids
        assert "run-1" in all_ids
        assert "run-2" in all_ids

    def test_cleanup_run(
        self, temp_persistence: RuntimePersistence, sample_state: RunState
    ) -> None:
        """Test cleaning up a specific run."""
        temp_persistence.save_run_state(sample_state)
        assert temp_persistence.run_exists(sample_state.run_id) is True
        temp_persistence.cleanup_run(sample_state.run_id)
        assert temp_persistence.run_exists(sample_state.run_id) is False

    def test_cleanup_all(
        self, temp_persistence: RuntimePersistence, sample_state: RunState
    ) -> None:
        """Test cleaning up all runs."""
        temp_persistence.save_run_state(sample_state)
        assert temp_persistence.run_exists(sample_state.run_id) is True
        temp_persistence.cleanup_all()
        assert temp_persistence.run_exists(sample_state.run_id) is False

    # =========================================================================
    # ATOMIC WRITE TESTS
    # =========================================================================

    def test_atomic_write_plan(
        self, temp_persistence: RuntimePersistence, sample_plan: Plan
    ) -> None:
        """Test that plan writes are atomic."""
        temp_persistence.save_plan(sample_plan)
        plan_path = temp_persistence._get_plan_path(sample_plan.run_id)
        assert plan_path.exists()
        # Verify no .tmp files left behind
        assert not any(p.suffix == ".tmp" for p in plan_path.parent.glob("*"))

    def test_atomic_write_state(
        self, temp_persistence: RuntimePersistence, sample_state: RunState
    ) -> None:
        """Test that state writes are atomic."""
        temp_persistence.save_run_state(sample_state)
        state_path = temp_persistence._get_state_path(sample_state.run_id)
        assert state_path.exists()
        # Verify no .tmp files left behind
        assert not any(p.suffix == ".tmp" for p in state_path.parent.glob("*"))

    def test_atomic_write_evidence(
        self, temp_persistence: RuntimePersistence, sample_evidence: EvidenceRecord
    ) -> None:
        """Test that evidence writes are atomic."""
        temp_persistence.save_evidence(sample_evidence)
        evidence_dir = temp_persistence._get_evidence_dir(sample_evidence.run_id)
        evidence_path = evidence_dir / f"{sample_evidence.evidence_id}.json"
        assert evidence_path.exists()
        # Verify no .tmp files left behind
        assert not any(p.suffix == ".tmp" for p in evidence_path.parent.glob("*"))


class TestPersistencePaths:
    """Tests for persistence path calculations."""

    @pytest.fixture
    def persistence(self) -> RuntimePersistence:
        """Create a persistence instance with default paths."""
        return RuntimePersistence()

    def test_get_run_dir(self, persistence: RuntimePersistence) -> None:
        """Test run directory path."""
        run_dir = persistence._get_run_dir("run-123")
        assert run_dir == DEFAULT_RUNTIME_DIR / "runs" / "run-123"

    def test_get_state_path(self, persistence: RuntimePersistence) -> None:
        """Test state file path."""
        state_path = persistence._get_state_path("run-123")
        assert state_path == DEFAULT_RUNTIME_DIR / "runs" / "run-123" / "state.json"

    def test_get_plan_path(self, persistence: RuntimePersistence) -> None:
        """Test plan file path."""
        plan_path = persistence._get_plan_path("run-123")
        assert plan_path == DEFAULT_RUNTIME_DIR / "runs" / "run-123" / "plan.json"

    def test_get_evidence_dir(self, persistence: RuntimePersistence) -> None:
        """Test evidence directory path."""
        evidence_dir = persistence._get_evidence_dir("run-123")
        assert evidence_dir == DEFAULT_RUNTIME_DIR / "runs" / "run-123" / "evidence"

    def test_get_run_log_path(self, persistence: RuntimePersistence) -> None:
        """Test run log file path."""
        log_path = persistence._get_run_log_path("run-123")
        assert log_path == DEFAULT_RUNTIME_DIR / "runs" / "run-123" / "run.log.jsonl"


class TestGoalInputPersistence:
    """Tests for GoalInput persistence."""

    def test_save_goal_input_without_run_id(self) -> None:
        """Test saving GoalInput without run_id generates one."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = RuntimePersistence(runtime_dir=Path(tmpdir) / "runtime")
            input = GoalInput(goal="Test goal")
            result = persistence.save_goal_input(input)
            assert result.run_id is not None
            assert len(result.run_id) > 0

    def test_save_goal_input_with_run_id(self) -> None:
        """Test saving GoalInput with existing run_id preserves it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = RuntimePersistence(runtime_dir=Path(tmpdir) / "runtime")
            input = GoalInput(goal="Test goal", run_id="custom-run-id")
            result = persistence.save_goal_input(input)
            assert result.run_id == "custom-run-id"
