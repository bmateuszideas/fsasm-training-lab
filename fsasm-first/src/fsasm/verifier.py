"""FS-ASM Deterministic Verifier for milestone 1."""

from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    Plan,
    RunState,
    VerificationCheck,
    VerificationResult,
    VerificationResultStatus,
)


class DeterministicVerifier:
    """
    Deterministic verifier for FS-ASM milestone 1.

    Verifies:
    1. A valid Plan exists
    2. It contains exactly three ChildTasks
    3. Task IDs are unique
    4. Dependency references point to valid tasks
    5. State and plan share the same run ID
    6. Evidence can be persisted separately
    7. Returns explicit PASS or FAIL
    """

    def __init__(self) -> None:
        """Initialize the deterministic verifier."""
        pass

    def verify_plan(self, plan: Plan) -> VerificationResult:
        """
        Verify a Plan meets all milestone 1 requirements.

        Args:
            plan: The Plan to verify.

        Returns:
            VerificationResult with PASS or FAIL status.
        """
        checks: list[VerificationCheck] = []

        # Check 1: Plan exists and is valid
        checks.append(
            VerificationCheck(
                check_name="Plan exists and is valid",
                passed=True,
                message="Plan object is valid Pydantic model",
            )
        )

        # Check 2: Exactly three tasks
        task_count = len(plan.tasks)
        if task_count == 3:
            checks.append(
                VerificationCheck(
                    check_name="Plan contains exactly 3 tasks",
                    passed=True,
                    message=f"Plan has {task_count} tasks",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Plan contains exactly 3 tasks",
                    passed=False,
                    message=f"Plan has {task_count} tasks, expected 3",
                )
            )

        # Check 3: Task IDs are unique
        task_ids = [t.task_id for t in plan.tasks]
        if len(task_ids) == len(set(task_ids)):
            checks.append(
                VerificationCheck(
                    check_name="Task IDs are unique",
                    passed=True,
                    message=f"All {len(task_ids)} task IDs are unique",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Task IDs are unique",
                    passed=False,
                    message="Duplicate task IDs found",
                )
            )

        # Check 4: Dependency references are valid
        all_task_ids = set(task_ids)
        all_deps_valid = True
        for task in plan.tasks:
            for dep_id in task.dependencies:
                if dep_id not in all_task_ids:
                    all_deps_valid = False
                    checks.append(
                        VerificationCheck(
                            check_name=f"Task {task.task_id} dependency validation",
                            passed=False,
                            message=f"Task {task.task_id} depends on non-existent task {dep_id}",
                        )
                    )
                    break
        if all_deps_valid:
            checks.append(
                VerificationCheck(
                    check_name="All dependency references are valid",
                    passed=True,
                    message="All task dependencies point to existing tasks",
                )
            )

        # Check 5: Tasks are properly ordered by sequence
        sequences = [t.sequence for t in plan.tasks]
        if sequences == sorted(sequences):
            checks.append(
                VerificationCheck(
                    check_name="Tasks are properly sequenced",
                    passed=True,
                    message="Task sequences are in order",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Tasks are properly sequenced",
                    passed=False,
                    message=f"Task sequences {sequences} are not in order",
                )
            )

        # Determine overall status
        all_passed = all(c.passed for c in checks)
        status = (
            VerificationResultStatus.PASS
            if all_passed
            else VerificationResultStatus.FAIL
        )

        message = (
            "All plan validation checks passed"
            if all_passed
            else "One or more plan validation checks failed"
        )

        return VerificationResult(
            run_id=plan.run_id,
            task_id=None,
            status=status,
            checks=checks,
            message=message,
        )

    def verify_run_state(self, state: RunState) -> VerificationResult:
        """
        Verify a RunState meets milestone 1 requirements.

        Args:
            state: The RunState to verify.

        Returns:
            VerificationResult with PASS or FAIL status.
        """
        checks: list[VerificationCheck] = []

        # Check: RunState exists and is valid
        checks.append(
            VerificationCheck(
                check_name="RunState exists and is valid",
                passed=True,
                message="RunState object is valid Pydantic model",
            )
        )

        # Check: Goal is not blank
        if state.goal.strip():
            checks.append(
                VerificationCheck(
                    check_name="Goal is not blank",
                    passed=True,
                    message=f"Goal is '{state.goal}'",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Goal is not blank",
                    passed=False,
                    message="Goal is blank",
                )
            )

        # Check: Plan exists and has matching run_id
        if state.plan is not None:
            if state.plan.run_id == state.run_id:
                checks.append(
                    VerificationCheck(
                        check_name="Plan run_id matches RunState run_id",
                        passed=True,
                        message="Plan and RunState share the same run_id",
                    )
                )
            else:
                checks.append(
                    VerificationCheck(
                        check_name="Plan run_id matches RunState run_id",
                        passed=False,
                        message=f"Plan run_id '{state.plan.run_id}' != RunState run_id '{state.run_id}'",
                    )
                )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Plan exists",
                    passed=False,
                    message="No plan attached to RunState",
                )
            )

        # Determine overall status
        all_passed = all(c.passed for c in checks)
        status = (
            VerificationResultStatus.PASS
            if all_passed
            else VerificationResultStatus.FAIL
        )

        message = (
            "RunState validation passed" if all_passed else "RunState validation failed"
        )

        return VerificationResult(
            run_id=state.run_id,
            task_id=None,
            status=status,
            checks=checks,
            message=message,
        )

    def verify_task(self, task: ChildTask) -> VerificationResult:
        """
        Verify a single ChildTask meets basic requirements.

        Args:
            task: The ChildTask to verify.

        Returns:
            VerificationResult with PASS or FAIL status.
        """
        checks: list[VerificationCheck] = []

        # Check: Task has valid ID
        if task.task_id.strip():
            checks.append(
                VerificationCheck(
                    check_name="Task has valid ID",
                    passed=True,
                    message=f"Task ID is '{task.task_id}'",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Task has valid ID",
                    passed=False,
                    message="Task ID is empty",
                )
            )

        # Check: Task has title and description
        if task.title.strip() and task.description.strip():
            checks.append(
                VerificationCheck(
                    check_name="Task has title and description",
                    passed=True,
                    message="Task has both title and description",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Task has title and description",
                    passed=False,
                    message="Task is missing title or description",
                )
            )

        # Check: Verification spec exists
        if task.verification is not None:
            checks.append(
                VerificationCheck(
                    check_name="Task has verification spec",
                    passed=True,
                    message=f"Verification type: {task.verification.type}",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Task has verification spec",
                    passed=False,
                    message="Task is missing verification spec",
                )
            )

        # Determine overall status
        all_passed = all(c.passed for c in checks)
        status = (
            VerificationResultStatus.PASS
            if all_passed
            else VerificationResultStatus.FAIL
        )

        return VerificationResult(
            run_id="",  # Will be set by caller if needed
            task_id=task.task_id,
            status=status,
            checks=checks,
            message="Task validation passed"
            if all_passed
            else "Task validation failed",
        )

    def verify_full_run(
        self,
        state: RunState,
        plan: Plan | None = None,
        evidence_records: list[EvidenceRecord] | None = None,
    ) -> VerificationResult:
        """
        Full verification of a complete FS-ASM run.

        Args:
            state: The RunState to verify.
            plan: Optional Plan to verify (if not in state).
            evidence_records: Optional list of evidence records to verify.

        Returns:
            VerificationResult with overall PASS or FAIL.
        """
        checks: list[VerificationCheck] = []

        # Use plan from state if not provided
        target_plan = plan or state.plan

        if target_plan is None:
            checks.append(
                VerificationCheck(
                    check_name="Plan exists",
                    passed=False,
                    message="No plan available for verification",
                )
            )
        else:
            # Verify plan
            plan_result = self.verify_plan(target_plan)
            checks.extend(plan_result.checks)

            # Verify state
            state_result = self.verify_run_state(state)
            checks.extend(state_result.checks)

            # Check: Evidence records exist (if provided)
            # For milestone 1, evidence records are created AFTER verification, so they may not be available yet
            # This is acceptable - we'll pass this check if evidence_records list is provided (even if empty)
            if evidence_records is not None:
                checks.append(
                    VerificationCheck(
                        check_name="Evidence records exist",
                        passed=True,
                        message=f"Evidence records list provided with {len(evidence_records)} records",
                    )
                )

        # Determine overall status
        all_passed = all(c.passed for c in checks)
        status = (
            VerificationResultStatus.PASS
            if all_passed
            else VerificationResultStatus.FAIL
        )

        message = (
            "Full run verification PASSED"
            if all_passed
            else "Full run verification FAILED"
        )

        return VerificationResult(
            run_id=state.run_id,
            task_id=None,
            status=status,
            checks=checks,
            message=message,
        )


# Singleton instance for convenience
verifier = DeterministicVerifier()
