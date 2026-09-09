"""Tests for FS-ASM Milestone Four workflow - Bounded Retry + Human Gate."""

import pytest

from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    ExecutorBackend,
    ExecutorConfig,
    GoalInput,
    Plan,
    PlannerBackend,
    PlannerConfig,
    PlannerMetadata,
    PlannerOutput,
    PlannerProposal,
    RunState,
    RunStatus,
    TaskProposal,
    TaskStatus,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
)
from workflows.fsasm_milestone_four import (
    WorkflowInput,
    WorkflowOutput,
    create_input_activity,
    validate_config_activity,
    find_next_ready_task_activity,
    check_retry_budget_activity,
    transition_to_needs_human_activity,
    persist_final_m4_state_activity,
)
from fsasm.errors import ConfigurationError
from fsasm.persistence import RuntimePersistence


class TestM4WorkflowInput:
    """Tests for M4 WorkflowInput model."""

    def test_workflow_input_defaults(self) -> None:
        """Test WorkflowInput has correct defaults."""
        input_data = WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
        )
        assert input_data.goal == "Test goal"
        assert input_data.planner_backend == PlannerBackend.STUB
        assert input_data.executor_backend == ExecutorBackend.STUB
        assert input_data.max_retries_per_task == 2
        assert input_data.run_id is None
        assert input_data.planner_model_name is None
        assert input_data.planner_prompt_version == "v1.0"
        assert input_data.executor_model_name is None

    def test_workflow_input_custom_retries(self) -> None:
        """Test WorkflowInput with custom retry settings."""
        input_data = WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=5,
        )
        assert input_data.max_retries_per_task == 5

    def test_workflow_input_validation(self) -> None:
        """Test WorkflowInput validation."""
        # Valid input
        input_data = WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=3,
        )
        assert input_data.max_retries_per_task == 3

        # Test bounds
        input_data = WorkflowInput(
            goal="Test",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=0,
        )
        assert input_data.max_retries_per_task == 0

        input_data = WorkflowInput(
            goal="Test",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=5,
        )
        assert input_data.max_retries_per_task == 5

        # Test out of bounds
        with pytest.raises(ValidationError):
            WorkflowInput(
                goal="Test",
                planner_backend=PlannerBackend.STUB,
                executor_backend=ExecutorBackend.STUB,
                max_retries_per_task=6,  # > 5
            )

        with pytest.raises(ValidationError):
            WorkflowInput(
                goal="Test",
                planner_backend=PlannerBackend.STUB,
                executor_backend=ExecutorBackend.STUB,
                max_retries_per_task=-1,  # < 0
            )


class TestM4WorkflowOutput:
    """Tests for M4 WorkflowOutput model."""

    def test_workflow_output_structure(self) -> None:
        """Test WorkflowOutput has all required fields."""
        output = WorkflowOutput(
            run_id="run-123",
            goal="Test goal",
            status="RUNNING",
            plan_id="plan-123",
            task_count=3,
            executed_task_ids=["TASK-001"],
            passed_task_ids=["TASK-001"],
            failed_task_ids=[],
            needs_human_task_ids=[],
            verification_statuses={"TASK-001": "PASS"},
            verification_messages={"TASK-001": "All checks passed"},
            evidence_count=5,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            success=True,
            human_gate_invoked=False,
            human_gate_reason=None,
            planner_provider="stub",
            planner_model=None,
            planner_model_call_count=0,
            executor_provider="stub",
            executor_model_call_count=0,
        )
        assert output.run_id == "run-123"
        assert output.success is True
        assert output.human_gate_invoked is False


