"""T25 — consistent trajectory integrity over existing IDs.

Architecture §35 defines the target trajectory:
``task → context → model response → tool call → observation → verification →
evidence → accepted result``. T25 composes the existing identifiers the
runtime already produces into a correlatable, append-only trajectory. The
trajectory is an **audit projection only**: it never grants PASS and never
substitutes for the authoritative snapshot. Losing the auxiliary trajectory
log must not change the accepted state.
"""

from __future__ import annotations

from fsasm.models import (
    EvidenceRecord,
    ToolObservation,
    ToolOperationKind,
    VerificationResult,
    VerificationResultStatus,
)
from fsasm.model_types import (
    BudgetUsage,
    EscalationRequest,
    FinalResponse,
    ModelResult,
    ModelUsage,
    ToolCall,
)
from fsasm.trajectory import (
    Trajectory,
    TrajectoryEvent,
    TrajectoryEventKind,
    escalation_event,
    evidence_event,
    from_budget_usage,
    model_call_event,
    observation_event,
    state_transition_event,
    task_context_event,
    tool_call_event,
    verification_event,
)


def _model_result(
    *,
    response_kind: str = "FinalResponse",
    usage: ModelUsage | None = None,
    backend: str = "scripted",
    step: int = 1,
) -> ModelResult:
    response: object
    if response_kind == "FinalResponse":
        response = FinalResponse(content="done")
    elif response_kind == "ToolCall":
        response = ToolCall(tool_call_id="tc-1", name="read_file", arguments={})
    else:
        response = FinalResponse(content="x")
    return ModelResult(
        run_id="RUN-1",
        task_id="TASK-001",
        attempt=1,
        step=step,
        response=response,
        usage=usage or ModelUsage(),
        backend=backend,
    )


def _obs(operation_id: str = "op-1", duration: int | None = 10) -> ToolObservation:
    return ToolObservation(
        operation_id=operation_id,
        kind=ToolOperationKind.APPLY_PATCH,
        ok=True,
        duration_ms=duration,
    )


def _verification(
    status: VerificationResultStatus = VerificationResultStatus.PASS,
    evidence_refs: list[str] | None = None,
) -> VerificationResult:
    return VerificationResult(
        run_id="RUN-1",
        task_id="TASK-001",
        status=status,
        attempt=1,
        operation_id="op-1",
        artifact_id="art-1",
        evidence_refs=evidence_refs or ["ev-1"],
        message="ok",
    )


def _evidence(evidence_id: str = "ev-1") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        run_id="RUN-1",
        task_id="TASK-001",
        kind="test_result",
        source="pytest",
        payload="ok",
        attempt=1,
        operation_id="op-1",
        artifact_id="art-1",
        check_identity="pytest",
    )


