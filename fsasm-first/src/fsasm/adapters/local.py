"""FS-ASM LM Studio local adapter (T19).

One chosen local inference protocol (canonical TODO §6, resolved before T19):
LM Studio, which exposes an OpenAI-compatible ``/v1/chat/completions`` endpoint
with tool calling and usage metadata over plain HTTP. The adapter translates
ONLY transport and format between the provider-neutral
:class:`fsasm.gateway.ModelBackend` contract and LM Studio's request/response
shapes. It holds NO domain rules: no retry, no PASS, no scope or routing
policy — those stay in the Domain Core, the Model Router (T21) and the
Executor Loop (T17) (architecture §25, §27; canonical TODO T19).

Normalization contract (mirrors the strictness the gateway parser enforces):

- A native tool call (LM Studio ``choices[].message.tool_calls``) maps to a
  :class:`ToolCall`. A malformed tool call (missing id/name/arguments, or
  arguments that are not a JSON object) is ALWAYS :class:`InvalidResponse`,
  never a silent :class:`ToolCall`.
- A final assistant message whose content contains the ``[VERIFY]`` stop
  marker maps to :class:`FinalResponse` (a verification request, NOT PASS);
  ``[ESCALATE consultation|handover] <reason> [-> <target>]`` maps to
  :class:`EscalationRequest`. Anything else unparseable is
  :class:`InvalidResponse`.
- A transport failure (connection refused, timeout, non-2xx, bad JSON, empty
  choices) is ALWAYS a :class:`ModelError` on the returned :class:`ModelResult`,
  never a domain success. The adapter maps HTTP status to the normalized
  :class:`ModelErrorKind`: 408/timeout → ``TIMEOUT``; 429 → ``RATE_LIMITED``;
  401/403 → ``AUTHENTICATION``; 400 → ``BAD_REQUEST``; 5xx / connection →
  ``UNAVAILABLE``; malformed body → ``PROTOCOL_ERROR``.

The adapter is testable on a controlled fixture (httpx ``MockTransport``) with
NO real 7B model and NO network. The Domain Core never imports the httpx or
server library: it depends only on the :class:`ModelBackend` Protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from fsasm.model_types import (
    InvalidResponse,
    ModelError,
    ModelErrorKind,
    ModelMessageRole,
    ModelRequest,
    ModelResult,
    ModelResponse,
    ModelUsage,
    ToolCall,
    ToolDeclaration,
)

# The marker the Executor Loop / Domain uses to signal a final (verification)
# response; emitted by the model via the stop sequence. Re-imported from the
# canonical scripted parser's contract so the adapter stays consistent with it.
from fsasm.gateway import parse_scripted_output

# LM Studio default local endpoint. Overridable per adapter instance; bound
# to a loopback address so the runtime never opens a broad listener and never
# exposes the local model beyond the operator's machine.
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_TIMEOUT_SECONDS = 60.0

# OpenAI role names used on the wire.
_WIRE_ROLES = {
    ModelMessageRole.SYSTEM: "system",
    ModelMessageRole.USER: "user",
    ModelMessageRole.ASSISTANT: "assistant",
    ModelMessageRole.TOOL: "tool",
}


@dataclass
class LMStudioAdapter:
    """Adapter for one local inference protocol: LM Studio (OpenAI-compatible).

    Translates a normalized :class:`ModelRequest` to an OpenAI-compatible
    ``/chat/completions`` POST, calls the local endpoint over httpx, and parses
    the response back to a normalized :class:`ModelResult`. The adapter holds no
    domain rules and grants no PASS; any transport or format failure is a
    :class:`ModelError` on the result, never a domain success. It is
    deterministic given a deterministic backend (e.g. httpx ``MockTransport``).
    """

    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    # The model identifier the adapter sends on the wire. LM Studio accepts an
    # arbitrary model name; we send the configured one. We do NOT assume a
    # concrete 7B model name — that is resolved at T29 on the laptop.
    model: str = "local"
    # The stop sequence that signals a final (verification) response. Mirrors
    # ModelParameters.stop default so the adapter and the domain agree.
    stop: tuple[str, ...] = ("[VERIFY]",)
    # Injectable transport for tests (httpx.MockTransport). When None the
    # adapter uses a real httpx.Client against base_url.
    transport: httpx.BaseTransport | None = None
    name: str = "lm-studio"
    # Recorded wire requests for assertions / audit (no secrets).
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate(self, request: ModelRequest) -> ModelResult:
        """One normalized model call to LM Studio; returns ModelResult, never raises."""
        try:
            return self._do_call(request)
        except ModelError as err:
            return _error_result(request, err, self.name)
        except httpx.TimeoutException as err:
            return _error_result(
                request,
                ModelError(str(err), kind=ModelErrorKind.TIMEOUT, retryable=True),
                self.name,
            )
        except httpx.ConnectError as err:
            return _error_result(
                request,
                ModelError(str(err), kind=ModelErrorKind.UNAVAILABLE, retryable=True),
                self.name,
            )
        except httpx.HTTPStatusError as err:
            return _error_result(
                request,
                _status_error(err.response.status_code, str(err)),
                self.name,
            )
        except Exception as err:  # pragma: no cover - defensive normalization
            return _error_result(
                request,
                ModelError(str(err), kind=ModelErrorKind.UNKNOWN, retryable=False),
                self.name,
            )

    # -- internals --------------------------------------------------------

    def _do_call(self, request: ModelRequest) -> ModelResult:
        payload = self._build_payload(request)
        self.calls.append({"url": self.base_url, "payload": payload})
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            resp = client.post("/chat/completions", json=payload)
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"LM Studio returned {resp.status_code}",
                request=resp.request,
                response=resp,
            )
        try:
            body = resp.json()
        except Exception as err:  # JSONDecodeError or other
            raise ModelError(
                f"non-JSON response: {err}",
                kind=ModelErrorKind.PROTOCOL_ERROR,
                retryable=False,
            ) from err
        return self._parse_response(request, body)

    def _build_payload(self, request: ModelRequest) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        for m in request.messages:
            entry: dict[str, Any] = {
                "role": _WIRE_ROLES[m.role],
                "content": m.content,
            }
            if m.role is ModelMessageRole.ASSISTANT and m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            if m.role is ModelMessageRole.TOOL and m.tool_result_for:
                entry["tool_call_id"] = m.tool_result_for
            messages.append(entry)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": request.parameters.temperature,
            "max_tokens": request.parameters.max_tokens,
            "stream": False,
        }
        if request.tools:
            payload["tools"] = [_tool_to_openai(t) for t in request.tools]
            payload["tool_choice"] = "auto"
        # Stop sequences signal the final (verification) response.
        stop = list(request.parameters.stop) or list(self.stop)
        if stop:
            payload["stop"] = stop
        return payload

    def _parse_response(
        self, request: ModelRequest, body: dict[str, Any]
    ) -> ModelResult:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelError(
                "LM Studio response has no choices",
                kind=ModelErrorKind.PROTOCOL_ERROR,
                retryable=False,
            )
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ModelError(
                "LM Studio choice is not an object",
                kind=ModelErrorKind.PROTOCOL_ERROR,
                retryable=False,
            )
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ModelError(
                "LM Studio message is not an object",
                kind=ModelErrorKind.PROTOCOL_ERROR,
                retryable=False,
            )
        response = self._normalize_message(message)
        usage = _parse_usage(body.get("usage"))
        if isinstance(response, ModelError):
            return _error_result(request, response, self.name, usage)
        return ModelResult(
            run_id=request.run_id,
            task_id=request.task_id,
            attempt=request.attempt,
            step=request.step,
            response=response,
            usage=usage,
            backend=self.name,
        )

    def _normalize_message(self, message: dict[str, Any]) -> ModelResponse | ModelError:
        """Map one LM Studio assistant message to a normalized response.

        Tool calls take precedence over final text: if the server returned
        ``tool_calls`` we parse them (strictly). Otherwise the text is parsed
        via the strict scripted-output parser (``[VERIFY]`` / ``[ESCALATE]`` /
        JSON tool / invalid), so a bad format is ALWAYS InvalidResponse.
        """
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            return self._parse_tool_calls(tool_calls)
        content = message.get("content")
        if not isinstance(content, str):
            return InvalidResponse(
                raw=str(content), reason="assistant content is not a string"
            )
        return parse_scripted_output(content)

    def _parse_tool_calls(self, tool_calls: list[Any]) -> ModelResponse | ModelError:
        """Strictly parse LM Studio tool_calls into a single ToolCall.

        The Executor Loop handles one tool call per step; LM Studio may return
        several. We surface the first valid tool call (consistent with the
        single-call-per-step loop contract). A malformed tool call (missing
        id/name, or non-object arguments) is ALWAYS InvalidResponse, never a
        silent ToolCall. If all are malformed, return InvalidResponse.
        """
        for raw in tool_calls:
            if not isinstance(raw, dict):
                continue
            tcid = raw.get("id")
            fn = raw.get("function")
            if not isinstance(tcid, str) or not tcid.strip():
                continue
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            args_raw = fn.get("arguments")
            if not isinstance(name, str) or not name.strip():
                continue
            arguments: dict[str, Any]
            if args_raw is None:
                arguments = {}
            elif isinstance(args_raw, dict):
                arguments = args_raw
            elif isinstance(args_raw, str):
                if not args_raw.strip():
                    arguments = {}
                else:
                    try:
                        parsed = json.loads(args_raw)
                    except json.JSONDecodeError:
                        # Malformed arguments JSON => InvalidResponse, not a
                        # silent ToolCall with garbage.
                        return InvalidResponse(
                            raw=str(args_raw),
                            reason="tool call arguments not valid JSON",
                        )
                    if not isinstance(parsed, dict):
                        return InvalidResponse(
                            raw=str(args_raw),
                            reason="tool call arguments JSON is not an object",
                        )
                    arguments = parsed
            else:
                return InvalidResponse(
                    raw=str(args_raw),
                    reason="tool call arguments not an object or JSON string",
                )
            return ToolCall(tool_call_id=tcid, name=name, arguments=arguments)
        return InvalidResponse(
            raw=str(tool_calls), reason="no valid tool call in tool_calls"
        )


# -- helpers ------------------------------------------------------------------


def _tool_to_openai(tool: ToolDeclaration) -> dict[str, Any]:
    """Map a provider-neutral ToolDeclaration to OpenAI tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_usage(raw: Any) -> ModelUsage:
    """Parse OpenAI-style usage into ModelUsage; absent fields stay None (honest)."""
    if not isinstance(raw, dict):
        return ModelUsage()
    return ModelUsage(
        prompt_tokens=_as_int(raw.get("prompt_tokens")),
        completion_tokens=_as_int(raw.get("completion_tokens")),
        total_tokens=_as_int(raw.get("total_tokens")),
    )


def _as_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _status_error(status: int, detail: str) -> ModelError:
    """Map an HTTP status to a normalized ModelErrorKind."""
    if status == 408:
        return ModelError(detail, kind=ModelErrorKind.TIMEOUT, retryable=True)
    if status == 429:
        return ModelError(detail, kind=ModelErrorKind.RATE_LIMITED, retryable=True)
    if status in (401, 403):
        return ModelError(detail, kind=ModelErrorKind.AUTHENTICATION, retryable=False)
    if status == 400:
        return ModelError(detail, kind=ModelErrorKind.BAD_REQUEST, retryable=False)
    if 500 <= status < 600:
        return ModelError(detail, kind=ModelErrorKind.UNAVAILABLE, retryable=True)
    return ModelError(detail, kind=ModelErrorKind.PROTOCOL_ERROR, retryable=False)


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
    "DEFAULT_BASE_URL",
    "DEFAULT_TIMEOUT_SECONDS",
    "LMStudioAdapter",
]
