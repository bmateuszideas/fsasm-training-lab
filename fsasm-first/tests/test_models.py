"""Tests for FS-ASM domain models."""

import pytest
from uuid import uuid4

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


class TestGoalInput:
    """Tests for GoalInput model."""

    def test_goal_input_valid(self) -> None:
        """Test valid GoalInput creation."""
        input = GoalInput(goal="Test goal")
        assert input.goal == "Test goal"
        assert input.run_id is None

    def test_goal_input_with_run_id(self) -> None:
        """Test GoalInput with explicit run_id."""
        run_id = str(uuid4())
        input = GoalInput(goal="Test goal", run_id=run_id)
        assert input.run_id == run_id

    def test_goal_input_blank_goal_rejected(self) -> None:
        """Test that blank goal is rejected."""
        with pytest.raises(ValueError):
            GoalInput(goal="")

    def test_goal_input_whitespace_goal_rejected(self) -> None:
        """Test that whitespace-only goal is rejected."""
        with pytest.raises(ValueError):
            GoalInput(goal="   ")

    def test_goal_input_generate_run_id(self) -> None:
        """Test run_id generation."""
        input = GoalInput(goal="Test goal")
        generated = input.generate_run_id()
        assert generated is not None
        assert len(generated) > 0


class TestVerificationSpec:
    """Tests for VerificationSpec model."""

    def test_verification_spec_valid(self) -> None:
        """Test valid VerificationSpec creation."""
        spec = VerificationSpec(
            type=VerificationType.SCHEMA,
            expected="some condition",
        )
        assert spec.type == VerificationType.SCHEMA
        assert spec.expected == "some condition"

    def test_verification_spec_all_types(self) -> None:
        """Test all verification types."""
        for vtype in VerificationType:
            spec = VerificationSpec(type=vtype, expected="test")
            assert spec.type == vtype


class TestVerificationCheck:
    """Tests for VerificationCheck model."""

    def test_verification_check_valid(self) -> None:
        """Test valid VerificationCheck creation."""
        check = VerificationCheck(
            check_name="test_check",
            passed=True,
            message="All good",
        )
        assert check.check_name == "test_check"
        assert check.passed is True
        assert check.message == "All good"


class TestVerificationResult:
    """Tests for VerificationResult model."""

    def test_verification_result_pass(self) -> None:
        """Test PASS VerificationResult."""
        result = VerificationResult(
            run_id="run-123",
            task_id=None,
            status=VerificationResultStatus.PASS,
            checks=[],
            message="All checks passed",
        )
        assert result.status == VerificationResultStatus.PASS
        assert result.message == "All checks passed"

    def test_verification_result_fail(self) -> None:
        """Test FAIL VerificationResult."""
        result = VerificationResult(
            run_id="run-123",
            task_id="TASK-001",
            status=VerificationResultStatus.FAIL,
            checks=[],
            message="Some checks failed",
        )
        assert result.status == VerificationResultStatus.FAIL
        assert result.task_id == "TASK-001"