class TestM4Activities:
    """Tests for M4 activities."""

    @pytest.fixture
    def sample_workflow_input(self) -> WorkflowInput:
        """Create a sample WorkflowInput."""
        return WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=2,
        )

    @pytest.fixture
    def sample_plan(self) -> Plan:
        """Create a sample Plan with 3 tasks."""
        tasks = [
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Task 1",
                description="First task",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
                dependencies=[],
            ),
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Task 2",
                description="Second task",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
                dependencies=["TASK-001"],
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Task 3",
                description="Third task",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
                dependencies=["TASK-002"],
            ),
        ]
        return Plan(
            plan_id="plan-123",
            run_id="run-123",
            goal="Test goal",
            tasks=tasks,
        )

    @pytest.fixture
    def sample_state(self) -> RunState:
        """Create a sample RunState."""
        return RunState(
            run_id="run-123",
            goal="Test goal",
            status=RunStatus.RUNNING,
            plan=None,
            active_task_id=None,
            completed_task_ids=[],
            failed_task_ids=[],
        )

    async def test_create_input_activity(self, sample_workflow_input: WorkflowInput) -> None:
        """Test create_input_activity creates valid GoalInput."""
        result = await create_input_activity(sample_workflow_input)
        assert isinstance(result, GoalInput)
        assert result.goal == sample_workflow_input.goal
        assert result.run_id == sample_workflow_input.run_id

    async def test_validate_config_activity_valid(self, sample_workflow_input: WorkflowInput) -> None:
        """Test validate_config_activity with valid input."""
        planner_config, executor_config = await validate_config_activity(
            sample_workflow_input
        )
        assert isinstance(planner_config, PlannerConfig)
        assert isinstance(executor_config, ExecutorConfig)
        assert planner_config.backend == PlannerBackend.STUB
        assert executor_config.backend == ExecutorBackend.STUB

    async def test_validate_config_activity_invalid_executor(self) -> None:
        """Test validate_config_activity raises error for non-STUB executor."""
        input_data = WorkflowInput(
            goal="Test",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.MISTRAL,  # Invalid for M4
        )
        with pytest.raises(ConfigurationError):
            await validate_config_activity(input_data)

    async def test_find_next_ready_task_activity_first_task(
        self, sample_plan: Plan
    ) -> None:
        """Test find_next_ready_task_activity finds first task."""
        result = await find_next_ready_task_activity(sample_plan, [])
        assert result is not None
        assert result.task_id == "TASK-001"
        assert result.status == TaskStatus.READY

    async def test_find_next_ready_task_activity_with_deps(
        self, sample_plan: Plan
    ) -> None:
        """Test find_next_ready_task_activity respects dependencies."""
        # Complete TASK-001
        completed = ["TASK-001"]
        result = await find_next_ready_task_activity(sample_plan, completed)
        assert result is not None
        assert result.task_id == "TASK-002"

    async def test_find_next_ready_task_activity_all_complete(
        self, sample_plan: Plan
    ) -> None:
        """Test find_next_ready_task_activity returns None when all complete."""
        completed = ["TASK-001", "TASK-002", "TASK-003"]
        result = await find_next_ready_task_activity(sample_plan, completed)
        assert result is None

    async def test_check_retry_budget_activity_can_retry(self) -> None:
        """Test check_retry_budget_activity allows retry."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=0,
            max_attempts=3,
        )
        can_retry, reason = await check_retry_budget_activity(task, max_retries_per_task=2)
        assert can_retry is True
        assert "2 retry attempts remaining" in reason

    async def test_check_retry_budget_activity_exhausted(self) -> None:
        """Test check_retry_budget_activity detects exhausted budget."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=2,
            max_attempts=3,
        )
        can_retry, reason = await check_retry_budget_activity(task, max_retries_per_task=2)
        assert can_retry is False
        assert "exhausted all 2 retry attempts" in reason

    async def test_check_retry_budget_activity_zero_retries(self) -> None:
        """Test check_retry_budget_activity with zero retries configured."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=0,
            max_attempts=3,
        )
        can_retry, reason = await check_retry_budget_activity(task, max_retries_per_task=0)
        assert can_retry is False
        assert "exhausted all 0 retry attempts" in reason

    async def test_transition_to_needs_human_activity(
        self, sample_state: RunState
    ) -> None:
        """Test transition_to_needs_human_activity transitions task to NEEDS_HUMAN."""
        # Create 3 tasks for the plan (required by validation)
        tasks = [
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Test",
                description="Test",
                status=TaskStatus.FAILED,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
                attempt=2,
                max_attempts=3,
            ),
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Test 2",
                description="Test 2",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Test 3",
                description="Test 3",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            ),
        ]

        # Add plan to state
        sample_state.plan = Plan(
            plan_id="plan-123",
            run_id="run-123",
            goal="Test",
            tasks=tasks,
        )
        
        task = tasks[0]  # TASK-001

        updated_task, updated_state = await transition_to_needs_human_activity(
            task, sample_state, "Retry budget exhausted"
        )

        assert updated_task.status == TaskStatus.NEEDS_HUMAN
        assert updated_state.plan is not None
        assert updated_state.plan.tasks[0].status == TaskStatus.NEEDS_HUMAN


class TestM4RetryLogic:
    """Tests for retry logic in M4."""

    def test_retry_counter_increment(self) -> None:
        """Test that retry attempts are tracked correctly."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.READY,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=0,
            max_attempts=3,
        )

        # Initial state
        assert task.attempt == 0
        assert task.can_retry() is True
        assert task.retry_count_remaining() == 2

        # After first failure
        task.attempt += 1
        assert task.attempt == 1
        assert task.can_retry() is True
        assert task.retry_count_remaining() == 1

        # After second failure
        task.attempt += 1
        assert task.attempt == 2
        assert task.can_retry() is False
        assert task.retry_count_remaining() == 0


