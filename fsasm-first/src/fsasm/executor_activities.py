"""FS-ASM Executor Activities - activity-based execution with Stub backend for milestone 3."""

import logging

import mistralai.workflows as workflows
from mistralai.workflows import activity

# Import fsasm modules - these are used in activities, not workflow code
with workflows.workflow.unsafe.imports_passed_through():
    from fsasm.errors import ConfigurationError, ProvenanceValidationError
    from fsasm.models import (
        ChildTask,
        ExecutorBackend,
        ExecutorConfig,
        ExecutorOutput,
        EvidenceRecord,
        RunState,
        RunStatus,
        TaskStatus,
        VerificationResult,
        VerificationResultStatus,
    )
    from fsasm.executor import ExecutorStub
    from fsasm.transitions import transition_task
    from fsasm.persistence import RuntimePersistence

logger = logging.getLogger(__name__)


# =============================================================================
# EXECUTOR ACTIVITIES
# =============================================================================


@activity(
    name="fsasm-execute-task",
    retry_policy_max_attempts=1,
)
async def execute_task_activity(
    task: ChildTask,
    run_id: str,
    executor_config: ExecutorConfig,
) -> ExecutorOutput:
    """
    Execute a single task using the configured executor backend.

    For M3, only STUB backend is implemented.
    The executor produces ExecutorOutput (a CLAIM/RESULT).

    Args:
        task: The ChildTask to execute.
        run_id: The run_id for traceability.
        executor_config: The ExecutorConfig specifying which backend to use.

    Returns:
        ExecutorOutput from the executor.

    Raises:
        ConfigurationError: If backend is not STUB (for M3).
    """
    if executor_config.backend != ExecutorBackend.STUB:
        raise ConfigurationError(
            message=f"Milestone 3 only supports ExecutorBackend.STUB, got '{executor_config.backend}'",
            backend=executor_config.backend.value,
        )

    # Use the stub executor
    executor = ExecutorStub()
    output = await executor.execute_async(task, run_id)

    return output


@activity(
    name="fsasm-validate-executor-output-provenance",
    retry_policy_max_attempts=1,
)
async def validate_executor_output_provenance_activity(
    executor_output: ExecutorOutput,
    expected_task_id: str,
    expected_run_id: str,
) -> ExecutorOutput:
    """
    Validate ExecutorOutput provenance before converting to EvidenceRecord.

    Checks:
    - executor_output.task_id == expected_task_id
    - executor_output.metadata.task_id == expected_task_id
    - executor_output.metadata.run_id == expected_run_id

    Rejects mismatches. Never relabels mismatched ExecutorOutput as evidence.

    Args:
        executor_output: The ExecutorOutput to validate.
        expected_task_id: The expected task_id from the canonical ChildTask.
        expected_run_id: The expected run_id from the canonical RunState.

    Returns:
        The validated ExecutorOutput (same object).

    Raises:
        ProvenanceValidationError: If any provenance check fails.
    """
    # Check all three provenance requirements
    if executor_output.task_id != expected_task_id:
        raise ProvenanceValidationError(
            message=f"ExecutorOutput task_id mismatch: expected '{expected_task_id}', got '{executor_output.task_id}'",
            expected_task_id=expected_task_id,
            actual_task_id=executor_output.task_id,
            expected_run_id=expected_run_id,
            actual_run_id=executor_output.run_id,
            check_type="output_task_id",
        )

    if executor_output.run_id != expected_run_id:
        raise ProvenanceValidationError(
            message=f"ExecutorOutput run_id mismatch: expected '{expected_run_id}', got '{executor_output.run_id}'",
            expected_task_id=expected_task_id,
            actual_task_id=executor_output.task_id,
            expected_run_id=expected_run_id,
            actual_run_id=executor_output.run_id,
            check_type="output_run_id",
        )

    if executor_output.metadata.task_id != expected_task_id:
        raise ProvenanceValidationError(
            message=f"ExecutorOutput metadata.task_id mismatch: expected '{expected_task_id}', got '{executor_output.metadata.task_id}'",
            expected_task_id=expected_task_id,
            actual_task_id=executor_output.metadata.task_id,
            expected_run_id=expected_run_id,
            actual_run_id=executor_output.metadata.run_id,
            check_type="metadata_task_id",
        )

    if executor_output.metadata.run_id != expected_run_id:
        raise ProvenanceValidationError(
            message=f"ExecutorOutput metadata.run_id mismatch: expected '{expected_run_id}', got '{executor_output.metadata.run_id}'",
            expected_task_id=expected_task_id,
            actual_task_id=executor_output.task_id,
            expected_run_id=expected_run_id,
            actual_run_id=executor_output.metadata.run_id,
            check_type="metadata_run_id",
        )

    return executor_output


