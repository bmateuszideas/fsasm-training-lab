"""T19 — LM Studio local adapter contract.

Proves the LM Studio adapter (one chosen local inference protocol, canonical
TODO §6) implements the provider-neutral :class:`ModelBackend` contract over a
controlled fixture (httpx ``MockTransport``) with NO real 7B model and NO
network. All gateway contract scenarios pass through the local adapter:
correct tool calls, final response, escalation, invalid output, normalized
usage, and transport errors (timeout, unavailable, rate-limited, auth,
bad-request, protocol error). A malformed tool call is ALWAYS InvalidResponse,
never a silent ToolCall; a transport failure is ALWAYS a ModelError, never a
domain success. The adapter holds no domain rules and grants no PASS
(architecture §25, §27; canonical TODO T19).
"""

import json

import httpx

from fsasm.adapters.local import (
    DEFAULT_BASE_URL,
    LMStudioAdapter,
)
from fsasm.gateway import ModelGateway
from fsasm.model_types import (
    EscalationRequest,
    FinalResponse,
    InvalidResponse,
    ModelErrorKind,
    ModelMessage,
    ModelMessageRole,
    ModelRequest,
    ModelResult,
    ToolCall,
    ToolDeclaration,
)


def _req(step: int = 1, tools: list[ToolDeclaration] | None = None) -> ModelRequest:
    return ModelRequest(
        run_id="r",
        task_id="t",
        attempt=1,
        step=step,
        messages=[ModelMessage(role=ModelMessageRole.USER, content="do the task")],
        tools=tools or [],
    )


def _tool(name: str = "read_file") -> ToolDeclaration:
    return ToolDeclaration(
        name=name,
        description="read a file",
        parameters={"type": "object", "properties": {}},
    )


def _ok_body(
    content: str | None = None,
    *,
    tool_calls: list[dict] | None = None,
    usage: dict | None = None,
) -> dict:
    message: dict = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    body: dict = {
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _mock(handler, adapter: LMStudioAdapter) -> LMStudioAdapter:
    adapter.transport = httpx.MockTransport(handler)
    return adapter


def _adapter() -> LMStudioAdapter:
    return LMStudioAdapter(base_url=DEFAULT_BASE_URL, model="local-7b")


class TestProviderNeutralInterface:
    """The adapter implements the ModelBackend contract; returns ModelResult."""

    def test_generate_returns_model_result(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert isinstance(result, ModelResult)
        assert isinstance(result.response, FinalResponse)
        assert result.backend == "lm-studio"

    def test_adapter_satisfies_modelbackend_protocol(self) -> None:
        adapter = _adapter()
        assert adapter.name == "lm-studio"
        assert callable(adapter.generate)

    def test_works_through_gateway(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        gw = ModelGateway(backend=adapter)
        result = gw.generate(_req())
        assert isinstance(result.response, FinalResponse)


class TestToolCalls:
    """Native LM Studio tool_calls map to ToolCall; malformed -> InvalidResponse."""

    def test_native_tool_call(self) -> None:
        body = _ok_body(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": "calc.py"}),
                    },
                }
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req(tools=[_tool()]))
        assert isinstance(result.response, ToolCall)
        assert result.response.tool_call_id == "call_1"
        assert result.response.name == "read_file"
        assert result.response.arguments == {"path": "calc.py"}

    def test_tool_call_dict_arguments(self) -> None:
        body = _ok_body(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": {"path": "calc.py"}},
                }
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req(tools=[_tool()]))
        assert isinstance(result.response, ToolCall)
        assert result.response.arguments == {"path": "calc.py"}

    def test_tool_call_empty_arguments_string(self) -> None:
        body = _ok_body(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": ""},
                }
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req(tools=[_tool()]))
        assert isinstance(result.response, ToolCall)
        assert result.response.arguments == {}

    def test_malformed_tool_call_id_missing_is_invalid(self) -> None:
        body = _ok_body(
            tool_calls=[
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req(tools=[_tool()]))
        # No valid tool call => InvalidResponse, never a silent ToolCall.
        assert isinstance(result.response, InvalidResponse)

    def test_malformed_tool_call_name_missing_is_invalid(self) -> None:
        body = _ok_body(
            tool_calls=[
                {"id": "call_1", "type": "function", "function": {"arguments": "{}"}}
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req(tools=[_tool()]))
        assert isinstance(result.response, InvalidResponse)

    def test_tool_call_bad_json_arguments_is_invalid(self) -> None:
        body = _ok_body(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{not json"},
                }
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req(tools=[_tool()]))
        assert isinstance(result.response, InvalidResponse)

    def test_tool_call_non_object_json_arguments_is_invalid(self) -> None:
        body = _ok_body(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "[1, 2, 3]"},
                }
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req(tools=[_tool()]))
        assert isinstance(result.response, InvalidResponse)

    def test_tool_declaration_mapped_to_openai(self) -> None:
        body = _ok_body("[VERIFY] done")

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        adapter.generate(_req(tools=[_tool("read_file")]))
        tools = captured["payload"]["tools"]
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "read_file"
        assert captured["payload"]["tool_choice"] == "auto"


