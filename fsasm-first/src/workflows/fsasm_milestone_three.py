"""FS-ASM Milestone Three Workflow - Executor + execution verification for ONE eligible ChildTask."""

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

logger = logging.getLogger(__name__)


# =============================================================================
# INPUT/OUTPUT MODELS
# =============================================================================


class WorkflowInput(BaseModel):
    """Input model for the FS-ASM milestone three workflow."""

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
        description="Backend to use for execution: 'stub' only for M3. Must be explicitly provided.",
    )
    executor_model_name: str | None = Field(
        default=None,
        description="Model name for executor backend (not used for STUB).",
    )


class WorkflowOutput(BaseModel):
    """Output model for the FS-ASM milestone three workflow."""

    run_id: str
    goal: str
    status: str
    plan_id: str
    task_count: int
    executed_task_id: str | None
    executed_task_status: str | None
    verification_status: str
    verification_message: str
    evidence_count: int
    created_at: str
    updated_at: str
    success: bool
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
    name="fsasm-create-m3-input",
    retry_policy_max_attempts=1,
)
async def create_input_activity(input_data: WorkflowInput) -> GoalInput:
    """
    Create and validate GoalInput from workflow input.
    """
    goal_input = GoalInput(goal=input_data.goal, run_id=input_data.run_id)
    return goal_input


@workflows.activity(
    name="fsasm-validate-m3-config",
    retry_policy_max_attempts=1,
)
async def validate_config_activity(
    input: WorkflowInput,
) -> tuple[PlannerConfig, ExecutorConfig]:
    """
    Validate workflow input and create PlannerConfig and ExecutorConfig.

    For M3, executor_backend must be STUB.
    """
    if input.executor_backend != ExecutorBackend.STUB:
        raise ConfigurationError(
            message=f"Milestone 3 only supports ExecutorBackend.STUB, got '{input.executor_backend}'",
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
    name="fsasm-find-first-ready-task",
    retry_policy_max_attempts=1,
)
async def find_first_ready_task_activity(
    plan: Plan, completed_task_ids: list[str]
) -> ChildTask:
    """
    Find the first READY task in the plan.

    For M3, we execute exactly ONE eligible task.
    Eligible means:
    - PENDING or READY status
    - All dependencies are in completed_task_ids (satisfied)
    We select the first one by sequence order.

    Args:
        plan: The Plan with tasks.
        completed_task_ids: List of task IDs that have been completed.

    Returns:
        The first eligible task (transitioned to READY).
    """
    from fsasm.transitions import transition_task

    # Find first task that is PENDING/READY and has all dependencies satisfied
    for task in sorted(plan.tasks, key=lambda t: t.sequence):
        if task.status in [TaskStatus.PENDING, TaskStatus.READY]:
            # Check if all dependencies are completed
            all_deps_satisfied = all(
                dep in completed_task_ids for dep in task.dependencies
            )
            if not all_deps_satisfied:
                continue  # Skip tasks with unmet dependencies

            # Transition PENDING -> READY if needed
            if task.status == TaskStatus.PENDING:
                task = transition_task(task, TaskStatus.READY)
            return task

    # If no eligible tasks found, raise error
    raise ValueError("No eligible tasks found in plan")


@workflows.activity(
    name="fsasm-persist-m3-initial-state",
    retry_policy_max_attempts=1,
)
async def persist_initial_state_activity(
    planner_output: PlannerOutput,
    goal_input: GoalInput,
) -> tuple[Plan, RunState]:
    """
    Persist the plan, planner proposal (as evidence), and initial run state to filesystem.

    Creates initial RunState with PLANNED status (from M2).
    Then transitions to RUNNING for M3 execution.
    """
    from fsasm.transitions import transition_run

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

    # Transition PLANNED -> RUNNING in activity
    transition_run(state, RunStatus.RUNNING)

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
        source="fsasm_milestone_three_workflow",
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
            "event": "m3_run_started",
            "run_id": run_id,
            "goal": goal_input.goal,
            "status": RunStatus.RUNNING.value,
            "planner_provider": metadata.provider,
            "timestamp": state.created_at,
        },
    )

    return plan, state


