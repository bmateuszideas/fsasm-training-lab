"""FS-ASM Deterministic Verifier for milestone 1.

The v1 Verification Plane (T13) lives here too: :class:`ArtifactVerifier`
reads the real artifact and a real ``run_checks`` observation — never the
Executor's claim — and produces evidence bound to one attempt + operation +
artifact + check. The Domain Core alone grants the transition.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    Plan,
    RunState,
    ToolObservation,
    ToolOperationKind,
    VerificationCheck,
    VerificationResult,
    VerificationResultStatus,
    artifact_id_for,
    evidence_id_for,
)

if TYPE_CHECKING:
    from fsasm.tool_broker import ToolBroker


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

            # Check: Evidence records exist
            # For milestone 1, evidence records are created AFTER verification in the workflow
            # We need to verify that evidence was actually created (evidence_records should have items)
            if evidence_records is not None and len(evidence_records) > 0:
                checks.append(
                    VerificationCheck(
                        check_name="Evidence records exist",
                        passed=True,
                        message=f"Found {len(evidence_records)} evidence records",
                    )
                )
            else:
                checks.append(
                    VerificationCheck(
                        check_name="Evidence records exist",
                        passed=False,
                        message="No evidence records provided or list is empty",
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

    def verify_task_execution(
        self,
        run_id: str,
        task: ChildTask,
        evidence_records: list[EvidenceRecord],
    ) -> VerificationResult:
        """
        Verify task execution using deterministic checks.

        Pure domain verification moved from executor_activities.py.
        Verification operates on:
        - authoritative run_id
        - ChildTask
        - list[EvidenceRecord]

        Evidence must match BOTH:
        - evidence.run_id == authoritative run_id
        - evidence.task_id == task.task_id

        Verification requires ALL declared expected evidence kinds to be present.
        Also verifies task.verification.expected is present in evidence.

        Args:
            run_id: The authoritative run_id.
            task: The ChildTask being verified.
            evidence_records: List of EvidenceRecord for this task.

        Returns:
            VerificationResult with PASS or FAIL.
        """
        checks: list[VerificationCheck] = []

        # Check 1: Evidence records are not empty
        if len(evidence_records) > 0:
            checks.append(
                VerificationCheck(
                    check_name="Evidence records exist",
                    passed=True,
                    message=f"Found {len(evidence_records)} evidence records",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="Evidence records exist",
                    passed=False,
                    message="No evidence records provided",
                )
            )

        # Check 2: All evidence has correct run_id
        all_run_ids_correct = True
        for evidence in evidence_records:
            if evidence.run_id != run_id:
                all_run_ids_correct = False
                checks.append(
                    VerificationCheck(
                        check_name=f"Evidence {evidence.evidence_id} run_id match",
                        passed=False,
                        message=f"Evidence run_id '{evidence.run_id}' != authoritative run_id '{run_id}'",
                    )
                )
        if all_run_ids_correct:
            checks.append(
                VerificationCheck(
                    check_name="All evidence run_ids match authoritative run_id",
                    passed=True,
                    message=f"All {len(evidence_records)} evidence records have run_id '{run_id}'",
                )
            )

        # Check 3: All evidence has correct task_id
        all_task_ids_correct = True
        for evidence in evidence_records:
            if evidence.task_id != task.task_id:
                all_task_ids_correct = False
                checks.append(
                    VerificationCheck(
                        check_name=f"Evidence {evidence.evidence_id} task_id match",
                        passed=False,
                        message=f"Evidence task_id '{evidence.task_id}' != task task_id '{task.task_id}'",
                    )
                )
        if all_task_ids_correct:
            checks.append(
                VerificationCheck(
                    check_name="All evidence task_ids match task",
                    passed=True,
                    message=f"All {len(evidence_records)} evidence records have task_id '{task.task_id}'",
                )
            )

        # Check 4: All expected evidence kinds are present
        expected_kinds = (
            set(task.expected_evidence) if task.expected_evidence else set()
        )
        actual_kinds = set(e.kind for e in evidence_records)

        if not expected_kinds:
            # If no expected evidence, we MUST have at least one fallback with kind "executor_output"
            has_executor_output = "executor_output" in actual_kinds
            if has_executor_output and len(actual_kinds) >= 1:
                checks.append(
                    VerificationCheck(
                        check_name="Expected evidence kinds check",
                        passed=True,
                        message="No expected evidence kinds - fallback executor_output evidence present",
                    )
                )
            else:
                checks.append(
                    VerificationCheck(
                        check_name="Expected evidence kinds check",
                        passed=False,
                        message=f"No expected evidence kinds but no executor_output fallback found. Actual kinds: {sorted(actual_kinds)}",
                    )
                )
        else:
            # All expected kinds must be present
            missing_kinds = expected_kinds - actual_kinds
            if not missing_kinds:
                checks.append(
                    VerificationCheck(
                        check_name="All expected evidence kinds present",
                        passed=True,
                        message=f"All {len(expected_kinds)} expected kinds present: {sorted(expected_kinds)}",
                    )
                )
            else:
                checks.append(
                    VerificationCheck(
                        check_name="All expected evidence kinds present",
                        passed=False,
                        message=f"Missing expected evidence kinds: {sorted(missing_kinds)}",
                    )
                )

        # Check 5: Verify against task.verification.expected
        verification_expected = (
            task.verification.expected if task.verification else None
        )
        if verification_expected:
            # Check if any evidence payload contains the expected value
            expected_found = False
            for evidence in evidence_records:
                payload = evidence.payload
                if isinstance(payload, dict):
                    # Check in executor_output.result
                    executor_output_data = payload.get("executor_output", {})
                    if isinstance(executor_output_data, dict):
                        result = executor_output_data.get("result", "")
                        if verification_expected in result:
                            expected_found = True
                            break

            if expected_found:
                checks.append(
                    VerificationCheck(
                        check_name="VerificationSpec expected value present",
                        passed=True,
                        message=f"Expected value '{verification_expected}' found in evidence",
                    )
                )
            else:
                checks.append(
                    VerificationCheck(
                        check_name="VerificationSpec expected value present",
                        passed=False,
                        message=f"Expected value '{verification_expected}' NOT found in evidence",
                    )
                )
        else:
            # No expected value to check
            checks.append(
                VerificationCheck(
                    check_name="VerificationSpec expected value check",
                    passed=True,
                    message="No verification expected value specified",
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
            "Task execution verification PASSED"
            if all_passed
            else "Task execution verification FAILED"
        )

        return VerificationResult(
            run_id=run_id,
            task_id=task.task_id,
            status=status,
            checks=checks,
            message=message,
        )


# Singleton instance for convenience
verifier = DeterministicVerifier()


# =============================================================================
# T13 — Independent Verifier and Evidence Plane
# =============================================================================


@dataclass
class VerifyRequest:
    """Inputs the v1 Verifier needs to inspect the real artifact and checks.

    The Verifier never trusts the Executor's claim (``"I am done"``); it reads
    the actual artifact/diff and the real ``run_checks`` observation produced
    by the Tool Broker, then binds the result to one attempt + operation +
    artifact + check. It returns a :class:`VerificationResult` and the
    :class:`EvidenceRecord` list it produced; it never grants the state
    transition — the Domain Core does (architecture §29, §30; F8).
    """

    run_id: str
    task_id: str
    attempt: int
    artifact_path: str
    patch_observation_id: str
    check_observation_id: str
    check_observation: "ToolObservation"


@dataclass
class ArtifactVerifier:
    """Independent verifier reading the real artifact and a real check result.

    The Executor may claim ``"DONE"``; this verifier reads the actual artifact
    via the Tool Broker (so a claim with no effect cannot PASS), inspects the
    real ``run_checks`` :class:`ToolObservation` (so a stale or foreign check
    cannot PASS), and binds the result to the full identity of the attempt. It
    produces evidence records for the current attempt; the Domain Core decides
    the transition. A negative check, missing evidence, a stale attempt, a
    foreign artifact or a ``"DONE"`` without effect all block PASS.

    The verifier holds no authority: it does not grant PASS, retry or gate. It
    returns ``(result, evidence_records)``; the caller persists evidence then
    asks the Domain Core to apply ``EvidenceAccepted`` + PASS/FAIL.
    """

    broker: "ToolBroker"
    allowed_files: list[str] = field(default_factory=list)
    # The expected check outcome: a non-zero exit is a negative result (FAIL);
    # zero is a pass. The broker already proved the check ran in-scope.
    expected_exit_code: int = 0
    # Optional expected content substring the real artifact must contain (e.g.
    # the patched code). When empty, only the artifact's existence + a passing
    # check are required; the Executor's text claim is never sufficient.
    expected_artifact_contains: str = ""

    def verify(
        self, request: VerifyRequest
    ) -> tuple[VerificationResult, list[EvidenceRecord]]:
        run_id = request.run_id
        task_id = request.task_id
        attempt = request.attempt
        artifact_id = artifact_id_for(run_id, task_id, attempt)
        checks: list[VerificationCheck] = []
        evidence: list[EvidenceRecord] = []
        # The check identity is the CheckKind of the run_checks observation.
        check_identity = (
            request.check_observation.check_kind.value
            if request.check_observation.check_kind is not None
            else request.check_observation.kind.value
        )

        # 1. Identity: the check observation must belong to THIS attempt. A
        # stale or foreign observation cannot authorize PASS. The operation id
        # is bound to a specific attempt (and any step within it); we verify the
        # supplied id matches the observation and the observation's attempt
        # matches the request's attempt.
        expected_op_prefix = f"op-{run_id}-{task_id}-attempt-{attempt}-"
        if request.check_observation_id != request.check_observation.operation_id:
            checks.append(
                VerificationCheck(
                    check_name="check observation identity",
                    passed=False,
                    message=(
                        "check observation id mismatch: supplied "
                        f"{request.check_observation_id!r} != observation "
                        f"{request.check_observation.operation_id!r}"
                    ),
                    check_identity=check_identity,
                )
            )
        elif not request.check_observation.operation_id.startswith(expected_op_prefix):
            checks.append(
                VerificationCheck(
                    check_name="check observation bound to attempt",
                    passed=False,
                    message=(
                        f"check observation {request.check_observation.operation_id!r}"
                        f" does not match attempt {attempt} (expected prefix "
                        f"{expected_op_prefix!r})"
                    ),
                    check_identity=check_identity,
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="check observation identity",
                    passed=True,
                    message="check observation bound to current attempt/operation",
                    check_identity=check_identity,
                )
            )

        # 2. The check observation must not be a policy block / timeout /
        # process error. A blocked or timed-out check cannot be a PASS.
        if request.check_observation.kind is not ToolOperationKind.RUN_CHECKS:
            checks.append(
                VerificationCheck(
                    check_name="observation is a run_checks result",
                    passed=False,
                    message=(
                        "observation kind is "
                        f"{request.check_observation.kind.value!r}, not run_checks"
                    ),
                    check_identity=check_identity,
                )
            )
        elif request.check_observation.blocked:
            checks.append(
                VerificationCheck(
                    check_name="check not blocked by policy",
                    passed=False,
                    message=f"check was blocked: {request.check_observation.reason}",
                    check_identity=check_identity,
                )
            )
        elif request.check_observation.timed_out:
            checks.append(
                VerificationCheck(
                    check_name="check did not time out",
                    passed=False,
                    message="check timed out",
                    check_identity=check_identity,
                )
            )
        elif request.check_observation.exit_code is None:
            checks.append(
                VerificationCheck(
                    check_name="check produced an exit code",
                    passed=False,
                    message="check produced no exit code (process error)",
                    check_identity=check_identity,
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    check_name="check ran to completion",
                    passed=True,
                    message=f"check completed, exit code "
                    f"{request.check_observation.exit_code}",
                    check_identity=check_identity,
                )
            )

        # 3. The check result: exit code must match the expected outcome. A
        # negative result is recorded honestly (FAIL), never as PASS.
        if request.check_observation.exit_code is not None and not (
            request.check_observation.blocked or request.check_observation.timed_out
        ):
            passed = request.check_observation.exit_code == self.expected_exit_code
            checks.append(
                VerificationCheck(
                    check_name=f"check exit code == {self.expected_exit_code}",
                    passed=passed,
                    message=(
                        f"exit code {request.check_observation.exit_code}"
                        + ("" if passed else f" != {self.expected_exit_code}")
                    ),
                    check_identity=check_identity,
                )
            )

        # 4. The artifact must actually exist and contain the expected effect.
        # This reads the REAL file via the Broker, so a ``"DONE"`` claim with no
        # change cannot PASS (G2 reproducer).
        inspect = self.broker.inspect_changes(
            run_id,
            task_id,
            attempt,
            0,
            request.artifact_path,
            allowed_files=self.allowed_files,
        )
        if inspect.blocked or not inspect.ok:
            checks.append(
                VerificationCheck(
                    check_name="artifact exists and is readable",
                    passed=False,
                    message=f"artifact not readable: {inspect.reason}",
                    check_identity=check_identity,
                )
            )
            artifact_ok = False
        else:
            checks.append(
                VerificationCheck(
                    check_name="artifact exists and is readable",
                    passed=True,
                    message=f"read artifact {request.artifact_path}",
                    check_identity=check_identity,
                )
            )
            artifact_ok = True
            if self.expected_artifact_contains:
                present = self.expected_artifact_contains in inspect.content
                checks.append(
                    VerificationCheck(
                        check_name="artifact contains expected effect",
                        passed=present,
                        message=(
                            "expected content present"
                            if present
                            else "expected content NOT present in artifact"
                        ),
                        check_identity=check_identity,
                    )
                )

        # Overall PASS requires: identity ok, check ran, check passed, and
        # artifact readable (and contains expected effect if specified). A
        # single failed check means FAIL — no PASS from a "DONE" claim.
        all_passed = bool(checks) and all(c.passed for c in checks)
        status = (
            VerificationResultStatus.PASS
            if all_passed
            else VerificationResultStatus.FAIL
        )

        # Build evidence for the current attempt. Evidence is produced for the
        # real artifact + real check observation, bound to the full identity.
        # On FAIL, evidence still records what was observed (diagnostic); only
        # accepted evidence refs authorize PASS, and the Domain Core enforces
        # that. The caller persists evidence BEFORE the snapshot accepts refs.
        if artifact_ok:
            evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id_for(run_id, task_id, attempt, "artifact"),
                    run_id=run_id,
                    task_id=task_id,
                    kind="artifact",
                    source="tool_broker.inspect_changes",
                    payload={
                        "artifact_path": request.artifact_path,
                        "content_excerpt": inspect.content[:512],
                    },
                    attempt=attempt,
                    operation_id=request.patch_observation_id,
                    artifact_id=artifact_id,
                    check_identity=check_identity,
                )
            )
        evidence.append(
            EvidenceRecord(
                evidence_id=evidence_id_for(run_id, task_id, attempt, "check"),
                run_id=run_id,
                task_id=task_id,
                kind="check_result",
                source="tool_broker.run_checks",
                payload={
                    "exit_code": request.check_observation.exit_code,
                    "stdout_excerpt": request.check_observation.stdout[:512],
                    "stderr_excerpt": request.check_observation.stderr[:512],
                    "timed_out": request.check_observation.timed_out,
                    "blocked": request.check_observation.blocked,
                },
                attempt=attempt,
                operation_id=request.check_observation_id,
                artifact_id=artifact_id,
                check_identity=check_identity,
            )
        )

        result = VerificationResult(
            run_id=run_id,
            task_id=task_id,
            status=status,
            checks=checks,
            message=(
                "artifact verification PASSED"
                if all_passed
                else "artifact verification FAILED"
            ),
            attempt=attempt,
            operation_id=request.patch_observation_id,
            artifact_id=artifact_id,
            evidence_refs=[e.evidence_id for e in evidence] if all_passed else [],
        )
        return result, evidence
