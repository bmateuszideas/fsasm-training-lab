"""FS-ASM state transition rules and functions.

The transition matrices are owned by the Domain Core (``fsasm.domain``) so
there is one set of rules, not two. This module keeps the imperative M4 API
(``transition_task``/``transition_run``/``apply_human_authorized_*``) that the
milestone demonstrator calls; it re-uses the matrices from ``fsasm.domain`` via
private aliases so the rules live exactly once. The clean ``apply_event`` path
in ``fsasm.domain`` is the v1 single mutation path (T05); activities migrate to
it in T07.
"""

from fsasm.models import ChildTask, RunState, RunStatus, TaskStatus
from fsasm.errors import InvalidTransitionError, RetryExhaustedError
from fsasm.domain import (
    TASK_ALLOWED_TRANSITIONS as _TASK_ALLOWED_TRANSITIONS,
    RUN_ALLOWED_TRANSITIONS as _RUN_ALLOWED_TRANSITIONS,
    TASK_REQUIRES_VERIFICATION_PASS as _TASK_REQUIRES_VERIFICATION_PASS,
    TASK_REQUIRES_VERIFICATION_FAIL as _TASK_REQUIRES_VERIFICATION_FAIL,
    TASK_REQUIRES_RETRY_CHECK as _TASK_REQUIRES_RETRY_CHECK,
    RUN_REQUIRES_VERIFICATION_PASS as _RUN_REQUIRES_VERIFICATION_PASS,
)


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

    Attempt semantics:
    - attempt counts actual execution attempts started
    - increment on READY -> RUNNING (exactly once BEFORE Executor execution)
    - FAILED -> READY does NOT increment
    - never increment attempt manually in workflow code

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

    # Increment attempt counter on READY -> RUNNING (actual execution attempt started)
    # This is the ONLY place where attempt is incremented
    if current_status == TaskStatus.READY and target_status == TaskStatus.RUNNING:
        task.attempt += 1

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

    # Check retry budget for FAILED -> READY or FAILED -> NEEDS_HUMAN
    # Under unified semantics: can_retry() returns True iff attempt < max_attempts
    # So if attempt < max_attempts, we can retry; if attempt >= max_attempts, we must go to NEEDS_HUMAN
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
            # Do NOT increment attempt here - it was already incremented on READY->RUNNING

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
# HUMAN-AUTHORIZED TRANSITIONS (M4)
# =============================================================================


def apply_human_authorized_task_transition(
    task: ChildTask,
    target_status: TaskStatus,
    new_max_attempts: int | None = None,
) -> ChildTask:
    """
    Apply a human-authorized transition that bypasses normal domain rules.

    This is used for human decisions (RETRY_ONCE, ABORT) that need to transition
    out of NEEDS_HUMAN terminal state.

    For RETRY_ONCE:
    - NEEDS_HUMAN -> READY
    - Set max_attempts = attempt + 1 (exactly one more try)
    - Do NOT reset attempt

    For ABORT:
    - NEEDS_HUMAN -> FAILED

    Args:
        task: The ChildTask to transition.
        target_status: The desired new status (READY for RETRY_ONCE, FAILED for ABORT).
        new_max_attempts: New max_attempts value (for RETRY_ONCE).

    Returns:
        The updated ChildTask with new status.

    Raises:
        InvalidTransitionError: If the transition is not a valid human-authorized transition.
    """
    current_status = task.status

    # Only allow human-authorized transitions from NEEDS_HUMAN
    if current_status != TaskStatus.NEEDS_HUMAN:
        raise InvalidTransitionError(
            from_status=current_status.value,
            to_status=target_status.value,
            entity_type="ChildTask",
            entity_id=task.task_id,
            reason=f"Human-authorized transitions only allowed from NEEDS_HUMAN, got {current_status.value}",
        )

    # Only allow NEEDS_HUMAN -> READY or NEEDS_HUMAN -> FAILED
    if target_status not in {TaskStatus.READY, TaskStatus.FAILED}:
        raise InvalidTransitionError(
            from_status=current_status.value,
            to_status=target_status.value,
            entity_type="ChildTask",
            entity_id=task.task_id,
            reason="Human-authorized transitions only allow READY or FAILED from NEEDS_HUMAN",
        )

    # Apply the transition
    task.status = target_status

    # For RETRY_ONCE: set max_attempts
    if new_max_attempts is not None:
        task.max_attempts = new_max_attempts

    return task


def apply_human_authorized_run_transition(
    state: RunState,
    target_status: RunStatus,
) -> RunState:
    """
    Apply a human-authorized transition that bypasses normal domain rules.

    This is used for human decisions (RETRY_ONCE, ABORT) that need to transition
    out of NEEDS_HUMAN terminal state.

    For RETRY_ONCE:
    - NEEDS_HUMAN -> RUNNING

    For ABORT:
    - NEEDS_HUMAN -> FAILED

    Args:
        state: The RunState to transition.
        target_status: The desired new status (RUNNING for RETRY_ONCE, FAILED for ABORT).

    Returns:
        The updated RunState with new status.

    Raises:
        InvalidTransitionError: If the transition is not a valid human-authorized transition.
    """
    current_status = state.status

    # Only allow human-authorized transitions from NEEDS_HUMAN
    if current_status != RunStatus.NEEDS_HUMAN:
        raise InvalidTransitionError(
            from_status=current_status.value,
            to_status=target_status.value,
            entity_type="RunState",
            entity_id=state.run_id,
            reason=f"Human-authorized transitions only allowed from NEEDS_HUMAN, got {current_status.value}",
        )

    # Only allow NEEDS_HUMAN -> RUNNING or NEEDS_HUMAN -> FAILED
    if target_status not in {RunStatus.RUNNING, RunStatus.FAILED}:
        raise InvalidTransitionError(
            from_status=current_status.value,
            to_status=target_status.value,
            entity_type="RunState",
            entity_id=state.run_id,
            reason="Human-authorized transitions only allow RUNNING or FAILED from NEEDS_HUMAN",
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
