"""T23 — Reconcile of partial and uncertain effects.

Proves the recovery/reconcile layer (canonical TODO T23; architecture §15) is
deterministic and safe across all four checkpoints:

- ``BEFORE_EFFECT`` — no effect applied -> RETRY (transport error is NOT a
  merytoryczny FAIL).
- ``EFFECT_APPLIED`` — real artifact present -> VERIFY; artifact absent -> RETRY.
- ``EVIDENCE_PERSISTED`` — real effect + evidence -> VERIFY; effect absent or
  no evidence refs -> RETRY (never fabricate evidence/PASS).
- ``COMMITTED`` — snapshot already owns the outcome (PASS/FAIL/escalate/gate/
  terminal run) -> STOP.

Fault injection at each checkpoint does NOT give a false PASS, does NOT blindly
re-apply a patch or a consent, and leads to exactly one unambiguous safe state.
The reconcile layer is NOT a second authoritative event store: the snapshot +
the real artifact on disk are the only sources of truth; the reconcile decision
is diagnostic (the driver acts on it; only the Domain Core grants transitions).
Transport error is never an automatic merytoryczny FAIL.
"""

import pytest

from fsasm.models import (
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
    artifact_id_for,
    operation_id_for,
)
from fsasm.recovery import (
    OperationBinding,
    ReconcileDecision,
    RecoveryCheckpoint,
    inspect_artifact,
    reconcile_attempt,
)

RUN = "r"
TASK = "TASK-1"
ARTIFACT_PATH = "artifact_TASK-1.py"


def _task(max_attempts: int = 3) -> ChildTask:
    return ChildTask(
        task_id=TASK,
        sequence=1,
        title="Title",
        description="Desc",
        dependencies=[],
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
        max_attempts=max_attempts,
    )


def _plan(run_id: str = RUN) -> Plan:
    return Plan(plan_id=f"plan-{run_id}", run_id=run_id, goal="g", tasks=[_task()])


def _running_state(
    run_id: str = RUN,
    attempt: int = 1,
    status: RunStatus = RunStatus.RUNNING,
    task_status: TaskStatus = TaskStatus.RUNNING,
) -> RunState:
    """A state with TASK-1 RUNNING at the given attempt."""
    plan = _plan(run_id)
    state = RunState(run_id=run_id, goal="g", status=status, plan=plan)
    state.plan.tasks[0].status = task_status
    state.plan.tasks[0].attempt = attempt
    state.active_task_id = TASK
    return state


def _binding(
    checkpoint: RecoveryCheckpoint,
    run_id: str = RUN,
    task_id: str = TASK,
    attempt: int = 1,
    evidence_refs: list[str] | None = None,
    transport_error: bool = False,
) -> OperationBinding:
    return OperationBinding(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        operation_id=operation_id_for(run_id, task_id, attempt, 1),
        artifact_id=artifact_id_for(run_id, task_id, attempt),
        artifact_path=ARTIFACT_PATH,
        checkpoint=checkpoint,
        evidence_refs=evidence_refs if evidence_refs is not None else [],
        transport_error=transport_error,
    )


ARTIFACT_CONTENT = "def f():\n    return 42\n"


class TestCheckpointsBeforeEffect:
    """Checkpoint BEFORE_EFFECT: no effect applied."""

    def test_no_effect_retry(self) -> None:
        s = _running_state()
        report = reconcile_attempt(s, _binding(RecoveryCheckpoint.BEFORE_EFFECT), None)
        assert report.decision is ReconcileDecision.RETRY
        assert "no effect" in report.reason

    def test_transport_error_is_not_merytoryczny_fail(self) -> None:
        s = _running_state()
        report = reconcile_attempt(
            s, _binding(RecoveryCheckpoint.BEFORE_EFFECT, transport_error=True), None
        )
        assert report.decision is ReconcileDecision.RETRY
        assert "transport" in report.reason
        assert "not a merytoryczny FAIL" in report.reason

    def test_artifact_present_still_retry_before_effect(self) -> None:
        # Even if an artifact somehow exists, BEFORE_EFFECT means the runtime
        # never recorded applying it for this attempt -> RETRY (do not trust a
        # stale/unowned artifact).
        s = _running_state()
        report = reconcile_attempt(
            s, _binding(RecoveryCheckpoint.BEFORE_EFFECT), ARTIFACT_CONTENT
        )
        assert report.decision is ReconcileDecision.RETRY


