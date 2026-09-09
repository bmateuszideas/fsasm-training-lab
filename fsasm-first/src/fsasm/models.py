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


class ChildTask(BaseModel):
    """An atomic task in the FS-ASM plan."""

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
    """The FS-ASM plan containing tasks to execute."""

    plan_id: str = Field(..., description="Unique identifier for this plan.")
    run_id: str = Field(..., description="The run ID this plan belongs to.")
    goal: str = Field(..., min_length=1, description="The goal this plan addresses.")
    tasks: list[ChildTask] = Field(..., description="List of tasks in this plan.")

    @field_validator("tasks")
    @classmethod
    def validate_tasks(cls, v: list[ChildTask]) -> list[ChildTask]:
        if len(v) != 3:
            raise ValueError("Plan must contain exactly 3 ChildTasks for milestone 1")
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


class RunState(BaseModel):
    """The complete state of an FS-ASM run."""

    run_id: str = Field(..., description="Unique identifier for this run.")
    goal: str = Field(..., min_length=1, description="The goal this run addresses.")
    status: RunStatus = Field(
        default=RunStatus.CREATED, description="Current status of the run."
    )
    plan: Plan | None = Field(
        default=None, description="The plan for this run, if planning is complete."
    )
    active_task_id: str | None = Field(
        default=None, description="ID of the currently active task, if any."
    )
    completed_task_ids: list[str] = Field(
        default_factory=list, description="List of completed task IDs."
    )
    failed_task_ids: list[str] = Field(
        default_factory=list, description="List of failed task IDs."
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

    Represents a typed human decision with task context.
    Signal handlers must only mutate deterministic workflow-local data.
    Validate and persist the decision through domain/activity code.
    """

    task_id: str = Field(..., description="The task_id this decision applies to.")
    action: HumanDecisionAction = Field(
        ..., description="Human decision action: RETRY_ONCE or ABORT."
    )
    reason: str = Field(default="", description="Optional reason for the decision.")

    @field_validator("task_id")
    @classmethod
    def task_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task_id cannot be empty")
        return v.strip()
