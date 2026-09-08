"""FS-ASM Milestone One Workflow - Deterministic workflow without LLM calls."""

import logging

import mistralai.workflows as workflows
from pydantic import BaseModel

from fsasm.models import (
    EvidenceRecord,
    GoalInput,
    Plan,
    RunState,
    RunStatus,
    VerificationResult,
    VerificationResultStatus,
)
from fsasm.planner import PlannerStub
from fsasm.verifier import DeterministicVerifier
from fsasm.persistence import RuntimePersistence
from fsasm.transitions import transition_run

logger = logging.getLogger(__name__)


# =============================================================================
# INPUT/OUTPUT MODELS
# =============================================================================


class WorkflowInput(BaseModel):
    """Input model for the FS-ASM milestone one workflow."""

    goal: str
    run_id: str | None = None


class WorkflowOutput(BaseModel):
    """Output model for the FS-ASM milestone one workflow."""

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
    name="fsasm-plan",
    retry_policy_max_attempts=1,
)
async def plan_activity(goal_input: GoalInput) -> Plan:
    """
    Create a plan using the deterministic stub planner.

    This is an activity because it could later call an LLM.
    For milestone 1, it uses the deterministic stub.
    """
    planner = PlannerStub()
    plan = planner.create_plan(goal_input)
    return plan


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
    name="fsasm-persist-plan-and-state",
    retry_policy_max_attempts=3,
)
async def persist_plan_and_state_activity(
    plan: Plan, goal_input: GoalInput
) -> tuple[Plan, RunState]:
    """
    Persist the plan and initial run state to filesystem.

    This is an activity because it performs filesystem I/O.
    Uses atomic writes for mutable state.
    """
    persistence = RuntimePersistence()

    # Create initial run state
    run_id = plan.run_id
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

    # Log the creation
    persistence.save_run_log_entry(
        run_id,
        {
            "event": "run_created",
            "run_id": run_id,
            "goal": goal_input.goal,
            "status": RunStatus.PLANNED.value,
            "timestamp": state.created_at,
        },
    )

    return plan, state


@workflows.activity(
    name="fsasm-verify-run",
    retry_policy_max_attempts=1,
)
async def verify_run_activity(
    state: RunState, plan: Plan
) -> tuple[RunState, VerificationResult]:
    """
    Verify the run using deterministic verifier.

    This is an activity because verification could later use an LLM.
    For milestone 1, it uses deterministic checks.
    """
    verifier = DeterministicVerifier()

    # Create evidence record for the verification itself
    # (This will be saved separately in the next activity)

    # Run verification
    verification_result = verifier.verify_full_run(state, plan, [])

    return state, verification_result


@workflows.activity(
    name="fsasm-persist-evidence",
    retry_policy_max_attempts=3,
)
async def persist_evidence_activity(
    run_id: str,
    verification_result: VerificationResult,
    plan: Plan,
) -> list[EvidenceRecord]:
    """
    Persist evidence records separately from state.

    This is an activity because it performs filesystem I/O.
    """
    persistence = RuntimePersistence()

    evidence_records: list[EvidenceRecord] = []

    # Create evidence for the plan
    plan_evidence = EvidenceRecord(
        evidence_id=f"evidence-plan-{run_id}",
        run_id=run_id,
        task_id=None,
        kind="plan_validation",
        source="fsasm_milestone_one_workflow",
        payload={
            "plan_id": plan.plan_id,
            "task_count": len(plan.tasks),
            "task_ids": [t.task_id for t in plan.tasks],
            "validation_passed": verification_result.status
            == VerificationResultStatus.PASS,
        },
    )
    persistence.save_evidence(plan_evidence)
    evidence_records.append(plan_evidence)

    # Create evidence for verification result
    verification_evidence = EvidenceRecord(
        evidence_id=f"evidence-verification-{run_id}",
        run_id=run_id,
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

    # Save verification result to log
    persistence.save_verification_result(verification_result)

    return evidence_records


@workflows.activity(
    name="fsasm-persist-final-state",
    retry_policy_max_attempts=3,
)
async def persist_final_state_activity(
    state: RunState,
    verification_result: VerificationResult,
    evidence_records: list[EvidenceRecord],
) -> RunState:
    """
    Persist the final run state and complete the run.

    This is an activity because it performs filesystem I/O.
    """
    persistence = RuntimePersistence()

    # Transition to RUNNING first, then to final state based on verification
    transition_run(state, RunStatus.RUNNING)

    if verification_result.status == VerificationResultStatus.PASS:
        transition_run(state, RunStatus.PASSED, verification_pass=True)
    else:
        transition_run(state, RunStatus.FAILED, verification_pass=False)

    # Save final state
    persistence.save_run_state(state)

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
            "timestamp": state.updated_at,
        },
    )

    return state


# =============================================================================
# WORKFLOW
# =============================================================================


@workflows.workflow.define(
    name="fsasm-milestone-one",
    workflow_display_name="FS-ASM Milestone One",
    workflow_description=(
        "Deterministic FS-ASM workflow for milestone 1. "
        "Creates exactly 3 tasks, validates plan, persists state, "
        "verifies deterministically, and produces evidence. "
        "No LLM calls required."
    ),
    enforce_determinism=True,
)
class FsasmMilestoneOneWorkflow:
    """
    FS-ASM Milestone One Workflow.

    Control flow:
    1. Create/normalize input
    2. Planner activity (deterministic stub)
    3. Validate plan
    4. Persist plan/state activity
    5. Verification activity (deterministic)
    6. Persist evidence activity
    7. Persist final state/log activity
    8. Return structured result

    All workflow code is deterministic. I/O belongs in activities.
    """

    @workflows.workflow.entrypoint
    async def run(self, input: WorkflowInput) -> WorkflowOutput:
        """
        Entry point for the FS-ASM milestone one workflow.

        Args:
            input: Raw input dictionary with at least 'goal' key.

        Returns:
            Structured result with run_id, status, and details.
        """
        # Step 1: Create/normalize input
        goal_input = await create_input_activity(input)

        # Step 2: Planner activity (deterministic stub)
        plan = await plan_activity(goal_input)

        # Step 3: Validate plan
        validated_plan = await validate_plan_activity(plan)

        # Step 4: Persist plan/state activity
        plan, state = await persist_plan_and_state_activity(validated_plan, goal_input)

        # Ensure state transitions from CREATED to PLANNED
        if state.status == RunStatus.CREATED:
            transition_run(state, RunStatus.PLANNED)

        # Step 5: Verification activity (deterministic)
        state, verification_result = await verify_run_activity(state, plan)

        # Step 6: Persist evidence activity
        evidence_records = await persist_evidence_activity(
            state.run_id, verification_result, plan
        )

        # Step 6.5: Re-run verification with actual evidence records
        verifier = DeterministicVerifier()
        verification_result = verifier.verify_full_run(state, plan, evidence_records)

        # Step 7: Persist final state/log activity
        final_state = await persist_final_state_activity(
            state, verification_result, evidence_records
        )

        # Step 8: Return structured result
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
        )
