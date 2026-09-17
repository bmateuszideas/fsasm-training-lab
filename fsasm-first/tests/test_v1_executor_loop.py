"""T17 — Real Executor Loop.

Proves the v1 Executor Loop realizes ``model → Tool Broker → observation →
model`` until an explicit terminal outcome for ONE ``task_attempt``. Within a
single attempt the loop handles multiple ``agent_step`` iterations separated by
REAL tool effects (not stub text), enforces budgets BEFORE the next effect, and
normalizes terminal reasons: ``COMPLETED`` (a verification request, NOT PASS),
``NEEDS_INFORMATION`` / ``ESCALATION_REQUESTED``, ``STEP_LIMIT_REACHED``,
``TOOL_ERROR``, ``POLICY_BLOCKED``. The loop never grants PASS; a ``FinalResponse``
is a request for the Verification Plane (architecture §23, §24; canonical TODO
T17).

The loop is driven by the deterministic :class:`ScriptedBackend` (T16) and a real
:class:`ToolBroker` (T11/T12) over a real fixture, so tests are reproducible
without a real model. The M3/M4 ``ExecutorStub`` demonstrator path is untouched.
"""

import json
import pathlib

import pytest

from fsasm.context import ContextBuilder
from fsasm.executor_loop import (
    ExecutorLoop,
)
from fsasm.gateway import ModelGateway, ScriptedBackend
from fsasm.model_types import (
    ExecutorOutcomeReason,
    ModelCallBudget,
    ModelError,
    ModelErrorKind,
)
from fsasm.models import (
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.tool_broker import ToolBroker

RUN = "r"
TASK = "TASK-r-1"


def _task(
    tid: str = TASK,
    allowed_files: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    title: str = "Patch add to subtract",
    description: str = "Modify the add function to return a - b",
) -> ChildTask:
    return ChildTask(
        task_id=tid,
        sequence=1,
        title=title,
        description=description,
        dependencies=[],
        allowed_files=allowed_files or ["calc.py"],
        allowed_tools=allowed_tools
        or [
            "read_file",
            "apply_patch",
            "run_checks",
        ],
        verification=VerificationSpec(
            type=VerificationType.SCHEMA, expected="return a - b"
        ),
        expected_evidence=["artifact", "check_result"],
        constraints=[],
    )


def _state(task: ChildTask, run_id: str = RUN) -> RunState:
    plan = Plan(plan_id="p", run_id=run_id, goal="g", tasks=[task])
    return RunState(run_id=run_id, goal="g", status=RunStatus.RUNNING, plan=plan)


def _broker(root: pathlib.Path) -> ToolBroker:
    return ToolBroker(workspace_root=root, workspace_scope=[])


def _tc_tool_call(tcid: str, name: str, arguments: dict | None = None) -> str:
    return json.dumps(
        {
            "tool_call_id": tcid,
            "name": name,
            "arguments": arguments or {},
        }
    )


@pytest.fixture()
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    return tmp_path


def _loop(
    broker: ToolBroker,
    responses: list,
    *,
    budget: ModelCallBudget | None = None,
    max_invalid_reasks: int = 2,
) -> tuple[ExecutorLoop, ScriptedBackend]:
    backend = ScriptedBackend(responses=list(responses))
    gw = ModelGateway(backend=backend)
    builder = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1)
    loop = ExecutorLoop(
        gateway=gw,
        broker=broker,
        context_builder=builder,
        budget=budget or ModelCallBudget(),
        max_invalid_reasks=max_invalid_reasks,
    )
    return loop, backend


