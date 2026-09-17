"""FS-ASM domain models - Pydantic schemas for the core domain."""

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# ENUMS
# =============================================================================


class PlannerBackend(str, Enum):
    """Available planner backends."""

    STUB = "stub"
    MISTRAL = "mistral"


class ExecutorBackend(str, Enum):
    """Available executor backends."""

    STUB = "stub"
    LOCAL = "local"
    MISTRAL = "mistral"


class TaskStatus(str, Enum):
    """Status of a ChildTask in the FS-ASM state machine."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class RunStatus(str, Enum):
    """Status of a RunState in the FS-ASM state machine."""

    CREATED = "CREATED"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class VerificationResultStatus(str, Enum):
    """Status of a VerificationResult."""

    PASS = "PASS"
    FAIL = "FAIL"


class VerificationType(str, Enum):
    """Type of verification to perform."""

    SCHEMA = "schema"
    EXISTS = "exists"
    COUNT = "count"
    CUSTOM = "custom"


# =============================================================================
# HUMAN DECISION ENUMS (M4)
# =============================================================================


class HumanDecisionAction(str, Enum):
    """Human decision actions for Human Gate (M4)."""

    RETRY_ONCE = "RETRY_ONCE"
    ABORT = "ABORT"


# =============================================================================
# MODELS
# =============================================================================


class TaskProposal(BaseModel):
    """
    Semantic task proposal from LLM - contains only content, no runtime-owned fields.

    Dependencies use proposal-local references (sequence numbers) that the assembler
    maps deterministically to runtime task IDs.
    """

    title: str = Field(..., min_length=1, description="Short title of the task.")
    description: str = Field(
        ..., min_length=1, description="Detailed description of the task."
    )
    dependencies: list[int] = Field(
        default_factory=list,
        description="List of sequence numbers this task depends on (proposal-local refs).",
    )
    verification_type: str = Field(
        ...,
        description="Type of verification: 'schema', 'exists', 'count', 'custom'.",
    )
    verification_expected: str = Field(
        ..., description="Expected value or condition for verification."
    )
    constraints: list[str] = Field(
        default_factory=list, description="List of constraints for this task."
    )
    allowed_files: list[str] = Field(
        default_factory=list,
        description="List of file patterns this task is allowed to modify.",
    )
    expected_evidence: list[str] = Field(
        default_factory=list, description="List of expected evidence types/paths."
    )

    @field_validator(
        "title", "description", "verification_type", "verification_expected"
    )
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text cannot be empty")
        return v.strip()


class PlannerProposal(BaseModel):
    """
    Semantic plan proposal from LLM - contains only content, no runtime-owned fields.

    The authoritative Plan.goal always comes from GoalInput.goal.
    Task IDs are assigned by the deterministic assembler, not by the LLM.
    """

    tasks: list[TaskProposal] = Field(
        ..., min_length=3, max_length=3, description="Exactly 3 task proposals."
    )

    @field_validator("tasks")
    @classmethod
    def validate_task_count(cls, v: list[TaskProposal]) -> list[TaskProposal]:
        if len(v) != 3:
            raise ValueError(
                "Proposal must contain exactly 3 TaskProposal for milestone 1"
            )
        return v


class PlannerConfig(BaseModel):
    """Serializable planner configuration for workflow input."""

    backend: PlannerBackend = Field(
        ..., description="Selected backend: 'stub' or 'mistral'."
    )
    model_name: str | None = Field(
        default=None, description="Model name (required for backend='mistral')."
    )
    model_version: str | None = Field(default=None, description="Model version.")
    prompt_version: str = Field(default="v1.0", description="Prompt template version.")
    max_tokens: int = Field(
        default=4096, ge=1, description="Maximum tokens for LLM response."
    )
    temperature: float = Field(
        default=0.0, ge=0.0, le=2.0, description="Sampling temperature."
    )


class ExecutorConfig(BaseModel):
    """Serializable executor configuration for workflow input."""

    backend: ExecutorBackend = Field(
        ..., description="Selected backend: 'stub', 'local', or 'mistral'."
    )
    model_name: str | None = Field(
        default=None,
        description="Model name (required for backend='mistral' or 'local').",
    )
    model_version: str | None = Field(default=None, description="Model version.")
    max_tokens: int = Field(
        default=4096, ge=1, description="Maximum tokens for LLM response."
    )
    temperature: float = Field(
        default=0.0, ge=0.0, le=2.0, description="Sampling temperature."
    )
    # M4: Deterministic stub failure configuration
    stub_fail_first_n_attempts: int = Field(
        default=0,
        ge=0,
        description="Number of initial attempts that should fail (0=always pass, 999=always fail).",
    )


class ExecutorMetadata(BaseModel):
    """
    Executor metadata for observability - explicitly tied to run_id and task_id.

    Contains all required observability fields:
    - provider, requested/resolved model
    - model_call_count (0 for stub)
    - token usage (None if not available)
    - run_id and task_id for traceability
    """

    run_id: str = Field(..., description="The run_id this metadata belongs to.")
    task_id: str = Field(..., description="The task_id this metadata belongs to.")
    provider: str = Field(
        ..., description="Provider name: 'stub', 'local', or 'mistral'."
    )
    requested_model: str | None = Field(
        default=None, description="Requested model name (None for stub)."
    )
    resolved_model: str | None = Field(
        default=None, description="Actually resolved model name."
    )
    model_version: str | None = Field(
        default=None, description="Model version (if available)."
    )
    model_call_count: int = Field(
        default=0,
        ge=0,
        description="Number of model API calls made (0=stub).",
    )
    executor_invocation_count: int = Field(
        default=1,
        ge=1,
        description="Number of executor invocations.",
    )
    input_tokens: int | None = Field(
        default=None, ge=0, description="Input tokens used (None if not available)."
    )
    output_tokens: int | None = Field(
        default=None, ge=0, description="Output tokens used (None if not available)."
    )
    total_tokens: int | None = Field(
        default=None, ge=0, description="Total tokens used (None if not available)."
    )
    provider_request_id: str | None = Field(
        default=None,
        description="Provider-specific request ID.",
    )


class PlannerMetadata(BaseModel):
    """
    Planner metadata for observability - explicitly tied to run_id.

    Contains all required observability fields:
    - provider, requested/resolved model, prompt_version, prompt hash
    - model_call_count (0 for stub, 1 for mistral)
    - token usage (None if not available from the chosen method)
    - run_id for traceability
    """

    run_id: str = Field(..., description="The run_id this metadata belongs to.")
    provider: str = Field(..., description="Provider name: 'stub' or 'mistral'.")
    requested_model: str | None = Field(
        default=None, description="Requested model name (None for stub)."
    )
    resolved_model: str | None = Field(
        default=None, description="Actually resolved model name."
    )
    model_version: str | None = Field(
        default=None, description="Model version (if available)."
    )
    prompt_version: str = Field(..., description="Prompt template version used.")
    template_hash: str = Field(
        ...,
        description="SHA256 hash of the prompt template (deterministic, no runtime data).",
    )
    rendered_hash: str = Field(
        ...,
        description="SHA256 hash of the rendered prompt (includes runtime goal).",
    )
    model_call_count: int = Field(
        default=0,
        ge=0,
        description="Number of model API calls made (0=stub, 1=mistral).",
    )
    planner_invocation_count: int = Field(
        default=1,
        ge=1,
        description="Number of planner invocations (always >= model_call_count).",
    )
    input_tokens: int | None = Field(
        default=None, ge=0, description="Input tokens used (None if not available)."
    )
    output_tokens: int | None = Field(
        default=None, ge=0, description="Output tokens used (None if not available)."
    )
    total_tokens: int | None = Field(
        default=None, ge=0, description="Total tokens used (None if not available)."
    )
    provider_request_id: str | None = Field(
        default=None,
        description="Provider-specific request ID (e.g., Mistral response.id).",
    )

    @field_validator("template_hash", "rendered_hash")
    @classmethod
    def validate_hash_length(cls, v: str) -> str:
        if len(v) != 64:
            raise ValueError("SHA256 hash must be 64 characters")
        return v.lower()

    @classmethod
    def compute_template_hash(cls, template: str) -> str:
        """Compute SHA256 hash of a prompt template."""
        return hashlib.sha256(template.encode("utf-8")).hexdigest()

    @classmethod
    def compute_rendered_hash(cls, rendered: str) -> str:
        """Compute SHA256 hash of a rendered prompt."""
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


class GoalInput(BaseModel):
    """Input for a new FS-ASM run - the user's goal."""

    goal: str = Field(
        ..., min_length=1, description="The goal to achieve. Cannot be blank."
    )
    run_id: str | None = Field(
        default=None, description="Optional run ID. If omitted, one will be generated."
    )

    @field_validator("goal")
    @classmethod
    def goal_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("goal cannot be blank")
        return v.strip()

    def generate_run_id(self) -> str:
        """Generate a deterministic run_id if not provided."""
        return self.run_id or str(uuid4())


