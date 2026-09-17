"""FS-ASM Provider-neutral Model Gateway types (T16).

The Gateway is the single provider-neutral boundary between the FS-ASM domain
and any LLM backend (local adapter, Mistral adapter, scripted test backend).
Only normalized, domain-owned types cross this boundary: provider-specific
request/response/usage/error shapes are translated here and never leak into the
Domain Core or Executor Loop. A deterministic scripted backend (T16) lets tests
schedule responses and errors without a real model.

The parser cannot confuse a bad format with a successful tool call or final
response: an unparseable output is always ``InvalidResponse`` (never a silent
``ToolCall``/``FinalResponse``), and a normalized transport failure is always a
``ModelError`` (never a domain success). No type here grants PASS, retry or
gate; the Gateway normalizes transport only (architecture §24; canonical TODO
T16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from fsasm.errors import FSASMError


class ModelMessageRole(str, Enum):
    """Normalized conversation role (provider-neutral)."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelMessage(BaseModel):
    """One normalized conversation message (provider-neutral)."""

    role: ModelMessageRole = Field(..., description="The message role.")
    content: str = Field(..., description="The message text content.")
    # For an assistant tool call turn, the id of the tool call this message
    # produced (so the provider round-trip can correlate tool results).
    tool_call_id: str | None = Field(
        default=None, description="Tool call id this assistant/tool turn produced."
    )
    # For a TOOL role message, the id of the tool call this is the result of.
    tool_result_for: str | None = Field(
        default=None, description="Tool call id this tool result answers."
    )


class ToolDeclaration(BaseModel):
    """A tool the model may call, declared in the normalized schema.

    ``name`` and ``description`` are provider-neutral; ``parameters`` is a JSON
    schema dict the Gateway translates to the provider's tool format. The
    model never receives a raw terminal here — only declared tools.
    """

    name: str = Field(..., min_length=1, description="Tool name the model may call.")
    description: str = Field(..., description="What the tool does (for the model).")
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON schema for the tool's parameters.",
    )


class ModelParameters(BaseModel):
    """Provider-neutral generation parameters.

    These are the only knobs the domain is allowed to set; the adapter maps them
    to the provider's equivalents. No provider-specific parameters leak here.
    """

    temperature: float = Field(default=0.0, ge=0.0, description="Sampling temperature.")
    max_tokens: int = Field(
        default=1024, ge=1, description="Max tokens to generate in the response."
    )
    # The model must stop and ask for verification when it emits the stop
    # sequence (the "final response" marker). A tool call never ends a turn.
    stop: list[str] = Field(
        default_factory=lambda: ["[VERIFY]"],
        description="Stop sequences that signal a final (verification) response.",
    )


class ModelRequest(BaseModel):
    """The single provider-neutral request to a backend.

    ``generate(messages, tools, parameters)`` is built from this; the adapter
    translates it to the provider's request shape. No domain type depends on a
    provider library here.
    """

    run_id: str = Field(..., description="The run this call belongs to.")
    task_id: str = Field(..., description="The task this call belongs to.")
    attempt: int = Field(..., ge=1, description="The attempt this call belongs to.")
    step: int = Field(..., ge=1, description="The agent step within the attempt.")
    messages: list[ModelMessage] = Field(
        ..., min_length=1, description="The normalized conversation."
    )
    tools: list[ToolDeclaration] = Field(
        default_factory=list, description="Tools the model may call."
    )
    parameters: ModelParameters = Field(
        default_factory=ModelParameters, description="Generation parameters."
    )


# -- normalized responses ----------------------------------------------------


class ToolCall(BaseModel):
    """The model requested a tool invocation (NOT a final response).

    A tool call never ends the turn and never grants PASS; the Executor Loop
    runs the tool through the Broker and feeds the observation back. The id
    correlates the assistant tool-call turn with the tool result message.
    """

    tool_call_id: str = Field(..., min_length=1, description="Correlation id.")
    name: str = Field(..., min_length=1, description="Tool name to invoke.")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Arguments the model supplied."
    )


class FinalResponse(BaseModel):
    """The model produced a terminal response requesting verification (NOT PASS).

    A final response is a request for the Verification Plane, not a PASS claim:
    it signals the model believes it is done; the Verifier inspects the real
    artifact. The ``content`` is the model's rationale/summary.
    """

    content: str = Field(..., description="The model's final rationale/summary.")


class EscalationRequest(BaseModel):
    """The model explicitly asked to escalate (consult/handover an expert).

    The model cannot escalate itself; it requests it. The Model Router (T21)
    decides whether consultation or handover applies, within the approved limits.
    Escalation never bypasses scope or adds attempts.
    """

    kind: str = Field(
        ...,
        description="Escalation kind: 'consultation' (advice only) or 'handover' (transfer).",
    )
    reason: str = Field(..., description="Why the model requests escalation.")
    target: str | None = Field(
        default=None, description="Requested target role/adapter (optional)."
    )


class InvalidResponse(BaseModel):
    """The model output could not be parsed into a tool call or final response.

    The parser cannot confuse a bad format with a successful tool call or final
    response: an unparseable output is ALWAYS ``InvalidResponse``, never a
    silent success. The Executor Loop treats this as a recoverable step error
    (re-ask), not a PASS or a tool effect.
    """

    raw: str = Field(..., description="The raw unparseable output.")
    reason: str = Field(..., description="Why the output was invalid.")