class TestCheckpointEffectApplied:
    """Checkpoint EFFECT_APPLIED: patch landed, no evidence/commit."""

    def test_real_artifact_present_verify(self) -> None:
        s = _running_state()
        report = reconcile_attempt(
            s, _binding(RecoveryCheckpoint.EFFECT_APPLIED), ARTIFACT_CONTENT
        )
        assert report.decision is ReconcileDecision.VERIFY
        assert report.observed_artifact == ARTIFACT_CONTENT
        assert "real effect present" in report.reason

    def test_artifact_absent_retry(self) -> None:
        # EFFECT_APPLIED checkpoint but the artifact is gone (e.g. an external
        # cleanup) -> the effect never actually landed -> RETRY.
        s = _running_state()
        report = reconcile_attempt(s, _binding(RecoveryCheckpoint.EFFECT_APPLIED), None)
        assert report.decision is ReconcileDecision.RETRY
        assert "effect never landed" in report.reason

    def test_empty_artifact_treated_as_absent(self) -> None:
        s = _running_state()
        report = reconcile_attempt(s, _binding(RecoveryCheckpoint.EFFECT_APPLIED), "")
        assert report.decision is ReconcileDecision.RETRY


class TestCheckpointEvidencePersisted:
    """Checkpoint EVIDENCE_PERSISTED: evidence on disk, no commit."""

    def test_real_effect_and_evidence_verify(self) -> None:
        s = _running_state()
        report = reconcile_attempt(
            s,
            _binding(
                RecoveryCheckpoint.EVIDENCE_PERSISTED,
                evidence_refs=["evidence-r-TASK-1-attempt-1-pass"],
            ),
            ARTIFACT_CONTENT,
        )
        assert report.decision is ReconcileDecision.VERIFY
        assert "evidence" in report.reason

    def test_effect_absent_despite_checkpoint_retry(self) -> None:
        # Stale/inconsistent binding: checkpoint says evidence persisted but the
        # artifact is absent -> RETRY (do not fabricate PASS from a checkpoint
        # marker alone).
        s = _running_state()
        report = reconcile_attempt(
            s,
            _binding(
                RecoveryCheckpoint.EVIDENCE_PERSISTED,
                evidence_refs=["evidence-r-TASK-1-attempt-1-pass"],
            ),
            None,
        )
        assert report.decision is ReconcileDecision.RETRY
        assert "stale/inconsistent" in report.reason

    def test_evidence_refs_empty_retry(self) -> None:
        # Checkpoint says evidence persisted but no refs bound -> RETRY (do not
        # fabricate evidence).
        s = _running_state()
        report = reconcile_attempt(
            s,
            _binding(RecoveryCheckpoint.EVIDENCE_PERSISTED, evidence_refs=[]),
            ARTIFACT_CONTENT,
        )
        assert report.decision is ReconcileDecision.RETRY
        assert "no evidence refs" in report.reason


class TestCheckpointCommitted:
    """Checkpoint COMMITTED: snapshot committed; response outstanding.

    When the snapshot already owns the outcome, the reconcile decision is
    STOP — the driver must not replay a stale effect or a stale consent.
    """

    def test_task_passed_stop(self) -> None:
        s = _running_state(task_status=TaskStatus.PASSED)
        report = reconcile_attempt(
            s,
            _binding(
                RecoveryCheckpoint.COMMITTED,
                evidence_refs=["evidence-r-TASK-1-attempt-1-pass"],
            ),
            ARTIFACT_CONTENT,
        )
        assert report.decision is ReconcileDecision.STOP
        assert "snapshot owns task outcome" in report.reason

    def test_task_failed_stop(self) -> None:
        s = _running_state(task_status=TaskStatus.FAILED)
        report = reconcile_attempt(
            s, _binding(RecoveryCheckpoint.COMMITTED), ARTIFACT_CONTENT
        )
        assert report.decision is ReconcileDecision.STOP

    def test_task_needs_human_stop(self) -> None:
        s = _running_state(task_status=TaskStatus.NEEDS_HUMAN)
        report = reconcile_attempt(
            s, _binding(RecoveryCheckpoint.COMMITTED), ARTIFACT_CONTENT
        )
        assert report.decision is ReconcileDecision.STOP

    def test_task_retried_to_new_attempt_stop(self) -> None:
        # The snapshot advanced to attempt 2 (a retry); a stale binding for
        # attempt 1 must STOP, not replay the old effect.
        s = _running_state(attempt=2)
        report = reconcile_attempt(
            s,
            _binding(
                RecoveryCheckpoint.COMMITTED,
                attempt=1,
                evidence_refs=["evidence-r-TASK-1-attempt-1-pass"],
            ),
            ARTIFACT_CONTENT,
        )
        assert report.decision is ReconcileDecision.STOP
        assert "attempt" in report.reason

    def test_run_terminal_passed_stop(self) -> None:
        s = _running_state(status=RunStatus.PASSED, task_status=TaskStatus.PASSED)
        report = reconcile_attempt(
            s,
            _binding(
                RecoveryCheckpoint.COMMITTED,
                evidence_refs=["evidence-r-TASK-1-attempt-1-pass"],
            ),
            ARTIFACT_CONTENT,
        )
        assert report.decision is ReconcileDecision.STOP
        assert "run is terminal" in report.reason

    def test_run_terminal_failed_stop(self) -> None:
        s = _running_state(status=RunStatus.FAILED, task_status=TaskStatus.FAILED)
        report = reconcile_attempt(
            s, _binding(RecoveryCheckpoint.COMMITTED), ARTIFACT_CONTENT
        )
        assert report.decision is ReconcileDecision.STOP
        assert "run is terminal" in report.reason