@activity(
    name="fsasm-convert-executor-output-to-evidence",
    retry_policy_max_attempts=1,
)
async def convert_executor_output_to_evidence_activity(
    executor_output: ExecutorOutput,
    task: ChildTask,
    evidence_counter: int,
) -> list[EvidenceRecord]:
    """
    Convert validated ExecutorOutput to EvidenceRecord(s).

    For deterministic M3 stub execution:
    - If task.expected_evidence is empty, create one fallback evidence record with kind "executor_output"
    - Otherwise, create one EvidenceRecord per declared expected evidence kind

    Uses deterministic safe IDs (ordinal counters) while keeping the original evidence kind as data.

    Args:
        executor_output: The validated ExecutorOutput.
        task: The ChildTask being executed.
        evidence_counter: An ordinal counter for generating deterministic evidence IDs.

    Returns:
        List of EvidenceRecord instances.
    """
    run_id = executor_output.run_id
    task_id = executor_output.task_id
    evidence_records: list[EvidenceRecord] = []

    if not task.expected_evidence:
        # Fallback: one evidence record with kind "executor_output"
        evidence_id = f"evidence-{run_id}-{task_id}-exec-{evidence_counter:03d}-000"
        evidence_record = EvidenceRecord(
            evidence_id=evidence_id,
            run_id=run_id,
            task_id=task_id,
            kind="executor_output",
            source="executor_stub",
            payload={
                "executor_output": executor_output.model_dump(),
                "original_evidence_kinds": [],
            },
        )
        evidence_records.append(evidence_record)
    else:
        # Create one EvidenceRecord per declared expected evidence kind
        for idx, expected_kind in enumerate(task.expected_evidence):
            evidence_id = (
                f"evidence-{run_id}-{task_id}-exec-{evidence_counter:03d}-{idx:03d}"
            )
            evidence_record = EvidenceRecord(
                evidence_id=evidence_id,
                run_id=run_id,
                task_id=task_id,
                kind=expected_kind,
                source="executor_stub",
                payload={
                    "executor_output": executor_output.model_dump(),
                    "original_evidence_kind": expected_kind,
                    "evidence_index": idx,
                },
            )
            evidence_records.append(evidence_record)

    return evidence_records


@activity(
    name="fsasm-verify-task-execution",
    retry_policy_max_attempts=1,
)
async def verify_task_execution_activity(
    run_id: str,
    task: ChildTask,
    evidence_records: list[EvidenceRecord],
) -> VerificationResult:
    """
    Verify task execution using deterministic checks.

    Thin wrapper around domain verifier.VerificationSpec.expected check.

    Verification operates on:
    - authoritative run_id
    - ChildTask
    - list[EvidenceRecord]

    Evidence must match BOTH:
    - evidence.run_id == authoritative run_id
    - evidence.task_id == task.task_id

    Verification requires ALL declared expected evidence kinds to be present.

    Args:
        run_id: The authoritative run_id.
        task: The ChildTask being verified.
        evidence_records: List of EvidenceRecord for this task.

    Returns:
        VerificationResult with PASS or FAIL.
    """
    from fsasm.verifier import DeterministicVerifier

    verifier = DeterministicVerifier()
    return verifier.verify_task_execution(run_id, task, evidence_records)


