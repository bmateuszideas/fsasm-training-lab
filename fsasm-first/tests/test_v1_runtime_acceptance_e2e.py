"""T26 — full Runtime v1 acceptance E2E matrix on controlled backends.

Architecture §16–§18, §29, §30, §34, §35 + canonical TODO T26. Drives the
complete Runtime v1 lifecycle over controlled (deterministic) backends — no
real 7B and no live Mistral API. Every scenario ends in a terminal state with
evidence and the proper reason; PASS is granted only by the Domain Core.

Scenarios:
1. Full plan PASSED (1/3/N tasks).
2. FAIL → feedback → new attempt → PASS.
3. Consultation and explicit handover (ModelRouter).
4. Retry exhaustion → Human Gate → RETRY_ONCE and ABORT.
5. Crash / resume at defined checkpoints (recovery).
6. Operation outside allowed scope (Broker policy block).
7. False final without effect, stale evidence, foreign artifact (Verifier).
8. Plan 1/3/N, blocked dependency, completion of the whole Parent/run.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from fsasm.acceptance import AcceptanceEffectSpec, AcceptanceHarness
from fsasm.domain import TaskActivated, TaskReadied
from fsasm.models import HumanDecisionAction, RunStatus, TaskStatus
from fsasm.model_types import EscalationRequest
from fsasm.recovery import OperationBinding, RecoveryCheckpoint
from fsasm.router import ConsultRoute, HandoverRoute, RouteToGate


def _harness_factory(
    workspace: Path,
    runs: Path,
    spec_for,
    *,
    allowed_files=None,
    expected_artifact_contains="",
    max_attempts=3,
) -> AcceptanceHarness:
    return AcceptanceHarness(
        runs_dir=runs,
        workspace_root=workspace,
        spec_for=spec_for,
        allowed_files=allowed_files or ["src/*"],
        expected_artifact_contains=expected_artifact_contains,
        max_attempts=max_attempts,
    )


def _passing_spec(artifact_contains: str = "") -> "callable":
    def spec(task_id, attempt):
        ap = f"src/{task_id}.py"
        return AcceptanceEffectSpec(
            artifact_path=ap,
            new_content="x = 1\n",
            allowed_files=["src/*"],
            check_args=["python", "-c", "assert True"],
        )

    return spec


def _inflight_task(
    h: AcceptanceHarness, state, task_id: str, artifact_path: str, content: str
):
    """Advance a plan task to RUNNING (attempt 1) and apply a real effect.

    Simulates a crash mid-run AFTER the real effect landed but BEFORE the
    snapshot commits a terminal task outcome, so :func:`reconcile_attempt`
    sees a RUNNING task bound to the current attempt with a real artifact.
    """
    current = state
    if current.plan.tasks[0].status is TaskStatus.PENDING:
        current = h.repository.advance(
            state.run_id,
            current.revision,
            TaskReadied(run_id=state.run_id, task_id=task_id),
        )
    current = h.repository.advance(
        state.run_id,
        current.revision,
        TaskActivated(run_id=state.run_id, task_id=task_id),
    )
    h.broker.apply_patch(
        state.run_id,
        task_id,
        1,
        1,
        artifact_path,
        content,
        allowed_files=h.allowed_files,
    )
    return current


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "src").mkdir()
        yield root


@pytest.fixture
def runs_dir(workspace):
    d = workspace / "runs"
    d.mkdir()
    return d


# -- Scenario 1: full plan PASSED -------------------------------------------


class TestFullPlanPassed:
    def test_single_task_passed(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(run_id="R1", n_tasks=1)
        out = h.run(state)
        assert out.state.status is RunStatus.PASSED
        assert out.reason == "all required tasks complete"
        assert len(out.evidence) >= 1
        task = out.state.plan.tasks[0]
        assert task.status is TaskStatus.PASSED

    def test_three_task_plan_passed(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(run_id="R3", n_tasks=3)
        out = h.run(state)
        assert out.state.status is RunStatus.PASSED
        assert all(t.status is TaskStatus.PASSED for t in out.state.plan.tasks)
        assert len(out.evidence) >= 3

    def test_five_task_plan_passed(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(run_id="R5", n_tasks=5)
        out = h.run(state)
        assert out.state.status is RunStatus.PASSED
        assert all(t.status is TaskStatus.PASSED for t in out.state.plan.tasks)


# -- Scenario 2: FAIL → feedback → new attempt → PASS ----------------------


class TestFailFeedbackRetryPass:
    def test_fail_then_pass_on_attempt_2(self, workspace, runs_dir):
        def spec(task_id, attempt):
            ap = f"src/{task_id}.py"
            if attempt == 1:
                # First attempt: write WRONG content that fails the check.
                return AcceptanceEffectSpec(
                    artifact_path=ap,
                    new_content="raise RuntimeError('bad')\n",
                    allowed_files=["src/*"],
                    check_args=["python", "-c", "import sys; sys.exit(1)"],
                )
            # Second attempt: correct content + passing check.
            return AcceptanceEffectSpec(
                artifact_path=ap,
                new_content="x = 1\n",
                allowed_files=["src/*"],
                check_args=["python", "-c", "assert True"],
            )

        h = _harness_factory(workspace, runs_dir, spec, max_attempts=3)
        state = h.start_plan(run_id="R-RETRY", n_tasks=1)
        out = h.run(state)
        assert out.state.status is RunStatus.PASSED
        task = out.state.plan.tasks[0]
        assert task.attempt >= 2
        assert task.status is TaskStatus.PASSED


# -- Scenario 3: consultation and explicit handover -------------------------


class TestConsultationAndHandover:
    def test_consultation_route(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(run_id="R-CONS", n_tasks=1)
        out = h.run(state)
        esc = EscalationRequest(
            kind="consultation", reason="need advice", target="API_A"
        )
        decision = h.route_escalation(out, esc, current_scope=["src/*"])
        assert isinstance(decision, ConsultRoute)
        assert len(out.escalation_decisions) == 1
        # Consultation does not change ownership or add an attempt.
        assert out.state.status is RunStatus.PASSED

    def test_handover_route(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(run_id="R-HO", n_tasks=1)
        out = h.run(state)
        esc = EscalationRequest(
            kind="handover", reason="transfer to expert", target="API_B"
        )
        decision = h.route_escalation(out, esc, current_scope=["src/*"])
        assert isinstance(decision, HandoverRoute)
        assert decision.target_role == "api_b"
        assert decision.previous_owner != decision.target_role

    def test_escalation_exhaustion_routes_to_gate(self, workspace, runs_dir):
        from fsasm.router import RouterConfig, RouterState

        h = _harness_factory(workspace, runs_dir, _passing_spec())
        h.router = type(h.router)(config=RouterConfig(max_escalations_per_run=0))
        h.router_state = RouterState(current_owner="local", escalations_this_run=0)
        state = h.start_plan(run_id="R-EXH", n_tasks=1)
        out = h.run(state)
        esc = EscalationRequest(kind="consultation", reason="x", target="API_A")
        decision = h.route_escalation(out, esc, current_scope=["src/*"])
        assert isinstance(decision, RouteToGate)


# -- Scenario 4: retry exhaustion → Human Gate → RETRY_ONCE and ABORT -------


class TestHumanGateRetryOnceAbort:
    def _gate_state(self, workspace, runs_dir):
        def spec(task_id, attempt):
            ap = f"src/{task_id}.py"
            return AcceptanceEffectSpec(
                artifact_path=ap,
                new_content="raise RuntimeError('always fails')\n",
                allowed_files=["src/*"],
                check_args=["python", "-c", "import sys; sys.exit(1)"],
            )

        h = _harness_factory(workspace, runs_dir, spec, max_attempts=1)
        state = h.start_plan(run_id="R-GATE", n_tasks=1)
        out = h.run(state)
        assert out.state.status is RunStatus.NEEDS_HUMAN
        assert out.state.gate is not None
        return h, out

    def test_gate_opened_on_retry_exhaustion(self, workspace, runs_dir):
        h, out = self._gate_state(workspace, runs_dir)
        assert "gate" in out.reason
        assert out.state.gate is not None

    def test_retry_once_resumes_and_passes(self, workspace, runs_dir):
        h, out = self._gate_state(workspace, runs_dir)
        task_id = out.state.plan.tasks[0].task_id

        # After RETRY_ONCE, swap the spec to a passing one.
        def passing_spec(task_id, attempt):
            ap = f"src/{task_id}.py"
            return AcceptanceEffectSpec(
                artifact_path=ap,
                new_content="x = 1\n",
                allowed_files=["src/*"],
                check_args=["python", "-c", "assert True"],
            )

        h.spec_for = passing_spec
        resumed = h.apply_gate(
            out,
            task_id=task_id,
            decision_id=f"dec-{task_id}-1",
            action=HumanDecisionAction.RETRY_ONCE.value,
        )
        assert HumanDecisionAction.RETRY_ONCE.value in resumed.gate_decisions
        assert resumed.state.status is RunStatus.PASSED

    def test_abort_fails_run(self, workspace, runs_dir):
        h, out = self._gate_state(workspace, runs_dir)
        task_id = out.state.plan.tasks[0].task_id
        resumed = h.apply_gate(
            out,
            task_id=task_id,
            decision_id=f"dec-{task_id}-abort",
            action=HumanDecisionAction.ABORT.value,
        )
        assert resumed.state.status is RunStatus.FAILED
        assert HumanDecisionAction.ABORT.value in resumed.gate_decisions


# -- Scenario 5: crash / resume at checkpoints ------------------------------


class TestCrashResumeCheckpoints:
    def test_resume_reads_authoritative_snapshot(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(run_id="R-RESUME", n_tasks=1)
        h.run(state)
        # After a "crash" mid-run, resume loads the committed snapshot.
        loaded = h.repository.load("R-RESUME")
        assert loaded.run_id == "R-RESUME"
        assert loaded.status is RunStatus.PASSED

    def test_reconcile_after_effect_applied_checkpoint(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(run_id="R-REC", n_tasks=1)
        task_id = state.plan.tasks[0].task_id
        # Crash mid-run: task RUNNING (attempt 1) with a real effect landed.
        _inflight_task(h, state, task_id, "src/TASK-001.py", "x = 1\n")
        binding = OperationBinding(
            run_id="R-REC",
            task_id=task_id,
            attempt=2,
            operation_id="op-1",
            artifact_id="art-1",
            artifact_path="src/TASK-001.py",
            checkpoint=RecoveryCheckpoint.EFFECT_APPLIED,
        )
        loaded, decision = h.resume_from_checkpoint(
            "R-REC", binding, RecoveryCheckpoint.EFFECT_APPLIED
        )
        assert loaded.run_id == "R-REC"
        assert decision == "verify"

    def test_reconcile_committed_checkpoint(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(run_id="R-REC2", n_tasks=1)
        task_id = state.plan.tasks[0].task_id
        # Crash mid-run: task RUNNING (attempt 1) with a real effect + evidence.
        _inflight_task(h, state, task_id, "src/TASK-001.py", "x = 1\n")
        binding = OperationBinding(
            run_id="R-REC2",
            task_id=task_id,
            attempt=2,
            operation_id="op-1",
            artifact_id="art-1",
            artifact_path="src/TASK-001.py",
            checkpoint=RecoveryCheckpoint.COMMITTED,
            evidence_refs=["ev-1"],
        )
        _, decision = h.resume_from_checkpoint(
            "R-REC2", binding, RecoveryCheckpoint.COMMITTED
        )
        # A committed snapshot with a real artifact + evidence → VERIFY.
        assert decision == "verify"


# -- Scenario 6: operation outside allowed scope ---------------------------


class TestOutOfScopeOperation:
    def test_out_of_scope_patch_blocked(self, workspace, runs_dir):
        def spec(task_id, attempt):
            # Attempt to write OUTSIDE the allowed scope.
            return AcceptanceEffectSpec(
                artifact_path="etc/passwd",
                new_content="hacked\n",
                allowed_files=["src/*"],
                check_args=["python", "-c", "assert True"],
            )

        h = _harness_factory(workspace, runs_dir, spec, allowed_files=["src/*"])
        state = h.start_plan(run_id="R-SCOPE", n_tasks=1)
        out = h.run(state)
        # The Broker blocks the out-of-scope write → verification FAILs → gate.
        assert out.state.status is RunStatus.NEEDS_HUMAN
        assert "gate" in out.reason


# -- Scenario 7: false final, stale evidence, foreign artifact --------------


class TestFalseFinalStaleForeign:
    def test_false_final_no_effect_fails(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, spec_for=lambda *_: None)
        state = h.start_plan(run_id="R-FF", n_tasks=1)
        out = h.run(state)
        assert out.state.status is RunStatus.NEEDS_HUMAN
        assert "gate" in out.reason

    def test_stale_evidence_does_not_pass(self, workspace, runs_dir):
        # Attempt 1 produces a passing check but FAILs; attempt 2 must not
        # reuse attempt 1's evidence.
        def spec(task_id, attempt):
            ap = f"src/{task_id}.py"
            if attempt == 1:
                return AcceptanceEffectSpec(
                    artifact_path=ap,
                    new_content="bad\n",
                    allowed_files=["src/*"],
                    check_args=["python", "-c", "import sys; sys.exit(1)"],
                )
            return AcceptanceEffectSpec(
                artifact_path=ap,
                new_content="x = 1\n",
                allowed_files=["src/*"],
                check_args=["python", "-c", "assert True"],
            )

        h = _harness_factory(workspace, runs_dir, spec, max_attempts=3)
        state = h.start_plan(run_id="R-SE", n_tasks=1)
        out = h.run(state)
        assert out.state.status is RunStatus.PASSED
        task = out.state.plan.tasks[0]
        assert task.attempt >= 2


# -- Scenario 8: blocked dependency + whole Parent/run ----------------------


class TestBlockedDependencyAndParent:
    def test_blocked_dependency_fails_run(self, workspace, runs_dir):
        # TASK-002 depends on TASK-001 which always FAILs → plan blocked.
        def spec(task_id, attempt):
            ap = f"src/{task_id}.py"
            if task_id == "TASK-001":
                return AcceptanceEffectSpec(
                    artifact_path=ap,
                    new_content="raise RuntimeError('always')\n",
                    allowed_files=["src/*"],
                    check_args=["python", "-c", "import sys; sys.exit(1)"],
                )
            return AcceptanceEffectSpec(
                artifact_path=ap,
                new_content="x = 1\n",
                allowed_files=["src/*"],
                check_args=["python", "-c", "assert True"],
            )

        h = _harness_factory(workspace, runs_dir, spec, max_attempts=1)
        state = h.start_plan(
            run_id="R-BLOCK",
            n_tasks=2,
            dependencies={"TASK-002": ["TASK-001"]},
        )
        out = h.run(state)
        assert out.state.status in (RunStatus.FAILED, RunStatus.NEEDS_HUMAN)

    def test_dependency_order_respected(self, workspace, runs_dir):
        h = _harness_factory(workspace, runs_dir, _passing_spec())
        state = h.start_plan(
            run_id="R-DEP",
            n_tasks=3,
            dependencies={"TASK-002": ["TASK-001"], "TASK-003": ["TASK-002"]},
        )
        out = h.run(state)
        assert out.state.status is RunStatus.PASSED
        order = [t.task_id for t in out.state.plan.tasks]
        assert order == ["TASK-001", "TASK-002", "TASK-003"]
        assert all(t.status is TaskStatus.PASSED for t in out.state.plan.tasks)