class ModelUsage(BaseModel):
    """Normalized token/cost usage, recorded only when the provider reports it.

    All fields optional: a local backend may report no usage at all. Cost is
    recorded only if available; absence is honest, never fabricated.
    """

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost: float | None = Field(
        default=None, ge=0.0, description="Cost in provider units if available."
    )
    duration_ms: int | None = Field(default=None, ge=0)


# -- normalized errors -------------------------------------------------------


class ModelErrorKind(str, Enum):
    """Normalized transport/model error categories (provider-neutral).

    These are transport failures, NOT domain outcomes: they never grant PASS,
    retry or gate. The Executor Loop distinguishes a transport retry from a
    merytoryczny FAIL (architecture §24; T16/T17).
    """

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    BAD_REQUEST = "bad_request"
    AUTHENTICATION = "authentication"
    PROTOCOL_ERROR = "protocol_error"
    UNKNOWN = "unknown"


class ModelError(FSASMError):
    """A normalized transport/model error from the backend.

    Wraps any provider-specific exception in a provider-neutral category so the
    domain never imports a provider exception type. It is a transport failure,
    not a domain decision: the Executor Loop may retry the call (without
    consuming a merytoryczna attempt) or escalate, but never grants PASS.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: ModelErrorKind,
        retryable: bool = False,
    ) -> None:
        self.kind = kind
        self.retryable = retryable
        super().__init__(message, {"kind": kind.value, "retryable": retryable})


# The union of normalized model responses. ``Any``-free: the Executor Loop
# pattern-matches on this union and never receives a provider type.
ModelResponse = ToolCall | FinalResponse | EscalationRequest | InvalidResponse


@dataclass
class ModelResult:
    """The full normalized result of one ``generate`` call.

    Carries exactly one response variant (``response``) plus normalized usage
    and whether a transport error occurred. The Executor Loop uses ``error`` to
    decide a technical retry (no attempt consumed) vs a merytoryczny step.
    ``ModelResult`` is a dataclass (not a snapshot model): it is a transient
    transport result, not authoritative state, and it carries a ``ModelError``
    exception instance Pydantic cannot serialize.
    """

    run_id: str
    task_id: str
    attempt: int
    step: int
    response: ToolCall | FinalResponse | EscalationRequest | InvalidResponse
    usage: ModelUsage = field(default_factory=ModelUsage)
    error: ModelError | None = None
    backend: str = ""


# -- budgets (counters enforced at the Gateway/Executor boundary) ------------


class ModelCallBudget(BaseModel):
    """Per-attempt model-call/tool-call/agent-step/token/time budgets (T16).

    These are the counters the Gateway/Executor enforce before the next model
    call or tool effect. They are advisory caps (configurable); the Gateway
    records usage and the Executor decides the terminal reason on exhaustion.
    A budget exhaustion is a terminal outcome (e.g. STEP_LIMIT_REACHED), never
    a silent extra attempt.
    """

    max_model_calls: int | None = Field(default=None, ge=1)
    max_tool_calls: int | None = Field(default=None, ge=1)
    max_agent_steps: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_cost: float | None = Field(default=None, ge=0.0)
    max_time_ms: int | None = Field(default=None, ge=1)


class ExecutorOutcomeReason(str, Enum):
    """Normalized terminal reasons for one Executor attempt (architecture \u00a724).

    These are the normalized outcomes of the Executor Loop for ONE
    ``task_attempt``. They are NOT domain statuses and grant no PASS: a
    ``COMPLETED`` outcome is a request for the Verification Plane, not a PASS
    claim \u2014 only the Domain Core grants the task transition after the
    Verifier inspects the real artifact. The Executor never grants PASS,
    retry or gate; it reports why it stopped (architecture \u00a724; canonical
    TODO T17).
    """

    COMPLETED = "completed"
    NEEDS_INFORMATION = "needs_information"
    ESCALATION_REQUESTED = "escalation_requested"
    STEP_LIMIT_REACHED = "step_limit_reached"
    TOOL_ERROR = "tool_error"
    POLICY_BLOCKED = "policy_blocked"


class BudgetUsage(BaseModel):
    """Live counters against a :class:`ModelCallBudget` for one attempt."""

    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    agent_steps: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    cost: float = Field(default=0.0, ge=0.0)
    elapsed_ms: int = Field(default=0, ge=0)

    def would_exceed(self, budget: ModelCallBudget) -> bool:
        """True if incrementing model_calls by one would exceed any set cap."""
        if (
            budget.max_model_calls is not None
            and self.model_calls >= budget.max_model_calls
        ):
            return True
        if budget.max_tokens is not None and self.tokens >= budget.max_tokens:
            return True
        if budget.max_cost is not None and self.cost >= budget.max_cost:
            return True
        if budget.max_time_ms is not None and self.elapsed_ms >= budget.max_time_ms:
            return True
        return False

    def would_exceed_tool(self, budget: ModelCallBudget) -> bool:
        """True if incrementing tool_calls by one would exceed any set cap."""
        if (
            budget.max_tool_calls is not None
            and self.tool_calls >= budget.max_tool_calls
        ):
            return True
        if (
            budget.max_agent_steps is not None
            and self.agent_steps >= budget.max_agent_steps
        ):
            return True
        return False


__all__ = [
    "BudgetUsage",
    "EscalationRequest",
    "ExecutorOutcomeReason",
    "FinalResponse",
    "InvalidResponse",
    "ModelCallBudget",
    "ModelError",
    "ModelErrorKind",
    "ModelMessage",
    "ModelMessageRole",
    "ModelParameters",
    "ModelRequest",
    "ModelResponse",
    "ModelResult",
    "ModelUsage",
    "ToolCall",
    "ToolDeclaration",
]
