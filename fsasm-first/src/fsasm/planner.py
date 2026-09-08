"""FS-ASM Planner - deterministic stub for milestone 1."""

from fsasm.models import (
    ChildTask,
    GoalInput,
    Plan,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)


class PlannerStub:
    """
    Deterministic stub planner for FS-ASM milestone 1.

    Always creates exactly 3 ChildTasks for any goal.
    The tasks are deterministic and follow a fixed pattern:
    1. TASK-001: Inspect/prepare input
    2. TASK-002: Perform core action
    3. TASK-003: Verify/finalize result
    """

    def __init__(self) -> None:
        """Initialize the stub planner."""
        pass

    def create_plan(self, input: GoalInput) -> Plan:
        """
        Create a plan with exactly 3 ChildTasks from a GoalInput.

        Args:
            input: The GoalInput containing the goal and optional run_id.

        Returns:
            A Plan with exactly 3 ChildTasks.
        """
        run_id = input.generate_run_id()
        plan_id = f"plan-{run_id}"

        # Task 1: Inspect/prepare input
        task_001 = ChildTask(
            task_id="TASK-001",
            parent_id=None,
            sequence=1,
            title="Inspect and prepare input",
            description=f"Inspect the goal '{input.goal}' and prepare the execution context.",
            status=TaskStatus.PENDING,
            dependencies=[],
            constraints=["Must not modify any files"],
            allowed_files=[],
            verification=VerificationSpec(
                type=VerificationType.SCHEMA,
                expected="Input inspection complete and context prepared",
            ),
            expected_evidence=["input_inspection_report"],
            attempt=0,
            max_attempts=3,
        )

        # Task 2: Perform core action
        task_002 = ChildTask(
            task_id="TASK-002",
            parent_id=None,
            sequence=2,
            title="Perform core action",
            description=f"Perform the core action to achieve goal: '{input.goal}'.",
            status=TaskStatus.PENDING,
            dependencies=["TASK-001"],
            constraints=["Must only modify allowed files"],
            allowed_files=["*.py", "*.md", "*.txt"],
            verification=VerificationSpec(
                type=VerificationType.EXISTS,
                expected="Core action completed successfully",
            ),
            expected_evidence=["action_output", "modified_files_list"],
            attempt=0,
            max_attempts=3,
        )

        # Task 3: Verify/finalize result
        task_003 = ChildTask(
            task_id="TASK-003",
            parent_id=None,
            sequence=3,
            title="Verify and finalize result",
            description=f"Verify that goal '{input.goal}' has been achieved and finalize.",
            status=TaskStatus.PENDING,
            dependencies=["TASK-002"],
            constraints=["Must not modify any files"],
            allowed_files=[],
            verification=VerificationSpec(
                type=VerificationType.CUSTOM,
                expected="Goal verified and all evidence collected",
            ),
            expected_evidence=["verification_report", "final_state"],
            attempt=0,
            max_attempts=3,
        )

        plan = Plan(
            plan_id=plan_id,
            run_id=run_id,
            goal=input.goal,
            tasks=[task_001, task_002, task_003],
        )

        return plan


# Singleton instance for convenience
planner_stub = PlannerStub()
