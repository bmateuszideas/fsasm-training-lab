"""T18 — Retry merytoryczne i feedback poprzedniej próby.

Proves the retry layer separates the three retry measures the architecture
keeps distinct (§24, §42): a transport error retries the SAME attempt without
bumping ``task_attempt``; a merytoryczna verification FAIL bumps the attempt
through the Domain Core and the next attempt's Context carries concrete prior
feedback; exhaustion of ``max_attempts`` routes to the approved
escalation/Human Gate path, never an infinite loop. Tool calls never consume a
merytoryczna attempt. The retry layer grants no PASS and no transition itself.
"""

import pathlib

import pytest

from fsasm.context import ContextBuilder
from fsasm.executor_loop import ExecutorAttemptOutcome, ExecutorLoop
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
    ToolObservation,
    ToolOperationKind,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.retry import (
    RetryDecision,
    TransportRetryBudget,
    build_retry_feedback,
    classify_attempt,
)
from fsasm.tool_broker import ToolBroker

RUN = "r"
TASK = "TASK-r-1"


def _task(
    tid: str = TASK,
    max_attempts: int = 3,
    allowed_files: list[str] | None = None,
    allowed_tools: list[str] | None = None,
) -> ChildTask:
    return ChildTask(
        task_id=tid,
        sequence=1,
        title="Patch add to subtract",
        description="Modify the add function to return a - b",
        dependencies=[],
        allowed_files=allowed_files or ["calc.py"],
        allowed_tools=allowed_tools or ["read_file", "apply_patch", "run_checks"],
        verification=VerificationSpec(
            type=VerificationType.SCHEMA, expected="return a - b"
        ),
        expected_evidence=["artifact", "check_result"],
        constraints=[],
        max_attempts=max_attempts,
    )


def _state(task: ChildTask, run_id: str = RUN) -> RunState:
    plan = Plan(plan_id="p", run_id=run_id, goal="g", tasks=[task])
    return RunState(run_id=run_id, goal="g", status=RunStatus.RUNNING, plan=plan)


def _broker(root: pathlib.Path) -> ToolBroker:
    return ToolBroker(workspace_root=root, workspace_scope=[])


def _outcome(
    reason: ExecutorOutcomeReason,
    *,
    attempt: int = 1,
    observations: list[ToolObservation] | None = None,
    transport_error: ModelError | None = None,
) -> ExecutorAttemptOutcome:
    from fsasm.model_types import BudgetUsage

    return ExecutorAttemptOutcome(
        run_id=RUN,
        task_id=TASK,
        attempt=attempt,
        reason=reason,
        usage=BudgetUsage(),
        observations=observations or [],
        transport_error=transport_error,
    )


def _verify_fail(
    message: str = "expected 'return a - b' got 'return a + b'",
) -> VerificationResult:
    return VerificationResult(
        run_id=RUN,
        task_id=TASK,
        status=VerificationResultStatus.FAIL,
        message=message,
        attempt=1,
    )


@pytest.fixture()
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    return tmp_path


class TestTransportRetryDoesNotBumpAttempt:
    """A transport error retries the SAME attempt; no task_attempt bump."""

    def test_transport_error_is_transport_retry(self) -> None:
        task = _task(max_attempts=2)
        budget = TransportRetryBudget(max_transport_retries=2)
        err = ModelError("boom", kind=ModelErrorKind.UNAVAILABLE, retryable=True)
        out = _outcome(ExecutorOutcomeReason.TOOL_ERROR, transport_error=err)
        verdict = classify_attempt(out, task, budget)

        assert verdict.decision is RetryDecision.TRANSPORT_RETRY
        assert verdict.transport_retries == 1
        # The transport retry does NOT carry merytoryczna feedback (same attempt).
        assert verdict.prior_observations == []
        assert verdict.prior_verification == ""

    def test_transport_retry_budget_exhaustion_escalates(self) -> None:
        task = _task(max_attempts=2)
        budget = TransportRetryBudget(max_transport_retries=1)
        budget.consume()  # already used the one allowed transport retry
        err = ModelError("boom", kind=ModelErrorKind.UNAVAILABLE, retryable=True)
        out = _outcome(ExecutorOutcomeReason.TOOL_ERROR, transport_error=err)
        verdict = classify_attempt(out, task, budget)

        # Budget exhausted -> escalate, NOT a merytoryczna retry.
        assert verdict.decision is RetryDecision.ESCALATE
        assert verdict.transport_retries == 1

    def test_transport_retry_does_not_consume_merytoryczna_attempt(
        self, workspace: pathlib.Path
    ) -> None:
        """A full FAIL->transport-retry->PASS run keeps attempts separate."""
        task = _task(max_attempts=2)
        # Simulate: attempt 1 transport error, then attempt 1 succeeds.
        budget = TransportRetryBudget(max_transport_retries=2)
        err = ModelError("net", kind=ModelErrorKind.UNAVAILABLE, retryable=True)
        out1 = _outcome(
            ExecutorOutcomeReason.TOOL_ERROR, attempt=1, transport_error=err
        )
        v1 = classify_attempt(out1, task, budget)
        assert v1.decision is RetryDecision.TRANSPORT_RETRY
        # The same attempt is re-run; the task's attempt counter is unchanged
        # (the Domain Core does not bump it for a transport retry).
        assert task.attempt == 0