class TestForeignRunAndMissingTask:
    """Foreign run_id and missing task are STOP (snapshot owns truth)."""

    def test_foreign_run_id_stop(self) -> None:
        s = _running_state(run_id="r")
        report = reconcile_attempt(
            s, _binding(RecoveryCheckpoint.EFFECT_APPLIED, run_id="other"), None
        )
        assert report.decision is ReconcileDecision.STOP
        assert "foreign run" in report.reason

    def test_missing_task_stop(self) -> None:
        s = _running_state()
        report = reconcile_attempt(
            s,
            _binding(RecoveryCheckpoint.EFFECT_APPLIED, task_id="TASK-99"),
            None,
        )
        assert report.decision is ReconcileDecision.STOP
        assert "not in snapshot plan" in report.reason


class TestNoFalsePass:
    """Fault injection at any checkpoint never gives a false PASS.

    The reconcile layer never returns PASS — it only returns VERIFY/RETRY/STOP.
    The verifier (a separate plane) decides PASS; the Domain Core grants it.
    """

    @pytest.mark.parametrize(
        "checkpoint,artifact,refs",
        [
            (RecoveryCheckpoint.BEFORE_EFFECT, None, []),
            (RecoveryCheckpoint.BEFORE_EFFECT, ARTIFACT_CONTENT, []),
            (RecoveryCheckpoint.EFFECT_APPLIED, None, []),
            (RecoveryCheckpoint.EFFECT_APPLIED, ARTIFACT_CONTENT, []),
            (RecoveryCheckpoint.EVIDENCE_PERSISTED, None, ["e"]),
            (RecoveryCheckpoint.EVIDENCE_PERSISTED, ARTIFACT_CONTENT, []),
            (RecoveryCheckpoint.EVIDENCE_PERSISTED, ARTIFACT_CONTENT, ["e"]),
            (RecoveryCheckpoint.COMMITTED, None, []),
            (RecoveryCheckpoint.COMMITTED, ARTIFACT_CONTENT, ["e"]),
        ],
    )
    def test_never_returns_pass(
        self,
        checkpoint: RecoveryCheckpoint,
        artifact: str | None,
        refs: list[str],
    ) -> None:
        s = _running_state()
        report = reconcile_attempt(
            s, _binding(checkpoint, evidence_refs=refs), artifact
        )
        assert report.decision in (
            ReconcileDecision.VERIFY,
            ReconcileDecision.RETRY,
            ReconcileDecision.STOP,
        )


class TestNotSecondEventStore:
    """The binding ties operation to identity WITHOUT a second event store.

    The binding is provenance; the snapshot is the only authority. Two
    reconcile calls with the same inputs yield the same decision (determinism).
    """

    def test_determinism(self) -> None:
        s = _running_state()
        b = _binding(RecoveryCheckpoint.EFFECT_APPLIED)
        r1 = reconcile_attempt(s, b, ARTIFACT_CONTENT)
        r2 = reconcile_attempt(s, b, ARTIFACT_CONTENT)
        assert r1.decision is r2.decision
        assert r1.reason == r2.reason
        assert r1.observed_artifact == r2.observed_artifact

    def test_binding_carries_full_identity(self) -> None:
        b = _binding(
            RecoveryCheckpoint.EVIDENCE_PERSISTED,
            evidence_refs=["evidence-r-TASK-1-attempt-1-pass"],
        )
        assert b.run_id == RUN
        assert b.task_id == TASK
        assert b.attempt == 1
        assert b.operation_id.startswith("op-r-TASK-1-attempt-1-")
        assert b.artifact_id == "artifact-r-TASK-1-attempt-1"
        assert b.artifact_path == ARTIFACT_PATH
        assert b.evidence_refs == ["evidence-r-TASK-1-attempt-1-pass"]

    def test_state_not_mutated(self) -> None:
        import copy

        s = _running_state()
        snapshot = copy.deepcopy(s)
        b = _binding(RecoveryCheckpoint.EFFECT_APPLIED)
        reconcile_attempt(s, b, ARTIFACT_CONTENT)
        assert s == snapshot
        assert s.plan.tasks[0].status is TaskStatus.RUNNING
        assert s.plan.tasks[0].attempt == 1