class TestTrajectoryAppendOnly:
    def test_append_adds_event(self):
        traj = Trajectory(run_id="RUN-1")
        ev = task_context_event("RUN-1", "TASK-001", 1, 500)
        traj.append(ev)
        assert len(traj.events) == 1
        assert traj.events[0] is ev

    def test_append_preserves_order(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(task_context_event("RUN-1", "TASK-001", 1, 100))
        traj.append(model_call_event(_model_result()))
        assert traj.events[0].kind == TrajectoryEventKind.TASK_CONTEXT
        assert traj.events[1].kind == TrajectoryEventKind.MODEL_CALL


class TestCorrelationKey:
    def test_same_attempt_events_share_key(self):
        ev1 = task_context_event("RUN-1", "TASK-001", 1, 100)
        ev2 = model_call_event(_model_result())
        assert ev1.correlation_key() == ev2.correlation_key()

    def test_different_attempt_events_differ(self):
        ev1 = task_context_event("RUN-1", "TASK-001", 1, 100)
        ev3 = task_context_event("RUN-1", "TASK-001", 2, 100)
        assert ev1.correlation_key() != ev3.correlation_key()


class TestForAttempt:
    def test_filters_to_one_attempt(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(task_context_event("RUN-1", "TASK-001", 1, 100))
        traj.append(task_context_event("RUN-1", "TASK-001", 2, 100))
        traj.append(task_context_event("RUN-1", "TASK-002", 1, 100))
        a1 = traj.for_attempt("TASK-001", 1)
        assert len(a1) == 1
        assert a1[0].attempt == 1


class TestCounters:
    def test_counts_by_kind(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(task_context_event("RUN-1", "TASK-001", 1, 100))
        traj.append(model_call_event(_model_result()))
        traj.append(model_call_event(_model_result(step=2)))
        traj.append(tool_call_event("RUN-1", "TASK-001", 1, 1, "op-1", "read_file"))
        traj.append(observation_event("RUN-1", "TASK-001", 1, 1, _obs()))
        assert traj.model_calls() == 2
        assert traj.tool_calls() == 1
        assert traj.observations() == 1


class TestBackendsRecordedOnlyWhenAvailable:
    def test_backend_recorded_when_present(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(model_call_event(_model_result(backend="scripted")))
        traj.append(model_call_event(_model_result(backend="local", step=2)))
        assert traj.backends() == ["scripted", "local"]

    def test_empty_backend_not_recorded(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(model_call_event(_model_result(backend="")))
        assert traj.backends() == []

    def test_duplicate_backend_recorded_once(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(model_call_event(_model_result(backend="local")))
        traj.append(model_call_event(_model_result(backend="local", step=2)))
        assert traj.backends() == ["local"]


class TestUsageTotalOnlyWhenReported:
    def test_aggregates_reported_usage(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(
            model_call_event(
                _model_result(usage=ModelUsage(prompt_tokens=100, completion_tokens=50))
            )
        )
        traj.append(
            model_call_event(
                _model_result(
                    usage=ModelUsage(prompt_tokens=20, completion_tokens=5), step=2
                )
            )
        )
        total = traj.usage_total()
        assert total.prompt_tokens == 120
        assert total.completion_tokens == 55

    def test_absent_fields_stay_none(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(model_call_event(_model_result(usage=ModelUsage())))
        total = traj.usage_total()
        assert total.prompt_tokens is None
        assert total.completion_tokens is None
        assert total.cost is None

    def test_cost_aggregated(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(model_call_event(_model_result(usage=ModelUsage(cost=0.1))))
        traj.append(model_call_event(_model_result(usage=ModelUsage(cost=0.2), step=2)))
        assert abs(traj.usage_total().cost - 0.3) < 1e-9

    def test_no_model_calls_gives_all_none(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(task_context_event("RUN-1", "TASK-001", 1, 100))
        total = traj.usage_total()
        assert total.prompt_tokens is None


class TestBuilderIdentityBinding:
    def test_task_context_event(self):
        ev = task_context_event("RUN-1", "TASK-001", 1, 750)
        assert ev.run_id == "RUN-1"
        assert ev.task_id == "TASK-001"
        assert ev.attempt == 1
        assert ev.kind == TrajectoryEventKind.TASK_CONTEXT
        assert ev.payload["context_chars"] == 750

    def test_model_call_event_binds_result(self):
        result = _model_result(usage=ModelUsage(prompt_tokens=10))
        ev = model_call_event(result)
        assert ev.run_id == "RUN-1"
        assert ev.task_id == "TASK-001"
        assert ev.attempt == 1
        assert ev.step == 1
        assert ev.backend == "scripted"
        assert ev.usage is not None
        assert ev.usage.prompt_tokens == 10
        assert ev.payload["response_kind"] == "FinalResponse"

    def test_model_call_no_usage_recorded_as_none(self):
        result = _model_result(usage=ModelUsage())
        ev = model_call_event(result)
        assert ev.usage is None

    def test_tool_call_event_binds_operation(self):
        ev = tool_call_event("RUN-1", "TASK-001", 1, 1, "op-7", "apply_patch")
        assert ev.operation_id == "op-7"
        assert ev.payload["tool_name"] == "apply_patch"
        assert ev.kind == TrajectoryEventKind.TOOL_CALL

    def test_observation_event_binds_operation_and_timing(self):
        ev = observation_event(
            "RUN-1", "TASK-001", 1, 1, _obs(operation_id="op-9", duration=42)
        )
        assert ev.operation_id == "op-9"
        assert ev.duration_ms == 42
        assert ev.kind == TrajectoryEventKind.OBSERVATION

    def test_verification_event_binds_artifact_and_refs(self):
        ev = verification_event("RUN-1", "TASK-001", 1, _verification())
        assert ev.artifact_id == "art-1"
        assert ev.payload["status"] == "PASS"
        assert ev.payload["evidence_refs"] == ["ev-1"]

    def test_evidence_event_binds_full_identity(self):
        ev = evidence_event("RUN-1", _evidence("ev-2"))
        assert ev.evidence_id == "ev-2"
        assert ev.artifact_id == "art-1"
        assert ev.operation_id == "op-1"
        assert ev.payload["kind"] == "test_result"

    def test_state_transition_event_records_decision(self):
        ev = state_transition_event(
            "RUN-1", "TASK-001", 1, "TaskVerificationPassed", passed=True
        )
        assert ev.kind == TrajectoryEventKind.STATE_TRANSITION
        assert ev.payload["event"] == "TaskVerificationPassed"
        assert ev.payload["passed"] is True

    def test_escalation_event_records_kind(self):
        esc = EscalationRequest(kind="consultation", reason="stuck", target="API_A")
        ev = escalation_event("RUN-1", "TASK-001", 1, esc)
        assert ev.kind == TrajectoryEventKind.ESCALATION
        assert ev.payload["kind"] == "consultation"
        assert ev.payload["target"] == "API_A"


class TestTrajectoryIsNotPassAuthority:
    def test_report_has_no_pass_field(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(task_context_event("RUN-1", "TASK-001", 1, 100))
        traj.append(state_transition_event("RUN-1", "TASK-001", 1, "X", passed=True))
        report = traj.to_report()
        assert "passed" not in report
        assert "PASS" not in report
        for ev in report["events"]:
            assert "payload" not in ev
            assert "passed" not in ev

    def test_report_counts_and_ids_present(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(model_call_event(_model_result()))
        report = traj.to_report()
        assert report["run_id"] == "RUN-1"
        assert report["model_calls"] == 1
        assert report["event_count"] == 1
        assert report["events"][0]["kind"] == "model_call"
        assert report["events"][0]["backend"] == "scripted"

    def test_trajectory_does_not_hold_state(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(state_transition_event("RUN-1", "TASK-001", 1, "RunFailed"))
        ev: TrajectoryEvent | None = None
        ev = traj.events[0]
        assert ev.payload["event"] == "RunFailed"
        assert "status" not in ev.payload


class TestFullSequenceCorrelatable:
    def test_full_attempt_sequence_correlates(self):
        traj = Trajectory(run_id="RUN-1")
        traj.append(task_context_event("RUN-1", "TASK-001", 1, 800))
        traj.append(model_call_event(_model_result(usage=ModelUsage(prompt_tokens=10))))
        traj.append(tool_call_event("RUN-1", "TASK-001", 1, 1, "op-1", "apply_patch"))
        traj.append(
            observation_event("RUN-1", "TASK-001", 1, 1, _obs("op-1", duration=5))
        )
        traj.append(verification_event("RUN-1", "TASK-001", 1, _verification()))
        traj.append(evidence_event("RUN-1", _evidence()))
        traj.append(
            state_transition_event(
                "RUN-1", "TASK-001", 1, "TaskVerificationPassed", passed=True
            )
        )
        a1 = traj.for_attempt("TASK-001", 1)
        assert len(a1) == 7
        kinds = [e.kind for e in a1]
        assert kinds == [
            TrajectoryEventKind.TASK_CONTEXT,
            TrajectoryEventKind.MODEL_CALL,
            TrajectoryEventKind.TOOL_CALL,
            TrajectoryEventKind.OBSERVATION,
            TrajectoryEventKind.VERIFICATION,
            TrajectoryEventKind.EVIDENCE,
            TrajectoryEventKind.STATE_TRANSITION,
        ]
        # All share one attempt identity.
        assert all(e.run_id == "RUN-1" for e in a1)
        assert all(e.task_id == "TASK-001" for e in a1)
        assert all(e.attempt == 1 for e in a1)
        # tool/observation share operation_id.
        assert a1[2].operation_id == a1[3].operation_id == "op-1"


class TestFromBudgetUsage:
    def test_projects_tokens_when_present(self):
        usage = BudgetUsage(tokens=250, cost=0.4, elapsed_ms=1200)
        out = from_budget_usage(usage)
        assert out is not None
        assert out.total_tokens == 250
        assert out.cost == 0.4
        assert out.duration_ms == 1200
        assert out.prompt_tokens is None

    def test_none_when_no_usage(self):
        usage = BudgetUsage()
        assert from_budget_usage(usage) is None