@workflows.activity(
    name="fsasm-persist-m3-final-state",
    retry_policy_max_attempts=1,
)
async def persist_final_m3_state_activity(
    state: RunState,
    plan: Plan,
    executed_task_id: str | None,
    verification_result: VerificationResult,
    all_evidence_records: list[EvidenceRecord],
    planner_metadata: PlannerMetadata,
) -> RunState:
    """
    Persist the final M3 run state with execution results.

    For M3:
    - Exactly one task was executed
    - The run remains RUNNING (not PASSED or FAILED)
    - Other tasks remain PENDING

    Creates final evidence and logs.
    """
    persistence = RuntimePersistence()

    # Create final execution evidence
    execution_evidence = EvidenceRecord(
        evidence_id=f"evidence-m3-execution-{state.run_id}",
        run_id=state.run_id,
        task_id=None,
        kind="m3_execution_summary",
        source="fsasm_milestone_three_workflow",
        payload={
            "executed_task_id": executed_task_id,
            "verification_status": verification_result.status.value,
            "verification_checks": [
                {"name": c.check_name, "passed": c.passed, "message": c.message}
                for c in verification_result.checks
            ],
            "total_evidence_count": len(all_evidence_records),
            "planner_provider": planner_metadata.provider,
            "planner_model_call_count": planner_metadata.model_call_count,
        },
    )
    persistence.save_evidence(execution_evidence)
    all_evidence_records.append(execution_evidence)

    # Save final state
    state.touch()
    persistence.save_run_state(state)

    # Save final plan
    persistence.save_plan(plan)

    # Log final result
    persistence.save_run_log_entry(
        state.run_id,
        {
            "event": "m3_execution_completed",
            "run_id": state.run_id,
            "executed_task_id": executed_task_id,
            "final_run_status": state.status.value,
            "verification_status": verification_result.status.value,
            "verification_message": verification_result.message,
            "evidence_count": len(all_evidence_records),
            "planner_provider": planner_metadata.provider,
            "planner_model_call_count": planner_metadata.model_call_count,
            "timestamp": state.updated_at,
        },
    )

    return state


# =============================================================================
# WORKFLOW
# =============================================================================


