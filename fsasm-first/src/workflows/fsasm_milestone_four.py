"""FS-ASM Milestone Four Workflow - Bounded Retry + Human Gate.

IMPLEMENTS:
1. Real durable Human Gate using @workflow.signal and workflow.wait_condition()
2. Proper execution-attempt semantics (increment only on READY->RUNNING)
3. Typed human decisions (RETRY_ONCE, ABORT)
4. Persisted failure semantics with evidence per attempt
5. Scope: exactly ONE ChildTask (TASK-001 only, TASK-002/003 stay PENDING)
6. No direct status assignments - use transition API only
7. Human-authorized transitions via explicit domain operations
8. All filesystem I/O in activities (no direct persistence in workflow code)
"""

import logging

import mistralai.workflows as workflows
from mistralai.workflows import workflow
from pydantic import BaseModel, Field

# Import fsasm modules - these are used in activities, not workflow code directly
with workflow.unsafe.imports_passed_through():
    from fsasm.models import (
        ChildTask,
        EvidenceRecord,
        ExecutorBackend,
        ExecutorConfig,
        GoalInput,
        HumanDecision,
        HumanDecisionAction,
        Plan,
        PlannerBackend,
        PlannerConfig,
        PlannerMetadata,
        PlannerOutput,
        RunState,
        RunStatus,
        TaskStatus,
        VerificationResult,
        VerificationResultStatus,
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
    from fsasm.persistence import RuntimePersistence
    from fsasm.errors import ConfigurationError, InvalidTransitionError
    from fsasm.transitions import (
        transition_task,
        transition_run,
        apply_human_authorized_task_transition,
        apply_human_authorized_run_transition,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# HUMAN DECISION SIGNAL MODEL
# =============================================================================


class HumanDecisionSignal(BaseModel):
    """Signal payload for human decision."""

    task_id: str = Field(..., description="The task_id this decision applies to.")
    action: HumanDecisionAction = Field(
        ..., description="Human decision action: RETRY_ONCE or ABORT."
    )
    reason: str = Field(default="", description="Optional reason for the decision.")


# =============================================================================
# INPUT/OUTPUT MODELS
# =============================================================================


class WorkflowInput(BaseModel):
    """Input model for the FS-ASM milestone four workflow."""

    goal: str
    run_id: str | None = None
    planner_backend: PlannerBackend = Field(
        ...,
        description="Backend to use for planning: 'stub' or 'mistral'. Must be explicitly provided.",
    )
    planner_model_name: str | None = Field(
        default=None,
        description="Model name for Mistral planner backend.",
    )
    planner_prompt_version: str = Field(
        default="v1.0", description="Prompt template version."
    )
    executor_backend: ExecutorBackend = Field(
        ...,
        description="Backend to use for execution: 'stub' for M4. Must be explicitly provided.",
    )
    executor_model_name: str | None = Field(
        default=None,
        description="Model name for executor backend (not used for STUB).",
    )
    max_retries_per_task: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum retry attempts per task (0 = no retries, go straight to Human Gate).",
    )
    stub_fail_first_n_attempts: int = Field(
        default=0,
        ge=0,
        description="Number of initial attempts that should fail (0=first passes, 1=fail first then pass, 999=always fail).",
    )


class WorkflowOutput(BaseModel):
    """Output model for the FS-ASM milestone four workflow."""

    run_id: str
    goal: str
    status: str
    plan_id: str
    task_count: int
    executed_task_ids: list[str]
    passed_task_ids: list[str]
    failed_task_ids: list[str]
    needs_human_task_ids: list[str]
    verification_statuses: dict[str, str]
    verification_messages: dict[str, str]
    evidence_count: int
    created_at: str
    updated_at: str
    success: bool
    human_gate_invoked: bool
    human_gate_reason: str | None
    human_decision: dict[str, object] | None = None
    # Planner metadata
    planner_provider: str
    planner_model: str | None
    planner_model_call_count: int
    # Executor metadata
    executor_provider: str
    executor_model_call_count: int


# =============================================================================
# ACTIVITIES
# =============================================================================


@workflows.activity(
    name="fsasm-create-m4-input",
    retry_policy_max_attempts=1,
)
async def create_input_activity(input_data: WorkflowInput) -> GoalInput:
    """Create and validate GoalInput from workflow input."""
    goal_input = GoalInput(goal=input_data.goal, run_id=input_data.run_id)
    return goal_input


@workflows.activity(
    name="fsasm-validate-m4-config",
    retry_policy_max_attempts=1,
)
async def validate_config_activity(
    input: WorkflowInput,
) -> tuple[PlannerConfig, ExecutorConfig]:
    """
    Validate workflow input and create PlannerConfig and ExecutorConfig.

    For M4, executor_backend must be STUB.
    """
    if input.executor_backend != ExecutorBackend.STUB:
        raise ConfigurationError(
            message=f"Milestone 4 only supports ExecutorBackend.STUB, got '{input.executor_backend}'",
            backend=input.executor_backend.value,
        )

    planner_config = PlannerConfig(
        backend=input.planner_backend,
        model_name=input.planner_model_name,
        model_version=None,
        prompt_version=input.planner_prompt_version,
        max_tokens=4096,
        temperature=0.0,
    )

    executor_config = ExecutorConfig(
        backend=input.executor_backend,
        model_name=input.executor_model_name,
        model_version=None,
        max_tokens=4096,
        temperature=0.0,
        stub_fail_first_n_attempts=input.stub_fail_first_n_attempts,
    )

    return planner_config, executor_config


@workflows.activity(
    name="fsasm-find-next-ready-task",
    retry_policy_max_attempts=1,
)
async def find_next_ready_task_activity(
    plan: Plan, completed_task_ids: list[str]
) -> ChildTask | None:
    """
    Find the next READY task in the plan with all dependencies satisfied.

    For M4, we only execute TASK-001. TASK-002 and TASK-003 must remain PENDING.

    Args:
        plan: The Plan with tasks.
        completed_task_ids: List of task IDs that have been completed.

    Returns:
        The next eligible task (already READY), or None if no more tasks.
    """
    # For M4: Only execute TASK-001
    # Find TASK-001
    task_001 = None
    for task in plan.tasks:
        if task.task_id == "TASK-001":
            task_001 = task
            break

    if task_001 is None:
        return None

    # Skip if already completed or failed or needs_human
    if task_001.task_id in completed_task_ids:
        return None
    if task_001.status == TaskStatus.PASSED:
        return None
    if task_001.status == TaskStatus.NEEDS_HUMAN:
        return None

    # Transition PENDING -> READY if needed
    if task_001.status == TaskStatus.PENDING:
        task_001 = transition_task(task_001, TaskStatus.READY)

    return task_001


@workflows.activity(
    name="fsasm-persist-m4-initial-state",
    retry_policy_max_attempts=1,
)
async def persist_initial_state_activity(
    planner_output: PlannerOutput,
    goal_input: GoalInput,
) -> tuple[Plan, RunState]:
    """
    Persist the plan, planner proposal (as evidence), and initial run state to filesystem.

    Creates initial RunState with PLANNED status, then transitions to RUNNING.
    """
    persistence = RuntimePersistence()

    plan = planner_output.plan
    metadata = planner_output.metadata
    run_id = plan.run_id

    # Set task.max_attempts from planner config or default
    # For M4, we use the workflow's max_retries_per_task + 1 as the authoritative budget
    # The authoritative max_attempts is set by set_task_max_attempts_activity before first persistence
    # No hack needed - the workflow will set it properly

    # Create initial run state with PLANNED status
    state = RunState(
        run_id=run_id,
        goal=goal_input.goal,
        status=RunStatus.PLANNED,
        plan=plan,
        active_task_id=None,
        completed_task_ids=[],
        failed_task_ids=[],
    )

    # Transition to RUNNING
    state = transition_run(state, RunStatus.RUNNING)

    # Save plan
    persistence.save_plan(plan)

    # Save state
    persistence.save_run_state(state)

    # Save planner proposal as evidence artifact
    proposal_evidence = EvidenceRecord(
        evidence_id=f"evidence-proposal-{run_id}",
        run_id=run_id,
        task_id=None,
        kind="planner_proposal",
        source="fsasm_milestone_four_workflow",
        payload={
            "proposal": planner_output.proposal.model_dump(),
            "metadata": metadata.model_dump(),
        },
    )
    persistence.save_evidence(proposal_evidence)

    # Log the creation
    persistence.save_run_log_entry(
        run_id,
        {
            "event": "m4_run_started",
            "run_id": run_id,
            "goal": goal_input.goal,
            "status": RunStatus.RUNNING.value,
            "planner_provider": metadata.provider,
            "timestamp": state.created_at,
        },
    )

    return plan, state


@workflows.activity(
    name="fsasm-set-task-max-attempts",
    retry_policy_max_attempts=1,
)
async def set_task_max_attempts_activity(
    plan: Plan,
    max_retries_per_task: int,
) -> Plan:
    """
    Set task.max_attempts to the authoritative value from workflow config.

    Under unified semantics, ChildTask.max_attempts is the authoritative total-attempt budget.
    effective_max_attempts = max_retries_per_task + 1 (initial attempt + retries)

    Args:
        plan: The Plan with tasks.
        max_retries_per_task: The configured max retries from workflow input.

    Returns:
        The updated Plan with max_attempts set on all tasks.
    """
    effective_max_attempts = max_retries_per_task + 1
    for task in plan.tasks:
        task.max_attempts = effective_max_attempts
    return plan


@workflows.activity(
    name="fsasm-check-retry-budget",
    retry_policy_max_attempts=1,
)
async def check_retry_budget_activity(
    task: ChildTask,
) -> tuple[bool, str]:
    """
    Check if a task can be retried and return the decision.

    Attempt semantics:
    - attempt counts actual execution attempts started
    - READY -> RUNNING increments exactly once BEFORE Executor execution
    - FAILED -> READY does NOT increment
    - never increment attempt manually in workflow code

    Under unified semantics: task.max_attempts is the authoritative budget.
    can_retry() returns True iff task.attempt < task.max_attempts.

    Args:
        task: The ChildTask to check.

    Returns:
        Tuple of (can_retry: bool, reason: str)
    """
    # Use task.max_attempts as the authoritative budget
    can_retry = task.can_retry()

    if can_retry:
        reason = f"Task has {task.retry_count_remaining()} retry attempts remaining (attempt={task.attempt}, max_attempts={task.max_attempts})"
    else:
        reason = f"Task has exhausted all {task.max_attempts} attempts (attempt={task.attempt})"

    return can_retry, reason


@workflows.activity(
    name="fsasm-persist-failure-state",
    retry_policy_max_attempts=1,
)
async def persist_failure_state_activity(
    task: ChildTask,
    state: RunState,
    verification_result: VerificationResult,
    evidence_records: list[EvidenceRecord],
    attempt: int,
) -> tuple[ChildTask, RunState, list[EvidenceRecord]]:
    """
    Persist FAILED state durably before retry/escalation decision.

    Every failed execution attempt must persist:
    - ExecutorOutput provenance path
    - unique per-attempt EvidenceRecord(s)
    - VerificationResult FAIL
    - task/state/plan
    - run log entry

    Args:
        task: The ChildTask that failed.
        state: The current RunState.
        verification_result: The VerificationResult with FAIL status.
        evidence_records: The EvidenceRecord list for this attempt.
        attempt: The current attempt number.

    Returns:
        Tuple of (updated ChildTask in FAILED state, updated RunState, all evidence records).
    """
    persistence = RuntimePersistence()

    # Transition task to FAILED (this is the ONLY place we set FAILED for execution)
    task = transition_task(task, TaskStatus.FAILED, verification_pass=False)

    # Update state - DO NOT add to failed_task_ids yet (we may retry)
    if task.task_id in state.completed_task_ids:
        state.completed_task_ids.remove(task.task_id)
    state.active_task_id = None
    state.touch()

    # Update plan in state to reflect task status change
    if state.plan is not None:
        for plan_task in state.plan.tasks:
            if plan_task.task_id == task.task_id:
                plan_task.status = task.status
                plan_task.attempt = task.attempt

    # Persist evidence records (per-attempt)
    for evidence in evidence_records:
        persistence.save_evidence(evidence)

    # Persist verification result
    persistence.save_verification_result(verification_result)

    # Persist state
    persistence.save_run_state(state)

    # Persist plan
    if state.plan is not None:
        persistence.save_plan(state.plan)

    # Log failure
    persistence.save_run_log_entry(
        state.run_id,
        {
            "event": "task_execution_failed",
            "run_id": state.run_id,
            "task_id": task.task_id,
            "attempt": attempt,
            "status": task.status.value,
            "verification_status": verification_result.status.value,
            "verification_message": verification_result.message,
            "timestamp": state.updated_at,
        },
    )

    return task, state, evidence_records


@workflows.activity(
    name="fsasm-transition-to-needs-human",
    retry_policy_max_attempts=1,
)
async def transition_to_needs_human_activity(
    task: ChildTask,
    state: RunState,
    reason: str,
) -> tuple[ChildTask, RunState]:
    """
    Transition task and run to NEEDS_HUMAN status when retry budget is exhausted.

    BEFORE the workflow waits, the filesystem MUST already durably contain:
    - run.status = NEEDS_HUMAN
    - task.status = NEEDS_HUMAN
    - active_task_id = None
    - attempt == max_attempts
    - state.plan == plan.json

    The test must observe this persisted state BEFORE sending the signal.

    Args:
        task: The ChildTask that has exhausted retries.
        state: The current RunState.
        reason: The reason for transitioning to NEEDS_HUMAN.

    Returns:
        Tuple of (updated ChildTask, updated RunState).
    """
    persistence = RuntimePersistence()

    # Add to failed_task_ids since we're not retrying
    if task.task_id not in state.failed_task_ids:
        state.failed_task_ids.append(task.task_id)

    # Transition task to NEEDS_HUMAN
    task = transition_task(task, TaskStatus.NEEDS_HUMAN, verification_pass=False)

    # Transition run to NEEDS_HUMAN
    state = transition_run(state, RunStatus.NEEDS_HUMAN)

    # Update state
    state.active_task_id = None
    state.touch()

    # Update plan in state to reflect task status change
    if state.plan is not None:
        for plan_task in state.plan.tasks:
            if plan_task.task_id == task.task_id:
                plan_task.status = task.status
                plan_task.attempt = task.attempt

    # Persist state
    persistence.save_run_state(state)
    if state.plan is not None:
        persistence.save_plan(state.plan)

    # Log human gate invocation
    persistence.save_run_log_entry(
        state.run_id,
        {
            "event": "human_gate_invoked",
            "run_id": state.run_id,
            "task_id": task.task_id,
            "reason": reason,
            "task_status": task.status.value,
            "run_status": state.status.value,
            "active_task_id": state.active_task_id,
            "attempt": task.attempt,
            "max_attempts": task.max_attempts,
            "timestamp": state.updated_at,
        },
    )

    return task, state


@workflows.activity(
    name="fsasm-persist-retry-state",
    retry_policy_max_attempts=1,
)
async def persist_retry_state_activity(
    state: RunState,
    plan: Plan,
    task: ChildTask,
    reason: str,
) -> tuple[RunState, Plan]:
    """
    Persist state when transitioning to READY for retry.

    Args:
        state: The RunState.
        plan: The Plan.
        task: The ChildTask being retried.
        reason: The reason for retry.

    Returns:
        Tuple of (updated RunState, updated Plan).
    """
    persistence = RuntimePersistence()

    # Update plan to reflect task status
    if plan is not None:
        for plan_task in plan.tasks:
            if plan_task.task_id == task.task_id:
                plan_task.status = task.status
                plan_task.attempt = task.attempt

    # Persist state
    persistence.save_run_state(state)
    if plan is not None:
        persistence.save_plan(plan)

    # Log retry
    persistence.save_run_log_entry(
        state.run_id,
        {
            "event": "task_retry",
            "run_id": state.run_id,
            "task_id": task.task_id,
            "attempt": task.attempt,
            "max_attempts": task.max_attempts,
            "reason": reason,
            "timestamp": state.updated_at,
        },
    )

    return state, plan


@workflows.activity(
    name="fsasm-validate-and-apply-human-decision",
    retry_policy_max_attempts=1,
)
async def validate_and_apply_human_decision_activity(
    decision: HumanDecision,
    task: ChildTask,
    state: RunState,
) -> tuple[ChildTask, RunState, HumanDecision]:
    """
    Validate and apply a human decision to the workflow state.

    Signal handlers must only mutate deterministic workflow-local data.
    No filesystem I/O in signal handlers. Validate and persist through domain/activity code.

    Validation:
    - decision.task_id must exactly match the currently gated task
    - decision.action must be RETRY_ONCE or ABORT

    RETRY_ONCE:
    - authorized human action only
    - apply_human_authorized_task_transition: NEEDS_HUMAN -> READY
    - apply_human_authorized_run_transition: NEEDS_HUMAN -> RUNNING
    - set max_attempts = attempt + 1
    - do NOT reset attempt
    - remove unresolved failure classification
    - transition back for exactly one additional execution

    ABORT:
    - explicit human-authorized task FAILED
    - apply_human_authorized_task_transition: NEEDS_HUMAN -> FAILED
    - apply_human_authorized_run_transition: NEEDS_HUMAN -> FAILED
    - active_task_id = None

    Args:
        decision: The HumanDecision from the signal.
        task: The ChildTask to apply the decision to.
        state: The current RunState.

    Returns:
        Tuple of (updated ChildTask, updated RunState, the decision for persistence).

    Raises:
        InvalidTransitionError: If validation fails or transition is invalid.
    """
    persistence = RuntimePersistence()

    # Validate decision.task_id matches the gated task
    if decision.task_id != task.task_id:
        raise InvalidTransitionError(
            from_status=task.status.value,
            to_status=TaskStatus.NEEDS_HUMAN.value,
            entity_type="ChildTask",
            entity_id=task.task_id,
            reason=f"Human decision task_id '{decision.task_id}' does not match gated task '{task.task_id}'",
        )

    # Validate task is in NEEDS_HUMAN state
    if task.status != TaskStatus.NEEDS_HUMAN:
        raise InvalidTransitionError(
            from_status=task.status.value,
            to_status=TaskStatus.NEEDS_HUMAN.value,
            entity_type="ChildTask",
            entity_id=task.task_id,
            reason=f"Task must be NEEDS_HUMAN to apply human decision, got {task.status.value}",
        )

    # Validate run is in NEEDS_HUMAN state
    if state.status != RunStatus.NEEDS_HUMAN:
        raise InvalidTransitionError(
            from_status=state.status.value,
            to_status=RunStatus.NEEDS_HUMAN.value,
            entity_type="RunState",
            entity_id=state.run_id,
            reason=f"Run must be NEEDS_HUMAN to apply human decision, got {state.status.value}",
        )

    if decision.action == HumanDecisionAction.RETRY_ONCE:
        # Apply human-authorized task transition: NEEDS_HUMAN -> READY
        task = apply_human_authorized_task_transition(
            task, TaskStatus.READY, new_max_attempts=task.attempt + 1
        )

        # Apply human-authorized run transition: NEEDS_HUMAN -> RUNNING
        state = apply_human_authorized_run_transition(state, RunStatus.RUNNING)

        # Remove from failed_task_ids since we're retrying
        if task.task_id in state.failed_task_ids:
            state.failed_task_ids.remove(task.task_id)

        # Update plan
        if state.plan is not None:
            for plan_task in state.plan.tasks:
                if plan_task.task_id == task.task_id:
                    plan_task.status = task.status
                    plan_task.max_attempts = task.max_attempts

        # Persist state
        state.touch()
        persistence.save_run_state(state)
        if state.plan is not None:
            persistence.save_plan(state.plan)

        # Persist Human Gate audit evidence
        audit_evidence = EvidenceRecord(
            evidence_id=f"evidence-human-gate-retry-{state.run_id}-{task.task_id}",
            run_id=state.run_id,
            task_id=task.task_id,
            kind="human_gate_audit",
            source="fsasm_milestone_four_workflow",
            payload={
                "action": "RETRY_ONCE",
                "reason": decision.reason,
                "task_id": task.task_id,
                "attempt_before": task.attempt,
                "max_attempts_before": task.attempt,
                "max_attempts_after": task.max_attempts,
                "task_status_before": "NEEDS_HUMAN",
                "task_status_after": task.status.value,
                "run_status_before": "NEEDS_HUMAN",
                "run_status_after": state.status.value,
                "active_task_id": state.active_task_id,
            },
        )
        persistence.save_evidence(audit_evidence)

        # Log RETRY_ONCE decision
        persistence.save_run_log_entry(
            state.run_id,
            {
                "event": "human_decision_retry_once",
                "run_id": state.run_id,
                "task_id": task.task_id,
                "action": "RETRY_ONCE",
                "reason": decision.reason,
                "new_max_attempts": task.max_attempts,
                "current_attempt": task.attempt,
                "timestamp": state.updated_at,
            },
        )

    elif decision.action == HumanDecisionAction.ABORT:
        # Apply human-authorized task transition: NEEDS_HUMAN -> FAILED
        task = apply_human_authorized_task_transition(task, TaskStatus.FAILED)

        # Apply human-authorized run transition: NEEDS_HUMAN -> FAILED
        state = apply_human_authorized_run_transition(state, RunStatus.FAILED)

        # Ensure in failed_task_ids
        if task.task_id not in state.failed_task_ids:
            state.failed_task_ids.append(task.task_id)

        # Ensure active_task_id is None
        state.active_task_id = None

        # Update plan
        if state.plan is not None:
            for plan_task in state.plan.tasks:
                if plan_task.task_id == task.task_id:
                    plan_task.status = task.status
                    plan_task.attempt = task.attempt

        # Persist state
        state.touch()
        persistence.save_run_state(state)
        if state.plan is not None:
            persistence.save_plan(state.plan)

        # Persist Human Gate audit evidence
        audit_evidence = EvidenceRecord(
            evidence_id=f"evidence-human-gate-abort-{state.run_id}-{task.task_id}",
            run_id=state.run_id,
            task_id=task.task_id,
            kind="human_gate_audit",
            source="fsasm_milestone_four_workflow",
            payload={
                "action": "ABORT",
                "reason": decision.reason,
                "task_id": task.task_id,
                "attempt": task.attempt,
                "max_attempts": task.max_attempts,
                "task_status_before": "NEEDS_HUMAN",
                "task_status_after": task.status.value,
                "run_status_before": "NEEDS_HUMAN",
                "run_status_after": state.status.value,
                "active_task_id": state.active_task_id,
            },
        )
        persistence.save_evidence(audit_evidence)

        # Log ABORT decision
        persistence.save_run_log_entry(
            state.run_id,
            {
                "event": "human_decision_abort",
                "run_id": state.run_id,
                "task_id": task.task_id,
                "action": "ABORT",
                "reason": decision.reason,
                "run_status": state.status.value,
                "active_task_id": state.active_task_id,
                "timestamp": state.updated_at,
            },
        )

    return task, state, decision


@workflows.activity(
    name="fsasm-persist-final-m4-state",
    retry_policy_max_attempts=1,
)
async def persist_final_m4_state_activity(
    state: RunState,
    plan: Plan,
    executed_task_ids: list[str],
    verification_results: dict[str, VerificationResult],
    all_evidence_records: list[EvidenceRecord],
    planner_metadata: PlannerMetadata,
    human_gate_invoked: bool,
    human_gate_reason: str | None,
    human_decision: HumanDecision | None = None,
) -> tuple[RunState, int]:
    """
    Persist the final M4 run state with execution results.

    For M4:
    - Only TASK-001 is executed
    - TASK-002 and TASK-003 remain PENDING
    - On successful M4 completion: TASK-001 = PASSED, TASK-002/003 = PENDING, run = RUNNING, active_task_id = None
    - A PASSED task must never exist in both completed and failed collections
    - A NEEDS_HUMAN task is NOT completed
    - Evidence count must match actual persisted evidence records

    Creates final evidence and logs.
    """
    persistence = RuntimePersistence()

    # Ensure active_task_id is None
    state.active_task_id = None

    # Create final execution evidence
    execution_evidence = EvidenceRecord(
        evidence_id=f"evidence-m4-execution-{state.run_id}",
        run_id=state.run_id,
        task_id=None,
        kind="m4_execution_summary",
        source="fsasm_milestone_four_workflow",
        payload={
            "executed_task_ids": executed_task_ids,
            "verification_statuses": {
                tid: vr.status.value for tid, vr in verification_results.items()
            },
            "verification_checks": {
                tid: [
                    {"name": c.check_name, "passed": c.passed, "message": c.message}
                    for c in vr.checks
                ]
                for tid, vr in verification_results.items()
            },
            "planner_provider": planner_metadata.provider,
            "planner_model_call_count": planner_metadata.model_call_count,
            "human_gate_invoked": human_gate_invoked,
            "human_gate_reason": human_gate_reason,
            "human_decision": human_decision.model_dump() if human_decision else None,
        },
    )
    persistence.save_evidence(execution_evidence)

    # Save final state
    state.touch()
    persistence.save_run_state(state)

    # Save final plan
    persistence.save_plan(plan)

    # Log final result
    persistence.save_run_log_entry(
        state.run_id,
        {
            "event": "m4_execution_completed",
            "run_id": state.run_id,
            "executed_task_ids": executed_task_ids,
            "final_run_status": state.status.value,
            "final_task_statuses": {t.task_id: t.status.value for t in plan.tasks},
            "verification_statuses": {
                tid: vr.status.value for tid, vr in verification_results.items()
            },
            "human_gate_invoked": human_gate_invoked,
            "human_gate_reason": human_gate_reason,
            "human_decision": human_decision.model_dump() if human_decision else None,
            "timestamp": state.updated_at,
        },
    )

    # Count ALL persisted evidence records to get authoritative count
    persisted_evidence = persistence.load_all_evidence(state.run_id)
    final_evidence_count = len(persisted_evidence)

    return state, final_evidence_count


# =============================================================================
# WORKFLOW
# =============================================================================


@workflows.workflow.define(
    name="fsasm-milestone-four",
    workflow_display_name="FS-ASM Milestone Four",
    workflow_description=(
        "FS-ASM Milestone 4: Bounded Retry + Human Gate. "
        "Proves: PENDING -> READY -> RUNNING -> PASSED/FAILED -> READY (retry) -> NEEDS_HUMAN. "
        "Demonstrates bounded retry with Human Gate escalation when retries exhausted. "
        "Uses @workflow.signal and workflow.wait_condition() for real durable Human Gate."
    ),
    enforce_determinism=True,
)
class FsasmMilestoneFourWorkflow:
    """
    FS-ASM Milestone Four Workflow.

    This workflow demonstrates:
    1. Bounded retry: FAILED tasks can retry up to task.max_attempts times
    2. Real durable Human Gate using @workflow.signal and workflow.wait_condition()
    3. Typed human decisions (RETRY_ONCE, ABORT)
    4. Proper execution-attempt semantics
    5. Exactly ONE ChildTask execution (TASK-001 only)

    Control flow:
    1. Validate configuration
    2. Create/normalize input
    3. Planner activity (Mistral or Stub backend)
    4. Persist initial state (PLANNED -> RUNNING)
    5. Set task.max_attempts from workflow config (authoritative budget)
    6. Execute ONE task (TASK-001 only) with retry loop:
       a. Prepare task (READY -> RUNNING, increments attempt exactly once)
       b. Execute task (produces ExecutorOutput)
       c. Validate ExecutorOutput provenance
       d. Convert ExecutorOutput to EvidenceRecord(s)
       e. Verify task execution
       f. If PASS: Finalize task as PASSED, break
       g. If FAIL: Persist FAILED state durably
          - Check retry budget (using task.can_retry())
          - If budget remains: Transition to READY (NO attempt increment), persist, loop back
          - If budget exhausted: Transition task AND run to NEEDS_HUMAN, wait for signal
    7. On NEEDS_HUMAN: Wait for human decision signal (RETRY_ONCE or ABORT)
    8. Validate and apply human decision through domain/activity code
    9. If RETRY_ONCE: Continue retry loop with exactly one more execution
    10. If ABORT: Terminate with task FAILED, run FAILED
    11. Persist final state
    12. Return structured result

    Key invariants:
    - Only TASK-001 is executed; TASK-002 and TASK-003 remain PENDING
    - attempt increments exactly once on READY -> RUNNING (BEFORE Executor execution)
    - FAILED -> READY does NOT increment attempt
    - All state transitions use transition API or human-authorized domain operations
    - Evidence is separate from ExecutorOutput
    - Verifier receives EvidenceRecord, not ExecutorOutput
    - NEEDS_HUMAN state is persisted for BOTH task AND run BEFORE waiting for signal
    - Human decisions are typed, validated, and persisted
    - success field represents successful completion of M4 task path (not run == PASSED)
    - ALL filesystem I/O happens in activities, not in workflow code
    """

    def __init__(self):
        self.human_decision: HumanDecision | None = None
        self.human_decision_consumed: bool = False

    @workflows.workflow.signal(
        name="human_decision",
        description="Signal to provide human decision for Human Gate (RETRY_ONCE or ABORT).",
    )
    async def receive_human_decision(self, signal_data: HumanDecisionSignal) -> None:
        """
        Receive human decision signal.

        Signal handlers must only mutate deterministic workflow-local data.
        No filesystem I/O in signal handlers.
        """
        self.human_decision = HumanDecision(
            task_id=signal_data.task_id,
            action=signal_data.action,
            reason=signal_data.reason,
        )
        self.human_decision_consumed = False

    @workflows.workflow.entrypoint
    async def run(self, input: WorkflowInput) -> WorkflowOutput:
        """
        Entry point for the FS-ASM milestone four workflow.

        Args:
            input: WorkflowInput with goal, optional run_id, backend configs, and retry settings.

        Returns:
            Structured result with run_id, executed task info, verification statuses, and human gate info.
        """
        # Step 1: Validate configuration
        planner_config, executor_config = await validate_config_activity(input)

        # Step 2: Create/normalize input
        goal_input = await create_input_activity(input)

        # Step 3: Planner activity (selected backend)
        planner_output = await plan_activity(goal_input, planner_config)

        # Step 4: Persist initial state (PLANNED -> RUNNING)
        # This also transitions to RUNNING and persists everything
        plan, state = await persist_initial_state_activity(planner_output, goal_input)

        # Step 5: Set authoritative task.max_attempts from workflow config
        plan = await set_task_max_attempts_activity(plan, input.max_retries_per_task)
        state.plan = plan

        # Track execution results
        executed_task_ids: list[str] = []
        passed_task_ids: list[str] = []
        failed_task_ids: list[str] = []
        needs_human_task_ids: list[str] = []
        verification_results: dict[str, VerificationResult] = {}
        all_evidence_records: list[EvidenceRecord] = []

        human_gate_invoked = False
        human_gate_reason: str | None = None
        final_human_decision: HumanDecision | None = None
        executor_output = None

        # Step 6: Execute ONE task with retry loop (TASK-001 only)
        completed_task_ids = list(state.completed_task_ids)

        # Find first eligible task (TASK-001 only)
        task = await find_next_ready_task_activity(plan, completed_task_ids)

        if task is not None:
            # Track that we're executing this task
            executed_task_ids.append(task.task_id)

            # Retry loop
            while True:
                # Prepare task (READY -> RUNNING)
                # This increments task.attempt by 1 exactly once BEFORE Executor execution
                state, task = await prepare_task_activity(state, task)
                plan = state.plan if state.plan is not None else plan

                # Execute task - pass current attempt for stub deterministic failure
                executor_output = await execute_task_activity(
                    task, state.run_id, executor_config, attempt=task.attempt
                )

                # Validate provenance
                await validate_executor_output_provenance_activity(
                    executor_output, task.task_id, state.run_id
                )

                # Convert to evidence - pass attempt for per-attempt evidence
                evidence_counter = len(all_evidence_records)
                task_evidence_records = (
                    await convert_executor_output_to_evidence_activity(
                        executor_output, task, evidence_counter, attempt=task.attempt
                    )
                )
                all_evidence_records.extend(task_evidence_records)

                # Verify task execution
                verification_result = await verify_task_execution_activity(
                    state.run_id, task, task_evidence_records
                )
                verification_results[task.task_id] = verification_result

                # Check verification result
                if verification_result.status == VerificationResultStatus.PASS:
                    # Task passed - finalize as PASSED
                    state, task = await finalize_task_activity(
                        state, task, verification_result, task_evidence_records
                    )
                    passed_task_ids.append(task.task_id)
                    completed_task_ids.append(task.task_id)
                    plan = state.plan if state.plan is not None else plan
                    break  # Exit retry loop on success

                else:
                    # Task failed - persist FAILED state durably BEFORE retry check
                    task, state, _ = await persist_failure_state_activity(
                        task,
                        state,
                        verification_result,
                        task_evidence_records,
                        task.attempt,
                    )
                    plan = state.plan if state.plan is not None else plan

                    # Check retry budget using authoritative task.max_attempts
                    can_retry, reason = await check_retry_budget_activity(task)

                    if can_retry:
                        # DO NOT increment attempt here - it was already incremented on READY->RUNNING
                        # Transition to READY for retry
                        task = transition_task(task, TaskStatus.READY)

                        # Persist retry state through activity
                        state, plan = await persist_retry_state_activity(
                            state, plan, task, reason
                        )

                        # Continue to retry this task
                        continue

                    else:
                        # Retry budget exhausted - transition to NEEDS_HUMAN (Human Gate)
                        human_gate_invoked = True
                        human_gate_reason = reason

                        # Transition to NEEDS_HUMAN (both task AND run)
                        # BEFORE waiting, filesystem MUST durably contain NEEDS_HUMAN state
                        task, state = await transition_to_needs_human_activity(
                            task, state, reason
                        )
                        needs_human_task_ids.append(task.task_id)
                        # DO NOT add to completed_task_ids - NEEDS_HUMAN is NOT completed
                        plan = state.plan if state.plan is not None else plan

                        # Clear the workflow-local pending decision before waiting
                        # A previous RETRY_ONCE must never satisfy a later wait_condition()
                        self.human_decision_consumed = True
                        self.human_decision = None

                        # Set waiting flag and wait for signal
                        # Wait for human decision signal
                        await workflows.workflow.wait_condition(
                            lambda: self.human_decision is not None
                        )

                        # Get the decision and clear it immediately
                        # Consume Human Gate signals exactly once
                        decision = self.human_decision
                        self.human_decision = None

                        if decision is not None:
                            # Validate and apply human decision through domain/activity code
                            (
                                task,
                                state,
                                applied_decision,
                            ) = await validate_and_apply_human_decision_activity(
                                decision, task, state
                            )
                            plan = state.plan if state.plan is not None else plan
                            final_human_decision = applied_decision

                            if decision.action == HumanDecisionAction.ABORT:
                                # ABORT: task FAILED, run FAILED, active_task_id = None
                                # Already handled in validate_and_apply_human_decision_activity
                                if task.task_id not in failed_task_ids:
                                    failed_task_ids.append(task.task_id)
                                break  # Exit retry loop on ABORT

                            elif decision.action == HumanDecisionAction.RETRY_ONCE:
                                # RETRY_ONCE: max_attempts = attempt + 1, do NOT reset attempt
                                # Remove from needs_human_task_ids since we're retrying
                                if task.task_id in needs_human_task_ids:
                                    needs_human_task_ids.remove(task.task_id)
                                # Continue to retry loop - will execute once more
                                # task is already READY from validate_and_apply_human_decision_activity
                                continue

                        else:
                            # No decision received, stay in NEEDS_HUMAN
                            break

        # Step 7: Persist final state
        final_state, final_evidence_count = await persist_final_m4_state_activity(
            state,
            plan,
            executed_task_ids,
            verification_results,
            all_evidence_records,
            planner_output.metadata,
            human_gate_invoked,
            human_gate_reason,
            final_human_decision,
        )

        # Determine success: successful completion of M4 task path
        # For M4, success means TASK-001 is PASSED (run may be RUNNING or FAILED)
        success = "TASK-001" in passed_task_ids

        # Step 8: Return structured result
        return WorkflowOutput(
            run_id=final_state.run_id,
            goal=final_state.goal,
            status=final_state.status.value,
            plan_id=plan.plan_id,
            task_count=len(plan.tasks),
            executed_task_ids=executed_task_ids,
            passed_task_ids=passed_task_ids,
            failed_task_ids=failed_task_ids,
            needs_human_task_ids=needs_human_task_ids,
            verification_statuses={
                tid: vr.status.value for tid, vr in verification_results.items()
            },
            verification_messages={
                tid: vr.message for tid, vr in verification_results.items()
            },
            evidence_count=final_evidence_count,
            created_at=final_state.created_at,
            updated_at=final_state.updated_at,
            success=success,
            human_gate_invoked=human_gate_invoked,
            human_gate_reason=human_gate_reason,
            human_decision={
                "task_id": final_human_decision.task_id,
                "action": final_human_decision.action.value
                if final_human_decision
                else None,
                "reason": final_human_decision.reason if final_human_decision else None,
            }
            if final_human_decision
            else None,
            # Planner metadata
            planner_provider=planner_output.metadata.provider,
            planner_model=planner_output.metadata.requested_model,
            planner_model_call_count=planner_output.metadata.model_call_count,
            # Executor metadata
            executor_provider=executor_output.metadata.provider
            if executor_output
            else "stub",
            executor_model_call_count=executor_output.metadata.model_call_count
            if executor_output
            else 0,
        )