class VerificationSpec(BaseModel):
    """Specification for how to verify a task's result."""

    type: VerificationType = Field(..., description="Type of verification to perform.")
    expected: str = Field(
        ..., description="Expected value or condition for verification."
    )


class VerificationCheck(BaseModel):
    """A single verification check result."""

    check_name: str = Field(..., description="Name/description of the check.")
    passed: bool = Field(..., description="Whether the check passed.")
    message: str = Field(default="", description="Additional message about the check.")


class VerificationResult(BaseModel):
    """Result of verification for a task or plan."""

    run_id: str = Field(..., description="The run ID this verification belongs to.")
    task_id: str | None = Field(
        default=None, description="The task ID being verified, if applicable."
    )
    status: VerificationResultStatus = Field(..., description="PASS or FAIL.")
    checks: list[VerificationCheck] = Field(
        default_factory=list, description="List of individual verification checks."
    )
    message: str = Field(
        default="", description="Summary message for the verification."
    )


class TaskBudget(BaseModel):
    """Configurable limits for a single Child Task attempt (T04).

    Budgets are advisory caps enforced at the execution boundary; they are
    part of the authoritative snapshot so a resumed run keeps the same limits.
    ``None`` means the limit is not set (falls back to the run budget or the
    runtime default). All counters are non-negative.
    """

    max_agent_steps: int | None = Field(
        default=None, ge=1, description="Max model->tool iterations in one attempt."
    )
    max_model_calls: int | None = Field(
        default=None, ge=1, description="Max model calls in one attempt."
    )
    max_tool_calls: int | None = Field(
        default=None, ge=1, description="Max tool calls in one attempt."
    )
    max_attempts: int | None = Field(
        default=None, ge=1, description="Max attempts for this task (overrides Plan)."
    )


