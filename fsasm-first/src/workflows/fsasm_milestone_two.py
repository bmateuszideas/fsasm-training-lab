"""FS-ASM Milestone Two Workflow - Real Mistral Planner integration."""

import logging

import mistralai.workflows as workflows
from mistralai.workflows import workflow
from pydantic import BaseModel, Field

# Import fsasm modules - these are used in activities, not workflow code directly
# Mark them as pass-through for sandbox compatibility
with workflow.unsafe.imports_passed_through():
    from fsasm.models import (
        EvidenceRecord,
        GoalInput,
        Plan,
        PlannerBackend,
        PlannerConfig,
        PlannerMetadata,
        PlannerOutput,
        RunState,
        RunStatus,
        VerificationResult,
        VerificationResultStatus,
    )
    from fsasm.planner_activities import plan_activity
    from fsasm.verifier import DeterministicVerifier
    from fsasm.persistence import RuntimePersistence
    from fsasm.errors import ConfigurationError
    from fsasm.transitions import transition_run

logger = logging.getLogger(__name__)


# =============================================================================
# INPUT/OUTPUT MODELS
# =============================================================================


class WorkflowInput(BaseModel):
    """Input model for the FS-ASM milestone two workflow."""

    goal: str
    run_id: str | None = None
    planner_backend: PlannerBackend = Field(
        ...,
        description="Backend to use for planning: 'stub' or 'mistral' - MUST be explicitly provided.",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name for Mistral backend (required when backend='mistral').",
    )
    prompt_version: str = Field(default="v1.0", description="Prompt template version.")


class WorkflowOutput(BaseModel):
    """Output model for the FS-ASM milestone two workflow."""

    run_id: str
    goal: str
    status: str
    plan_id: str
    task_count: int
    task_ids: list[str]
    verification_status: str
    verification_message: str
    evidence_count: int
    created_at: str
    updated_at: str
    success: bool
    # Planner metadata
    planner_provider: str
    planner_model: str | None
    planner_prompt_version: str
    planner_model_call_count: int
    planner_invocation_count: int
    planner_input_tokens: int | None
    planner_output_tokens: int | None
    planner_total_tokens: int | None


# =============================================================================
# ACTIVITIES (I/O operations belong here, not in workflow code)
# =============================================================================


@workflows.activity(
    name="fsasm-create-input",
    retry_policy_max_attempts=1,
)
async def create_input_activity(input_data: WorkflowInput) -> GoalInput:
    """
    Create and validate GoalInput from workflow input.

    This is an activity because it performs I/O-like normalization.
    """
    goal_input = GoalInput(goal=input_data.goal, run_id=input_data.run_id)
    return goal_input


@workflows.activity(
    name="fsasm-validate-plan",
    retry_policy_max_attempts=1,
)
async def validate_plan_activity(plan: Plan) -> Plan:
    """
    Validate a plan (Pydantic validation happens automatically).

    This activity explicitly validates the plan structure.
    """
    # Pydantic already validated on construction
    # This is a placeholder for future validation logic
    if len(plan.tasks) != 3:
        raise ValueError(f"Plan must have exactly 3 tasks, got {len(plan.tasks)}")
    return plan


@workflows.activity(
    name="fsasm-validate-config",
    retry_policy_max_attempts=1,
)
async def validate_config_activity(input: WorkflowInput) -> PlannerConfig:
    """
    Validate workflow input and create PlannerConfig.

    Performs explicit configuration validation:
    - If backend='mistral', model_name must be provided
    - Returns serializable PlannerConfig for the workflow

    Raises:
        ConfigurationError: If configuration is invalid.
    """
    if input.planner_backend == PlannerBackend.MISTRAL:
        if not input.model_name:
            raise ConfigurationError(
                message="planner_backend='mistral' wymaga podania model_name",
                backend="mistral",
                missing_field="model_name",
            )

    return PlannerConfig(
        backend=input.planner_backend,
        model_name=input.model_name,
        model_version=None,
        prompt_version=input.prompt_version,
        max_tokens=4096,
        temperature=0.0,
    )


