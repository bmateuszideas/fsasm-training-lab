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


class PersistenceError(FSASMError):
    """Raised when persistence operations fail."""

    def __init__(
        self, message: str, path: str | None = None, operation: str = "unknown"
    ) -> None:
        self.path = path
        self.operation = operation
        super().__init__(message, {"path": path, "operation": operation})
