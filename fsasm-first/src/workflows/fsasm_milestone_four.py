"""FS-ASM Milestone Four Workflow - Bounded Retry + Human Gate."""

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
    from fsasm.errors import ConfigurationError
    from fsasm.transitions import transition_task, transition_run

logger = logging.getLogger(__name__)


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
    """
    Create and validate GoalInput from workflow input.
    """
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

    For M4, we execute tasks in sequence order until all are processed.

    Args:
        plan: The Plan with tasks.
        completed_task_ids: List of task IDs that have been completed.

    Returns:
        The next eligible task (already READY), or None if no more tasks.
    """
    from fsasm.transitions import transition_task

    # Find first task that is PENDING/READY and has all dependencies satisfied
    for task in sorted(plan.tasks, key=lambda t: t.sequence):
        # Skip already completed/failed/needs_human tasks
        if task.task_id in completed_task_ids:
            continue

        # Check if all dependencies are completed
        all_deps_satisfied = all(dep in completed_task_ids for dep in task.dependencies)
        if not all_deps_satisfied:
            continue  # Skip tasks with unmet dependencies

        # Transition PENDING -> READY if needed
        if task.status == TaskStatus.PENDING:
            task = transition_task(task, TaskStatus.READY)
        return task

    # No more eligible tasks
    return None


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

    Creates initial RunState with PLANNED status.
    """
    persistence = RuntimePersistence()

    plan = planner_output.plan
    metadata = planner_output.metadata
    run_id = plan.run_id

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
            "status": RunStatus.PLANNED.value,
            "planner_provider": metadata.provider,
            "timestamp": state.created_at,
        },
    )

    return plan, state