class TestTransportErrorNotMerytorycznyFail:
    """A transport error is never an automatic merytoryczny FAIL.

    At BEFORE_EFFECT with a transport error the decision is RETRY (same
    attempt), not STOP/FAIL. The retry layer (T18) separately classifies
    transport vs merytoryczna retry.
    """

    def test_transport_error_retry_not_stop(self) -> None:
        s = _running_state()
        report = reconcile_attempt(
            s, _binding(RecoveryCheckpoint.BEFORE_EFFECT, transport_error=True), None
        )
        assert report.decision is ReconcileDecision.RETRY

    def test_transport_error_with_artifact_retry_not_verify(self) -> None:
        # Even if an artifact exists, BEFORE_EFFECT + transport error means the
        # runtime never owned the effect for this attempt -> RETRY.
        s = _running_state()
        report = reconcile_attempt(
            s,
            _binding(RecoveryCheckpoint.BEFORE_EFFECT, transport_error=True),
            ARTIFACT_CONTENT,
        )
        assert report.decision is ReconcileDecision.RETRY


class TestInspectArtifactRealBroker:
    """inspect_artifact reads the REAL on-disk artifact through the Broker.

    The reconcile layer never trusts a claim: it asks the Broker (scope-enforced)
    for the actual file bound to the attempt's artifact_path. Absent or
    out-of-scope artifacts return None (no fabricated content).
    """

    def test_inspect_reads_real_file(self, tmp_path) -> None:
        from fsasm.tool_broker import ToolBroker

        (tmp_path / ARTIFACT_PATH).write_text(ARTIFACT_CONTENT, encoding="utf-8")
        broker = ToolBroker(workspace_root=tmp_path)
        b = _binding(RecoveryCheckpoint.EFFECT_APPLIED)
        content = inspect_artifact(broker, b)
        assert content == ARTIFACT_CONTENT

    def test_inspect_absent_returns_none(self, tmp_path) -> None:
        from fsasm.tool_broker import ToolBroker

        broker = ToolBroker(workspace_root=tmp_path)
        b = _binding(RecoveryCheckpoint.EFFECT_APPLIED)
        assert inspect_artifact(broker, b) is None

    def test_inspect_out_of_scope_returns_none(self, tmp_path) -> None:
        from fsasm.tool_broker import ToolBroker

        (tmp_path / ARTIFACT_PATH).write_text(ARTIFACT_CONTENT, encoding="utf-8")
        broker = ToolBroker(workspace_root=tmp_path)
        b = _binding(RecoveryCheckpoint.EFFECT_APPLIED)
        # allowed_files excludes the artifact -> None (scope-enforced).
        assert inspect_artifact(broker, b, allowed_files=["other.py"]) is None

    def test_inspect_then_reconcile_verify(self, tmp_path) -> None:
        from fsasm.tool_broker import ToolBroker

        (tmp_path / ARTIFACT_PATH).write_text(ARTIFACT_CONTENT, encoding="utf-8")
        broker = ToolBroker(workspace_root=tmp_path)
        b = _binding(RecoveryCheckpoint.EFFECT_APPLIED)
        content = inspect_artifact(broker, b)
        s = _running_state()
        report = reconcile_attempt(s, b, content)
        assert report.decision is ReconcileDecision.VERIFY
        assert report.observed_artifact == ARTIFACT_CONTENT

    def test_inspect_absent_then_reconcile_retry(self, tmp_path) -> None:
        from fsasm.tool_broker import ToolBroker

        broker = ToolBroker(workspace_root=tmp_path)
        b = _binding(RecoveryCheckpoint.EFFECT_APPLIED)
        content = inspect_artifact(broker, b)
        s = _running_state()
        report = reconcile_attempt(s, b, content)
        assert report.decision is ReconcileDecision.RETRY
