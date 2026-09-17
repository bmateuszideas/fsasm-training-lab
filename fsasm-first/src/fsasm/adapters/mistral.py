"""FS-ASM Mistral transport adapter (T20).

One transport adapter for Mistral API, configured with **logical roles**
(Planner, API A = consultation/expertise, API B = handover/harder execution)
rather than concrete model names. The concrete model name per role is resolved
in configuration (T29), NOT assumed by the adapter (architecture §26: "do not
assume A is always cheaper than B or that the second model is a judge of every
result"). The adapter translates ONLY transport and format between the
provider-neutral :class:`fsasm.gateway.ModelBackend` contract and Mistral's
OpenAI-compatible ``/v1/chat/completions`` shape. It holds NO domain rules: no
retry, no PASS, no scope or routing policy — those stay in the Domain Core, the
Model Router (T21) and the Executor Loop (T17) (architecture §25, §27; canonical
TODO T20).

The same adapter instance serves the Planner, the consultation role (API A)
and the handover role (API B): each is a :class:`MistralRole` carrying a
configurable ``model`` name and ``backend`` label. The adapter normalizes
tool calls, final response, escalation, invalid output, usage and
rate/transport failure identically across roles, so the Planner and roles A/B
share one contract (canonical TODO T20 reception).

Normalization contract (mirrors the strictness the gateway parser and the LM
Studio adapter enforce):

- A native Mistral tool call (``choices[].message.tool_calls``) maps to a
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
  never a domain success. HTTP status maps to the normalized
  :class:`ModelErrorKind` exactly as the local adapter (408/timeout →
  ``TIMEOUT``; 429 → ``RATE_LIMITED``; 401/403 → ``AUTHENTICATION``; 400 →
  ``BAD_REQUEST``; 5xx/connection → ``UNAVAILABLE``; malformed body →
  ``PROTOCOL_ERROR``).

Tests run on a controlled fixture (httpx ``MockTransport``) with NO live or
paid Mistral call. The Domain Core never imports httpx or the Mistral SDK: it
depends only on the :class:`ModelBackend` Protocol. The existing
``mistralai_chat_complete``-based ``plan_with_mistral`` activity is NOT used by
this adapter; the Planner is reconnected through the common Gateway so the
adapter is the single transport path for the Planner and roles A/B.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
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

# Re-imported from the canonical scripted parser so the adapter stays
# consistent with it (a final text is parsed strictly: [VERIFY] / [ESCALATE] /
# JSON tool / invalid).
from fsasm.gateway import parse_scripted_output

# Mistral API default endpoint. Overridable per adapter instance. The real
# base URL and key are configured out of band (T29, T33); tests inject
# httpx.MockTransport so NO live/paid call is ever made before Gate H.
DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
DEFAULT_TIMEOUT_SECONDS = 60.0

# OpenAI-compatible role names used on the wire (Mistral is OpenAI-compatible).
_WIRE_ROLES = {
    ModelMessageRole.SYSTEM: "system",
    ModelMessageRole.USER: "user",
    ModelMessageRole.ASSISTANT: "assistant",
    ModelMessageRole.TOOL: "tool",
}


class MistralRole(str, Enum):
    """Logical Mistral role (architecture §26; canonical TODO T20).

    A role is a logical function with a configurable model name, NOT a fixed
    model identity. The Planner proposes plan content; API A provides
    consultation/expertise; API B is a handover target for harder execution.
    Roles A/B are not assumed cheaper/relative or a judge of the other
    (architecture §26). The Model Router (T21) decides which role a call goes
    to; the adapter only transports it.
    """

    PLANNER = "planner"
    API_A = "api_a"
    API_B = "api_b"


@dataclass
class MistralRoleConfig:
    """Per-role transport configuration for the Mistral adapter.

    ``model`` is the configured model name for THIS role (resolved in
    configuration, not assumed by the adapter). ``backend`` is the label
    recorded on :class:`ModelResult` so trajectories distinguish which role
    produced a result. Defaults hold no concrete model name.
    """

    role: MistralRole
    model: str = ""
    backend: str = "mistral"

    def effective_backend(self) -> str:
        return self.backend or f"mistral:{self.role.value}"


@dataclass
class MistralAdapter:
    """One transport adapter for Mistral API across logical roles (T20).

    The SAME adapter instance serves the Planner and roles A/B: callers pass a
    :class:`MistralRoleConfig` (or a role) to :meth:`generate` to select the
    transport model name and backend label. The adapter translates a normalized
    :class:`ModelRequest` to a Mistral OpenAI-compatible
    ``/chat/completions`` POST over httpx, parses the response back to a
    normalized :class:`ModelResult`, and maps transport/format failures to
    :class:`ModelError`. It holds no domain rules and grants no PASS; any
    transport or format failure is a :class:`ModelError` on the result, never a
    domain success. It is deterministic given a deterministic backend (e.g.
    httpx ``MockTransport``).

    A role can be supplied three ways, in priority order:

    1. ``role`` keyword arg to :meth:`generate` (a :class:`MistralRole` or
       :class:`MistralRoleConfig`).
    2. A role configured on the adapter via ``default_role``.
    3. A single role bound at construction (``roles`` with one entry), used as
       the adapter's identity.

    This lets one adapter instance be role-configurable (Planner + A/B) while a
    per-role fixed adapter is still expressible.
    """

    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    # Map of role -> config. The adapter never assumes a concrete model name;
    # each role's model is configured by the caller (T29). Empty model means
    # "unconfigured for that role" — calling generate for an unconfigured role
    # is a deterministic BAD_REQUEST ModelError, not a live call.
    roles: dict[MistralRole, MistralRoleConfig] = field(default_factory=dict)
    # Role used when generate() is called without an explicit role.
    default_role: MistralRole | None = None
    # Stop sequences that signal a final (verification) response. Mirrors
    # ModelParameters.stop default so the adapter and the domain agree.
    stop: tuple[str, ...] = ("[VERIFY]",)
    # Injectable transport for tests (httpx.MockTransport). When None the
    # adapter uses a real httpx.Client against base_url.
    transport: httpx.BaseTransport | None = None
    # API key read from the environment/config, never logged, never in evidence.
    # Tests inject MockTransport so no real key is ever used before Gate H.
    api_key: str | None = None
    name: str = "mistral"
    # Recorded wire requests for assertions / audit (no secrets).
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # If a single role was bound, prefer it as the default when none set.
        if self.default_role is None and len(self.roles) == 1:
            self.default_role = next(iter(self.roles))

    def generate(
        self,
        request: ModelRequest,
        role: MistralRole | MistralRoleConfig | None = None,
    ) -> ModelResult:
        """One normalized model call to Mistral; returns ModelResult, never raises.

        ``role`` selects the logical role (Planner / API A / API B) for this
        call: it picks the transport model name and the backend label recorded
        on the result. If omitted, the adapter's ``default_role`` is used. If
        no role is configured at all, the adapter uses its ``name``/``model``
        defaults (a role-less transport identity) so the contract still holds.
        """
        cfg = self._resolve_role(role)
        try:
            return self._do_call(request, cfg)
        except ModelError as err:
            return _error_result(request, err, cfg.effective_backend())
        except httpx.TimeoutException as err:
            return _error_result(
                request,
                ModelError(str(err), kind=ModelErrorKind.TIMEOUT, retryable=True),
                cfg.effective_backend(),
            )
        except httpx.ConnectError as err:
            return _error_result(
                request,
                ModelError(str(err), kind=ModelErrorKind.UNAVAILABLE, retryable=True),
                cfg.effective_backend(),
            )
        except httpx.HTTPStatusError as err:
            return _error_result(
                request,
                _status_error(err.response.status_code, str(err)),
                cfg.effective_backend(),
            )
        except Exception as err:  # pragma: no cover - defensive normalization
            return _error_result(
                request,
                ModelError(str(err), kind=ModelErrorKind.UNKNOWN, retryable=False),
                cfg.effective_backend(),
            )

    # -- internals --------------------------------------------------------

    def _resolve_role(
        self, role: MistralRole | MistralRoleConfig | None
    ) -> MistralRoleConfig:
        if isinstance(role, MistralRoleConfig):
            return role
        if isinstance(role, MistralRole):
            cfg = self.roles.get(role)
            if cfg is not None:
                return cfg
            return MistralRoleConfig(role=role)
        if self.default_role is not None:
            cfg = self.roles.get(self.default_role)
            if cfg is not None:
                return cfg
        # Role-less fallback: a generic transport identity. A caller that
        # configured no roles still gets a deterministic, contract-holding
        # adapter (used by tests that only check transport normalization).
        return MistralRoleConfig(role=MistralRole.PLANNER, backend=self.name)

    def _do_call(self, request: ModelRequest, cfg: MistralRoleConfig) -> ModelResult:
        if not cfg.model:
            raise ModelError(
                f"role '{cfg.role.value}' has no configured model",
                kind=ModelErrorKind.BAD_REQUEST,
                retryable=False,
            )
        payload = self._build_payload(request, cfg)
        self.calls.append(
            {"role": cfg.role.value, "url": self.base_url, "payload": payload}
        )
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
            headers=headers,
        ) as client:
            resp = client.post("/chat/completions", json=payload)
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Mistral returned {resp.status_code}",
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
        return self._parse_response(request, body, cfg)

    def _build_payload(
        self, request: ModelRequest, cfg: MistralRoleConfig
    ) -> dict[str, Any]:
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
            "model": cfg.model,
            "messages": messages,
            "temperature": request.parameters.temperature,
            "max_tokens": request.parameters.max_tokens,
            "stream": False,
        }
        if request.tools:
            payload["tools"] = [_tool_to_openai(t) for t in request.tools]
            payload["tool_choice"] = "auto"
        stop = list(request.parameters.stop) or list(self.stop)
        if stop:
            payload["stop"] = stop
        return payload

    def _parse_response(
        self,
        request: ModelRequest,
        body: dict[str, Any],
        cfg: MistralRoleConfig,
    ) -> ModelResult:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelError(
                "Mistral response has no choices",
                kind=ModelErrorKind.PROTOCOL_ERROR,
                retryable=False,
            )
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ModelError(
                "Mistral choice is not an object",
                kind=ModelErrorKind.PROTOCOL_ERROR,
                retryable=False,
            )
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ModelError(
                "Mistral message is not an object",
                kind=ModelErrorKind.PROTOCOL_ERROR,
                retryable=False,
            )
        response = self._normalize_message(message)
        usage = _parse_usage(body.get("usage"))
        backend = cfg.effective_backend()
        if isinstance(response, ModelError):
            return _error_result(request, response, backend, usage)
        return ModelResult(
            run_id=request.run_id,
            task_id=request.task_id,
            attempt=request.attempt,
            step=request.step,
            response=response,
            usage=usage,
            backend=backend,
        )

    def _normalize_message(self, message: dict[str, Any]) -> ModelResponse | ModelError:
        """Map one Mistral assistant message to a normalized response.

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
        """Strictly parse Mistral tool_calls into a single ToolCall.

        The Executor Loop handles one tool call per step; Mistral may return
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
    """Parse Mistral/OpenAI-style usage into ModelUsage; absent fields stay None."""
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
    """Map an HTTP status to a normalized ModelErrorKind (mirrors local adapter)."""
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
    "MistralAdapter",
    "MistralRole",
    "MistralRoleConfig",
]
