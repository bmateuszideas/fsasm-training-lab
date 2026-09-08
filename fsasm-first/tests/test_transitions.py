"""Tests for FS-ASM state transitions."""

import pytest

from fsasm.models import (
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.transitions import (
    transition_task,
    transition_run,
    is_task_transition_allowed,
    is_run_transition_allowed,
    get_allowed_task_transitions,
    get_allowed_run_transitions,
)
from fsasm.errors import InvalidTransitionError, RetryExhaustedError


class TestTaskTransitions:
    """Tests for task state transitions."""

    def _create_task(
        self,
        task_id: str = "TASK-001",
        status: TaskStatus = TaskStatus.PENDING,
        attempt: int = 0,
        max_attempts: int = 3,
    ) -> ChildTask:
        """Helper to create a ChildTask."""
        return ChildTask(
            task_id=task_id,
            sequence=1,
            title="Test task",
            description="Test description",
            status=status,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=attempt,
            max_attempts=max_attempts,
        )

    # =========================================================================
    # PENDING transitions
    # =========================================================================

    def test_pending_to_ready_allowed(self) -> None:
        """Test PENDING -> READY is allowed."""
        task = self._create_task(status=TaskStatus.PENDING)
        result = transition_task(task, TaskStatus.READY)
        assert result.status == TaskStatus.READY

    def test_pending_to_blocked_allowed(self) -> None:
        """Test PENDING -> BLOCKED is allowed."""
        task = self._create_task(status=TaskStatus.PENDING)
        result = transition_task(task, TaskStatus.BLOCKED)
        assert result.status == TaskStatus.BLOCKED

    def test_pending_to_running_not_allowed(self) -> None:
        """Test PENDING -> RUNNING is NOT allowed."""
        task = self._create_task(status=TaskStatus.PENDING)
        with pytest.raises(InvalidTransitionError):
            transition_task(task, TaskStatus.RUNNING)

    def test_pending_to_passed_not_allowed(self) -> None:
        """Test PENDING -> PASSED is NOT allowed."""
        task = self._create_task(status=TaskStatus.PENDING)
        with pytest.raises(InvalidTransitionError):
            transition_task(task, TaskStatus.PASSED)

    # =========================================================================
    # READY transitions
    # =========================================================================

    def test_ready_to_running_allowed(self) -> None:
        """Test READY -> RUNNING is allowed."""
        task = self._create_task(status=TaskStatus.READY)
        result = transition_task(task, TaskStatus.RUNNING)
        assert result.status == TaskStatus.RUNNING

    def test_ready_to_blocked_allowed(self) -> None:
        """Test READY -> BLOCKED is allowed."""
        task = self._create_task(status=TaskStatus.READY)
        result = transition_task(task, TaskStatus.BLOCKED)
        assert result.status == TaskStatus.BLOCKED

    def test_ready_to_pending_not_allowed(self) -> None:
        """Test READY -> PENDING is NOT allowed (backwards)."""
        task = self._create_task(status=TaskStatus.READY)
        with pytest.raises(InvalidTransitionError):
            transition_task(task, TaskStatus.PENDING)

    # =========================================================================
    # RUNNING transitions
    # =========================================================================

    def test_running_to_passed_with_verification(self) -> None:
        """Test RUNNING -> PASSED is allowed with verification PASS."""
        task = self._create_task(status=TaskStatus.RUNNING)
        result = transition_task(task, TaskStatus.PASSED, verification_pass=True)
        assert result.status == TaskStatus.PASSED

    def test_running_to_passed_without_verification_fails(self) -> None:
        """Test RUNNING -> PASSED fails without verification PASS."""
        task = self._create_task(status=TaskStatus.RUNNING)
        with pytest.raises(InvalidTransitionError, match="verification PASS"):
            transition_task(task, TaskStatus.PASSED)

    def test_running_to_failed_with_verification(self) -> None:
        """Test RUNNING -> FAILED is allowed with verification FAIL."""
        task = self._create_task(status=TaskStatus.RUNNING)
        result = transition_task(task, TaskStatus.FAILED, verification_pass=False)
        assert result.status == TaskStatus.FAILED

    def test_running_to_failed_without_verification_fails(self) -> None:
        """Test RUNNING -> FAILED fails without verification FAIL."""
        task = self._create_task(status=TaskStatus.RUNNING)
        with pytest.raises(InvalidTransitionError, match="verification FAIL"):
            transition_task(task, TaskStatus.FAILED)

    def test_running_to_blocked_allowed(self) -> None:
        """Test RUNNING -> BLOCKED is allowed."""
        task = self._create_task(status=TaskStatus.RUNNING)
        result = transition_task(task, TaskStatus.BLOCKED)
        assert result.status == TaskStatus.BLOCKED

    # =========================================================================
    # PASSED transitions (terminal)
    # =========================================================================

    def test_passed_no_outgoing_transitions(self) -> None:
        """Test PASSED has no outgoing transitions."""
        task = self._create_task(status=TaskStatus.PASSED)
        for target in TaskStatus:
            if target == TaskStatus.PASSED:
                continue
            with pytest.raises(InvalidTransitionError):
                transition_task(task, target)

    # =========================================================================
    # FAILED transitions
    # =========================================================================

    def test_failed_to_ready_with_retry_budget(self) -> None:
        """Test FAILED -> READY is allowed when retry budget remains."""
        task = self._create_task(status=TaskStatus.FAILED, attempt=0, max_attempts=3)
        result = transition_task(task, TaskStatus.READY)
        assert result.status == TaskStatus.READY
        assert result.attempt == 1  # Attempt incremented

    def test_failed_to_ready_exhausts_retry(self) -> None:
        """Test FAILED -> READY exhausts retry budget."""
        task = self._create_task(status=TaskStatus.FAILED, attempt=0, max_attempts=3)
        result = transition_task(task, TaskStatus.READY)
        assert result.attempt == 1
        result = transition_task(result, TaskStatus.RUNNING)
        result = transition_task(result, TaskStatus.FAILED, verification_pass=False)
        result = transition_task(result, TaskStatus.READY)
        assert result.attempt == 2

    def test_failed_to_ready_no_budget_fails(self) -> None:
        """Test FAILED -> READY fails when no retry budget remains."""
        task = self._create_task(status=TaskStatus.FAILED, attempt=2, max_attempts=3)
        with pytest.raises(RetryExhaustedError):
            transition_task(task, TaskStatus.READY)

    def test_failed_to_needs_human_with_budget_fails(self) -> None:
        """Test FAILED -> NEEDS_HUMAN fails when retry budget remains."""
        task = self._create_task(status=TaskStatus.FAILED, attempt=0, max_attempts=3)
        with pytest.raises(InvalidTransitionError, match="can still retry"):
            transition_task(task, TaskStatus.NEEDS_HUMAN, verification_pass=False)

    # =========================================================================
    # BLOCKED transitions
    # =========================================================================

    def test_blocked_to_ready_allowed(self) -> None:
        """Test BLOCKED -> READY is allowed."""
        task = self._create_task(status=TaskStatus.BLOCKED)
        result = transition_task(task, TaskStatus.READY)
        assert result.status == TaskStatus.READY

    def test_blocked_to_other_transitions_not_allowed(self) -> None:
        """Test BLOCKED -> other transitions are NOT allowed."""
        task = self._create_task(status=TaskStatus.BLOCKED)
        for target in [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PASSED, TaskStatus.FAILED]:
            with pytest.raises(InvalidTransitionError):
                transition_task(task, target)

    # =========================================================================
    # NEEDS_HUMAN transitions (terminal)
    # =========================================================================

    def test_needs_human_no_outgoing_transitions(self) -> None:
        """Test NEEDS_HUMAN has no outgoing transitions."""
        task = self._create_task(status=TaskStatus.NEEDS_HUMAN)
        for target in TaskStatus:
            if target == TaskStatus.NEEDS_HUMAN:
                continue
            with pytest.raises(InvalidTransitionError):
                transition_task(task, target)


class TestRunTransitions:
    """Tests for run state transitions."""

    def _create_state(
        self,
        run_id: str = "run-123",
        goal: str = "Test goal",
        status: RunStatus = RunStatus.CREATED,
        plan: Plan | None = None,
    ) -> RunState:
        """Helper to create a RunState."""
        return RunState(
            run_id=run_id,
            goal=goal,
            status=status,
            plan=plan,
        )

    # =========================================================================
    # CREATED transitions
    # =========================================================================

    def test_created_to_planned_allowed(self) -> None:
        """Test CREATED -> PLANNED is allowed."""
        state = self._create_state(status=RunStatus.CREATED)
        result = transition_run(state, RunStatus.PLANNED)
        assert result.status == RunStatus.PLANNED

    def test_created_to_running_not_allowed(self) -> None:
        """Test CREATED -> RUNNING is NOT allowed (must go through PLANNED)."""
        state = self._create_state(status=RunStatus.CREATED)
        with pytest.raises(InvalidTransitionError):
            transition_run(state, RunStatus.RUNNING)

    # =========================================================================
    # PLANNED transitions
    # =========================================================================

    def test_planned_to_running_allowed(self) -> None:
        """Test PLANNED -> RUNNING is allowed."""
        state = self._create_state(status=RunStatus.PLANNED)
        result = transition_run(state, RunStatus.RUNNING)
        assert result.status == RunStatus.RUNNING

    def test_planned_to_created_not_allowed(self) -> None:
        """Test PLANNED -> CREATED is NOT allowed (backwards)."""
        state = self._create_state(status=RunStatus.PLANNED)
        with pytest.raises(InvalidTransitionError):
            transition_run(state, RunStatus.CREATED)

    # =========================================================================
    # RUNNING transitions
    # =========================================================================

    def test_running_to_passed_with_verification(self) -> None:
        """Test RUNNING -> PASSED is allowed with verification PASS."""
        state = self._create_state(status=RunStatus.RUNNING)
        result = transition_run(state, RunStatus.PASSED, verification_pass=True)
        assert result.status == RunStatus.PASSED

    def test_running_to_passed_without_verification_fails(self) -> None:
        """Test RUNNING -> PASSED fails without verification PASS."""
        state = self._create_state(status=RunStatus.RUNNING)
        with pytest.raises(InvalidTransitionError, match="verification PASS"):
            transition_run(state, RunStatus.PASSED)

    def test_running_to_failed_allowed(self) -> None:
        """Test RUNNING -> FAILED is allowed."""
        state = self._create_state(status=RunStatus.RUNNING)
        result = transition_run(state, RunStatus.FAILED, verification_pass=False)
        assert result.status == RunStatus.FAILED

    def test_running_to_needs_human_allowed(self) -> None:
        """Test RUNNING -> NEEDS_HUMAN is allowed."""
        state = self._create_state(status=RunStatus.RUNNING)
        result = transition_run(state, RunStatus.NEEDS_HUMAN)
        assert result.status == RunStatus.NEEDS_HUMAN

    # =========================================================================
    # PASSED transitions (terminal)
    # =========================================================================

    def test_passed_no_outgoing_transitions(self) -> None:
        """Test PASSED has no outgoing transitions."""
        state = self._create_state(status=RunStatus.PASSED)
        for target in RunStatus:
            if target == RunStatus.PASSED:
                continue
            with pytest.raises(InvalidTransitionError):
                transition_run(state, target)

    # =========================================================================
    # FAILED transitions (terminal)
    # =========================================================================

    def test_failed_no_outgoing_transitions(self) -> None:
        """Test FAILED has no outgoing transitions."""
        state = self._create_state(status=RunStatus.FAILED)
        for target in RunStatus:
            if target == RunStatus.FAILED:
                continue
            with pytest.raises(InvalidTransitionError):
                transition_run(state, target)

    # =========================================================================
    # NEEDS_HUMAN transitions (terminal)
    # =========================================================================

    def test_needs_human_no_outgoing_transitions(self) -> None:
        """Test NEEDS_HUMAN has no outgoing transitions."""
        state = self._create_state(status=RunStatus.NEEDS_HUMAN)
        for target in RunStatus:
            if target == RunStatus.NEEDS_HUMAN:
                continue
            with pytest.raises(InvalidTransitionError):
                transition_run(state, target)


class TestTransitionHelpers:
    """Tests for transition helper functions."""

    def test_is_task_transition_allowed(self) -> None:
        """Test is_task_transition_allowed helper."""
        assert is_task_transition_allowed(TaskStatus.PENDING, TaskStatus.READY) is True
        assert is_task_transition_allowed(TaskStatus.PENDING, TaskStatus.RUNNING) is False
        assert is_task_transition_allowed(TaskStatus.READY, TaskStatus.RUNNING) is True
        assert is_task_transition_allowed(TaskStatus.RUNNING, TaskStatus.PASSED) is True
        assert is_task_transition_allowed(TaskStatus.PASSED, TaskStatus.READY) is False

    def test_is_run_transition_allowed(self) -> None:
        """Test is_run_transition_allowed helper."""
        assert is_run_transition_allowed(RunStatus.CREATED, RunStatus.PLANNED) is True
        assert is_run_transition_allowed(RunStatus.CREATED, RunStatus.RUNNING) is False
        assert is_run_transition_allowed(RunStatus.PLANNED, RunStatus.RUNNING) is True
        assert is_run_transition_allowed(RunStatus.RUNNING, RunStatus.PASSED) is True
        assert is_run_transition_allowed(RunStatus.PASSED, RunStatus.CREATED) is False

    def test_get_allowed_task_transitions(self) -> None:
        """Test get_allowed_task_transitions helper."""
        allowed = get_allowed_task_transitions(TaskStatus.PENDING)
        assert TaskStatus.READY in allowed
        assert TaskStatus.BLOCKED in allowed
        assert TaskStatus.RUNNING not in allowed
        assert len(allowed) == 2

    def test_get_allowed_run_transitions(self) -> None:
        """Test get_allowed_run_transitions helper."""
        allowed = get_allowed_run_transitions(RunStatus.CREATED)
        assert RunStatus.PLANNED in allowed
        assert len(allowed) == 1

        allowed = get_allowed_run_transitions(RunStatus.RUNNING)
        assert RunStatus.PASSED in allowed
        assert RunStatus.FAILED in allowed
        assert RunStatus.NEEDS_HUMAN in allowed
        assert len(allowed) == 3
