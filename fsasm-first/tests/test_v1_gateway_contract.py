"""T16 — Provider-neutral Model Gateway and scripted backend.

Proves the Gateway contract covers: correct tool calls, final responses,
escalation requests, invalid responses, normalized usage, and transport
errors — all through one provider-neutral ``generate`` interface with no
provider-specific types in the domain. The parser cannot confuse a bad format
with a successful tool call or final response (architecture §24; canonical
TODO T16). Budgets are enforced before the next effect.
"""

import json

import pytest

from fsasm.gateway import ModelGateway, ScriptedBackend, parse_scripted_output
from fsasm.model_types import (
    BudgetUsage,
    EscalationRequest,
    FinalResponse,
    InvalidResponse,
    ModelCallBudget,
    ModelError,
    ModelErrorKind,
    ModelMessage,
    ModelMessageRole,
    ModelRequest,
    ModelResult,
    ModelUsage,
    ToolCall,
)


def _req(step: int = 1) -> ModelRequest:
    return ModelRequest(
        run_id="r",
        task_id="t",
        attempt=1,
        step=step,
        messages=[ModelMessage(role=ModelMessageRole.USER, content="do the task")],
    )


class TestProviderNeutralInterface:
    """One generate(request) interface; no provider types leak into the domain."""

    def test_generate_returns_model_result(self) -> None:
        backend = ScriptedBackend(responses=["[VERIFY] done"])
        gw = ModelGateway(backend=backend)
        result = gw.generate(_req())
        assert isinstance(result, ModelResult)
        assert isinstance(result.response, FinalResponse)
        assert result.backend == "scripted"

    def test_request_is_provider_neutral(self) -> None:
        backend = ScriptedBackend(responses=["[VERIFY] done"])
        gw = ModelGateway(backend=backend)
        gw.generate(_req())
        recorded = backend.calls[0]
        assert isinstance(recorded, ModelRequest)
        # No provider-specific types on the request.
        assert recorded.run_id == "r"
        assert recorded.task_id == "t"
        assert recorded.messages[0].role is ModelMessageRole.USER

    def test_backend_protocol_attribute(self) -> None:
        # ScriptedBackend satisfies the ModelBackend Protocol (name + generate).
        backend = ScriptedBackend(responses=["[VERIFY] done"])
        assert hasattr(backend, "name")
        assert hasattr(backend, "generate")


class TestToolCall:
    """A correct JSON tool call yields a ToolCall response."""

    def test_json_tool_call(self) -> None:
        raw = json.dumps(
            {
                "tool_call_id": "c1",
                "name": "read_file",
                "arguments": {"path": "calc.py"},
            }
        )
        backend = ScriptedBackend(responses=[raw])
        result = ModelGateway(backend=backend).generate(_req())
        assert isinstance(result.response, ToolCall)
        assert result.response.tool_call_id == "c1"
        assert result.response.name == "read_file"
        assert result.response.arguments == {"path": "calc.py"}

    def test_prebuilt_tool_call_object(self) -> None:
        tc = ToolCall(tool_call_id="c2", name="apply_patch", arguments={"path": "a.py"})
        backend = ScriptedBackend(responses=[tc])
        result = ModelGateway(backend=backend).generate(_req())
        assert isinstance(result.response, ToolCall)
        assert result.response.tool_call_id == "c2"


class TestFinalResponse:
    """A [VERIFY] final response requests verification, never PASS."""

    def test_verify_final(self) -> None:
        backend = ScriptedBackend(responses=["[VERIFY] patched calc.py to subtract"])
        result = ModelGateway(backend=backend).generate(_req())
        assert isinstance(result.response, FinalResponse)
        assert "subtract" in result.response.content

    def test_final_is_not_pass(self) -> None:
        backend = ScriptedBackend(responses=["[VERIFY] done"])
        result = ModelGateway(backend=backend).generate(_req())
        # FinalResponse carries content only; it grants no transition.
        assert not hasattr(result.response, "granted")
        assert not hasattr(result.response, "pass")


class TestEscalationRequest:
    """A [ESCALATE] request asks for consultation/handover; model cannot escalate itself."""

    def test_consultation(self) -> None:
        backend = ScriptedBackend(
            responses=["[ESCALATE] consultation need expert advice"]
        )
        result = ModelGateway(backend=backend).generate(_req())
        assert isinstance(result.response, EscalationRequest)
        assert result.response.kind == "consultation"
        assert "expert advice" in result.response.reason

    def test_handover_with_target(self) -> None:
        backend = ScriptedBackend(
            responses=["[ESCALATE] handover too hard -> mistral-large"]
        )
        result = ModelGateway(backend=backend).generate(_req())
        assert isinstance(result.response, EscalationRequest)
        assert result.response.kind == "handover"
        assert result.response.target == "mistral-large"


