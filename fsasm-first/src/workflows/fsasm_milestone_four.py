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
from enum import Enum
from typing import Any

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
# F6/F7 DETERMINISTIC GATE / DECISION IDENTITY HELPERS
# =============================================================================
#
# Deterministic identifiers for Human Gate occurrences and logical decisions.
# No random identifiers or wall-clock values inside deterministic workflow
# control flow. ``gate_id`` derives from run_id/task_id/attempt (the attempt at
# gate time uniquely identifies each consecutive gate occurrence for the same
# task); ``decision_id`` derives from run_id/task_id/gate_id/action so the same
# logical decision is idempotent and a contradictory reuse is detectable.


def _gate_id(run_id: str, task_id: str, attempt: int) -> str:
    """Deterministic gate-occurrence identifier."""
    return f"gate-{run_id}-{task_id}-attempt-{attempt}"


def _decision_id(
    run_id: str, task_id: str, gate_id: str, action: HumanDecisionAction
) -> str:
    """Deterministic logical-decision identifier."""
    return f"decision-{run_id}-{task_id}-{gate_id}-{action.value}"


# =============================================================================
# F6/F7 OPEN-GATE IDENTITY CONTRACT (T04)
# =============================================================================
#
# A Human Decision can be accepted ONLY for the currently open gate, and only
# when its run, task and gate identities match EXACTLY. The open gate is
# represented by a typed ``OpenGate`` structure so the signal handler never
# infers run/task identity by substring matching against a concatenated
# gate-id string. Deterministic identifiers are generated only from
# run_id/task_id/attempt; no random identifiers or wall-clock values are used
# inside deterministic workflow control flow.


class GateLifecycle(str, Enum):
    """Lifecycle states of a Human Gate occurrence.

    IDENTITY_REGISTERED -> NEEDS_HUMAN_PERSISTED -> WAITING ->
    DECISION_ACCEPTED -> DECISION_APPLIED -> GATE_CLOSED.

    Registering the gate identity before NEEDS_HUMAN is durably persisted
    eliminates the signal-loss interval: a valid signal arriving after
    persistence but before the wait is retained for the correct gate, but it
    is NOT applied before the activity has successfully persisted
    NEEDS_HUMAN. If persistence fails, no pending signal may authorize
    execution through an uncommitted gate.
    """

    IDENTITY_REGISTERED = "identity_registered"
    NEEDS_HUMAN_PERSISTED = "needs_human_persisted"
    WAITING = "waiting"
    DECISION_ACCEPTED = "decision_accepted"
    DECISION_APPLIED = "decision_applied"
    GATE_CLOSED = "gate_closed"


class OpenGate(BaseModel):
    """Exact identity of the currently open Human Gate.

    Provides exact access to run_id, task_id, gate_id and attempt so the
    signal handler compares incoming identities with equality, never by
    substring membership in a serialized gate-id string.
    """

    run_id: str
    task_id: str
    gate_id: str
    attempt: int
    lifecycle: GateLifecycle = GateLifecycle.IDENTITY_REGISTERED


# =============================================================================
# HUMAN DECISION SIGNAL MODEL
# =============================================================================


