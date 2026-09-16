"""FS-ASM domain errors."""

from typing import Any


class FSASMError(Exception):
    """Base exception for all FS-ASM domain errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidTransitionError(FSASMError):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        from_status: str,
        to_status: str,
        entity_type: str,
        entity_id: str,
        reason: str | None = None,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.reason = reason or "Transition not allowed by domain rules"
        message = (
            f"Invalid transition: {entity_type}({entity_id}) "
            f"{from_status} -> {to_status}: {self.reason}"
        )
        super().__init__(
            message, {"from": from_status, "to": to_status, "reason": self.reason}
        )


class ValidationError(FSASMError):
    """Raised when domain validation fails."""

    def __init__(
        self, message: str, field: str | None = None, value: Any = None
    ) -> None:
        self.field = field
        self.value = value
        super().__init__(
            message, {"field": field, "value": str(value) if value else None}
        )


class RetryExhaustedError(FSASMError):
    """Raised when retry attempts are exhausted."""

    def __init__(self, task_id: str, max_attempts: int, current_attempt: int) -> None:
        self.task_id = task_id
        self.max_attempts = max_attempts
        self.current_attempt = current_attempt
        message = (
            f"Retry exhausted for task {task_id}: "
            f"max_attempts={max_attempts}, current_attempt={current_attempt}"
        )
        super().__init__(
            message,
            {
                "task_id": task_id,
                "max_attempts": max_attempts,
                "current_attempt": current_attempt,
            },
        )


class PlanValidationError(FSASMError):
    """Raised when plan validation fails."""

    def __init__(self, message: str, plan_id: str | None = None) -> None:
        self.plan_id = plan_id
        super().__init__(message, {"plan_id": plan_id})


class RunAlreadyExistsError(FSASMError):
    """Raised when an explicit new-run creation targets a run_id that already exists.

    This is the F4 identity boundary: separating *creating* a new run from
    *accessing* or *resuming* an existing run. A duplicate creation request
    (same run_id, whether with the same or a different goal) must fail through
    this explicit domain error rather than silently overwriting existing
    state, plan, evidence or log artifacts.
    """

    def __init__(self, message: str, run_id: str | None = None) -> None:
        self.run_id = run_id
        super().__init__(message, {"run_id": run_id})


class UnsupportedResumeError(FSASMError):
    """Raised when a resume/recovery operation is requested but unsupported.

    The system must reject an unsupported resume operation rather than quietly
    starting a new run over an existing run_id (F4)."""

    def __init__(self, message: str, run_id: str | None = None) -> None:
        self.run_id = run_id
        super().__init__(message, {"run_id": run_id})


class InvalidIdentifierError(FSASMError):
    """Raised when an untrusted filesystem identifier is unsafe.

    Raised by the persistence boundary before any identifier-derived filesystem
    side effect when a ``run_id`` or ``evidence_id`` is empty, contains path
    separators, traversal components, an absolute/drive/UNC prefix, null bytes,
    other path-unsafe characters, exceeds the length limit, or uses a
    Windows-reserved name. This is a path-safety boundary error, distinct from
    a malformed domain object: persistence enforces its own boundary even when
    called directly.
    """

    def __init__(self, message: str, identifier: str | None = None) -> None:
        self.identifier = identifier
        super().__init__(message, {"identifier": identifier})


class PersistenceError(FSASMError):
    """Raised when persistence operations fail."""

    def __init__(
        self, message: str, path: str | None = None, operation: str = "unknown"
    ) -> None:
        self.path = path
        self.operation = operation
        super().__init__(message, {"path": path, "operation": operation})


class ConfigurationError(FSASMError):
    """Raised when there is a configuration error (e.g., missing required config for backend)."""

    def __init__(
        self, message: str, backend: str | None = None, missing_field: str | None = None
    ) -> None:
        self.backend = backend
        self.missing_field = missing_field
        super().__init__(message, {"backend": backend, "missing_field": missing_field})


class ProvenanceValidationError(FSASMError):
    """Raised when ExecutorOutput provenance validation fails."""

    def __init__(
        self,
        message: str,
        expected_task_id: str,
        actual_task_id: str,
        expected_run_id: str,
        actual_run_id: str,
        check_type: str,
    ) -> None:
        self.message = message
        self.expected_task_id = expected_task_id
        self.actual_task_id = actual_task_id
        self.expected_run_id = expected_run_id
        self.actual_run_id = actual_run_id
        self.check_type = check_type
        super().__init__(
            message,
            {
                "expected_task_id": expected_task_id,
                "actual_task_id": actual_task_id,
                "expected_run_id": expected_run_id,
                "actual_run_id": actual_run_id,
                "check_type": check_type,
            },
        )