class TestInvalidResponse:
    """The parser never confuses a bad format with a successful response."""

    @pytest.mark.parametrize(
        "raw",
        [
            "garbage output",
            "",
            "[VERIFY]",  # empty rationale
            "[ESCALATE] badkind reason",  # invalid kind
            "[ESCALATE] consultation",  # no reason
            '{"tool_call_id": "", "name": "x"}',  # blank id
            '{"tool_call_id": "c1", "name": ""}',  # blank name
            "not json at all {",
        ],
    )
    def test_unparseable_is_invalid(self, raw: str) -> None:
        backend = ScriptedBackend(responses=[raw])
        result = ModelGateway(backend=backend).generate(_req())
        assert isinstance(result.response, InvalidResponse)
        assert result.response.reason

    def test_malformed_json_not_tool_call(self) -> None:
        """Malformed tool-call JSON is InvalidResponse, not a ToolCall."""
        backend = ScriptedBackend(responses=['{"tool_call_id": "c1", name broken}'])
        result = ModelGateway(backend=backend).generate(_req())
        assert isinstance(result.response, InvalidResponse)
        assert not isinstance(result.response, ToolCall)

    def test_non_object_json_is_invalid(self) -> None:
        backend = ScriptedBackend(responses=["[1, 2, 3]"])
        result = ModelGateway(backend=backend).generate(_req())
        assert isinstance(result.response, InvalidResponse)


class TestTransportErrors:
    """A normalized ModelError is a transport failure, never a domain success."""

    def test_timeout_error(self) -> None:
        err = ModelError("timed out", kind=ModelErrorKind.TIMEOUT, retryable=True)
        backend = ScriptedBackend(responses=[err])
        result = ModelGateway(backend=backend).generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.TIMEOUT
        assert result.error.retryable is True
        # A transport error is not a domain success: response is InvalidResponse.
        assert isinstance(result.response, InvalidResponse)

    def test_rate_limited(self) -> None:
        err = ModelError("429", kind=ModelErrorKind.RATE_LIMITED, retryable=True)
        backend = ScriptedBackend(responses=[err])
        result = ModelGateway(backend=backend).generate(_req())
        assert result.error.kind is ModelErrorKind.RATE_LIMITED

    def test_unavailable(self) -> None:
        err = ModelError("503", kind=ModelErrorKind.UNAVAILABLE, retryable=False)
        backend = ScriptedBackend(responses=[err])
        result = ModelGateway(backend=backend).generate(_req())
        assert result.error.kind is ModelErrorKind.UNAVAILABLE

    def test_backend_raising_is_normalized(self) -> None:
        """A backend that raises is defensively normalized to a ModelError."""

        class RaisingBackend:
            name = "raising"

            def generate(self, request: ModelRequest) -> ModelResult:
                raise RuntimeError("provider exploded")

        gw = ModelGateway(backend=RaisingBackend())  # type: ignore[arg-type]
        result = gw.generate(_req())
        assert result.error is not None
        assert result.error.kind is ModelErrorKind.UNKNOWN
        assert "provider exploded" in result.error.message


class TestUsage:
    """Normalized usage is recorded only when reported; absence is honest."""

    def test_usage_reported(self) -> None:
        usage = ModelUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        backend = ScriptedBackend(responses=["[VERIFY] done"], per_call_usage=usage)
        result = ModelGateway(backend=backend).generate(_req())
        assert result.usage.total_tokens == 15
        assert result.usage.prompt_tokens == 10

    def test_usage_absent_is_zero(self) -> None:
        backend = ScriptedBackend(responses=["[VERIFY] done"])
        result = ModelGateway(backend=backend).generate(_req())
        # No usage reported -> honest absence, not fabricated.
        assert result.usage.total_tokens is None
        assert result.usage.cost is None