class ChildTask(BaseModel):
    """An atomic task in the FS-ASM plan (v1 Task Register entry).

    Parent/Child: a Parent task aggregates Child tasks; a Child carries its
    ``parent_id``. The v1 plan is a flat list of tasks with dependencies; the
    Parent/run result is computed from the required Child tasks by the
    Scheduler, not stored as a second authority. Dynamic attempt state
    (``attempt``, ``status``, ``accepted_evidence_refs``) lives on the task so
    the single snapshot remains the only authority.
    """

    task_id: str = Field(..., description="Unique identifier for this task.")
    parent_id: str | None = Field(
        default=None, description="Parent task ID if this is a subtask."
    )
    sequence: int = Field(..., description="Execution order sequence number.")
    title: str = Field(..., min_length=1, description="Short title of the task.")
    description: str = Field(
        ..., min_length=1, description="Detailed description of the task."
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING, description="Current status of the task."
    )
    dependencies: list[str] = Field(
        default_factory=list, description="List of task IDs this task depends on."
    )
    constraints: list[str] = Field(
        default_factory=list, description="List of constraints for this task."
    )
    allowed_files: list[str] = Field(
        default_factory=list,
        description="List of file patterns this task is allowed to modify.",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="List of tool kinds this task is allowed to invoke.",
    )
    verification: VerificationSpec = Field(
        ..., description="How to verify this task's result."
    )
    expected_evidence: list[str] = Field(
        default_factory=list, description="List of expected evidence types/paths."
    )
    attempt: int = Field(
        default=0, ge=0, description="Current attempt number (0-indexed)."
    )
    max_attempts: int = Field(
        default=3, ge=1, description="Maximum number of attempts allowed."
    )
    # v1: accepted evidence references for the CURRENT attempt only. PASS is
    # granted solely when these refs are integral and the Verifier confirmed
    # the current artifact; orphan evidence must not yield PASS.
    accepted_evidence_refs: list[str] = Field(
        default_factory=list,
        description=(
            "Evidence IDs accepted for the current attempt. Cleared/replaced on "
            "a new attempt so stale evidence cannot authorize a later attempt."
        ),
    )
    budget: TaskBudget | None = Field(
        default=None, description="Per-task limits; None falls back to the run budget."
    )

    @field_validator("task_id")
    @classmethod
    def task_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task_id cannot be empty")
        return v.strip()

    @field_validator("title", "description")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text cannot be empty")
        return v.strip()

    def can_retry(self) -> bool:
        """
        Check if this task can be retried.

        Under the current attempt semantics, after attempt N has started,
        another execution is allowed iff attempt < max_attempts.
        """
        return self.attempt < self.max_attempts

    def retry_count_remaining(self) -> int:
        """Return remaining retry attempts."""
        return max(0, self.max_attempts - self.attempt)


