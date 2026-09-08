"""FS-ASM state transition rules and functions."""

from fsasm.models import ChildTask, RunState, RunStatus, TaskStatus
from fsasm.errors import InvalidTransitionError, RetryExhaustedError


# =============================================================================
# TASK TRANSITION RULES
# =============================================================================

# Allowed transitions for TaskStatus
_TASK_ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.READY, TaskStatus.BLOCKED},
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.BLOCKED},
    TaskStatus.RUNNING: {TaskStatus.PASSED, TaskStatus.FAILED, TaskStatus.BLOCKED},
    TaskStatus.PASSED: set(),  # Terminal state - no outgoing transitions
    TaskStatus.FAILED: {TaskStatus.READY, TaskStatus.NEEDS_HUMAN},  # Can retry if budget remains, or escalate
    TaskStatus.BLOCKED: {TaskStatus.READY},  # Can become ready when unblocked
    TaskStatus.NEEDS_HUMAN: set(),  # Terminal state - requires human intervention
}

# Transitions that require verification PASS
_TASK_REQUIRES_VERIFICATION_PASS: set[tuple[TaskStatus, TaskStatus]] = {
    (TaskStatus.RUNNING, TaskStatus.PASSED),
}

# Transitions that require verification FAIL or retry exhaustion
_TASK_REQUIRES_VERIFICATION_FAIL: set[tuple[TaskStatus, TaskStatus]] = {
    (TaskStatus.RUNNING, TaskStatus.FAILED),
}

# Transitions that require retry budget check
_TASK_REQUIRES_RETRY_CHECK: set[tuple[TaskStatus, TaskStatus]] = {
    (TaskStatus.FAILED, TaskStatus.READY),
    (TaskStatus.FAILED, TaskStatus.NEEDS_HUMAN),
}


# =============================================================================
# RUN TRANSITION RULES
# =============================================================================

# Allowed transitions for RunStatus
_RUN_ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.CREATED: {RunStatus.PLANNED},
    RunStatus.PLANNED: {RunStatus.RUNNING},
    RunStatus.RUNNING: {RunStatus.PASSED, RunStatus.FAILED, RunStatus.NEEDS_HUMAN},
    RunStatus.PASSED: set(),  # Terminal state
    RunStatus.FAILED: set(),  # Terminal state
    RunStatus.NEEDS_HUMAN: set(),  # Terminal state
}

# Transitions that require verification PASS for the entire run
_RUN_REQUIRES_VERIFICATION_PASS: set[tuple[RunStatus, RunStatus]] = {
    (RunStatus.RUNNING, RunStatus.PASSED),
}


# =============================================================================
# TRANSITION FUNCTIONS
# =============================================================================


def transition_task(
    task: ChildTask,
    target_status: TaskStatus,
    verification_pass: bool | None = None,
    verification_result: bool | None = None,
) -> ChildTask:
    """
    Transition a task to a new status, enforcing domain rules.

    Args:
        task: The ChildTask to transition.
        target_status: The desired new status.
        verification_pass: Whether verification passed (required for RUNNING->PASSED).
        verification_result: Alternative way to specify verification result.

    Returns:
        The updated ChildTask with new status.

    Raises:
        InvalidTransitionError: If the transition is not allowed by domain rules.
        RetryExhaustedError: If trying to retry but no budget remains.
    """
    current_status = task.status

    # Check if transition is allowed
    allowed_targets = _TASK_ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        raise InvalidTransitionError(
            from_status=current_status.value,
            to_status=target_status.value,
            entity_type="ChildTask",
            entity_id=task.task_id,
            reason=f"{current_status.value} cannot transition to {target_status.value}",
        )

    # Check verification requirements
    if (current_status, target_status) in _TASK_REQUIRES_VERIFICATION_PASS:
        if verification_pass is not True and verification_result is not True:
            raise InvalidTransitionError(
                from_status=current_status.value,
                to_status=target_status.value,
                entity_type="ChildTask",
                entity_id=task.task_id,
                reason="Transition to PASSED requires verification PASS",
            )

    if (current_status, target_status) in _TASK_REQUIRES_VERIFICATION_FAIL:
        if verification_pass is not False and verification_result is not False:
            raise InvalidTransitionError(
                from_status=current_status.value,
                to_status=target_status.value,
                entity_type="ChildTask",
                entity_id=task.task_id,
                reason="Transition to FAILED requires verification FAIL",
            )

    # Check retry budget
    if (current_status, target_status) in _TASK_REQUIRES_RETRY_CHECK:
        if target_status == TaskStatus.NEEDS_HUMAN:
            # FAILED -> NEEDS_HUMAN: only allowed if retry budget is exhausted
            if task.can_retry():
                raise InvalidTransitionError(
                    from_status=current_status.value,
                    to_status=target_status.value,
                    entity_type="ChildTask",
                    entity_id=task.task_id,
                    reason="Task can still retry - cannot transition to NEEDS_HUMAN",
                )
            # Allow the transition if retry exhausted
        else:
            # For FAILED -> READY, check retry budget
            if not task.can_retry():
                raise RetryExhaustedError(
                    task_id=task.task_id,
                    max_attempts=task.max_attempts,
                    current_attempt=task.attempt,
                )
            # Increment attempt counter when retrying
            if target_status == TaskStatus.READY and current_status == TaskStatus.FAILED:
                task.attempt += 1

    # Perform the transition
    task.status = target_status
    return task


def transition_run(
    state: RunState,
    target_status: RunStatus,
    verification_pass: bool | None = None,
) -> RunState:
    """
    Transition a run to a new status, enforcing domain rules.

    Args:
        state: The RunState to transition.
        target_status: The desired new status.
        verification_pass: Whether verification passed (required for RUNNING->PASSED).

    Returns:
        The updated RunState with new status.

    Raises:
        InvalidTransitionError: If the transition is not allowed by domain rules.
    """
    current_status = state.status

    # Check if transition is allowed
    allowed_targets = _RUN_ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        raise InvalidTransitionError(
            from_status=current_status.value,
            to_status=target_status.value,
            entity_type="RunState",
            entity_id=state.run_id,
            reason=f"{current_status.value} cannot transition to {target_status.value}",
        )

    # Check verification requirements for run PASS
    if (current_status, target_status) in _RUN_REQUIRES_VERIFICATION_PASS:
        if verification_pass is not True:
            raise InvalidTransitionError(
                from_status=current_status.value,
                to_status=target_status.value,
                entity_type="RunState",
                entity_id=state.run_id,
                reason="Transition to PASSED requires verification PASS",
            )

    # Perform the transition
    state.status = target_status
    state.touch()
    return state


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_task_transition_allowed(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """Check if a task transition is allowed by domain rules."""
    allowed = _TASK_ALLOWED_TRANSITIONS.get(from_status, set())
    return to_status in allowed


def is_run_transition_allowed(from_status: RunStatus, to_status: RunStatus) -> bool:
    """Check if a run transition is allowed by domain rules."""
    allowed = _RUN_ALLOWED_TRANSITIONS.get(from_status, set())
    return to_status in allowed


def get_allowed_task_transitions(from_status: TaskStatus) -> set[TaskStatus]:
    """Get all allowed target statuses from a given task status."""
    return _TASK_ALLOWED_TRANSITIONS.get(from_status, set()).copy()


def get_allowed_run_transitions(from_status: RunStatus) -> set[RunStatus]:
    """Get all allowed target statuses from a given run status."""
    return _RUN_ALLOWED_TRANSITIONS.get(from_status, set()).copy()