class TestScheduledSequence:
    """The scripted backend returns the scheduled sequence in order."""

    def test_sequence_in_order(self) -> None:
        backend = ScriptedBackend(
            responses=[
                '{"tool_call_id":"c1","name":"read_file","arguments":{}}',
                '{"tool_call_id":"c2","name":"apply_patch","arguments":{}}',
                "[VERIFY] done",
            ]
        )
        gw = ModelGateway(backend=backend)
        r1 = gw.generate(_req(step=1))
        r2 = gw.generate(_req(step=2))
        r3 = gw.generate(_req(step=3))
        assert isinstance(r1.response, ToolCall) and r1.response.name == "read_file"
        assert isinstance(r2.response, ToolCall) and r2.response.name == "apply_patch"
        assert isinstance(r3.response, FinalResponse)

    def test_exhausted_returns_invalid(self) -> None:
        backend = ScriptedBackend(responses=["[VERIFY] done"])
        gw = ModelGateway(backend=backend)
        gw.generate(_req())
        # Second call has no scheduled response.
        result = gw.generate(_req())
        assert isinstance(result.response, InvalidResponse)
        assert "exhausted" in result.response.reason

    def test_calls_recorded(self) -> None:
        backend = ScriptedBackend(responses=["[VERIFY] a", "[VERIFY] b"])
        gw = ModelGateway(backend=backend)
        gw.generate(_req())
        gw.generate(_req())
        assert len(backend.calls) == 2


class TestStrictParser:
    """parse_scripted_output directly, covering each branch."""

    def test_verify(self) -> None:
        r = parse_scripted_output("[VERIFY] rationale here")
        assert isinstance(r, FinalResponse)
        assert r.content == "rationale here"

    def test_escalate_handover(self) -> None:
        r = parse_scripted_output("[ESCALATE] handover hard -> big-model")
        assert isinstance(r, EscalationRequest)
        assert r.kind == "handover"
        assert r.target == "big-model"

    def test_tool_call_strict(self) -> None:
        r = parse_scripted_output('{"tool_call_id":"c","name":"x","arguments":{"a":1}}')
        assert isinstance(r, ToolCall)
        assert r.arguments == {"a": 1}

    def test_garbage_is_invalid(self) -> None:
        r = parse_scripted_output("???")
        assert isinstance(r, InvalidResponse)

    def test_arguments_not_object_is_invalid(self) -> None:
        r = parse_scripted_output('{"tool_call_id":"c","name":"x","arguments":[1]}')
        assert isinstance(r, InvalidResponse)


class TestBudgets:
    """Budgets cap model/tool/step/token/cost/time before the next effect."""

    def test_would_exceed_model_calls(self) -> None:
        budget = ModelCallBudget(max_model_calls=3)
        usage = BudgetUsage(model_calls=3)
        assert usage.would_exceed(budget)
        usage2 = BudgetUsage(model_calls=2)
        assert not usage2.would_exceed(budget)

    def test_would_exceed_tool_calls(self) -> None:
        budget = ModelCallBudget(max_tool_calls=2)
        assert BudgetUsage(tool_calls=2).would_exceed_tool(budget)
        assert not BudgetUsage(tool_calls=1).would_exceed_tool(budget)

    def test_would_exceed_agent_steps(self) -> None:
        budget = ModelCallBudget(max_agent_steps=5)
        assert BudgetUsage(agent_steps=5).would_exceed_tool(budget)

    def test_would_exceed_tokens(self) -> None:
        budget = ModelCallBudget(max_tokens=100)
        assert BudgetUsage(tokens=100).would_exceed(budget)
        assert not BudgetUsage(tokens=99).would_exceed(budget)

    def test_no_cap_never_exceeds(self) -> None:
        budget = ModelCallBudget()
        assert not BudgetUsage(model_calls=99999).would_exceed(budget)
        assert not BudgetUsage(tool_calls=99999).would_exceed_tool(budget)


class TestGatewayGrantsNoPass:
    """The Gateway / backend types hold no transition authority."""

    def test_gateway_has_no_pass_method(self) -> None:
        from fsasm.gateway import ModelGateway as GW

        for forbidden in ("grant_pass", "pass_task", "transition", "apply", "commit"):
            assert not hasattr(GW, forbidden)

    def test_scripted_backend_has_no_pass_method(self) -> None:
        from fsasm.gateway import ScriptedBackend as SB

        for forbidden in ("grant_pass", "pass_task", "transition", "apply", "commit"):
            assert not hasattr(SB, forbidden)

    def test_response_types_have_no_pass(self) -> None:
        for cls in (ToolCall, FinalResponse, EscalationRequest, InvalidResponse):
            for forbidden in ("grant_pass", "pass_task", "transition"):
                assert not hasattr(cls, forbidden)