class Plan(BaseModel):
    """The FS-ASM plan containing tasks to execute (v1 Task Register).

    The plan is the static configuration: task identity, dependencies,
    acceptance criteria, verification spec, allowed scope and limits. Dynamic
    per-attempt state (``attempt``, ``status``, ``accepted_evidence_refs``)
    lives on each ``ChildTask`` so the single snapshot remains the only
    authority; the plan is not a second writable register. A plan of 1, 3 or N
    tasks is accepted (the historical "exactly 3" constraint of the milestone
    demo does not apply to the v1 domain model).
    """

    plan_id: str = Field(..., description="Unique identifier for this plan.")
    run_id: str = Field(..., description="The run ID this plan belongs to.")
    goal: str = Field(..., min_length=1, description="The goal this plan addresses.")
    tasks: list[ChildTask] = Field(..., description="List of tasks in this plan.")

    @field_validator("tasks")
    @classmethod
    def validate_tasks(cls, v: list[ChildTask]) -> list[ChildTask]:
        if len(v) < 1:
            raise ValueError("Plan must contain at least 1 ChildTask")
        return v

    @model_validator(mode="after")
    def validate_task_ids_unique(self) -> "Plan":
        task_ids = [t.task_id for t in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Task IDs must be unique within a plan")
        return self

    @model_validator(mode="after")
    def validate_dependencies_exist(self) -> "Plan":
        all_task_ids = {t.task_id for t in self.tasks}
        for task in self.tasks:
            for dep_id in task.dependencies:
                if dep_id not in all_task_ids:
                    raise ValueError(
                        f"Task {task.task_id} depends on non-existent task {dep_id}"
                    )
        return self

    @model_validator(mode="after")
    def validate_no_dependency_cycles(self) -> "Plan":
        """Reject a dependency DAG that contains a cycle."""
        adj: dict[str, list[str]] = {
            t.task_id: list(t.dependencies) for t in self.tasks
        }
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {tid: WHITE for tid in adj}

        def visit(node: str, path: tuple[str, ...]) -> None:
            color[node] = GRAY
            for nxt in adj.get(node, []):
                if color[nxt] == GRAY:
                    cycle = " -> ".join(path + (nxt,))
                    raise ValueError(f"Dependency cycle detected: {cycle}")
                if color[nxt] == WHITE:
                    visit(nxt, path + (nxt,))
            color[node] = BLACK

        for tid in adj:
            if color[tid] == WHITE:
                visit(tid, (tid,))
        return self


class EvidenceRecord(BaseModel):
    """Record of evidence supporting a verification or task result."""

    evidence_id: str = Field(
        ..., description="Unique identifier for this evidence record."
    )
    run_id: str = Field(..., description="The run ID this evidence belongs to.")
    task_id: str | None = Field(
        default=None, description="The task ID this evidence relates to, if applicable."
    )
    kind: str = Field(
        ..., description="Type/kind of evidence (e.g., 'diff', 'test_result', 'log')."
    )
    source: str = Field(
        ..., description="Source of the evidence (e.g., 'git diff', 'pytest output')."
    )
    payload: dict[str, Any] | str = Field(
        ..., description="The actual evidence payload (structured or text)."
    )
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO 8601 timestamp when evidence was created.",
    )

    @field_validator("evidence_id")
    @classmethod
    def evidence_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("evidence_id cannot be empty")
        return v.strip()


