"""FS-ASM Provider-neutral Model Gateway (T16).

The Gateway is the single provider-neutral boundary for model calls. It
exposes one interface — :meth:`ModelGateway.generate` — taking a normalized
:class:`ModelRequest` and returning a normalized :class:`ModelResult`. Adapters
(local, Mistral) implement this interface; the Domain Core and Executor Loop
never import a provider type or a provider exception.

A deterministic :class:`ScriptedBackend` lets tests schedule a sequence of
normalized responses AND errors without a real model, so the Executor Loop
(T17) and the whole v1 runtime can be driven deterministically.

The parser is strict: it cannot confuse a bad format with a successful tool
call or final response. An unparseable provider output is always
``InvalidResponse``; a transport failure is always a ``ModelError``. No Gateway
type grants PASS, retry or gate (architecture §24; canonical TODO T16).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from fsasm.model_types import (
    EscalationRequest,
    FinalResponse,
    InvalidResponse,
    ModelError,
    ModelErrorKind,
    ModelRequest,
    ModelResult,
    ModelResponse,
    ModelUsage,
    ToolCall,
)


class ModelBackend(Protocol):
    """The provider-neutral backend contract an adapter implements.

    An adapter translates ``request`` to its provider's request shape, calls
    the provider, and returns a normalized :class:`ModelResult`. It never
    raises a provider exception past this boundary: any provider failure is
    wrapped in a :class:`ModelError` on the returned result. The adapter holds
    no domain rules (no retry, no PASS, no scope decisions).
    """

    name: str

    def generate(self, request: ModelRequest) -> ModelResult:
        """One normalized model call. Returns a ModelResult; never raises."""
        ...


@dataclass
class ModelGateway:
    """The single provider-neutral entry point for model calls.

    The Executor Loop (T17) calls :meth:`generate` with a normalized
    :class:`ModelRequest`; the Gateway delegates to its :class:`ModelBackend`
    and returns the normalized :class:`ModelResult`. The Gateway itself adds no
    domain logic: it is the seam so the domain never imports a provider.
    """

    backend: ModelBackend

    def generate(self, request: ModelRequest) -> ModelResult:
        """Delegate one normalized model call to the backend.

        The backend is contractually required to return a :class:`ModelResult`
        and never raise past this boundary (provider failures are wrapped in a
        ``ModelError`` on the result). A defensive guard keeps the contract even
        if an adapter raises: the exception is normalized to a ``ModelError`` so
        the Executor Loop never sees a provider exception type.
        """
        try:
            return self.backend.generate(request)
        except ModelError as err:
            return _error_result(request, err, self.backend.name)
        except Exception as err:  # pragma: no cover - defensive normalization
            wrapped = ModelError(str(err), kind=ModelErrorKind.UNKNOWN, retryable=False)
            return _error_result(request, wrapped, self.backend.name)


# -- deterministic scripted backend ------------------------------------------


@dataclass
class ScriptedBackend:
    """A deterministic backend that returns a scheduled sequence of results.

    ``responses`` is consumed in order: each :meth:`generate` call returns the
    next scheduled result. A scheduled item is either a normalized
    ``ModelResponse`` (``ToolCall``/``FinalResponse``/``EscalationRequest``/
    ``InvalidResponse``) or a :class:`ModelError` (a transport failure to
    inject). This lets tests drive the Executor Loop deterministically through
    tool calls, finals, escalations, invalid outputs and transport errors
    without a real model.

    The backend also supports raw-string scheduling: a ``str`` item is parsed
    into a response via :func:`parse_scripted_output` (strict JSON tool-call /
    ``[VERIFY]`` final / ``[ESCALATE]`` escalation), so tests can write compact
    scripts. An unparseable raw string becomes ``InvalidResponse``, never a
    silent success (the parser cannot confuse a bad format with a success).

    The backend records every call in ``calls`` for assertions. It holds no
    domain rules and grants no PASS.
    """

    responses: list = field(default_factory=list)
    name: str = "scripted"
    calls: list[ModelRequest] = field(default_factory=list)
    # Optional usage to report per call (deterministic); defaults to empty.
    per_call_usage: ModelUsage | None = None

    def generate(self, request: ModelRequest) -> ModelResult:
        self.calls.append(request)
        if not self.responses:
            # No more scheduled responses: return a deterministic invalid
            # response so the Executor Loop does not hang on a fabricated success.
            return ModelResult(
                run_id=request.run_id,
                task_id=request.task_id,
                attempt=request.attempt,
                step=request.step,
                response=InvalidResponse(
                    raw="", reason="scripted backend exhausted (no scheduled response)"
                ),
                backend=self.name,
            )
        item = self.responses.pop(0)
        response = self._normalize(item, request)
        if isinstance(response, ModelError):
            return _error_result(request, response, self.name, self.per_call_usage)
        return ModelResult(
            run_id=request.run_id,
            task_id=request.task_id,
            attempt=request.attempt,
            step=request.step,
            response=response,
            usage=self.per_call_usage or ModelUsage(),
            backend=self.name,
        )

    def _normalize(self, item, request: ModelRequest) -> ModelResponse | ModelError:
        if isinstance(item, ModelError):
            return item
        if isinstance(
            item, (ToolCall, FinalResponse, EscalationRequest, InvalidResponse)
        ):
            return item
        if isinstance(item, str):
            return parse_scripted_output(item)
        raise TypeError(
            f"scripted response must be a ModelResponse, ModelError or raw str; "
            f"got {type(item).__name__}"
        )


# -- strict parser for scripted raw strings ----------------------------------


def parse_scripted_output(raw: str) -> ModelResponse:
    """Strictly parse a scripted raw string into a normalized response.

    The parser cannot confuse a bad format with a successful tool call or final
    response. Accepted shapes (in order):

    1. ``[VERIFY] <rationale>`` -> ``FinalResponse`` (verification request).
    2. ``[ESCALATE consultation|handover] <reason> [-> <target>]`` ->
       ``EscalationRequest``.
    3. A JSON object ``{"tool_call_id":..., "name":..., "arguments":...}`` ->
       ``ToolCall``. Missing/blank fields -> ``InvalidResponse``.
    4. Anything else -> ``InvalidResponse`` (never a silent success).

    This mirrors the strictness the real adapter parsers must enforce: a
    malformed tool-call JSON is ``InvalidResponse``, not a ``ToolCall`` with
    empty fields.
    """
    text = raw.strip()
    if not text:
        return InvalidResponse(raw=raw, reason="empty output")
    if text.startswith("[VERIFY]"):
        content = text[len("[VERIFY]") :].strip()
        if not content:
            return InvalidResponse(raw=raw, reason="[VERIFY] with empty rationale")
        return FinalResponse(content=content)
    if text.startswith("[ESCALATE]"):
        body = text[len("[ESCALATE]") :].strip()
        kind, _, rest = body.partition(" ")
        if kind not in ("consultation", "handover") or not rest:
            return InvalidResponse(
                raw=raw,
                reason="[ESCALATE] requires 'consultation|handover <reason>'",
            )
        reason, sep, target = rest.partition("->")
        return EscalationRequest(
            kind=kind,
            reason=reason.strip(),
            target=target.strip() or None if sep else None,
        )
    # Attempt a strict JSON tool call.
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            return InvalidResponse(raw=raw, reason=f"invalid JSON: {exc}")
        if not isinstance(obj, dict):
            return InvalidResponse(raw=raw, reason="tool call JSON is not an object")
        tcid = obj.get("tool_call_id")
        name = obj.get("name")
        arguments = obj.get("arguments", {})
        if not isinstance(tcid, str) or not tcid.strip():
            return InvalidResponse(raw=raw, reason="tool call missing tool_call_id")
        if not isinstance(name, str) or not name.strip():
            return InvalidResponse(raw=raw, reason="tool call missing name")
        if not isinstance(arguments, dict):
            return InvalidResponse(raw=raw, reason="tool call arguments not an object")
        return ToolCall(tool_call_id=tcid, name=name, arguments=arguments)
    return InvalidResponse(raw=raw, reason="unrecognized output format")


def _error_result(
    request: ModelRequest,
    err: ModelError,
    backend_name: str,
    usage: ModelUsage | None = None,
) -> ModelResult:
    """Build a ModelResult carrying a transport error (no response variant)."""
    return ModelResult(
        run_id=request.run_id,
        task_id=request.task_id,
        attempt=request.attempt,
        step=request.step,
        response=InvalidResponse(raw="", reason=f"transport error: {err.kind.value}"),
        usage=usage or ModelUsage(),
        error=err,
        backend=backend_name,
    )


__all__ = [
    "ModelBackend",
    "ModelGateway",
    "ScriptedBackend",
    "parse_scripted_output",
]