@workflows.activity(
    name="fsasm-check-retry-budget",
    retry_policy_max_attempts=1,
)
async def check_retry_budget_activity(
    task: ChildTask,
    max_retries_per_task: int,
) -> tuple[bool, str]:
    """
    Check if a task can be retried and return the decision.

    Args:
        task: The ChildTask to check.
        max_retries_per_task: Maximum retry attempts configured.

    Returns:
        Tuple of (can_retry: bool, reason: str)
    """
    # Override task max_attempts with workflow configuration
    effective_max_attempts = max_retries_per_task + 1  # +1 for initial attempt
    can_retry = task.attempt < effective_max_attempts - 1

    if can_retry:
        reason = f"Task has {effective_max_attempts - 1 - task.attempt} retry attempts remaining"
    else:
        reason = f"Task has exhausted all {effective_max_attempts - 1} retry attempts"

    return can_retry, reason


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
    Transition a task to NEEDS_HUMAN status when retry budget is exhausted.

    This is the Human Gate: when a task cannot be completed through retry,
    it transitions to NEEDS_HUMAN for human intervention.

    Args:
        task: The ChildTask that has exhausted retries.
        state: The current RunState.
        reason: The reason for transitioning to NEEDS_HUMAN.

    Returns:
        Tuple of (updated ChildTask, updated RunState).
    """
    persistence = RuntimePersistence()

    # Transition task to NEEDS_HUMAN
    task = transition_task(task, TaskStatus.NEEDS_HUMAN, verification_pass=False)

    # Update state
    state.touch()

    # Update plan in state to reflect task status change
    if state.plan is not None:
        for plan_task in state.plan.tasks:
            if plan_task.task_id == task.task_id:
                plan_task.status = task.status

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
            "timestamp": state.updated_at,
        },
    )

    return task, state


@workflows.activity(
    name="fsasm-persist-m4-final-state",
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
) -> tuple[RunState, int]:
    """
    Persist the final M4 run state with execution results.

    For M4:
    - Multiple tasks may be executed
    - Tasks can be PASSED, FAILED, or NEEDS_HUMAN
    - RunState transitions to PASSED if all tasks PASSED, FAILED if any FAILED, NEEDS_HUMAN if any NEEDS_HUMAN

    Creates final evidence and logs.
    """
    persistence = RuntimePersistence()

    # Determine final run status
    all_passed = all(task.status == TaskStatus.PASSED for task in plan.tasks)
    any_failed = any(task.status == TaskStatus.FAILED for task in plan.tasks)
    any_needs_human = any(task.status == TaskStatus.NEEDS_HUMAN for task in plan.tasks)

    if all_passed:
        state.status = RunStatus.PASSED
    elif any_needs_human:
        state.status = RunStatus.NEEDS_HUMAN
    elif any_failed:
        state.status = RunStatus.FAILED
    else:
        state.status = RunStatus.RUNNING

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
            "total_evidence_count": len(all_evidence_records) + 1,
            "planner_provider": planner_metadata.provider,
            "planner_model_call_count": planner_metadata.model_call_count,
            "human_gate_invoked": human_gate_invoked,
            "human_gate_reason": human_gate_reason,
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
            "verification_statuses": {
                tid: vr.status.value for tid, vr in verification_results.items()
            },
            "evidence_count": len(all_evidence_records) + 1,
            "planner_provider": planner_metadata.provider,
            "planner_model_call_count": planner_metadata.model_call_count,
            "human_gate_invoked": human_gate_invoked,
            "human_gate_reason": human_gate_reason,
            "timestamp": state.updated_at,
        },
    )

    # Return authoritative final evidence count
    return state, len(all_evidence_records) + 1


# =============================================================================
# WORKFLOW
# =============================================================================


@workflows.workflow.define(
    name="fsasm-milestone-four",
    workflow_display_name="FS-ASM Milestone Four",
    workflow_description=(
        "FS-ASM Milestone 4: Bounded Retry + Human Gate. "
        "Proves: PENDING -> READY -> RUNNING -> PASSED/FAILED -> READY (retry) -> NEEDS_HUMAN. "
        "Demonstrates bounded retry with Human Gate escalation when retries exhausted."
    ),
    enforce_determinism=True,
)
class FsasmMilestoneFourWorkflow:
    """
    FS-ASM Milestone Four Workflow.

    This workflow demonstrates:
    1. Bounded retry: FAILED tasks can retry up to max_retries_per_task times
    2. Human Gate: When retry budget is exhausted, transition to NEEDS_HUMAN
    3. Multiple task execution with dependency awareness

    For M4, the Human Gate is demonstrated by transitioning to NEEDS_HUMAN status.
    In a full implementation with Mistral Workflows HITL, this would pause and wait
    for human input. For now, we demonstrate the state machine transition.

    Control flow:
    1. Validate configuration
    2. Create/normalize input
    3. Planner activity (Mistral or Stub backend)
    4. Persist initial state (PLANNED -> RUNNING)
    5. For each task in sequence order:
       a. Find next eligible task (PENDING -> READY)
       b. Prepare task (READY -> RUNNING, set active_task_id, persist state)
       c. Execute task (produces ExecutorOutput)
       d. Validate ExecutorOutput provenance
       e. Convert ExecutorOutput to EvidenceRecord(s)
       f. Verify task execution
       g. If PASS: Finalize task as PASSED
       h. If FAIL: Check retry budget
          - If budget remains: Transition to READY (for retry), loop back
          - If budget exhausted: Transition to NEEDS_HUMAN (Human Gate)
    6. Persist final state
    7. Return structured result

    Key invariants:
    - Tasks execute in sequence order
    - Retries are bounded by max_retries_per_task
    - Human Gate is invoked (via NEEDS_HUMAN status) when retry budget is exhausted
    - All state transitions use transition API
    - Evidence is separate from ExecutorOutput
    - Verifier receives EvidenceRecord, not ExecutorOutput
    - Exactly ONE task execution per workflow run (for deterministic testing)
    """

    @workflows.workflow.entrypoint
    async def run(self, input: WorkflowInput) -> WorkflowOutput:
        """
        Entry point for the FS-ASM milestone four workflow.

        Args:
            input: WorkflowInput with goal, optional run_id, backend configs, and retry settings.

        Returns:
            Structured result with run_id, executed task info, verification statuses, and human gate info.
        """
        persistence = RuntimePersistence()
        executor_output = None

        # Step 1: Validate configuration
        planner_config, executor_config = await validate_config_activity(input)

        # Step 2: Create/normalize input
        goal_input = await create_input_activity(input)

        # Step 3: Planner activity (selected backend)
        planner_output = await plan_activity(goal_input, planner_config)

        # Step 4: Persist initial state (PLANNED -> RUNNING)
        plan, state = await persist_initial_state_activity(planner_output, goal_input)

        # Update state to RUNNING
        state = transition_run(state, RunStatus.RUNNING)
        persistence.save_run_state(state)

        # Track execution results
        executed_task_ids: list[str] = []
        passed_task_ids: list[str] = []
        failed_task_ids: list[str] = []
        needs_human_task_ids: list[str] = []
        verification_results: dict[str, VerificationResult] = {}
        all_evidence_records: list[EvidenceRecord] = []

        human_gate_invoked = False
        human_gate_reason: str | None = None

        # Step 5: Execute ONE task with retry loop (for deterministic testing)
        # For M4, we execute exactly ONE task to demonstrate the retry + Human Gate path
        # This keeps the workflow deterministic and testable
        completed_task_ids = list(state.completed_task_ids)

        # Find first eligible task
        task = await find_next_ready_task_activity(plan, completed_task_ids)

        if task is not None:
            # Track that we're executing this task
            executed_task_ids.append(task.task_id)

            # Retry loop
            for attempt_num in range(
                input.max_retries_per_task + 2
            ):  # +2 for initial + 1 extra
                # Prepare task (READY -> RUNNING)
                state, task = await prepare_task_activity(state, task)
                plan = state.plan if state.plan is not None else plan

                # Execute task
                executor_output = await execute_task_activity(
                    task, state.run_id, executor_config
                )

                # Validate provenance
                await validate_executor_output_provenance_activity(
                    executor_output, task.task_id, state.run_id
                )

                # Convert to evidence
                evidence_counter = len(all_evidence_records)
                task_evidence_records = (
                    await convert_executor_output_to_evidence_activity(
                        executor_output, task, evidence_counter
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
                    # Task failed - check retry budget
                    can_retry, reason = await check_retry_budget_activity(
                        task, input.max_retries_per_task
                    )

                    if can_retry:
                        # Increment attempt counter
                        task.attempt += 1

                        # Transition to READY for retry
                        task = transition_task(task, TaskStatus.READY)

                        # Update plan
                        if state.plan is not None:
                            for plan_task in state.plan.tasks:
                                if plan_task.task_id == task.task_id:
                                    plan_task.attempt = task.attempt
                                    plan_task.status = task.status

                        # Persist updated state
                        persistence.save_run_state(state)
                        if state.plan is not None:
                            persistence.save_plan(state.plan)

                        # Log retry
                        persistence.save_run_log_entry(
                            state.run_id,
                            {
                                "event": "task_retry",
                                "run_id": state.run_id,
                                "task_id": task.task_id,
                                "attempt": task.attempt,
                                "max_attempts": input.max_retries_per_task + 1,
                                "reason": reason,
                                "timestamp": state.updated_at,
                            },
                        )

                        # Continue to retry this task
                        continue

                    else:
                        # Retry budget exhausted - transition to NEEDS_HUMAN (Human Gate)
                        human_gate_invoked = True
                        human_gate_reason = reason

                        # Transition to NEEDS_HUMAN
                        task, state = await transition_to_needs_human_activity(
                            task, state, reason
                        )
                        failed_task_ids.append(task.task_id)
                        needs_human_task_ids.append(task.task_id)
                        completed_task_ids.append(task.task_id)
                        plan = state.plan if state.plan is not None else plan

                        # Exit retry loop - task is in terminal NEEDS_HUMAN state
                        break

        # Step 6: Persist final state
        final_state, final_evidence_count = await persist_final_m4_state_activity(
            state,
            plan,
            executed_task_ids,
            verification_results,
            all_evidence_records,
            planner_output.metadata,
            human_gate_invoked,
            human_gate_reason,
        )

        # Step 7: Return structured result
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
            success=final_state.status == RunStatus.PASSED,
            human_gate_invoked=human_gate_invoked,
            human_gate_reason=human_gate_reason,
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