class TestChildTask:
    """Tests for ChildTask model."""

    def test_child_task_valid(self) -> None:
        """Test valid ChildTask creation."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test task",
            description="Test description",
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        )
        assert task.task_id == "TASK-001"
        assert task.sequence == 1
        assert task.title == "Test task"
        assert task.status == TaskStatus.PENDING
        assert task.attempt == 0
        assert task.max_attempts == 3

    def test_child_task_empty_task_id_rejected(self) -> None:
        """Test that empty task_id is rejected."""
        with pytest.raises(ValueError):
            ChildTask(
                task_id="",
                sequence=1,
                title="Test",
                description="Test",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            )

    def test_child_task_empty_title_rejected(self) -> None:
        """Test that empty title is rejected."""
        with pytest.raises(ValueError):
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="",
                description="Test",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            )

    def test_child_task_empty_description_rejected(self) -> None:
        """Test that empty description is rejected."""
        with pytest.raises(ValueError):
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Test",
                description="",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            )

    def test_child_task_can_retry(self) -> None:
        """Test can_retry method."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=0,
            max_attempts=3,
        )
        assert task.can_retry() is True
        task.attempt = 1
        assert task.can_retry() is True
        task.attempt = 2
        assert task.can_retry() is False

    def test_child_task_retry_count_remaining(self) -> None:
        """Test retry_count_remaining method."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=0,
            max_attempts=3,
        )
        assert task.retry_count_remaining() == 2
        task.attempt = 1
        assert task.retry_count_remaining() == 1
        task.attempt = 2
        assert task.retry_count_remaining() == 0


class TestPlan:
    """Tests for Plan model."""

    def test_plan_valid_with_3_tasks(self) -> None:
        """Test valid Plan with exactly 3 tasks."""
        tasks = [
            ChildTask(
                task_id=f"TASK-{i}",
                sequence=i,
                title=f"Task {i}",
                description=f"Description {i}",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            )
            for i in range(1, 4)
        ]
        plan = Plan(
            plan_id="plan-123",
            run_id="run-123",
            goal="Test goal",
            tasks=tasks,
        )
        assert len(plan.tasks) == 3
        assert plan.goal == "Test goal"

    def test_plan_exactly_3_tasks_required(self) -> None:
        """Test that Plan must have exactly 3 tasks."""
        tasks = [
            ChildTask(
                task_id="TASK-1",
                sequence=1,
                title="Task 1",
                description="Desc 1",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            )
        ]
        with pytest.raises(ValueError, match="exactly 3 ChildTasks"):
            Plan(
                plan_id="plan-123",
                run_id="run-123",
                goal="Test",
                tasks=tasks,
            )

    def test_plan_duplicate_task_ids_rejected(self) -> None:
        """Test that duplicate task IDs are rejected."""
        tasks = [
            ChildTask(
                task_id="TASK-1",
                sequence=1,
                title="Task 1",
                description="Desc 1",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            ),
            ChildTask(
                task_id="TASK-1",  # Duplicate!
                sequence=2,
                title="Task 2",
                description="Desc 2",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            ),
            ChildTask(
                task_id="TASK-3",
                sequence=3,
                title="Task 3",
                description="Desc 3",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            ),
        ]
        with pytest.raises(ValueError, match="Task IDs must be unique"):
            Plan(
                plan_id="plan-123",
                run_id="run-123",
                goal="Test",
                tasks=tasks,
            )

    def test_plan_invalid_dependency_rejected(self) -> None:
        """Test that invalid dependencies are rejected."""
        tasks = [
            ChildTask(
                task_id="TASK-1",
                sequence=1,
                title="Task 1",
                description="Desc 1",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
                dependencies=["NONEXISTENT"],
            ),
            ChildTask(
                task_id="TASK-2",
                sequence=2,
                title="Task 2",
                description="Desc 2",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            ),
            ChildTask(
                task_id="TASK-3",
                sequence=3,
                title="Task 3",
                description="Desc 3",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            ),
        ]
        with pytest.raises(ValueError, match="depends on non-existent task"):
            Plan(
                plan_id="plan-123",
                run_id="run-123",
                goal="Test",
                tasks=tasks,
            )


class TestEvidenceRecord:
    """Tests for EvidenceRecord model."""

    def test_evidence_record_valid(self) -> None:
        """Test valid EvidenceRecord creation."""
        record = EvidenceRecord(
            evidence_id="evidence-123",
            run_id="run-123",
            kind="test_result",
            source="pytest",
            payload={"passed": True},
        )
        assert record.evidence_id == "evidence-123"
        assert record.run_id == "run-123"
        assert record.kind == "test_result"
        assert "created_at" in record.model_dump()

    def test_evidence_record_empty_id_rejected(self) -> None:
        """Test that empty evidence_id is rejected."""
        with pytest.raises(ValueError):
            EvidenceRecord(
                evidence_id="",
                run_id="run-123",
                kind="test",
                source="test",
                payload={},
            )

    def test_evidence_record_string_payload(self) -> None:
        """Test EvidenceRecord with string payload."""
        record = EvidenceRecord(
            evidence_id="evidence-123",
            run_id="run-123",
            kind="log",
            source="stderr",
            payload="Error message here",
        )
        assert record.payload == "Error message here"


class TestRunState:
    """Tests for RunState model."""

    def test_run_state_valid(self) -> None:
        """Test valid RunState creation."""
        state = RunState(
            run_id="run-123",
            goal="Test goal",
            status=RunStatus.CREATED,
        )
        assert state.run_id == "run-123"
        assert state.goal == "Test goal"
        assert state.status == RunStatus.CREATED
        assert "created_at" in state.model_dump()
        assert "updated_at" in state.model_dump()

    def test_run_state_blank_goal_rejected(self) -> None:
        """Test that blank goal is rejected."""
        with pytest.raises(ValueError):
            RunState(
                run_id="run-123",
                goal="",
            )

    def test_run_state_plan_run_id_match(self) -> None:
        """Test that Plan run_id must match RunState run_id."""
        tasks = [
            ChildTask(
                task_id=f"TASK-{i}",
                sequence=i,
                title=f"Task {i}",
                description=f"Desc {i}",
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            )
            for i in range(1, 4)
        ]
        plan = Plan(
            plan_id="plan-123",
            run_id="run-456",  # Different from state!
            goal="Test",
            tasks=tasks,
        )
        with pytest.raises(ValueError, match="Plan run_id must match RunState run_id"):
            RunState(
                run_id="run-123",
                goal="Test",
                plan=plan,
            )

    def test_run_state_touch(self) -> None:
        """Test touch method updates timestamp."""
        state = RunState(run_id="run-123", goal="Test")
        original_updated = state.updated_at
        import time

        time.sleep(0.01)  # Small delay to ensure timestamp difference
        state.touch()
        assert state.updated_at != original_updated


class TestEnums:
    """Tests for enum values."""

    def test_task_status_values(self) -> None:
        """Test TaskStatus enum values."""
        assert TaskStatus.PENDING.value == "PENDING"
        assert TaskStatus.READY.value == "READY"
        assert TaskStatus.RUNNING.value == "RUNNING"
        assert TaskStatus.PASSED.value == "PASSED"
        assert TaskStatus.FAILED.value == "FAILED"
        assert TaskStatus.BLOCKED.value == "BLOCKED"
        assert TaskStatus.NEEDS_HUMAN.value == "NEEDS_HUMAN"

    def test_run_status_values(self) -> None:
        """Test RunStatus enum values."""
        assert RunStatus.CREATED.value == "CREATED"
        assert RunStatus.PLANNED.value == "PLANNED"
        assert RunStatus.RUNNING.value == "RUNNING"
        assert RunStatus.PASSED.value == "PASSED"
        assert RunStatus.FAILED.value == "FAILED"
        assert RunStatus.NEEDS_HUMAN.value == "NEEDS_HUMAN"

    def test_verification_result_status_values(self) -> None:
        """Test VerificationResultStatus enum values."""
        assert VerificationResultStatus.PASS.value == "PASS"
        assert VerificationResultStatus.FAIL.value == "FAIL"

    def test_verification_type_values(self) -> None:
        """Test VerificationType enum values."""
        assert VerificationType.SCHEMA.value == "schema"
        assert VerificationType.EXISTS.value == "exists"
        assert VerificationType.COUNT.value == "count"
        assert VerificationType.CUSTOM.value == "custom"