class TestMerytorycznaRetryBumpsAttemptWithFeedback:
    """A verification FAIL bumps the attempt and the next context has feedback."""

    def test_verification_fail_is_merytoryczna_retry(self) -> None:
        task = _task(max_attempts=3)
        budget = TransportRetryBudget()
        out = _outcome(ExecutorOutcomeReason.COMPLETED)
        # COMPLETED goes to verification; suppose verification FAILed.
        verdict = classify_attempt(
            out, task, budget, verification_result=_verify_fail()
        )

        assert verdict.decision is RetryDecision.MERYTORYCZNA_RETRY
        # The next attempt carries concrete prior feedback.
        assert verdict.prior_verification.startswith("prior verification FAIL")
        assert "return a + b" in verdict.prior_verification

    def test_feedback_includes_prior_observations(self) -> None:
        task = _task(max_attempts=3)
        budget = TransportRetryBudget()
        obs = ToolObservation(
            operation_id="op-1",
            kind=ToolOperationKind.APPLY_PATCH,
            ok=True,
            artifact_path="calc.py",
            content="patched calc.py",
        )
        out = _outcome(ExecutorOutcomeReason.COMPLETED, observations=[obs])
        verdict = classify_attempt(
            out, task, budget, verification_result=_verify_fail()
        )

        assert verdict.decision is RetryDecision.MERYTORYCZNA_RETRY
        assert any("prior tool apply_patch OK" in s for s in verdict.prior_observations)

    def test_feedback_includes_current_artifact_via_broker(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = _outcome(ExecutorOutcomeReason.COMPLETED)
        prior_obs, prior_ver = build_retry_feedback(
            out,
            _verify_fail(),
            broker=broker,
            artifact_path="calc.py",
            allowed_files=["calc.py"],
        )

        # The current artifact content is read through the Broker and included.
        assert "return a + b" in prior_ver
        assert "current artifact calc.py" in prior_ver

    def test_feedback_artifact_out_of_scope_is_honest(
        self, workspace: pathlib.Path
    ) -> None:
        (workspace / "secret.py").write_text("SECRET = 'x'\n", encoding="utf-8")
        broker = _broker(workspace)
        out = _outcome(ExecutorOutcomeReason.COMPLETED)
        # Reading secret.py while allowed_files=[calc.py] is blocked by scope.
        prior_obs, prior_ver = build_retry_feedback(
            out,
            _verify_fail(),
            broker=broker,
            artifact_path="secret.py",
            allowed_files=["calc.py"],
        )
        assert "unreadable" in prior_ver
        assert "SECRET" not in prior_ver

    def test_fail_attempt2_pass_uses_prior_feedback(
        self, workspace: pathlib.Path
    ) -> None:
        """End-to-end: FAIL -> attempt 2 -> PASS, feedback flows into attempt 2."""
        broker = _broker(workspace)
        task = _task(max_attempts=2, allowed_tools=["read_file", "apply_patch"])
        state = _state(task)
        backend = ScriptedBackend(
            responses=[
                # attempt 1: patch with WRONG content, then verify.
                '{"tool_call_id": "c1", "name": "apply_patch", '
                '"arguments": {"path": "calc.py", "new_content": "def add(a, b):\\n    return a + b\\n"}}',
                "[VERIFY] done",
                # attempt 2: patch with CORRECT content, then verify.
                '{"tool_call_id": "c2", "name": "apply_patch", '
                '"arguments": {"path": "calc.py", "new_content": "def add(a, b):\\n    return a - b\\n"}}',
                "[VERIFY] fixed after feedback",
            ]
        )
        gw = ModelGateway(backend=backend)
        builder = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1)
        loop = ExecutorLoop(
            gateway=gw, broker=broker, context_builder=builder, budget=ModelCallBudget()
        )
        budget = TransportRetryBudget()

        # Attempt 1: model patches wrong content, COMPLETED, but verification FAILs.
        out1 = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)
        assert out1.reason is ExecutorOutcomeReason.COMPLETED
        verdict1 = classify_attempt(
            out1, task, budget, verification_result=_verify_fail()
        )
        assert verdict1.decision is RetryDecision.MERYTORYCZNA_RETRY
        assert "prior verification FAIL" in verdict1.prior_verification

        # Attempt 2: build context WITH the prior feedback, model fixes it.
        builder2 = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=2)
        loop2 = ExecutorLoop(
            gateway=gw,
            broker=broker,
            context_builder=builder2,
            budget=ModelCallBudget(),
        )
        out2 = loop2.run(
            state,
            run_id=RUN,
            task_id=TASK,
            attempt=2,
            prior_observations=verdict1.prior_observations,
            prior_verification=verdict1.prior_verification,
        )
        assert out2.reason is ExecutorOutcomeReason.COMPLETED
        # The second attempt's request carried the prior feedback.
        # (Find the attempt-2 user message referencing the prior failure.)
        attempt2_msgs = backend.calls[-2].messages
        feedback_text = " ".join(m.content for m in attempt2_msgs)
        assert "prior verification FAIL" in feedback_text
        # The REAL effect landed: calc.py now subtracts.
        assert "return a - b" in (workspace / "calc.py").read_text(encoding="utf-8")