class HumanDecisionSignal(BaseModel):
    """Signal payload for human decision.

    F6/F7 identity: carries explicit gate_id and decision_id so conflicting
    overwrites, duplicate delivery and stale/gate-mismatched decisions can be
    detected deterministically. The handler derives gate_id/decision_id from
    run_id/task_id/attempt when not supplied. ``run_id`` lets the handler
    reject a wrong-run decision before it can authorize the open gate.
    """

    task_id: str = Field(..., description="The task_id this decision applies to.")
    action: HumanDecisionAction = Field(
        ..., description="Human decision action: RETRY_ONCE or ABORT."
    )
    reason: str = Field(default="", description="Optional reason for the decision.")
    run_id: str | None = Field(
        default=None,
        description=(
            "Run the decision targets. If supplied, the handler rejects a "
            "wrong-run signal before it can authorize the open gate."
        ),
    )
    gate_id: str | None = Field(
        default=None,
        description=(
            "Gate occurrence identifier. If supplied, it must equal the "
            "currently open gate or the signal is rejected as wrong_gate."
        ),
    )
    decision_id: str | None = Field(
        default=None,
        description="Logical decision identifier. If omitted, the handler derives it.",
    )


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

    Creates initial RunState with PLANNED status.
    active_task_id=None, all tasks PENDING, authoritative max_attempts already persisted.
    PLANNED -> RUNNING happens later when task execution is actually prepared.
    """
    persistence = RuntimePersistence()

    plan = planner_output.plan
    metadata = planner_output.metadata
    run_id = plan.run_id

    # Create initial run state with PLANNED status
    # active_task_id=None, all tasks PENDING
    state = RunState(
        run_id=run_id,
        goal=goal_input.goal,
        status=RunStatus.PLANNED,
        plan=plan,
        active_task_id=None,
        completed_task_ids=[],
        failed_task_ids=[],
    )

    # F4: explicitly reserve the run directory before any write. A duplicate
    # run_id is rejected here rather than silently overwriting existing state.
    persistence.create_run(run_id)

    # F3: commit the authoritative snapshot (state.json, with embedded plan)
    # first, then the derived plan.json. A crash between the two leaves a stale
    # plan.json that recovery repairs from state.json.
    persistence.commit_run_state(state)

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

    # Log the creation - report the actually persisted initial status (PLANNED),
    # not RUNNING. PLANNED -> RUNNING happens later during prepare_task_activity.
    persistence.save_run_log_entry(
        run_id,
        {
            "event": "m4_run_started",
            "run_id": run_id,
            "goal": goal_input.goal,
            "status": state.status.value,
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

    # F3: commit the authoritative snapshot (state.json first, then derived
    # plan.json). A crash before this point leaves the prior authoritative
    # snapshot intact; the FAILED transition is not committed until here.
    persistence.commit_run_state(state)

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

    # F3: commit the authoritative snapshot (state.json first, then derived
    # plan.json). The NEEDS_HUMAN transition is not durably committed until the
    # authoritative snapshot is written here.
    persistence.commit_run_state(state)

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

    # Single source of truth: the authoritative plan lives on state.plan.
    # Activity arguments cross the worker boundary via serialization, so `state`
    # and `plan` arrive as independent copies; mutating the `plan` arg alone
    # would leave state.plan (and thus state.json) stale relative to plan.json.
    # Reconcile both to one object before persisting, then return that object.
    if state.plan is None:
        authoritative_plan = plan
    else:
        authoritative_plan = state.plan

    if authoritative_plan is not None:
        for plan_task in authoritative_plan.tasks:
            if plan_task.task_id == task.task_id:
                plan_task.status = task.status
                plan_task.attempt = task.attempt

    # Keep state.plan and the returned plan as the same object so callers cannot
    # observe divergence regardless of how they reference the plan.
    state.plan = authoritative_plan
    plan = authoritative_plan

    # F3: commit the authoritative snapshot (state.json first, then derived
    # plan.json) from the single authoritative source.
    persistence.commit_run_state(state)

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
    gate_id: str | None = None,
    decision_id: str | None = None,
) -> tuple[ChildTask, RunState, HumanDecision]:
    """
    Validate and apply a human decision to the workflow state.

    Signal handlers must only mutate deterministic workflow-local data.
    No filesystem I/O in signal handlers. Validate and persist through domain/activity code.

    F6/F7 identity validation:
    - decision.task_id must exactly match the currently gated task
    - run_id must match the authoritative state run_id
    - gate_id (if supplied) must match the gate occurrence derived from
      state.run_id/task_id/attempt; a stale decision (different gate) is rejected
    - decision_id (if supplied) is stamped onto the decision for audit/idempotency

    Validation:
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

    # F6/F7: stamp deterministic gate_id / decision_id onto the decision for
    # audit and idempotency. The activity is the single application boundary;
    # duplicate deliveries are filtered by the workflow's applied_decision_ids
    # set, but the activity also validates gate identity independently.
    expected_gate_id = _gate_id(state.run_id, task.task_id, task.attempt)
    # Reject a stale decision: if an explicit gate_id was supplied OR the
    # decision already carries a gate_id from a previous application, it must
    # match the current gate occurrence. A decision accepted for an earlier
    # gate cannot authorize this (later) gate.
    supplied_gate_id = gate_id if gate_id is not None else decision.gate_id
    if supplied_gate_id is not None and supplied_gate_id != expected_gate_id:
        raise InvalidTransitionError(
            from_status=task.status.value,
            to_status=TaskStatus.NEEDS_HUMAN.value,
            entity_type="ChildTask",
            entity_id=task.task_id,
            reason=(
                f"Human decision gate_id '{supplied_gate_id}' does not match the "
                f"current gate occurrence '{expected_gate_id}' "
                f"(stale or wrong-gate decision)"
            ),
        )
    decision.gate_id = expected_gate_id
    if decision_id is not None:
        decision.decision_id = decision_id
    elif decision.decision_id is None:
        decision.decision_id = _decision_id(
            state.run_id, task.task_id, expected_gate_id, decision.action
        )

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
        # Capture the real pre-transition state snapshot before any mutation,
        # so the audit records the actual values rather than reconstructed ones.
        attempt_before = task.attempt
        max_attempts_before = task.max_attempts
        task_status_before = task.status.value
        run_status_before = state.status.value

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
        # F3: commit the authoritative snapshot (state.json first, then derived
        # plan.json). The human-authorized transition is not durably committed
        # until the authoritative snapshot is written here, before the audit
        # evidence and log.
        persistence.commit_run_state(state)

        # Read the real post-transition values from the actual objects.
        attempt_after = task.attempt
        max_attempts_after = task.max_attempts
        task_status_after = task.status.value
        run_status_after = state.status.value

        # Persist Human Gate audit evidence.
        # RETRY_ONCE does not reset task.attempt, so task.attempt at decision
        # time equals the execution attempt that just failed. It therefore
        # uniquely and deterministically identifies each consecutive
        # RETRY_ONCE decision on the same run/task, preventing a later audit
        # from overwriting an earlier one under a shared evidence_id path.
        audit_evidence = EvidenceRecord(
            evidence_id=(
                f"evidence-human-gate-retry-{state.run_id}-{task.task_id}"
                f"-attempt-{task.attempt}"
            ),
            run_id=state.run_id,
            task_id=task.task_id,
            kind="human_gate_audit",
            source="fsasm_milestone_four_workflow",
            payload={
                "action": "RETRY_ONCE",
                "reason": decision.reason,
                "task_id": task.task_id,
                "gate_id": decision.gate_id,
                "decision_id": decision.decision_id,
                "run_id": state.run_id,
                "attempt_before": attempt_before,
                "attempt_after": attempt_after,
                "max_attempts_before": max_attempts_before,
                "max_attempts_after": max_attempts_after,
                "task_status_before": task_status_before,
                "task_status_after": task_status_after,
                "run_status_before": run_status_before,
                "run_status_after": run_status_after,
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
                "gate_id": decision.gate_id,
                "decision_id": decision.decision_id,
                "reason": decision.reason,
                "new_max_attempts": task.max_attempts,
                "current_attempt": task.attempt,
                "timestamp": state.updated_at,
            },
        )

    elif decision.action == HumanDecisionAction.ABORT:
        # Capture the real pre-transition state snapshot before any mutation,
        # so the audit records the actual values rather than reconstructed ones.
        attempt_before = task.attempt
        max_attempts_before = task.max_attempts
        task_status_before = task.status.value
        run_status_before = state.status.value

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
        # F3: commit the authoritative snapshot (state.json first, then derived
        # plan.json). The human-authorized transition is not durably committed
        # until the authoritative snapshot is written here, before the audit
        # evidence and log.
        persistence.commit_run_state(state)

        # Read the real post-transition values from the actual objects.
        attempt_after = task.attempt
        max_attempts_after = task.max_attempts
        task_status_after = task.status.value
        run_status_after = state.status.value

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
                "gate_id": decision.gate_id,
                "decision_id": decision.decision_id,
                "run_id": state.run_id,
                "attempt_before": attempt_before,
                "attempt_after": attempt_after,
                "max_attempts_before": max_attempts_before,
                "max_attempts_after": max_attempts_after,
                "task_status_before": task_status_before,
                "task_status_after": task_status_after,
                "run_status_before": run_status_before,
                "run_status_after": run_status_after,
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
                "gate_id": decision.gate_id,
                "decision_id": decision.decision_id,
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

    # F3: commit the authoritative snapshot (state.json first, then derived
    # plan.json). Use the authoritative state's plan so the derived view cannot
    # diverge from the authoritative snapshot.
    state.touch()
    persistence.commit_run_state(state)

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


