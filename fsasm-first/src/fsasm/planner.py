"""FS-ASM Planner - deterministic stub for milestone 1 and assembler for all backends."""

from fsasm.models import (
    ChildTask,
    GoalInput,
    PlannerMetadata,
    PlannerOutput,
    PlannerProposal,
    Plan,
    TaskProposal,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)


def assemble_plan(goal_input: GoalInput, proposal: PlannerProposal) -> Plan:
    """
    Assemble a runtime-owned Plan from a semantic PlannerProposal.
    
    This is the SINGLE deterministic assembler used by both Stub and Mistral backends.
    It assigns all runtime-owned fields: run_id, plan_id, task_id, sequence, status, attempt, max_attempts.
    
    Dependencies in TaskProposal use proposal-local sequence numbers which are
    mapped deterministically to runtime task IDs (TASK-001, TASK-002, TASK-003).
    
    Args:
        goal_input: The GoalInput containing the authoritative goal and run_id.
        proposal: The PlannerProposal with semantic task content.
    
    Returns:
        A fully assembled Plan with all runtime-owned fields set.
    """
    run_id = goal_input.generate_run_id()
    plan_id = f"plan-{run_id}"

    # Map proposal-local sequence numbers to runtime task IDs
    # Sequence in TaskProposal is 1-indexed position in the proposal
    task_id_map: dict[int, str] = {}
    tasks: list[ChildTask] = []

    for idx, task_proposal in enumerate(proposal.tasks, start=1):
        task_id = f"TASK-{idx:03d}"
        task_id_map[idx] = task_id

        # Map proposal-local dependency sequence numbers to runtime task IDs
        runtime_dependencies = [
            task_id_map[dep_seq] for dep_seq in task_proposal.dependencies
        ]

        task = ChildTask(
            task_id=task_id,
            parent_id=None,
            sequence=idx,
            title=task_proposal.title,
            description=task_proposal.description,
            status=TaskStatus.PENDING,
            dependencies=runtime_dependencies,
            constraints=task_proposal.constraints,
            allowed_files=task_proposal.allowed_files,
            verification=VerificationSpec(
                type=task_proposal.verification_type,
                expected=task_proposal.verification_expected,
            ),
            expected_evidence=task_proposal.expected_evidence,
            attempt=0,
            max_attempts=3,
        )
        tasks.append(task)

    plan = Plan(
        plan_id=plan_id,
        run_id=run_id,
        goal=goal_input.goal,  # Authoritative goal from GoalInput
        tasks=tasks,
    )

    return plan


class PlannerStub:
    """
    Deterministic stub planner for FS-ASM milestone 1.

    Always creates exactly 3 TaskProposal instances for any goal.
    The proposals are deterministic and follow a fixed pattern:
    1. TaskProposal for inspect/prepare input
    2. TaskProposal for perform core action
    3. TaskProposal for verify/finalize result
    """

    def __init__(self) -> None:
        """Initialize the stub planner."""
        pass

    def create_proposal(self, input: GoalInput) -> PlannerProposal:
        """
        Create a PlannerProposal with exactly 3 TaskProposal instances.
        
        Args:
            input: The GoalInput containing the goal.
        
        Returns:
            A PlannerProposal with exactly 3 TaskProposal.
        """
        return PlannerProposal(
            tasks=[
                TaskProposal(
                    title="Inspect and prepare input",
                    description=f"Inspect the goal '{input.goal}' and prepare the execution context.",
                    dependencies=[],
                    verification_type="schema",
                    verification_expected="Input inspection complete and context prepared",
                    constraints=["Must not modify any files"],
                    allowed_files=[],
                    expected_evidence=["input_inspection_report"],
                ),
                TaskProposal(
                    title="Perform core action",
                    description=f"Perform the core action to achieve goal: '{input.goal}'.",
                    dependencies=[1],  # Depends on task with sequence=1
                    verification_type="exists",
                    verification_expected="Core action completed successfully",
                    constraints=["Must only modify allowed files"],
                    allowed_files=["*.py", "*.md", "*.txt"],
                    expected_evidence=["action_output", "modified_files_list"],
                ),
                TaskProposal(
                    title="Verify and finalize result",
                    description=f"Verify that goal '{input.goal}' has been achieved and finalize.",
                    dependencies=[2],  # Depends on task with sequence=2
                    verification_type="custom",
                    verification_expected="Goal verified and all evidence collected",
                    constraints=["Must not modify any files"],
                    allowed_files=[],
                    expected_evidence=["verification_report", "final_state"],
                ),
            ]
        )

    def create_plan(self, input: GoalInput) -> Plan:
        """
        Create a plan with exactly 3 ChildTasks from a GoalInput.
        
        This method is kept for backward compatibility with Milestone 1.
        It creates a proposal and assembles it using the shared assembler.

        Args:
            input: The GoalInput containing the goal and optional run_id.

        Returns:
            A Plan with exactly 3 ChildTasks.
        """
        proposal = self.create_proposal(input)
        return assemble_plan(input, proposal)

    async def plan(self, input: GoalInput) -> PlannerOutput:
        """
        Async planning interface for Milestone 2 compatibility.
        
        Creates a proposal and assembles the plan using the shared assembler.
        Returns PlannerOutput with metadata for stub backend.
        
        Args:
            input: The GoalInput containing the goal and optional run_id.
        
        Returns:
            PlannerOutput with proposal, assembled plan, and stub metadata.
        """
        from fsasm.models import PlannerMetadata

        proposal = self.create_proposal(input)
        plan = assemble_plan(input, proposal)

        run_id = plan.run_id

        # Compute hashes for stub (deterministic, no runtime data in template)
        template = "stub planner template v1"
        template_hash = PlannerMetadata.compute_template_hash(template)
        rendered_prompt = f"stub planner for goal: {input.goal}"
        rendered_hash = PlannerMetadata.compute_rendered_hash(rendered_prompt)

        metadata = PlannerMetadata(
            run_id=run_id,
            provider="stub",
            requested_model=None,
            resolved_model=None,
            model_version=None,
            prompt_version="v1.0",
            template_hash=template_hash,
            rendered_hash=rendered_hash,
            model_call_count=0,  # Stub makes 0 model calls
            planner_invocation_count=1,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
        )

        return PlannerOutput(
            proposal=proposal,
            plan=plan,
            metadata=metadata,
        )


# Singleton instance for convenience
planner_stub = PlannerStub()