@workflows.workflow.define(
    name="fsasm-milestone-three",
    workflow_display_name="FS-ASM Milestone Three",
    workflow_description=(
        "FS-ASM Milestone 3: Executor + execution verification for ONE eligible ChildTask. "
        "Proves: PENDING -> READY -> RUNNING -> PASSED/FAILED. "
        "Exactly one task executed, others remain PENDING. RunState remains RUNNING."
    ),
    enforce_determinism=True,
)
class FsasmMilestoneThreeWorkflow:
    """
    FS-ASM Milestone Three Workflow.

    Control flow:
    1. Validate configuration (executor_backend must be STUB for M3)
    2. Create/normalize input
    3. Planner activity (Mistral or Stub backend)
    4. Persist initial state (PLANNED -> RUNNING)
    5. Find first eligible task and transition to READY
    6. Prepare task (RUNNING status, active_task_id set, persist state)
    7. Execute task (produces ExecutorOutput)
    8. Validate ExecutorOutput provenance
    9. Convert ExecutorOutput to EvidenceRecord(s)
    10. Verify task execution
    11. Finalize task (PASSED/FAILED, clear active_task_id, persist)
    12. Persist final state
    13. Return structured result

    Key invariants:
    - Exactly ONE task is executed
    - After execution: executed task = PASSED or FAILED, others remain PENDING
    - RunState remains RUNNING (not transitioned to PASSED/FAILED)
    - All state transitions use transition API
    - Evidence is separate from ExecutorOutput
    - Verifier receives EvidenceRecord, not ExecutorOutput
    """

    @workflows.workflow.entrypoint
    async def run(self, input: WorkflowInput) -> WorkflowOutput:
        """
        Entry point for the FS-ASM milestone three workflow.

        Args:
            input: WorkflowInput with goal, optional run_id, and backend configs.

        Returns:
            Structured result with run_id, executed task info, and verification status.
        """
        # Step 1: Validate configuration
        planner_config, executor_config = await validate_config_activity(input)

        # Step 2: Create/normalize input
        goal_input = await create_input_activity(input)

        # Step 3: Planner activity (selected backend)
        planner_output = await plan_activity(goal_input, planner_config)

        # Step 4: Persist initial state (PLANNED -> RUNNING)
        plan, state = await persist_initial_state_activity(planner_output, goal_input)

        # Step 5: Find first eligible task (PENDING -> READY)
        task = await find_first_ready_task_activity(plan, state.completed_task_ids)

        # Step 6: Prepare task (READY -> RUNNING, set active_task_id, persist)
        state, task = await prepare_task_activity(state, task)

        # Update plan reference to use state.plan (authoritative after prepare)
        plan = state.plan if state.plan is not None else plan

        # Remember the executed task ID for final output
        executed_task_id = task.task_id

        # Step 7: Execute task (produces ExecutorOutput)
        executor_output = await execute_task_activity(
            task, state.run_id, executor_config
        )

        # Step 8: Validate ExecutorOutput provenance
        await validate_executor_output_provenance_activity(
            executor_output, task.task_id, state.run_id
        )

        # Step 9: Convert ExecutorOutput to EvidenceRecord(s)
        # Use a deterministic counter (0 for first/only execution)
        evidence_counter = 0
        task_evidence_records = await convert_executor_output_to_evidence_activity(
            executor_output, task, evidence_counter
        )

        # Step 10: Verify task execution
        verification_result = await verify_task_execution_activity(
            state.run_id, task, task_evidence_records
        )

        # Step 11: Finalize task (update status, clear active_task_id, persist)
        state, task = await finalize_task_activity(
            state, task, verification_result, task_evidence_records
        )

        # Update plan reference to use state.plan (authoritative after finalize)
        plan = state.plan if state.plan is not None else plan

        # Step 12: Collect all evidence and persist final state
        # For M3, we have: proposal evidence + task evidence
        all_evidence_records = [
            EvidenceRecord(
                evidence_id=f"evidence-proposal-{state.run_id}",
                run_id=state.run_id,
                task_id=None,
                kind="planner_proposal",
                source="fsasm_milestone_three_workflow",
                payload={
                    "proposal": planner_output.proposal.model_dump(),
                    "metadata": planner_output.metadata.model_dump(),
                },
            )
        ] + task_evidence_records

        final_state = await persist_final_m3_state_activity(
            state,
            plan,
            executed_task_id,
            verification_result,
            all_evidence_records,
            planner_output.metadata,
        )

        # Step 13: Return structured result
        return WorkflowOutput(
            run_id=final_state.run_id,
            goal=final_state.goal,
            status=final_state.status.value,
            plan_id=plan.plan_id,
            task_count=len(plan.tasks),
            executed_task_id=executed_task_id,
            executed_task_status=task.status.value,
            verification_status=verification_result.status.value,
            verification_message=verification_result.message,
            evidence_count=len(all_evidence_records),
            created_at=final_state.created_at,
            updated_at=final_state.updated_at,
            success=verification_result.status == VerificationResultStatus.PASS,
            # Planner metadata
            planner_provider=planner_output.metadata.provider,
            planner_model=planner_output.metadata.requested_model,
            planner_model_call_count=planner_output.metadata.model_call_count,
            # Executor metadata
            executor_provider=executor_output.metadata.provider,
            executor_model_call_count=executor_output.metadata.model_call_count,
        )