class TestM4HumanGate:
    """Tests for Human Gate functionality in M4."""

    def test_needs_human_terminal_state(self) -> None:
        """Test that NEEDS_HUMAN is a terminal state."""
        from fsasm.transitions import is_task_transition_allowed, get_allowed_task_transitions

        # NEEDS_HUMAN should have no outgoing transitions
        allowed = get_allowed_task_transitions(TaskStatus.NEEDS_HUMAN)
        assert len(allowed) == 0

        # No transitions from NEEDS_HUMAN should be allowed
        for target in TaskStatus:
            if target == TaskStatus.NEEDS_HUMAN:
                continue
            assert is_task_transition_allowed(TaskStatus.NEEDS_HUMAN, target) is False

    def test_failed_to_needs_human_requires_exhausted_retry(self) -> None:
        """Test that FAILED -> NEEDS_HUMAN requires retry exhaustion."""
        from fsasm.transitions import transition_task
        from fsasm.errors import InvalidTransitionError

        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=0,
            max_attempts=3,
        )

        # Should fail because task can still retry
        with pytest.raises(InvalidTransitionError, match="can still retry"):
            transition_task(task, TaskStatus.NEEDS_HUMAN, verification_pass=False)

    def test_failed_to_needs_human_allowed_when_exhausted(self) -> None:
        """Test that FAILED -> NEEDS_HUMAN is allowed when retry exhausted."""
        from fsasm.transitions import transition_task

        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=2,
            max_attempts=3,
        )

        # Should succeed because retry budget is exhausted
        result = transition_task(task, TaskStatus.NEEDS_HUMAN, verification_pass=False)
        assert result.status == TaskStatus.NEEDS_HUMAN


class TestM4RunStatus:
    """Tests for RunStatus transitions in M4."""

    def test_run_status_needs_human(self) -> None:
        """Test that RunStatus can transition to NEEDS_HUMAN."""
        from fsasm.transitions import is_run_transition_allowed

        # RUNNING -> NEEDS_HUMAN should be allowed
        assert is_run_transition_allowed(RunStatus.RUNNING, RunStatus.NEEDS_HUMAN) is True

        # NEEDS_HUMAN should be terminal
        from fsasm.transitions import get_allowed_run_transitions
        allowed = get_allowed_run_transitions(RunStatus.NEEDS_HUMAN)
        assert len(allowed) == 0


# Import for ValidationError
from pydantic import ValidationError
