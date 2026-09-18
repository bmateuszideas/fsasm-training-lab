"""T20 — Mistral transport adapter contract (one adapter, logical roles).

Proves the single Mistral adapter implements the provider-neutral
:class:`ModelBackend` contract over a controlled fixture (httpx
``MockTransport``) with NO live and NO paid Mistral call. The SAME adapter
instance serves the Planner, consultation role (API A) and handover role (API
B) under one contract: correct tool calls, final response, escalation,
invalid output, normalized usage, and transport errors (rate-limited,
timeout, auth, bad-request, unavailable, protocol error). A malformed tool
call is ALWAYS InvalidResponse, never a silent ToolCall; a transport failure
is ALWAYS a ModelError, never a domain success. The adapter holds no domain
rules (no retry, no PASS, no scope/routing) and assumes no concrete model
name (architecture §25–§26; canonical TODO T20).

Also proves the Planner is reconnectable through the common Gateway+adapter
contract WITHOUT changing Task Compiler ownership: a Planner routed via
``plan_with_mistral_gateway`` compiles the proposal through ``assemble_plan``
exactly once, makes exactly one normalized model call, and never reaches a
live/paid endpoint.
"""

import json

import httpx
import pytest

from fsasm.adapters.mistral import (
    DEFAULT_BASE_URL,
    MistralAdapter,
    MistralRole,
    MistralRoleConfig,
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
from fsasm.models import (
    GoalInput,
    PlannerBackend,
    PlannerConfig,
)
from fsasm.planner_activities import (
    build_planner_gateway,
    plan_with_mistral_gateway,
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


def _adapter(
    role: MistralRole = MistralRole.API_A, model: str = "mistral-role"
) -> MistralAdapter:
    return MistralAdapter(
        base_url=DEFAULT_BASE_URL,
        roles={role: MistralRoleConfig(role=role, model=model)},
        default_role=role,
    )


def _mock(handler, adapter: MistralAdapter) -> MistralAdapter:
    adapter.transport = httpx.MockTransport(handler)
    return adapter


class TestProviderNeutralInterface:
    """The adapter implements the ModelBackend contract; returns ModelResult."""

    def test_generate_returns_model_result(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert isinstance(result, ModelResult)
        assert isinstance(result.response, FinalResponse)

    def test_adapter_satisfies_modelbackend_protocol(self) -> None:
        adapter = _adapter()
        assert adapter.name == "mistral"
        assert callable(adapter.generate)

    def test_works_through_gateway(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        gw = ModelGateway(backend=adapter)
        result = gw.generate(_req())
        assert isinstance(result.response, FinalResponse)

    def test_generate_never_raises_on_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert isinstance(result, ModelResult)


class TestToolCalls:
    """Native Mistral tool_calls map to ToolCall; malformed -> InvalidResponse."""

    def test_native_tool_call_string_arguments(self) -> None:
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

    def test_escalate_handover(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[ESCALATE] handover too hard"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert isinstance(result.response, EscalationRequest)
        assert result.response.kind == "handover"
        assert result.response.target is None

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
            return httpx.Response(200, content=b"not json at all")

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.PROTOCOL_ERROR

    def test_empty_choices_is_protocol_error(self) -> None:
        body = {"choices": []}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.PROTOCOL_ERROR

    def test_transport_error_is_never_domain_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.error is not None
        assert not isinstance(result.response, FinalResponse)
        assert not isinstance(result.response, ToolCall)


class TestUsage:
    """Usage reported honestly; absent fields stay None (never fabricated)."""

    def test_usage_present(self) -> None:
        body = _ok_body(
            "[VERIFY] done",
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 4
        assert result.usage.total_tokens == 14

    def test_usage_absent_is_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        assert result.usage.prompt_tokens is None
        assert result.usage.completion_tokens is None
        assert result.usage.total_tokens is None


class TestWireRequest:
    """The adapter builds a Mistral/OpenAI-compatible wire request."""

    def test_request_shape(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter(model="mistral-a-config"))
        adapter.generate(_req())
        p = captured["payload"]
        assert p["model"] == "mistral-a-config"
        assert p["stream"] is False
        assert p["messages"][0]["role"] == "user"
        assert p["messages"][0]["content"] == "do the task"

    def test_conversation_round_trip_with_tool_messages(self) -> None:
        captured = {}
        body = _ok_body("[VERIFY] done")

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=body)

        adapter = _mock(handler, _adapter())
        request = ModelRequest(
            run_id="r",
            task_id="t",
            attempt=1,
            step=2,
            messages=[
                ModelMessage(role=ModelMessageRole.USER, content="do it"),
                ModelMessage(
                    role=ModelMessageRole.ASSISTANT,
                    content="",
                    tool_call_id="call_1",
                ),
                ModelMessage(
                    role=ModelMessageRole.TOOL, content="OK", tool_result_for="call_1"
                ),
            ],
        )
        adapter.generate(request)
        msgs = captured["payload"]["messages"]
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_call_id"] == "call_1"
        assert msgs[2]["role"] == "tool"
        assert msgs[2]["tool_call_id"] == "call_1"

    def test_stop_sequence_sent(self) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        adapter.generate(_req())
        assert captured["payload"]["stop"] == ["[VERIFY]"]


class TestLogicalRoles:
    """One adapter instance serves Planner, API A and API B under one contract."""

    def test_three_roles_share_one_adapter_instance(self) -> None:
        cfgs = {
            MistralRole.PLANNER: MistralRoleConfig(
                role=MistralRole.PLANNER, model="m-planner"
            ),
            MistralRole.API_A: MistralRoleConfig(role=MistralRole.API_A, model="m-a"),
            MistralRole.API_B: MistralRoleConfig(role=MistralRole.API_B, model="m-b"),
        }
        adapter = MistralAdapter(roles=cfgs)
        adapter.transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=_ok_body("[VERIFY] done"))
        )
        rp = adapter.generate(_req(), role=MistralRole.PLANNER)
        ra = adapter.generate(_req(), role=MistralRole.API_A)
        rb = adapter.generate(_req(), role=MistralRole.API_B)
        assert rp.backend == "mistral"
        assert ra.backend == "mistral"
        assert rb.backend == "mistral"
        # Each call recorded its role and configured model on the wire.
        roles_seen = [c["role"] for c in adapter.calls]
        assert roles_seen == ["planner", "api_a", "api_b"]
        models_seen = [c["payload"]["model"] for c in adapter.calls]
        assert models_seen == ["m-planner", "m-a", "m-b"]

    def test_role_config_object_overrides_role_model(self) -> None:
        adapter = _adapter(MistralRole.API_A, model="m-a")
        adapter.transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=_ok_body("[VERIFY] done"))
        )
        override = MistralRoleConfig(role=MistralRole.API_A, model="m-a-override")
        adapter.generate(_req(), role=override)
        assert adapter.calls[-1]["payload"]["model"] == "m-a-override"

    def test_unconfigured_role_is_bad_request_not_live_call(self) -> None:
        # No roles configured: asking for a role deterministically fails
        # without any network call (no MockTransport installed = no live call).
        adapter = MistralAdapter()
        result = adapter.generate(_req(), role=MistralRole.API_B)
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.BAD_REQUEST
        # No wire request was recorded => no live/paid call attempted.
        assert adapter.calls == []

    def test_no_concrete_model_name_assumed(self) -> None:
        # Defaults carry NO concrete model name; only caller config sets one.
        adapter = MistralAdapter()
        assert all(cfg.model == "" for cfg in adapter.roles.values())

    def test_default_role_used_when_omitted(self) -> None:
        adapter = _adapter(MistralRole.PLANNER, model="m-planner")
        adapter.transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=_ok_body("[VERIFY] done"))
        )
        result = adapter.generate(_req())
        assert isinstance(result.response, FinalResponse)
        assert adapter.calls[-1]["role"] == "planner"

    def test_single_role_bound_becomes_default(self) -> None:
        adapter = MistralAdapter(
            roles={
                MistralRole.API_B: MistralRoleConfig(
                    role=MistralRole.API_B, model="m-b"
                )
            }
        )
        adapter.transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=_ok_body("[VERIFY] done"))
        )
        adapter.generate(_req())
        assert adapter.calls[-1]["role"] == "api_b"