@workflows.activity(
    name="fsasm-persist-human-gate-rejections",
    retry_policy_max_attempts=1,
)
async def persist_human_gate_rejections_activity(
    run_id: str,
    task_id: str,
    gate_id: str,
    rejected_signals: list[dict[str, Any]],
) -> None:
    """Persist auditable records of rejected Human Gate signals.

    Signal handlers must not perform filesystem I/O, so rejected signals are
    collected in the workflow-local ``pending_rejections`` buffer and durably
    drained here (an activity) by the event-driven wait loop that reacts to BOTH
    an accepted decision AND unaudited rejections. This means a run waiting
    indefinitely after only invalid signals STILL produces a durable rejection
    record; rejections are never held only in memory pending a valid decision.
    A monotonic ``flushed_rejections`` cursor advances so a gate-1 rejection
    is never re-flushed or misattributed to gate 2. This gives an auditable,
    durable record explaining why a signal was rejected (wrong_gate, wrong_run,
    wrong_task, conflicting first-wins, contradictory decision_id reuse,
    no_open_gate). Rejection of an invalid signal does not terminate or
    authorize the workflow; it is recorded for explanation only.
    """
    if not rejected_signals:
        return
    persistence = RuntimePersistence()
    persistence.save_run_log_entry(
        run_id,
        {
            "event": "human_gate_rejected_signals",
            "run_id": run_id,
            "task_id": task_id,
            "gate_id": gate_id,
            "rejections": rejected_signals,
        },
    )


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
    4. Set task.max_attempts from workflow config (authoritative budget)
    5. Persist initial state (PLANNED, with authoritative max_attempts already set)
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
    - A successful M4 path is successful completion of the M4 TASK-001 path,
      NOT completion of all three tasks or the user's original goal
    - The Executor is a deterministic STUB, not a real coding Executor
    - attempt increments exactly once on READY -> RUNNING (BEFORE Executor execution)
    - FAILED -> READY does NOT increment attempt
    - All state transitions use transition API or human-authorized domain operations
    - Evidence is separate from ExecutorOutput
    - Verifier receives EvidenceRecord, not ExecutorOutput
    - NEEDS_HUMAN state is persisted for BOTH task AND run BEFORE waiting for
      signal. The open gate identity (current_gate_id) is registered BEFORE
      NEEDS_HUMAN is persisted, eliminating the signal-loss interval: a valid
      signal arriving after persistence but before the wait is preserved
    - Human decisions are typed, validated, persisted and identity-bound:
      each decision targets one gate occurrence (gate_id) and is idempotent
      (decision_id); the first accepted decision wins and a conflicting later
      signal cannot overwrite it; a stale (wrong-gate), future-gate,
      wrong-task or wrong-run decision is rejected (auditable) without
      terminating or authorizing the workflow; a decision for an unopened
      future gate cannot be pre-authorized; rejected signals are durably
      recorded via an activity for audit
    - Authoritative persistence (F3): state.json (with embedded plan) is the
      single source of truth; plan.json is a derived view, NEVER a competing
      authority. A transition is not durably committed until the authoritative
      snapshot is committed via commit_run_state (state.json first, then
      plan.json). This is NOT a fully transactional store: evidence/log writes
      are separate supplementary artifacts, not part of the same atomic
      transaction as state.json
    - Run identity (F4): create_run is the explicit new-run boundary; a
      duplicate run_id is rejected and existing artifacts are never silently
      overwritten
    - success field represents successful completion of M4 task path (not run == PASSED)
    - ALL filesystem I/O happens in activities, not in workflow code
    """

    def __init__(self):
        # F6/F7: bounded, identity-aware pending-decision mechanism. A single
        # overwritable slot let a later signal overwrite an earlier pending
        # signal before consumption. Instead we keep:
        #   * accepted_decisions: gate_id -> accepted HumanDecision (first-wins;
        #     a conflicting later signal for the same gate is rejected without
        #     overwriting the accepted one);
        #   * applied_decision_ids: set of decision_ids already applied (idempotent
        #     application; a duplicate delivery is a no-op, not a second
        #     transition);
        #   * pending_rejections: per-gate rejection records not yet durably
        #     flushed. Each entry carries its originating gate_id (or None for
        #     signals received while no gate is open) so a rejection belonging
        #     to gate 1 is never misattributed to gate 2. flushed_count tracks
        #     the number of entries already durably persisted so the draining
        #     loop advances a monotonically increasing cursor (no duplication).
        self.accepted_decisions: dict[str, HumanDecision] = {}
        self.applied_decision_ids: set[str] = set()
        self.pending_rejections: list[dict[str, Any]] = []
        self.flushed_rejections: int = 0
        # D3: rejection_ids already durably flushed, so a replayed/retried
        # flush does not duplicate logical audit records. Exactly-once is NOT
        # claimed across crashes (no durable dedup store); within a workflow
        # execution this prevents duplicate logical records from repeated
        # flushes of the same in-memory rejection.
        self.flushed_rejection_ids: set[str] = set()
        # T04: the exact identity of the currently open gate. The signal
        # handler compares incoming run_id/task_id/gate_id with EQUALITY
        # against this structure, never by substring matching against the
        # serialized gate-id string.
        self.current_gate: OpenGate | None = None
        # The current gate_id being waited on (set before wait_condition).
        self.current_gate_id: str | None = None

    def _append_rejection(self, record: dict[str, Any]) -> None:
        """Append a rejection record with a stable deterministic rejection_id.

        The rejection_id is a deterministic string key over the meaningful
        rejection payload (gate tag, reason, task/run/action/decision identity,
        accepted/rejected action and reason) so a replayed delivery of the
        same rejected signal does not create two distinct in-memory records
        (idempotent buffering). It is stamped onto the record for idempotent
        persistence (D3). No cryptographic hashing is used inside the
        deterministic workflow (the SDK forbids CPU-intensive crypto in
        workflow code); this key is for in-execution dedup only and is NOT a
        durable cross-crash dedup store (exactly-once across crashes is not
        claimed).
        """
        rid = record.get("rejection_id")
        if rid is None:
            rid = "rej|" + "|".join(
                str(record.get(k, ""))
                for k in (
                    "gate_id",
                    "reason",
                    "task_id",
                    "run_id",
                    "action",
                    "decision_id",
                    "accepted_action",
                    "rejected_action",
                    "accepted_reason",
                    "rejected_reason",
                )
            )
            record["rejection_id"] = rid
        if not any(r.get("rejection_id") == rid for r in self.pending_rejections):
            self.pending_rejections.append(record)

    async def _flush_pending_rejections(
        self, run_id: str, task_id: str, gate_id: str
    ) -> None:
        """Durably flush all unflushed pending rejections for the current
        cursor position, grouped by each rejection's OWN recorded gate tag so a
        rejection is never misattributed to a different gate occurrence (D1/D6).
        A ``no_open_gate`` rejection (gate tag None) is flushed with gate_id
        None, never under the currently open gate. Rejections already flushed
        (by rejection_id) are skipped so a retried flush does not duplicate
        logical audit records (D3). Advances the cursor over all processed
        (skipped or persisted) records.
        """
        if self.flushed_rejections >= len(self.pending_rejections):
            return
        # Group unflushed records by their recorded gate tag (the gate the
        # signal was evaluated against), preserving insertion order.
        groups: dict[str | None, list[dict[str, Any]]] = {}
        order: list[str | None] = []
        for r in self.pending_rejections[self.flushed_rejections :]:
            rid = r.get("rejection_id")
            if rid is not None and rid in self.flushed_rejection_ids:
                continue
            tag = r.get("gate_id")
            if tag not in groups:
                groups[tag] = []
                order.append(tag)
            groups[tag].append(r)
        for tag in order:
            batch = groups[tag]
            await persist_human_gate_rejections_activity(
                run_id, task_id, tag if tag is not None else gate_id, batch
            )
            for r in batch:
                rid = r.get("rejection_id")
                if rid is not None:
                    self.flushed_rejection_ids.add(rid)
        self.flushed_rejections = len(self.pending_rejections)

    @workflows.workflow.signal(
        name="human_decision",
        description="Signal to provide human decision for Human Gate (RETRY_ONCE or ABORT).",
    )
    async def receive_human_decision(self, signal_data: HumanDecisionSignal) -> None:
        """
        Receive human decision signal.

        Signal handlers must only mutate deterministic workflow-local data.
        No filesystem I/O in signal handlers.

        F6/F7 identity-aware handling (first VALID accepted decision wins):
        - An explicit ``gate_id`` must match the currently open gate. A signal
          for any other gate — future, closed, wrong-task or wrong-run — is
          rejected as ``wrong_gate`` and recorded, WITHOUT terminating or
          authorizing the workflow.
        - ``task_id`` must EXACTLY match the task belonging to the open gate
          (``current_gate.task_id``). A wrong-task signal is rejected as
          ``wrong_task`` BEFORE it can occupy the first-wins slot (BLOCKER A).
        - ``run_id`` (when supplied) must EXACTLY match the run the gate
          belongs to (``current_gate.run_id``), compared by equality — NOT by
          substring membership in the serialized gate-id (BLOCKER B). A
          wrong-run signal is rejected as ``wrong_run``.
        - An INVALID signal never reserves the gate: only the first VALID
          decision is accepted. A conflicting later signal is rejected without
          overwriting the accepted one; a repeated identical signal is a
          no-op duplicate acknowledgement.
        - Reusing the same ``decision_id`` with a contradictory payload
          (task_id, action, gate_id OR reason) is rejected.
        - Rejections are appended to ``pending_rejections`` (each tagged with
          its originating gate_id) and durably drained by the wait loop via an
          activity — even if no valid decision ever arrives (BLOCKER C).
        """
        decision = HumanDecision(
            task_id=signal_data.task_id,
            action=signal_data.action,
            reason=signal_data.reason,
            gate_id=signal_data.gate_id,
            decision_id=signal_data.decision_id,
        )

        gate_id = decision.gate_id
        decision_id = decision.decision_id
        gate_tag = self.current_gate_id if self.current_gate_id is not None else None

        # No open gate: reject every signal as no_open_gate (recorded with the
        # current gate tag, None). A signal before the first gate or after the
        # last gate is explicitly rejected, never silently buffered for a
        # future gate.
        if self.current_gate is None:
            self._append_rejection(
                {
                    "reason": "no_open_gate",
                    "gate_id": gate_tag,
                    "task_id": decision.task_id,
                    "action": decision.action.value,
                }
            )
            return

        cg = self.current_gate

        # BLOCKER 1: an explicit gate_id must match the currently open gate.
        if gate_id is not None and gate_id != cg.gate_id:
            self._append_rejection(
                {
                    "reason": "wrong_gate",
                    "gate_id": gate_id,
                    "current_gate_id": cg.gate_id,
                    "task_id": decision.task_id,
                    "action": decision.action.value,
                }
            )
            return

        # BLOCKER A: exact task_id comparison BEFORE accepting. A wrong-task
        # signal must not occupy the first-wins slot.
        if decision.task_id != cg.task_id:
            self._append_rejection(
                {
                    "reason": "wrong_task",
                    "gate_id": cg.gate_id,
                    "current_task_id": cg.task_id,
                    "task_id": decision.task_id,
                    "action": decision.action.value,
                }
            )
            return

        # BLOCKER B: exact run_id comparison (equality, not substring). A
        # wrong-run signal must not occupy the first-wins slot.
        if signal_data.run_id is not None and signal_data.run_id != cg.run_id:
            self._append_rejection(
                {
                    "reason": "wrong_run",
                    "gate_id": cg.gate_id,
                    "current_run_id": cg.run_id,
                    "run_id": signal_data.run_id,
                    "task_id": decision.task_id,
                    "action": decision.action.value,
                }
            )
            return

        effective_gate_id = cg.gate_id

        # Detect contradictory reuse of the same decision_id: if this
        # decision_id was already accepted but with a different payload (task,
        # action, gate OR reason), reject it without overwriting the accepted
        # one. Two payloads differing only by reason are NOT identical.
        existing_for_id = None
        for existing in self.accepted_decisions.values():
            if existing.decision_id == decision_id and decision_id is not None:
                existing_for_id = existing
                break
        if existing_for_id is not None:
            if (
                existing_for_id.task_id != decision.task_id
                or existing_for_id.action != decision.action
                or existing_for_id.gate_id != effective_gate_id
                or existing_for_id.reason != decision.reason
            ):
                self._append_rejection(
                    {
                        "reason": "contradictory_decision_id_reuse",
                        "decision_id": decision_id,
                        "task_id": decision.task_id,
                        "action": decision.action.value,
                    }
                )
                return
            # Identical duplicate of an already-accepted decision: no-op
            # acknowledgement (idempotent delivery).
            return

        # First accepted VALID decision wins for the open gate. If a decision
        # is already accepted for this gate, a signal is an identical duplicate
        # ONLY when its complete meaningful payload (task_id, action, gate_id,
        # reason) matches. A signal with the same action but a different reason
        # is a contradictory submission and is recorded as rejected, NOT a
        # silent no-op. Two legacy signals (decision_id=None) with the same
        # action but different reason are therefore contradictory.
        if effective_gate_id in self.accepted_decisions:
            existing = self.accepted_decisions[effective_gate_id]
            is_identical_duplicate = (
                existing.task_id == decision.task_id
                and existing.action == decision.action
                and existing.gate_id == effective_gate_id
                and existing.reason == decision.reason
            )
            if not is_identical_duplicate:
                self._append_rejection(
                    {
                        "reason": "conflicting_signal_rejected_first_wins",
                        "gate_id": effective_gate_id,
                        "accepted_action": existing.action.value,
                        "rejected_action": decision.action.value,
                        "accepted_reason": existing.reason,
                        "rejected_reason": decision.reason,
                    }
                )
                return
            # Identical duplicate for the same gate: no-op.
            return

        # Accept the VALID decision, keyed by the open gate so it is applied
        # only to the correct gate occurrence.
        decision.gate_id = effective_gate_id
        self.accepted_decisions[effective_gate_id] = decision

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

        # Step 4: Set authoritative task.max_attempts BEFORE first save_plan/save_run_state
        plan = await set_task_max_attempts_activity(
            planner_output.plan, input.max_retries_per_task
        )
        planner_output = PlannerOutput(
            plan=plan,
            proposal=planner_output.proposal,
            metadata=planner_output.metadata,
        )

        # Step 5: Persist initial state with authoritative max_attempts already set
        plan, state = await persist_initial_state_activity(planner_output, goal_input)

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

                        # F6/F7 BLOCKER 2: register the open gate identity BEFORE
                        # the NEEDS_HUMAN state is durably persisted. The gate_id
                        # derives from run_id/task_id/attempt, all known before the
                        # transition (transition_to_needs_human_activity does not
                        # change attempt). Registering the open-gate identity first
                        # eliminates the signal-loss interval: a valid legacy
                        # signal (no explicit gate_id) arriving after NEEDS_HUMAN
                        # is persisted but before wait_condition is bound to this
                        # gate and preserved, never lost as no_open_gate.
                        gate_id = _gate_id(state.run_id, task.task_id, task.attempt)
                        self.current_gate_id = gate_id
                        self.current_gate = OpenGate(
                            run_id=state.run_id,
                            task_id=task.task_id,
                            gate_id=gate_id,
                            attempt=task.attempt,
                        )

                        # Transition to NEEDS_HUMAN (both task AND run)
                        # BEFORE waiting, filesystem MUST durably contain NEEDS_HUMAN state
                        task, state = await transition_to_needs_human_activity(
                            task, state, reason
                        )
                        needs_human_task_ids.append(task.task_id)
                        # DO NOT add to completed_task_ids - NEEDS_HUMAN is NOT completed
                        plan = state.plan if state.plan is not None else plan
                        # NEEDS_HUMAN is now durably persisted.
                        self.current_gate.lifecycle = (
                            GateLifecycle.NEEDS_HUMAN_PERSISTED
                        )

                        # T05 (BLOCKER C): event-driven wait loop that reacts to BOTH
                        # a newly accepted valid decision AND pending unaudited
                        # rejection records. Rejections are durably flushed via an
                        # activity even if no valid decision ever arrives, so a
                        # run waiting indefinitely after an invalid signal still
                        # produces a durable rejection record. The cursor
                        # (flushed_rejections) advances monotonically, so a
                        # rejection belonging to gate 1 is never re-flushed under
                        # gate 2. The per-entry gate tag is fixed at signal time so
                        # a gate-1 rejection is never misattributed to gate 2.
                        self.current_gate.lifecycle = GateLifecycle.WAITING
                        while True:
                            # Drain rejections not yet durably persisted (D3:
                            # idempotent via flushed_rejection_ids).
                            if self.flushed_rejections < len(self.pending_rejections):
                                await self._flush_pending_rejections(
                                    state.run_id, task.task_id, gate_id
                                )
                                continue
                            # A valid decision for this gate releases the wait.
                            if gate_id in self.accepted_decisions:
                                break
                            await workflows.workflow.wait_condition(
                                lambda: (
                                    gate_id in self.accepted_decisions
                                    or self.flushed_rejections
                                    < len(self.pending_rejections)
                                )
                            )

                        # Flush any remaining rejections recorded before the
                        # accepted decision so the audit is complete before the
                        # transition is applied.
                        await self._flush_pending_rejections(
                            state.run_id, task.task_id, gate_id
                        )

                        # Consume the accepted decision for this gate.
                        decision = self.accepted_decisions[gate_id]
                        applied_id = decision.decision_id or _decision_id(
                            state.run_id, task.task_id, gate_id, decision.action
                        )
                        already_applied = applied_id in self.applied_decision_ids

                        self.current_gate.lifecycle = GateLifecycle.DECISION_ACCEPTED
                        if not already_applied and decision is not None:
                            # Validate and apply human decision through domain/activity code.
                            # Pass gate_id/decision_id so the activity binds the audit
                            # to the correct gate occurrence and rejects stale/gate-
                            # mismatched decisions.
                            (
                                task,
                                state,
                                applied_decision,
                            ) = await validate_and_apply_human_decision_activity(
                                decision,
                                task,
                                state,
                                gate_id=gate_id,
                                decision_id=applied_id,
                            )
                            # F6/F7 BLOCKER 3: mark the decision as applied ONLY
                            # after the activity has durably committed the
                            # transition and audit evidence. A crash or activity
                            # failure before this point leaves the decision_id
                            # unmarked, so recovery/replay can re-apply it.
                            self.applied_decision_ids.add(applied_id)
                            plan = state.plan if state.plan is not None else plan
                            final_human_decision = applied_decision
                            self.current_gate.lifecycle = GateLifecycle.DECISION_APPLIED

                            # D1: flush any rejection that arrived DURING the
                            # application activity (after the pre-application
                            # flush, before gate closure) and attribute it to the
                            # closing gate. This must happen BEFORE the open-gate
                            # identity is invalidated, while current_gate still
                            # identifies the closing gate so the rejection is
                            # not lost or misattributed to a later gate.
                            await self._flush_pending_rejections(
                                state.run_id, task.task_id, gate_id
                            )

                            # T06: close the gate. Invalidate the open-gate
                            # identity so a later signal (stale gate, future gate,
                            # wrong task/run) is rejected against a closed gate
                            # and cannot authorize a later gate occurrence. The
                            # accepted-decision entry is removed from the live
                            # map (it is durably recorded in evidence); a duplicate
                            # delivery of the same decision_id is caught by
                            # applied_decision_ids (idempotent).
                            self.current_gate.lifecycle = GateLifecycle.GATE_CLOSED
                            self.current_gate = None
                            self.current_gate_id = None
                            self.accepted_decisions.pop(gate_id, None)

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
                            # Duplicate delivery of an already-applied decision: no-op,
                            # do not re-transition. The workflow stays at the same
                            # gate state (the task is READY from the first application).
                            # This branch cannot normally run here because the gate is
                            # consumed once, but it documents exactly-once application.
                            # D1: still flush any rejection that arrived during
                            # this iteration before closing the gate.
                            await self._flush_pending_rejections(
                                state.run_id, task.task_id, gate_id
                            )
                            self.current_gate = None
                            self.current_gate_id = None
                            self.accepted_decisions.pop(gate_id, None)
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