@activity(
    name="fsasm-prepare-task",
    retry_policy_max_attempts=1,
)
async def prepare_task_activity(
    state: RunState,
    task: ChildTask,
) -> tuple[RunState, ChildTask]:
    """
    Prepare a task for execution.

    BEFORE Executor execution begins, persisted state must already truthfully represent:
    - RunState.status = RUNNING
    - RunState.active_task_id = executed task ID
    - TASK-001.status = RUNNING
    - TASK-002/003 = PENDING

    This must be true in BOTH runtime/.../state.json and runtime/.../plan.json.

    If the workflow crashes immediately after prepare, filesystem state must still be internally consistent.

    Args:
        state: The current RunState.
        task: The ChildTask to prepare.

    Returns:
        Tuple of (updated RunState, updated ChildTask).
    """
    persistence = RuntimePersistence()

    # Transition run to RUNNING (from PLANNED) first
    from fsasm.transitions import transition_run

    if state.status == RunStatus.PLANNED:
        state = transition_run(state, RunStatus.RUNNING)

    # Transition task to RUNNING
    task = transition_task(task, TaskStatus.RUNNING)

    # Update state
    state.active_task_id = task.task_id
    state.touch()

    # Update plan in state to reflect task status change
    # Replace the task object in the plan rather than just assigning status
    if state.plan is not None:
        plan = state.plan
        updated_tasks = []
        for plan_task in plan.tasks:
            if plan_task.task_id == task.task_id:
                # Replace with the transitioned task
                updated_tasks.append(task)
            else:
                # Keep other tasks as-is
                updated_tasks.append(plan_task)
        plan.tasks = updated_tasks

    # Persist state
    persistence.save_run_state(state)

    # Persist plan
    if state.plan is not None:
        persistence.save_plan(state.plan)

    return state, task


@activity(
    name="fsasm-finalize-task",
    retry_policy_max_attempts=1,
)
async def finalize_task_activity(
    state: RunState,
    task: ChildTask,
    verification_result: VerificationResult,
    evidence_records: list[EvidenceRecord],
) -> tuple[RunState, ChildTask]:
    """
    Finalize a task after execution and verification.

    After FINALIZE, persisted state must truthfully represent:

    PASS path:
    - TASK-001 = PASSED
    - completed_task_ids contains TASK-001
    - failed_task_ids does not
    - active_task_id = None
    - RunState = RUNNING

    FAIL path:
    - TASK-001 = FAILED
    - failed_task_ids contains TASK-001
    - completed_task_ids does not
    - active_task_id = None
    - RunState = RUNNING

    Again, state.plan and persisted plan.json must agree.

    Args:
        state: The current RunState.
        task: The ChildTask that was executed.
        verification_result: The VerificationResult from task verification.
        evidence_records: The EvidenceRecord list for this task.

    Returns:
        Tuple of (updated RunState, updated ChildTask).
    """
    persistence = RuntimePersistence()

    # Determine final task status from verification
    if verification_result.status == VerificationResultStatus.PASS:
        task = transition_task(task, TaskStatus.PASSED, verification_pass=True)
        state.completed_task_ids.append(task.task_id)
    else:
        task = transition_task(task, TaskStatus.FAILED, verification_pass=False)
        state.failed_task_ids.append(task.task_id)

    # Clear active task
    state.active_task_id = None

    # RunState remains RUNNING (per M3 requirements)
    # state.status = RunStatus.RUNNING  # Already RUNNING

    # Update plan in state to reflect task status change
    if state.plan is not None:
        plan = state.plan
        for plan_task in plan.tasks:
            if plan_task.task_id == task.task_id:
                plan_task.status = task.status
            # Other tasks remain in their current status (should be PENDING)

    # Persist evidence records
    for evidence in evidence_records:
        persistence.save_evidence(evidence)

    # Persist verification result
    persistence.save_verification_result(verification_result)

    # Persist state
    state.touch()
    persistence.save_run_state(state)

    # Persist plan
    if state.plan is not None:
        persistence.save_plan(state.plan)

    return state, task