class TestFinalAndEscalation:
    """Final/escalation text parsed via the strict scripted-output parser."""

    def test_verify_final(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[VERIFY] I am done"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert isinstance(result.response, FinalResponse)
        assert result.response.content == "I am done"

    def test_escalate_consultation(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_ok_body("[ESCALATE] consultation need advice -> api_b")
            )

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert isinstance(result.response, EscalationRequest)
        assert result.response.kind == "consultation"
        assert result.response.target == "api_b"

    def test_unparseable_text_is_invalid(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("just some random text"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert isinstance(result.response, InvalidResponse)

    def test_non_string_content_is_invalid(self) -> None:
        body = {"choices": [{"message": {"role": "assistant", "content": None}}]}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert isinstance(result.response, InvalidResponse)


class TestTransportErrors:
    """Every transport failure is a ModelError, never a domain success."""

    def test_timeout_is_model_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.TIMEOUT
        assert isinstance(result.response, InvalidResponse)

    def test_connection_refused_is_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.UNAVAILABLE

    def test_429_is_rate_limited(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.RATE_LIMITED

    def test_401_is_authentication(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.AUTHENTICATION

    def test_400_is_bad_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad request"})

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.BAD_REQUEST

    def test_500_is_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server error"})

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.UNAVAILABLE

    def test_non_json_body_is_protocol_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"not json at all", headers={"content-type": "text/plain"}
            )

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.PROTOCOL_ERROR

    def test_empty_choices_is_protocol_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.PROTOCOL_ERROR

    def test_transport_error_never_domain_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert not isinstance(
            result.response, (FinalResponse, ToolCall, EscalationRequest)
        )
        assert isinstance(result.response, InvalidResponse)
        assert result.error is not None


class TestUsage:
    """Usage is parsed when present; absent fields stay None (honest)."""

    def test_usage_reported(self) -> None:
        body = _ok_body(
            "[VERIFY] done",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 5
        assert result.usage.total_tokens == 15

    def test_usage_absent_is_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.usage.prompt_tokens is None
        assert result.usage.total_tokens is None


class TestWireRequest:
    """The wire request is a valid OpenAI-compatible chat-completions payload."""

    def test_payload_shape(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            captured["path"] = str(request.url)
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        adapter.generate(_req())
        p = captured["payload"]
        assert p["model"] == "local-7b"
        assert p["messages"][0]["role"] == "user"
        assert p["stream"] is False
        assert "[VERIFY]" in p["stop"]
        assert "/chat/completions" in captured["path"]

    def test_tool_result_message_has_tool_call_id(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        req = ModelRequest(
            run_id="r",
            task_id="t",
            attempt=1,
            step=2,
            messages=[
                ModelMessage(role=ModelMessageRole.USER, content="do it"),
                ModelMessage(
                    role=ModelMessageRole.ASSISTANT,
                    content="tool",
                    tool_call_id="call_1",
                ),
                ModelMessage(
                    role=ModelMessageRole.TOOL, content="OK", tool_result_for="call_1"
                ),
            ],
        )
        adapter.generate(req)
        msgs = captured["payload"]["messages"]
        assert msgs[1]["tool_call_id"] == "call_1"
        assert msgs[2]["tool_call_id"] == "call_1"
        assert msgs[2]["role"] == "tool"


class TestAdapterHasNoDomainRules:
    """The adapter grants no PASS and holds no retry/routing/scope policy."""

    def test_adapter_has_no_retry_method(self) -> None:
        adapter = _adapter()
        assert not hasattr(adapter, "retry")
        assert not hasattr(adapter, "grant_pass")
        assert not hasattr(adapter, "decide_routing")

    def test_adapter_does_not_consume_attempts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        # The result carries no attempt-bump or PASS field.
        assert not hasattr(result, "pass_")
        assert not hasattr(result, "new_attempt")
