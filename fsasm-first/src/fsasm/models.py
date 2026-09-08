"""FS-ASM domain models - Pydantic schemas for the core domain."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# ENUMS
# =============================================================================


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
# MODELS
# =============================================================================


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
        """Check if this task can be retried."""
        return self.attempt < self.max_attempts - 1

    def retry_count_remaining(self) -> int:
        """Return remaining retry attempts."""
        return max(0, self.max_attempts - self.attempt - 1)


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