class TestPlannerReconnectedThroughGateway:
    """Planner routed via the common Gateway+adapter contract; Task Compiler owns compilation."""

    @pytest.mark.asyncio
    async def test_planner_via_gateway_compiles_proposal_once(self) -> None:
        proposal_json = json.dumps(
            {
                "tasks": [
                    {
                        "title": "Inspect",
                        "description": "Inspect input",
                        "dependencies": [],
                        "verification_type": "schema",
                        "verification_expected": "inspected",
                        "constraints": [],
                        "allowed_files": [],
                        "expected_evidence": [],
                    },
                    {
                        "title": "Act",
                        "description": "Act on input",
                        "dependencies": [1],
                        "verification_type": "exists",
                        "verification_expected": "acted",
                        "constraints": [],
                        "allowed_files": ["*.py"],
                        "expected_evidence": [],
                    },
                    {
                        "title": "Verify",
                        "description": "Verify result",
                        "dependencies": [2],
                        "verification_type": "custom",
                        "verification_expected": "verified",
                        "constraints": [],
                        "allowed_files": [],
                        "expected_evidence": [],
                    },
                ]
            }
        )

        def handler(request: httpx.Request) -> httpx.Response:
            body = _ok_body(
                f"[VERIFY] {proposal_json}",
                usage={"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
            )
            return httpx.Response(200, json=body)

        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-planner-config",
            prompt_version="v1.0",
        )
        gateway = build_planner_gateway(config, transport=httpx.MockTransport(handler))
        goal_input = GoalInput(goal="Test goal for gateway planner")
        output = await plan_with_mistral_gateway(goal_input, config, gateway)

        assert output.proposal is not None
        assert len(output.proposal.tasks) == 3
        assert output.plan is not None
        assert len(output.plan.tasks) == 3
        assert output.metadata.provider == "mistral"
        assert output.metadata.model_call_count == 1
        assert output.metadata.input_tokens == 7
        assert output.metadata.output_tokens == 5
        assert output.metadata.total_tokens == 12
        # Task Compiler (assemble_plan) assigned runtime IDs, not the model.
        assert output.plan.tasks[0].task_id == "TASK-001"
        assert output.plan.tasks[1].dependencies == ["TASK-001"]

    @pytest.mark.asyncio
    async def test_planner_via_gateway_transport_error_is_failure(self) -> None:
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-planner-config",
        )
        gateway = build_planner_gateway(
            config,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, json={"error": "rate limited"})
            ),
        )
        goal_input = GoalInput(goal="goal")
        with pytest.raises(Exception):
            await plan_with_mistral_gateway(goal_input, config, gateway)

    @pytest.mark.asyncio
    async def test_planner_via_gateway_non_final_is_failure(self) -> None:
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-planner-config",
        )
        gateway = build_planner_gateway(
            config,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=_ok_body("unparseable text"))
            ),
        )
        goal_input = GoalInput(goal="goal")
        with pytest.raises(Exception):
            await plan_with_mistral_gateway(goal_input, config, gateway)

    def test_build_planner_gateway_requires_model_name(self) -> None:
        config = PlannerConfig(backend=PlannerBackend.MISTRAL, model_name=None)
        with pytest.raises(Exception):
            build_planner_gateway(config)