@workflows.activity(
    name="fsasm-persist-plan-and-state",
    retry_policy_max_attempts=3,
)
async def persist_plan_and_state_activity(
    planner_output: PlannerOutput,
    goal_input: GoalInput,
) -> tuple[Plan, RunState]:
    """
    Persist the plan, planner proposal (as evidence), and initial run state to filesystem.

    This is an activity because it performs filesystem I/O.
    Uses atomic writes for mutable state.
    Saves PlannerProposal as small structured evidence artifact.
    Transitions CREATED -> PLANNED here to avoid datetime.utcnow() in workflow body.
    """
    from fsasm.transitions import transition_run

    persistence = RuntimePersistence()

    plan = planner_output.plan
    metadata = planner_output.metadata
    run_id = plan.run_id

    # Create initial run state with CREATED status
    state = RunState(
        run_id=run_id,
        goal=goal_input.goal,
        status=RunStatus.CREATED,
        plan=plan,
        active_task_id=None,
        completed_task_ids=[],
        failed_task_ids=[],
    )

    # Transition CREATED -> PLANNED in activity (not workflow body)
    transition_run(state, RunStatus.PLANNED)

    # Save plan
    persistence.save_plan(plan)

    # Save state
    persistence.save_run_state(state)

    # Save planner proposal as evidence artifact (small structured data)
    proposal_evidence = EvidenceRecord(
        evidence_id=f"evidence-proposal-{run_id}",
        run_id=run_id,
        task_id=None,
        kind="planner_proposal",
        source="fsasm_milestone_two_workflow",
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
            "event": "run_created",
            "run_id": run_id,
            "goal": goal_input.goal,
            "status": RunStatus.CREATED.value,
            "planner_provider": metadata.provider,
            "planner_model": metadata.requested_model,
            "timestamp": state.created_at,
        },
    )

    return plan, state


@workflows.activity(
    name="fsasm-verify-run",
    retry_policy_max_attempts=1,
)
async def verify_run_activity(
    state: RunState, plan: Plan, evidence_records: list[EvidenceRecord]
) -> VerificationResult:
    """
    Verify the run using deterministic verifier with evidence.

    This is an activity because verification could later use an LLM.
    For milestone 2, it uses deterministic checks.

    Note: This is the FINAL verification that determines pass/fail status.
    Evidence records must already be persisted before calling this.
    """
    verifier = DeterministicVerifier()
    verification_result = verifier.verify_full_run(state, plan, evidence_records)
    return verification_result


@workflows.activity(
    name="fsasm-persist-evidence",
    retry_policy_max_attempts=3,
)
async def persist_evidence_activity(
    run_id: str,
    plan: Plan,
) -> list[EvidenceRecord]:
    """
    Persist evidence records separately from state.

    This is an activity because it performs filesystem I/O.
    Creates evidence for the plan and run state only (pre-verification).
    Final verification evidence is created after final verification passes.
    """
    persistence = RuntimePersistence()

    evidence_records: list[EvidenceRecord] = []

    # Create evidence for the plan
    plan_evidence = EvidenceRecord(
        evidence_id=f"evidence-plan-{run_id}",
        run_id=run_id,
        task_id=None,
        kind="plan",
        source="fsasm_milestone_two_workflow",
        payload={
            "plan_id": plan.plan_id,
            "task_count": len(plan.tasks),
            "task_ids": [t.task_id for t in plan.tasks],
        },
    )
    persistence.save_evidence(plan_evidence)
    evidence_records.append(plan_evidence)

    # Create evidence for the run state
    state_evidence = EvidenceRecord(
        evidence_id=f"evidence-state-{run_id}",
        run_id=run_id,
        task_id=None,
        kind="run_state",
        source="fsasm_milestone_two_workflow",
        payload={
            "run_id": run_id,
            "status": "PLANNED",
            "goal": plan.goal,
        },
    )
    persistence.save_evidence(state_evidence)
    evidence_records.append(state_evidence)

    return evidence_records