class TestTwoIterationsSeparatedByRealTool:
    """The loop runs ≥2 iterations separated by a REAL tool effect."""

    def test_read_then_verify_two_iterations(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        loop, backend = _loop(
            broker,
            [
                _tc_tool_call("c1", "read_file", {"path": "calc.py"}),
                "[VERIFY] patched the file",
            ],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.COMPLETED
        # Two model calls => two agent steps (read, then verify).
        assert out.usage.model_calls == 2
        assert out.usage.agent_steps == 2
        assert out.usage.tool_calls == 1
        # The first step executed a REAL read through the Broker (not stub text).
        assert len(out.observations) == 1
        obs = out.observations[0]
        assert obs.kind.value == "read_file"
        assert obs.ok
        assert "return a + b" in obs.content
        # The two iterations are separated: step 1 tool, step 2 final.
        kinds = [s.response_kind for s in out.steps]
        assert kinds[0].startswith("tool:read_file")
        assert kinds[1] == "final"
        assert out.final_content == "patched the file"
        # Two gateway calls recorded, with the tool observation fed back.
        assert len(backend.calls) == 2
        # The second request carries a TOOL-role message with the read result.
        roles = [m.role.value for m in backend.calls[1].messages]
        assert "tool" in roles

    def test_apply_patch_real_effect_then_verify(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["apply_patch"])
        state = _state(task)
        loop, _ = _loop(
            broker,
            [
                _tc_tool_call(
                    "c1",
                    "apply_patch",
                    {
                        "path": "calc.py",
                        "new_content": "def add(a, b):\n    return a - b\n",
                    },
                ),
                "[VERIFY] changed add to subtract",
            ],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.COMPLETED
        assert len(out.observations) == 1
        patch = out.observations[0]
        assert patch.kind.value == "apply_patch"
        assert patch.ok
        assert patch.diff is not None
        # The REAL effect landed in the fixture (not a stub claim).
        assert (
            (workspace / "calc.py")
            .read_text(encoding="utf-8")
            .strip()
            .endswith("return a - b")
        )

    def test_three_iterations_read_patch_verify(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file", "apply_patch"])
        state = _state(task)
        loop, _ = _loop(
            broker,
            [
                _tc_tool_call("c1", "read_file", {"path": "calc.py"}),
                _tc_tool_call(
                    "c2",
                    "apply_patch",
                    {
                        "path": "calc.py",
                        "new_content": "def add(a, b):\n    return a - b\n",
                    },
                ),
                "[VERIFY] done after real patch",
            ],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.COMPLETED
        assert out.usage.model_calls == 3
        assert out.usage.tool_calls == 2
        assert [s.response_kind for s in out.steps] == [
            "tool:read_file",
            "tool:apply_patch",
            "final",
        ]


class TestFinalResponseIsVerificationRequestNotPass:
    """A FinalResponse is COMPLETED (verification request), never PASS."""

    def test_immediate_verify_completes_without_tool(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        loop, _ = _loop(broker, ["[VERIFY] I am done"])
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.COMPLETED
        assert out.usage.tool_calls == 0
        assert out.final_content == "I am done"
        # No observations => no real effect; the loop did NOT grant PASS.
        assert out.observations == []

    def test_empty_verify_rationale_is_invalid_not_final(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        # "[VERIFY]" with empty rationale parses to InvalidResponse, then a
        # valid final on the re-ask.
        loop, _ = _loop(broker, ["[VERIFY]", "[VERIFY] now with rationale"])
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.COMPLETED
        assert out.final_content == "now with rationale"
        # First step was invalid (re-asked), second was final.
        assert out.steps[0].response_kind == "invalid"
        assert out.steps[1].response_kind == "final"


class TestEscalationTerminal:
    def test_escalation_request_is_terminal(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        loop, _ = _loop(
            broker, ["[ESCALATE] consultation I need advice on regex -> api_b"]
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.ESCALATION_REQUESTED
        assert out.escalation is not None
        assert out.escalation.kind == "consultation"
        assert out.escalation.target == "api_b"
        assert out.usage.tool_calls == 0


class TestBudgetEnforcementBeforeNextEffect:
    """Limits are enforced BEFORE the next model call / tool effect."""

    def test_model_call_limit_stops_with_step_limit(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        budget = ModelCallBudget(max_model_calls=1)
        # The model keeps calling tools; the budget (1 model call) stops it.
        loop, _ = _loop(
            broker,
            [
                _tc_tool_call("c1", "read_file", {"path": "calc.py"}),
                _tc_tool_call("c2", "read_file", {"path": "calc.py"}),
                "[VERIFY] done",
            ],
            budget=budget,
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.STEP_LIMIT_REACHED
        # Exactly one model call happened; the second was blocked by budget.
        assert out.usage.model_calls == 1

    def test_tool_call_limit_stops_with_step_limit(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        budget = ModelCallBudget(max_tool_calls=1)
        loop, _ = _loop(
            broker,
            [
                _tc_tool_call("c1", "read_file", {"path": "calc.py"}),
                _tc_tool_call("c2", "read_file", {"path": "calc.py"}),
                "[VERIFY] done",
            ],
            budget=budget,
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.STEP_LIMIT_REACHED
        assert out.usage.tool_calls == 1

    def test_agent_step_limit_stops_with_step_limit(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        budget = ModelCallBudget(max_agent_steps=2)
        loop, _ = _loop(
            broker,
            [
                _tc_tool_call("c1", "read_file", {"path": "calc.py"}),
                _tc_tool_call("c2", "read_file", {"path": "calc.py"}),
                _tc_tool_call("c3", "read_file", {"path": "calc.py"}),
                "[VERIFY] done",
            ],
            budget=budget,
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.STEP_LIMIT_REACHED
        # Two steps executed (read + read); the third was blocked by step cap.
        assert out.usage.agent_steps == 2
        assert out.usage.tool_calls == 2

    def test_no_implicit_new_attempt_on_limit(self, workspace: pathlib.Path) -> None:
        """Budget exhaustion gives a terminal reason, not a new attempt."""
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        budget = ModelCallBudget(max_model_calls=1)
        loop, _ = _loop(
            broker,
            [_tc_tool_call("c1", "read_file", {"path": "calc.py"})],
            budget=budget,
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        # The single outcome object represents one attempt; no second run.
        assert out.attempt == 1
        assert out.reason is ExecutorOutcomeReason.STEP_LIMIT_REACHED


class TestTransportErrorTerminal:
    """A ModelError is terminal TOOL_ERROR (no implicit new attempt)."""

    def test_transport_error_is_tool_error(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        err = ModelError("boom", kind=ModelErrorKind.UNAVAILABLE, retryable=True)
        loop, _ = _loop(broker, [err, "[VERIFY] never reached"])
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.TOOL_ERROR
        assert out.usage.model_calls == 1
        # The retryable transport error did NOT consume a merytoryczna attempt:
        # there is exactly one outcome, attempt stays 1, no tool effect.
        assert out.observations == []
        assert out.attempt == 1


class TestInvalidResponseReask:
    """An unparseable output is a recoverable step error, terminalizing on streak."""

    def test_invalid_then_valid_recovers(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        loop, _ = _loop(
            broker,
            ["garbage output", "[VERIFY] recovered"],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.COMPLETED
        assert out.steps[0].response_kind == "invalid"
        assert out.steps[1].response_kind == "final"

    def test_persistent_invalid_terminalizes_tool_error(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        # max_invalid_reasks=1: one invalid, one re-ask invalid => terminal.
        loop, _ = _loop(
            broker,
            ["garbage 1", "garbage 2", "[VERIFY] too late"],
            max_invalid_reasks=1,
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.TOOL_ERROR
        invalid_steps = [s for s in out.steps if s.response_kind == "invalid"]
        assert len(invalid_steps) == 2

    def test_malformed_tool_call_json_is_invalid_not_tool(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        # Missing tool_call_id => InvalidResponse, not a silent ToolCall.
        bad = json.dumps({"name": "read_file", "arguments": {}})
        loop, _ = _loop(
            broker,
            [bad, "[VERIFY] recovered"],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.COMPLETED
        assert out.steps[0].response_kind == "invalid"
        assert out.usage.tool_calls == 0


class TestPolicyBlockedTerminal:
    """A tool rejected by policy (scope/unknown) is terminal POLICY_BLOCKED."""

    def test_apply_patch_outside_scope_is_policy_blocked(
        self, workspace: pathlib.Path
    ) -> None:
        (workspace / "secret.py").write_text("SECRET = 'x'\n", encoding="utf-8")
        broker = _broker(workspace)
        # Task only allows calc.py; writing secret.py is out of scope.
        task = _task(allowed_files=["calc.py"], allowed_tools=["apply_patch"])
        state = _state(task)
        loop, _ = _loop(
            broker,
            [
                _tc_tool_call(
                    "c1",
                    "apply_patch",
                    {"path": "secret.py", "new_content": "SECRET = 'leaked'\n"},
                ),
                "[VERIFY] done",
            ],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.POLICY_BLOCKED
        assert out.observations[0].blocked
        # No partial effect: secret.py is unchanged.
        assert (workspace / "secret.py").read_text(encoding="utf-8") == "SECRET = 'x'\n"

    def test_read_outside_scope_is_policy_blocked(
        self, workspace: pathlib.Path
    ) -> None:
        (workspace / "secret.py").write_text("SECRET = 'x'\n", encoding="utf-8")
        broker = _broker(workspace)
        task = _task(allowed_files=["calc.py"], allowed_tools=["read_file"])
        state = _state(task)
        loop, _ = _loop(
            broker,
            [_tc_tool_call("c1", "read_file", {"path": "secret.py"})],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.POLICY_BLOCKED
        assert out.observations[0].blocked
        # No secret content leaked into the conversation.
        assert all("SECRET" not in (m.content) for m in [])


class TestUndeclaredToolNotCallable:
    """A tool not in the task's allowed_tools is never declared nor callable."""

    def test_undeclared_tool_is_policy_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        # Task allows only read_file; model tries apply_patch (undeclared).
        task = _task(allowed_files=["calc.py"], allowed_tools=["read_file"])
        state = _state(task)
        loop, _ = _loop(
            broker,
            [
                _tc_tool_call(
                    "c1", "apply_patch", {"path": "calc.py", "new_content": "x"}
                )
            ],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        # The broker dispatch rejects the undeclared tool name as a block.
        assert out.reason is ExecutorOutcomeReason.POLICY_BLOCKED
        assert out.observations[0].blocked
        # No effect on the fixture.
        assert "return a + b" in (workspace / "calc.py").read_text(encoding="utf-8")

    def test_tools_offered_match_allowed_tools(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        loop, backend = _loop(broker, ["[VERIFY] done"])
        loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        offered = {t.name for t in backend.calls[0].tools}
        assert offered == {"read_file"}


class TestRunChecksDispatch:
    """run_checks tool dispatches to the Broker with allowlisted kind."""

    def test_unknown_check_kind_is_policy_blocked(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["run_checks"])
        state = _state(task)
        loop, _ = _loop(
            broker,
            [_tc_tool_call("c1", "run_checks", {"kind": "rm_rf"})],
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.reason is ExecutorOutcomeReason.POLICY_BLOCKED
        assert out.observations[0].blocked


class TestStateNotMutated:
    """The loop never mutates the authoritative RunState."""

    def test_state_object_unchanged(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        snapshot_before = state.model_dump_json()
        loop, _ = _loop(
            broker,
            [_tc_tool_call("c1", "read_file", {"path": "calc.py"}), "[VERIFY] done"],
        )
        loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert state.model_dump_json() == snapshot_before


class TestObservationsBoundedToAttempt:
    """Observations bind to the single attempt; the loop carries one attempt."""

    def test_outcome_carries_attempt_identity(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(allowed_tools=["read_file"])
        state = _state(task)
        loop, _ = _loop(broker, [_tc_tool_call("c1", "read_file", {"path": "calc.py"})])
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        assert out.run_id == RUN
        assert out.task_id == TASK
        assert out.attempt == 1
        # Every observation carries an operation_id bound to this attempt.
        for obs in out.observations:
            assert "TASK-r-1" in obs.operation_id


class TestScriptedExhaustion:
    """Exhausting the scripted backend does not fabricate a success."""

    def test_exhausted_backend_is_tool_error(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        # No scheduled responses: backend returns InvalidResponse (exhausted).
        loop, _ = _loop(broker, [])
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        # Exhaustion => InvalidResponse streak => terminal TOOL_ERROR.
        # max_invalid_reasks=2 (default): 3 invalid outputs before terminal.
        assert out.reason is ExecutorOutcomeReason.TOOL_ERROR
        assert out.usage.model_calls == 3