class PlannerOutput(BaseModel):
    """
    Complete planner output - proposal + assembled Plan + metadata.

    The proposal contains the semantic content from LLM.
    The plan contains the runtime-assembled Plan with all runtime-owned fields.
    The metadata contains observability data.
    """

    proposal: PlannerProposal = Field(
        ..., description="Semantic proposal from LLM (no runtime-owned fields)."
    )
    plan: Plan = Field(
        ..., description="Runtime-assembled Plan with all runtime-owned fields."
    )
    metadata: PlannerMetadata = Field(
        ..., description="Observability metadata for this planning operation."
    )


class ExecutorOutput(BaseModel):
    """
    Complete executor output - the claim/result produced by the executor.

    This is a CLAIM/RESULT, not Evidence and not Verification.
    ExecutorOutput is separate from EvidenceRecord and VerificationResult.

    The verifier MUST NOT receive ExecutorOutput directly.
    ExecutorOutput must be converted to EvidenceRecord with provenance validation.
    """

    task_id: str = Field(..., description="The task_id this output belongs to.")
    run_id: str = Field(..., description="The run_id this output belongs to.")
    result: str = Field(..., description="The result/claim produced by the executor.")
    metadata: ExecutorMetadata = Field(
        ..., description="Observability metadata for this execution."
    )

    @field_validator("task_id", "run_id", "result")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text cannot be empty")
        return v.strip()

    def validate_provenance(self, expected_task_id: str, expected_run_id: str) -> bool:
        """
        Validate that this ExecutorOutput matches expected provenance.

        Checks:
        - executor_output.task_id == expected_task_id
        - executor_output.metadata.task_id == expected_task_id
        - executor_output.metadata.run_id == expected_run_id

        Args:
            expected_task_id: The expected task_id.
            expected_run_id: The expected run_id.

        Returns:
            True if all provenance checks pass.
        """
        return (
            self.task_id == expected_task_id
            and self.metadata.task_id == expected_task_id
            and self.metadata.run_id == expected_run_id
        )


class RunBudget(BaseModel):
    """Configurable limits for a whole run (T04).

    Caps are enforced at the execution/escalation boundary and live in the
    authoritative snapshot so a resumed run keeps them. ``None`` means the
    limit is not set (runtime default applies). All counters are non-negative.
    """

    max_attempts_per_task: int | None = Field(
        default=None, ge=1, description="Default max attempts for every task."
    )
    max_agent_steps: int | None = Field(
        default=None,
        ge=1,
        description="Default max model->tool iterations per attempt.",
    )
    max_model_calls: int | None = Field(
        default=None, ge=1, description="Default max model calls per attempt."
    )
    max_tool_calls: int | None = Field(
        default=None, ge=1, description="Default max tool calls per attempt."
    )
    max_escalations: int | None = Field(
        default=None, ge=0, description="Max consultation/handover escalations per run."
    )


class GateOccurrence(BaseModel):
    """One Human Gate occurrence in the authoritative snapshot (T04).

    The gate occurrence, its lifecycle and the accepted/applied decision are
    part of the snapshot (not an ephemeral workflow-only consent). The granted
    authority is bounded: a RETRY_ONCE authorizes exactly one additional
    attempt for the task this gate belongs to.
    """

    gate_id: str = Field(..., description="Deterministic gate occurrence identifier.")
    task_id: str = Field(..., description="The task this gate is open for.")
    attempt: int = Field(
        ..., ge=1, description="The attempt that reached this gate (1-indexed)."
    )
    accepted_decision_id: str | None = Field(
        default=None, description="Decision id accepted for this gate, once applied."
    )
    accepted_action: HumanDecisionAction | None = Field(
        default=None, description="The accepted human action for this gate."
    )
    applied: bool = Field(
        default=False, description="Whether the accepted decision was durably applied."
    )