@workflows.activity(
    name="fsasm-persist-final-state",
    retry_policy_max_attempts=3,
)
async def persist_final_state_activity(
    state: RunState,
    verification_result: VerificationResult,
    evidence_records: list[EvidenceRecord],
    planner_metadata: PlannerMetadata,
) -> RunState:
    """
    Persist the final run state, create verification evidence, and complete the run.

    This is an activity because it performs filesystem I/O.
    Creates final verification evidence record that documents the PASS/FAIL result.
    """
    persistence = RuntimePersistence()

    # Create final verification evidence BEFORE transitioning to final state
    # This ensures evidence documents the actual verification result
    verification_evidence = EvidenceRecord(
        evidence_id=f"evidence-verification-{state.run_id}",
        run_id=state.run_id,
        task_id=None,
        kind="verification_result",
        source="deterministic_verifier",
        payload={
            "status": verification_result.status.value,
            "check_count": len(verification_result.checks),
            "all_passed": verification_result.status == VerificationResultStatus.PASS,
            "checks": [
                {"name": c.check_name, "passed": c.passed, "message": c.message}
                for c in verification_result.checks
            ],
        },
    )
    persistence.save_evidence(verification_evidence)
    evidence_records.append(verification_evidence)

    # Transition to RUNNING first (in activity, not workflow body)
    transition_run(state, RunStatus.RUNNING)

    # Now transition to final state based on verification
    if verification_result.status == VerificationResultStatus.PASS:
        transition_run(state, RunStatus.PASSED, verification_pass=True)
    else:
        transition_run(state, RunStatus.FAILED, verification_pass=False)

    # Save final state
    persistence.save_run_state(state)

    # Save verification result to log
    persistence.save_verification_result(verification_result)

    # Log final result
    persistence.save_run_log_entry(
        state.run_id,
        {
            "event": "run_completed",
            "run_id": state.run_id,
            "final_status": state.status.value,
            "verification_status": verification_result.status.value,
            "verification_message": verification_result.message,
            "evidence_count": len(evidence_records),
            "planner_provider": planner_metadata.provider,
            "planner_model_call_count": planner_metadata.model_call_count,
            "planner_input_tokens": planner_metadata.input_tokens,
            "planner_output_tokens": planner_metadata.output_tokens,
            "timestamp": state.updated_at,
        },
    )

    return state


# =============================================================================
# WORKFLOW
# =============================================================================


@workflows.workflow.define(
    name="fsasm-milestone-two",
    workflow_display_name="FS-ASM Milestone Two",
    workflow_description=(
        "FS-ASM workflow with real Mistral Planner integration. "
        "Creates exactly 3 tasks, validates plan, persists state, "
        "verifies deterministically, and produces evidence. "
        "Uses PlannerConfig for backend selection."
    ),
    enforce_determinism=True,
)
class FsasmMilestoneTwoWorkflow:
    """
    FS-ASM Milestone Two Workflow.

    Control flow:
    1. Validate configuration
    2. Create/normalize input
    3. Planner activity (Mistral or Stub backend)
    4. Validate plan
    5. Persist plan/state/proposal activity
    6. Persist evidence activity
    7. Verification activity (deterministic)
    8. Persist final state/log activity
    9. Return structured result

    All workflow code is deterministic. I/O and model calls belong in activities.
    Backend is explicitly selected via input; no silent fallback.
    """

    @workflows.workflow.entrypoint
    async def run(self, input: WorkflowInput) -> WorkflowOutput:
        """
        Entry point for the FS-ASM milestone two workflow.

        Args:
            input: WorkflowInput with goal, optional run_id, and planner backend config.

        Returns:
            Structured result with run_id, status, and details including planner metadata.
        """
        # Step 1: Validate configuration (explicit, no silent fallback)
        planner_config = await validate_config_activity(input)

        # Step 2: Create/normalize input
        goal_input = await create_input_activity(input)

        # Step 3: Planner activity (selected backend)
        planner_output = await plan_activity(goal_input, planner_config)

        # Step 4: Validate plan
        await validate_plan_activity(planner_output.plan)

        # Step 5: Persist plan/state/proposal activity (includes CREATED->PLANNED transition)
        plan, state = await persist_plan_and_state_activity(planner_output, goal_input)

        # Step 6: Persist evidence activity (pre-verification evidence)
        evidence_records = await persist_evidence_activity(state.run_id, plan)

        # Step 7: Final verification activity with all evidence
        verification_result = await verify_run_activity(state, plan, evidence_records)

        # Step 8: Persist final state/log activity
        final_state = await persist_final_state_activity(
            state, verification_result, evidence_records, planner_output.metadata
        )

        # Step 9: Return structured result
        return WorkflowOutput(
            run_id=final_state.run_id,
            goal=final_state.goal,
            status=final_state.status.value,
            plan_id=plan.plan_id,
            task_count=len(plan.tasks),
            task_ids=[t.task_id for t in plan.tasks],
            verification_status=verification_result.status.value,
            verification_message=verification_result.message,
            evidence_count=len(evidence_records),
            created_at=final_state.created_at,
            updated_at=final_state.updated_at,
            success=final_state.status == RunStatus.PASSED,
            # Planner metadata
            planner_provider=planner_output.metadata.provider,
            planner_model=planner_output.metadata.requested_model,
            planner_prompt_version=planner_output.metadata.prompt_version,
            planner_model_call_count=planner_output.metadata.model_call_count,
            planner_invocation_count=planner_output.metadata.planner_invocation_count,
            planner_input_tokens=planner_output.metadata.input_tokens,
            planner_output_tokens=planner_output.metadata.output_tokens,
            planner_total_tokens=planner_output.metadata.total_tokens,
        )