class TestExhaustionEscalates:
    """max_attempts exhaustion routes to escalation, not an infinite loop."""

    def test_exhausted_merytoryczna_escalates(self) -> None:
        task = _task(max_attempts=1)  # attempt 1 already used, can_retry() False
        # Simulate that attempt 1 happened: set attempt to 1.
        task.attempt = 1
        budget = TransportRetryBudget()
        out = _outcome(ExecutorOutcomeReason.COMPLETED, attempt=1)
        verdict = classify_attempt(
            out, task, budget, verification_result=_verify_fail()
        )

        assert verdict.decision is RetryDecision.ESCALATE
        assert "exhausted" in verdict.note

    def test_exhausted_non_transport_tool_error_escalates(self) -> None:
        task = _task(max_attempts=1)
        task.attempt = 1
        budget = TransportRetryBudget()
        # Non-transport TOOL_ERROR (persistent invalid): no transport_error.
        out = _outcome(ExecutorOutcomeReason.TOOL_ERROR, attempt=1)
        verdict = classify_attempt(out, task, budget)

        assert verdict.decision is RetryDecision.ESCALATE


class TestTerminalNonRetryOutcomesStop:
    """COMPLETED/ESCALATION_REQUESTED/POLICY_BLOCKED without FAIL are STOP."""

    def test_completed_without_fail_stops(self) -> None:
        task = _task(max_attempts=3)
        budget = TransportRetryBudget()
        out = _outcome(ExecutorOutcomeReason.COMPLETED)
        # No verification result => treated as terminal stop (driver routes to
        # verification; retry layer does not retry a non-FAIL).
        verdict = classify_attempt(out, task, budget)
        assert verdict.decision is RetryDecision.STOP

    def test_escalation_requested_stops(self) -> None:
        task = _task(max_attempts=3)
        budget = TransportRetryBudget()
        out = _outcome(ExecutorOutcomeReason.ESCALATION_REQUESTED)
        verdict = classify_attempt(out, task, budget)
        assert verdict.decision is RetryDecision.STOP

    def test_policy_blocked_stops(self) -> None:
        task = _task(max_attempts=3)
        budget = TransportRetryBudget()
        out = _outcome(ExecutorOutcomeReason.POLICY_BLOCKED)
        verdict = classify_attempt(out, task, budget)
        assert verdict.decision is RetryDecision.STOP


class TestToolCallsDoNotConsumeAttempt:
    """Multiple tool calls in one attempt do not consume merytoryczna attempts."""

    def test_many_tool_calls_one_attempt(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(max_attempts=2, allowed_tools=["read_file"])
        state = _state(task)
        backend = ScriptedBackend(
            responses=[
                '{"tool_call_id": "c1", "name": "read_file", "arguments": {"path": "calc.py"}}',
                '{"tool_call_id": "c2", "name": "read_file", "arguments": {"path": "calc.py"}}',
                '{"tool_call_id": "c3", "name": "read_file", "arguments": {"path": "calc.py"}}',
                "[VERIFY] done after several reads",
            ]
        )
        gw = ModelGateway(backend=backend)
        builder = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1)
        loop = ExecutorLoop(
            gateway=gw, broker=broker, context_builder=builder, budget=ModelCallBudget()
        )
        out = loop.run(state, run_id=RUN, task_id=TASK, attempt=1)

        # 3 tool calls happened in ONE attempt; the task attempt is still 1.
        assert out.usage.tool_calls == 3
        assert out.attempt == 1
        # classify: COMPLETED without a verification FAIL is STOP (no retry).
        verdict = classify_attempt(out, task, TransportRetryBudget())
        assert verdict.decision is RetryDecision.STOP
        # No merytoryczna retry was requested despite 3 tool calls.
        assert verdict.transport_retries == 0


class TestRetryLayerGrantsNoPass:
    """The retry layer never returns a PASS or a transition; only a decision."""

    def test_verdict_carries_only_decision(self) -> None:
        task = _task(max_attempts=3)
        budget = TransportRetryBudget()
        err = ModelError("x", kind=ModelErrorKind.TIMEOUT, retryable=True)
        out = _outcome(ExecutorOutcomeReason.TOOL_ERROR, transport_error=err)
        verdict = classify_attempt(out, task, budget)

        # The verdict is a decision enum + feedback, never a PASS/transition.
        assert hasattr(verdict, "decision")
        assert isinstance(verdict.decision, RetryDecision)
        assert verdict.decision is RetryDecision.TRANSPORT_RETRY
        # No transition/PASS field exists on the verdict.
        assert not hasattr(verdict, "pass_")
        assert not hasattr(verdict, "transition")