class RunState(BaseModel):
    """The complete authoritative state of an FS-ASM run (v1 snapshot).

    One snapshot contains the plan (Task Register), per-attempt dynamic state,
    run/parent status, counters, gate occurrence and accepted evidence refs.
    ``revision`` is monotonic and incremented exactly once per accepted domain
    event; ``commit_snapshot(run_id, expected_revision, next_state)`` rejects a
    stale revision. The model validates structural invariants (no duplicate IDs,
    no missing references, no dependency cycles, at most one active task,
    consistent statuses) so an inconsistent snapshot is rejected before it can
    be committed.
    """

    run_id: str = Field(..., description="Unique identifier for this run.")
    goal: str = Field(..., min_length=1, description="The goal this run addresses.")
    status: RunStatus = Field(
        default=RunStatus.CREATED, description="Current status of the run."
    )
    schema_version: int = Field(
        default=1,
        ge=1,
        description="Snapshot schema version for forward-compatible reads.",
    )
    revision: int = Field(
        default=0,
        ge=0,
        description="Monotonic snapshot revision; one per accepted event.",
    )
    plan: Plan | None = Field(
        default=None, description="The plan for this run, if planning is complete."
    )
    active_task_id: str | None = Field(
        default=None, description="ID of the currently active task, if any."
    )
    completed_task_ids: list[str] = Field(
        default_factory=list, description="List of completed (PASSED) task IDs."
    )
    failed_task_ids: list[str] = Field(
        default_factory=list, description="List of permanently failed task IDs."
    )
    needs_human_task_ids: list[str] = Field(
        default_factory=list, description="Tasks currently waiting at a Human Gate."
    )
    gate: GateOccurrence | None = Field(
        default=None, description="The currently open Human Gate, if any."
    )
    budget: RunBudget | None = Field(
        default=None, description="Run-wide limits; tasks may override per-task."
    )
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO 8601 timestamp when run was created.",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO 8601 timestamp when run was last updated.",
    )

    @field_validator("goal")
    @classmethod
    def goal_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("goal cannot be blank")
        return v.strip()

    @model_validator(mode="after")
    def validate_plan_run_id_match(self) -> "RunState":
        if self.plan is not None and self.plan.run_id != self.run_id:
            raise ValueError("Plan run_id must match RunState run_id")
        return self

    @model_validator(mode="after")
    def validate_register_invariants(self) -> "RunState":
        """Enforce v1 snapshot invariants that are always destructive when
        violated: unique IDs, no missing references, no dependency cycles (Plan
        already checks cycles), and gate consistency *when* the new v1 gate/
        needs_human fields are populated.

        Intentionally lenient about transitional M4 states the demonstrator
        still writes before T07 adapts the activities: e.g. ``active_task_id``
        may briefly coincide with a terminal set during a FAILED->READY retry
        transition, and a NEEDS_HUMAN run may be expressed via the task's
        ``status`` rather than the new ``needs_human_task_ids`` field. These are
        not structural corruption; the clean Domain Core (T05) and the activity
        adapter (T07) tighten the contract once the single apply_event path is
        the only mutation path.
        """
        if self.plan is None:
            return self

        task_ids = [t.task_id for t in self.plan.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Task IDs must be unique within the plan")
        id_set = set(task_ids)

        # The active task must reference a real register entry.
        if self.active_task_id is not None and self.active_task_id not in id_set:
            raise ValueError(f"active_task_id {self.active_task_id} not in plan")

        # Terminal / needs_human sets must reference real tasks.
        for label, ids in (
            ("completed_task_ids", self.completed_task_ids),
            ("failed_task_ids", self.failed_task_ids),
            ("needs_human_task_ids", self.needs_human_task_ids),
        ):
            for tid in ids:
                if tid not in id_set:
                    raise ValueError(f"{label} references unknown task {tid}")

        done = set(self.completed_task_ids)
        failed = set(self.failed_task_ids)
        needs_human = set(self.needs_human_task_ids)
        if done & failed:
            raise ValueError("a task cannot be both completed and failed")
        if done & needs_human or failed & needs_human:
            raise ValueError("a needs_human task cannot be in a terminal set")

        # Gate consistency: when a v1 gate occurrence is recorded it must match
        # the run status and the needs_human set. M4 runs that express the gate
        # only via task.status do not set this field, so this check is skipped.
        if self.gate is not None:
            if self.status != RunStatus.NEEDS_HUMAN:
                raise ValueError("gate set but run status is not NEEDS_HUMAN")
            if self.gate.task_id not in needs_human:
                raise ValueError(
                    f"gate task {self.gate.task_id} not in needs_human_task_ids"
                )
        return self

    def touch(self) -> "RunState":
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow().isoformat() + "Z"
        return self


# =============================================================================
# HUMAN DECISION MODELS (M4)
# =============================================================================


class HumanDecision(BaseModel):
    """
    Human decision model for Human Gate.

    Represents a typed human decision with task context and explicit identity.

    Identity fields (F6/F7):
    - ``gate_id``: identifies one occurrence of a Human Gate for a task. A
      deterministic value derived from run_id/task_id/attempt (the attempt at
      gate time uniquely identifies each consecutive gate occurrence for the
      same task). It distinguishes successive gates for the SAME task and
      cannot collide across legitimate gate occurrences.
    - ``decision_id``: identifies one logical human decision. Deterministic from
      run_id/task_id/gate_id/action so that the same logical decision is
      idempotent and a contradictory reuse of the same decision_id is rejected.

    Signal handlers must only mutate deterministic workflow-local data.
    Validate and persist the decision through domain/activity code.
    """

    task_id: str = Field(..., description="The task_id this decision applies to.")
    action: HumanDecisionAction = Field(
        ..., description="Human decision action: RETRY_ONCE or ABORT."
    )
    reason: str = Field(default="", description="Optional reason for the decision.")
    gate_id: str | None = Field(
        default=None,
        description=(
            "Deterministic identifier of the gate occurrence this decision "
            "targets (run_id/task_id/attempt). Set by the workflow before the "
            "decision is applied."
        ),
    )
    decision_id: str | None = Field(
        default=None,
        description=(
            "Deterministic identifier of this logical decision "
            "(run_id/task_id/gate_id/action). Used for idempotent application."
        ),
    )

    @field_validator("task_id")
    @classmethod
    def task_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task_id cannot be empty")
        return v.strip()


# =============================================================================
# V1 DOMAIN IDENTITY HELPERS (T04)
# =============================================================================
# Deterministic, collision-resistant identifiers for the v1 domain. They derive
# only from stable domain inputs (run_id/task_id/attempt/...), never from random
# values or wall-clock time, so the same logical event yields the same id. The
# runtime owns id assignment; the LLM never proposes its own ids.


def task_id_for(run_id: str, sequence: int) -> str:
    """Runtime-owned Child Task id from run_id and sequence."""
    return f"TASK-{run_id}-{sequence}"


def parent_id_for(run_id: str) -> str:
    """Runtime-owned Parent (plan-level) task id from run_id."""
    return f"PARENT-{run_id}"


def operation_id_for(run_id: str, task_id: str, attempt: int, step: int) -> str:
    """One tool/model operation within a single attempt."""
    return f"op-{run_id}-{task_id}-attempt-{attempt}-step-{step}"


def artifact_id_for(run_id: str, task_id: str, attempt: int) -> str:
    """One produced artifact for a specific attempt."""
    return f"artifact-{run_id}-{task_id}-attempt-{attempt}"


def evidence_id_for(run_id: str, task_id: str, attempt: int, kind: str) -> str:
    """Evidence id binding a verification result to an attempt + kind."""
    return f"evidence-{run_id}-{task_id}-attempt-{attempt}-{kind}"


def gate_id_for(run_id: str, task_id: str, attempt: int) -> str:
    """Deterministic Human Gate occurrence id (run_id/task_id/attempt).

    Matches the workflow-level ``_gate_id`` so the snapshot and the signal
    handler agree on gate identity without a second authority.
    """
    return f"gate-{run_id}-{task_id}-attempt-{attempt}"


def decision_id_for(
    run_id: str, task_id: str, gate_id: str, action: HumanDecisionAction
) -> str:
    """Deterministic logical decision id (run_id/task_id/gate_id/action).

    Matches the workflow-level ``_decision_id`` so transport-level retry of the
    same decision is idempotent and a contradictory reuse is rejected.
    """
    return f"decision-{run_id}-{task_id}-{gate_id}-{action.value}"