class TestNoDomainRules:
    """The adapter holds no domain retry, PASS, scope or routing policy."""

    def test_adapter_has_no_retry(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, json={"error": "rate limited"})

        adapter = _mock(handler, _adapter())
        adapter.generate(_req())
        # No domain retry inside the adapter: exactly one wire call.
        assert calls["n"] == 1

    def test_adapter_grants_no_pass(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_body("I PASSED the task"))

        adapter = _mock(handler, _adapter())
        result = adapter.generate(_req())
        # "I PASSED..." is unparseable -> InvalidResponse, never a PASS signal.
        assert isinstance(result.response, InvalidResponse)

    def test_adapter_has_no_routing_policy(self) -> None:
        # The adapter exposes roles but applies NO routing decision: choosing a
        # role is the caller's job (Model Router, T21). generate() for any role
        # just transports; no role is "preferred" internally.
        adapter = _adapter(MistralRole.API_A, model="m-a")
        adapter.transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=_ok_body("[VERIFY] done"))
        )
        ra = adapter.generate(_req(), role=MistralRole.API_A)
        rb = adapter.generate(_req(), role=MistralRole.API_B)
        assert isinstance(ra.response, FinalResponse)
        # API_B not configured -> deterministic BAD_REQUEST, not a routing choice.
        assert rb.error is not None
        assert rb.error.kind is ModelErrorKind.BAD_REQUEST


class TestNoLiveOrPaidCalls:
    """Tests never reach a live or paid Mistral endpoint."""

    def test_no_real_endpoint_used_with_mock_transport(self) -> None:
        # The handler records that requests went ONLY to the mock transport,
        # never to a real network socket.
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json=_ok_body("[VERIFY] done"))

        adapter = _mock(handler, _adapter())
        adapter.generate(_req())
        assert seen, "mock transport handled the request"
        assert all("api.mistral.ai" in u for u in seen)

    def test_unconfigured_adapter_makes_no_network_call(self) -> None:
        # No transport, no roles: generate() fails deterministically before any
        # httpx.Client is opened (so no real socket is ever created).
        adapter = MistralAdapter()
        result = adapter.generate(_req(), role=MistralRole.API_A)
        assert result.error is not None
        assert adapter.calls == []
