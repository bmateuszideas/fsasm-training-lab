"""FS-ASM: File System as State Machine - Core domain package."""

from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    GoalInput,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationCheck,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
)
from fsasm.errors import (
    FSASMError,
    InvalidTransitionError,
    ValidationError,
    RetryExhaustedError,
)
from fsasm.transitions import transition_task, transition_run
from fsasm.planner import PlannerStub
from fsasm.verifier import DeterministicVerifier
from fsasm.persistence import RuntimePersistence

__all__ = [
    # Models
    "GoalInput",
    "Plan",
    "ChildTask",
    "VerificationSpec",
    "VerificationResult",
    "VerificationCheck",
    "VerificationResultStatus",
    "EvidenceRecord",
    "RunState",
    "RunStatus",
    "TaskStatus",
    # Errors
    "FSASMError",
    "InvalidTransitionError",
    "ValidationError",
    "RetryExhaustedError",
    # Transitions
    "transition_task",
    "transition_run",
    # Services
    "PlannerStub",
    "DeterministicVerifier",
    "RuntimePersistence",
]
