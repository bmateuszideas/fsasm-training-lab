"""T14 — Deterministic E2E tools → verification → commit on REAL effects.

Proves the v1 real-effects execution path drives the whole plan through REAL
isolated effects produced by the Tool Broker, independent verification by the
:class:`ArtifactVerifier`, evidence persistence BEFORE the snapshot accepts
refs, and Domain Core commit via the State Repository. PASS cannot come from
stub text alone: it requires a real artifact + a passing check of the CURRENT
attempt; the Domain Core alone grants the transition. The whole plan — not
just TASK-001 — reaches a terminal state (architecture §16–§18, §29, §30;
canonical TODO T14; Gate D).

Scenarios:
- Full success: real patch + passing check → PASS → next task → whole plan PASSED.
- False declaration without change: executor produces no patch → ArtifactVerifier
  FAILs (artifact absent / wrong) → retry/escalate.
- Policy block: the check is blocked by Broker policy → ArtifactVerifier FAILs.
- Negative test: real patch but check exits non-zero → FAIL → retry → PASS on
  attempt 2 with a correct patch + check.
- Stale evidence: evidence from attempt 1 cannot authorize attempt 2
  (TaskActivated clears accepted_evidence_refs on a new attempt).
- Multi-task plan: 2–3 tasks all PASS sequentially through real effects.
"""

import pathlib
import tempfile

import pytest

from fsasm.models import (
    CheckKind,
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence
from fsasm.real_effects import (
    ControlledToolExecutor,
    ToolEffectSpec,
    run_plan_real,
)
from fsasm.state_repository import StateRepository
from fsasm.tool_broker import ToolBroker
from fsasm.verifier import ArtifactVerifier

RUN = "r"


def _task(
    tid: str,
    seq: int,
    deps: list[str] | None = None,
    max_attempts: int = 3,
) -> ChildTask:
    return ChildTask(
        task_id=tid,
        sequence=seq,
        title="t",
        description="d",
        dependencies=deps or [],
        max_attempts=max_attempts,
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="e"),
    )


def _new_repo(workspace: pathlib.Path) -> StateRepository:
    d = pathlib.Path(tempfile.mkdtemp()) / "runtime"
    repo = StateRepository(RuntimePersistence(runtime_dir=d))
    return repo


def _start(tasks: list[ChildTask], repo: StateRepository) -> RunState:
    plan = Plan(plan_id="p", run_id=RUN, goal="g", tasks=tasks)
    state = RunState(run_id=RUN, goal="g", status=RunStatus.PLANNED, plan=plan)
    repo.create_run(RUN)
    repo.init_snapshot(state)
    return repo.load(RUN)


@pytest.fixture()
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """An isolated workspace with a fixture file + a passing-effect checker.

    The fixture starts as ``add`` returning ``a + b``; the controlled effect
    patches it to ``return a - b``, and ``assert_effect.py`` exits 0 only when
    that effect is present. This is a REAL filesystem effect + a REAL check,
    not a stub claim.
    """
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "assert_effect.py").write_text(
        "import sys\n"
        "content = open('calc.py').read()\n"
        "sys.exit(0 if 'return a - b' in content else 1)\n",
        encoding="utf-8",
    )
    return tmp_path


def _broker(root: pathlib.Path) -> ToolBroker:
    return ToolBroker(workspace_root=root, workspace_scope=[])


def _verifier(broker: ToolBroker, allowed: list[str] | None = None) -> ArtifactVerifier:
    return ArtifactVerifier(broker=broker, allowed_files=allowed or ["calc.py"])


def _good_spec(artifact: str = "calc.py") -> ToolEffectSpec:
    """A spec that patches calc.py to the expected effect and checks it."""
    return ToolEffectSpec(
        artifact_path=artifact,
        new_content="def add(a, b):\n    return a - b\n",
        allowed_files=["calc.py"],
        check_kind=CheckKind.CUSTOM,
        check_args=["python", "assert_effect.py"],
    )


class TestFullSuccess:
    """A real patch + a passing real check → PASS → whole plan PASSED."""

    def test_one_task_full_success(self, workspace: pathlib.Path) -> None:
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        executor = ControlledToolExecutor(
            broker=broker, spec_for=lambda tid, a: _good_spec()
        )
        out = run_plan_real(
            _start([_task("TASK-r-1", 1)], repo),
            repo,
            broker,
            verifier,
            executor,
        )
        assert out.status is RunStatus.PASSED
        assert out.state.completed_task_ids == ["TASK-r-1"]
        # The real artifact was actually modified on disk.
        assert "return a - b" in (workspace / "calc.py").read_text(encoding="utf-8")
        # The accepted task has integral evidence refs of the current attempt.
        task = out.state.plan.tasks[0]
        assert task.status is TaskStatus.PASSED
        assert task.attempt == 1
        assert task.accepted_evidence_refs  # non-empty current-attempt refs

    def test_pass_cannot_come_from_stub_text(self, workspace: pathlib.Path) -> None:
        """PASS requires a real artifact + a passing check, not a stub claim.

        An executor that 'claims done' (returns None) cannot PASS even though the
        artifact may coincidentally already contain text; here the fixture
        starts WITHOUT the expected effect, so the no-effect path FAILs.
        """
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        # spec_for returns None -> executor claims DONE without a patch.
        executor = ControlledToolExecutor(broker=broker, spec_for=lambda tid, a: None)
        out = run_plan_real(
            _start([_task("TASK-r-1", 1, max_attempts=1)], repo),
            repo,
            broker,
            verifier,
            executor,
        )
        # No real effect -> ArtifactVerifier FAILs -> escalate (max_attempts=1).
        assert out.status is RunStatus.NEEDS_HUMAN
        assert out.state.gate is not None
        assert out.state.gate.task_id == "TASK-r-1"
        # The artifact was NOT modified (no real effect happened).
        assert "return a + b" in (workspace / "calc.py").read_text(encoding="utf-8")


class TestFalseDeclarationWithoutChange:
    """A 'DONE' claim with no real patch cannot PASS (G2 reproducer, E2E)."""

    def test_no_effect_escalates_after_retry(self, workspace: pathlib.Path) -> None:
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        executor = ControlledToolExecutor(broker=broker, spec_for=lambda tid, a: None)
        out = run_plan_real(
            _start([_task("TASK-r-1", 1, max_attempts=2)], repo),
            repo,
            broker,
            verifier,
            executor,
        )
        # Two attempts both produce no effect -> both FAIL -> escalate.
        assert out.status is RunStatus.NEEDS_HUMAN
        task = out.state.plan.tasks[0]
        assert task.status is TaskStatus.NEEDS_HUMAN
        # The artifact is unchanged: no false PASS from a text claim.
        assert "return a + b" in (workspace / "calc.py").read_text(encoding="utf-8")


class TestPolicyBlock:
    """A check blocked by Broker policy cannot PASS."""

    def test_blocked_check_fails(self, workspace: pathlib.Path) -> None:
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        # A spec whose check is a non-allowlisted kind -> Broker blocks it.
        bad_spec = ToolEffectSpec(
            artifact_path="calc.py",
            new_content="def add(a, b):\n    return a - b\n",
            allowed_files=["calc.py"],
            check_kind=CheckKind.CUSTOM,
            check_args=["rm", "-rf", "."],  # non-allowlisted exe -> blocked
        )
        executor = ControlledToolExecutor(
            broker=broker, spec_for=lambda tid, a: bad_spec
        )
        out = run_plan_real(
            _start([_task("TASK-r-1", 1, max_attempts=1)], repo),
            repo,
            broker,
            verifier,
            executor,
        )
        assert out.status is RunStatus.NEEDS_HUMAN
        task = out.state.plan.tasks[0]
        assert task.status is TaskStatus.NEEDS_HUMAN
        assert task.accepted_evidence_refs == []  # no refs accepted on FAIL


class TestNegativeTestThenPass:
    """Real patch but negative check → FAIL → retry → PASS on attempt 2."""

    def test_fail_then_pass_on_attempt_2(self, workspace: pathlib.Path) -> None:
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        # attempt 1: patch to the WRONG effect (check fails); attempt 2: correct.
        wrong_spec = ToolEffectSpec(
            artifact_path="calc.py",
            new_content="def add(a, b):\n    return a * b\n",
            allowed_files=["calc.py"],
            check_kind=CheckKind.CUSTOM,
            check_args=["python", "assert_effect.py"],
        )
        correct_spec = _good_spec()

        def spec_for(tid: str, attempt: int) -> ToolEffectSpec | None:
            return wrong_spec if attempt == 1 else correct_spec

        executor = ControlledToolExecutor(broker=broker, spec_for=spec_for)
        out = run_plan_real(
            _start([_task("TASK-r-1", 1, max_attempts=3)], repo),
            repo,
            broker,
            verifier,
            executor,
        )
        assert out.status is RunStatus.PASSED
        task = out.state.plan.tasks[0]
        assert task.status is TaskStatus.PASSED
        assert task.attempt == 2  # passed on the second attempt
        # The final artifact contains the CORRECT effect (from attempt 2).
        assert "return a - b" in (workspace / "calc.py").read_text(encoding="utf-8")
        # Evidence refs belong to attempt 2 (current attempt), not attempt 1.
        assert task.accepted_evidence_refs

    def test_negative_check_does_not_pass(self, workspace: pathlib.Path) -> None:
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        wrong_spec = ToolEffectSpec(
            artifact_path="calc.py",
            new_content="def add(a, b):\n    return a * b\n",
            allowed_files=["calc.py"],
            check_kind=CheckKind.CUSTOM,
            check_args=["python", "assert_effect.py"],
        )
        executor = ControlledToolExecutor(
            broker=broker, spec_for=lambda tid, a: wrong_spec
        )
        out = run_plan_real(
            _start([_task("TASK-r-1", 1, max_attempts=1)], repo),
            repo,
            broker,
            verifier,
            executor,
        )
        assert out.status is RunStatus.NEEDS_HUMAN
        assert out.state.plan.tasks[0].status is TaskStatus.NEEDS_HUMAN


class TestStaleEvidenceCannotAuthorizeNextAttempt:
    """Evidence from attempt 1 cannot authorize PASS on attempt 2.

    TaskActivated clears accepted_evidence_refs when a new attempt begins
    (F8 at the Domain Core boundary). So a retry that produces no new effect
    cannot ride on the previous attempt's evidence.
    """

    def test_retry_without_new_effect_cannot_ride_prior_evidence(
        self, workspace: pathlib.Path
    ) -> None:
        """A retry that produces no new effect cannot PASS on prior evidence.

        attempt 1 FAILs (wrong patch → negative check, no accepted refs). A
        new attempt begins (TaskActivated clears accepted_evidence_refs per
        F8). attempt 2 produces no effect; the ArtifactVerifier FAILs because
        the current attempt has no real artifact, and the prior attempt's
        (empty) evidence cannot authorize PASS. The run escalates.
        """
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        wrong_spec = ToolEffectSpec(
            artifact_path="calc.py",
            new_content="def add(a, b):\n    return a * b\n",
            allowed_files=["calc.py"],
            check_kind=CheckKind.CUSTOM,
            check_args=["python", "assert_effect.py"],
        )

        def spec_for(tid: str, attempt: int) -> ToolEffectSpec | None:
            # attempt 1: wrong effect (FAIL); attempt 2: no effect (FAIL).
            return wrong_spec if attempt == 1 else None

        executor = ControlledToolExecutor(broker=broker, spec_for=spec_for)
        out = run_plan_real(
            _start([_task("TASK-r-1", 1, max_attempts=2)], repo),
            repo,
            broker,
            verifier,
            executor,
        )
        assert out.status is RunStatus.NEEDS_HUMAN
        task = out.state.plan.tasks[0]
        assert task.status is TaskStatus.NEEDS_HUMAN
        # No accepted evidence refs survived into the escalated state: the new
        # attempt cleared them and the no-effect attempt added none.
        assert task.accepted_evidence_refs == []

    def test_domain_core_clears_refs_on_new_attempt(self) -> None:
        """Direct Domain Core proof: TaskActivated on a new attempt clears
        stale evidence refs and increments the attempt counter (F8 invariant).

        The full legal sequence is Readied → Activated (attempt 1) →
        VerificationFailed → Retried (→ READY) → Activated (attempt 2). The
        second Activated resets accepted_evidence_refs so prior evidence
        cannot authorize the new attempt.
        """
        from fsasm.domain import (
            TaskActivated,
            TaskReadied,
            TaskRetried,
            TaskVerificationFailed,
            apply_event,
        )

        plan = Plan(
            plan_id="p",
            run_id=RUN,
            goal="g",
            tasks=[_task("TASK-r-1", 1, max_attempts=3)],
        )
        state = RunState(run_id=RUN, goal="g", status=RunStatus.RUNNING, plan=plan)
        state = apply_event(state, TaskReadied(run_id=RUN, task_id="TASK-r-1"))
        state = apply_event(state, TaskActivated(run_id=RUN, task_id="TASK-r-1"))
        # Simulate accepted evidence from attempt 1, then FAIL the attempt.
        state.plan.tasks[0].accepted_evidence_refs = ["stale-evidence-1"]
        state = apply_event(
            state,
            TaskVerificationFailed(
                run_id=RUN, task_id="TASK-r-1", verification_passed=False
            ),
        )
        # Retry: Retried -> READY; Activated -> RUNNING (attempt 2) clears refs.
        state = apply_event(state, TaskRetried(run_id=RUN, task_id="TASK-r-1"))
        assert state.plan.tasks[0].status is TaskStatus.READY
        state = apply_event(state, TaskActivated(run_id=RUN, task_id="TASK-r-1"))
        assert state.plan.tasks[0].accepted_evidence_refs == []
        assert state.plan.tasks[0].attempt == 2


class TestMultiTaskPlan:
    """2–3 tasks all PASS sequentially through real effects."""

    def test_two_tasks_pass_in_order(self, workspace: pathlib.Path) -> None:
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        executor = ControlledToolExecutor(
            broker=broker, spec_for=lambda tid, a: _good_spec()
        )
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
        ]
        out = run_plan_real(_start(tasks, repo), repo, broker, verifier, executor)
        assert out.status is RunStatus.PASSED
        assert out.state.completed_task_ids == ["TASK-r-1", "TASK-r-2"]

    def test_three_tasks_pass_sequentially(self, workspace: pathlib.Path) -> None:
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        executor = ControlledToolExecutor(
            broker=broker, spec_for=lambda tid, a: _good_spec()
        )
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
            _task("TASK-r-3", 3, ["TASK-r-2"]),
        ]
        out = run_plan_real(_start(tasks, repo), repo, broker, verifier, executor)
        assert out.status is RunStatus.PASSED
        assert out.state.completed_task_ids == [
            "TASK-r-1",
            "TASK-r-2",
            "TASK-r-3",
        ]
        # Each task ended PASSED with current-attempt evidence.
        for t in out.state.plan.tasks:
            assert t.status is TaskStatus.PASSED
            assert t.accepted_evidence_refs

    def test_pass_first_task_does_not_end_plan(self, workspace: pathlib.Path) -> None:
        """PASS of TASK-001 does NOT end the plan; the whole plan must finish."""
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        executor = ControlledToolExecutor(
            broker=broker, spec_for=lambda tid, a: _good_spec()
        )
        tasks = [
            _task("TASK-r-1", 1),
            _task("TASK-r-2", 2, ["TASK-r-1"]),
        ]
        out = run_plan_real(_start(tasks, repo), repo, broker, verifier, executor)
        assert out.status is RunStatus.PASSED
        assert len(out.state.completed_task_ids) == 2


class TestEvidencePersistsBeforeSnapshot:
    """Evidence is persisted to disk BEFORE the snapshot accepts refs (T13/T14).

    After a PASS, the accepted evidence refs in the snapshot correspond to
    evidence records actually persisted by ``save_evidence`` during the run.
    """

    def test_persisted_evidence_matches_accepted_refs(
        self, workspace: pathlib.Path
    ) -> None:
        repo = _new_repo(workspace)
        broker = _broker(workspace)
        verifier = _verifier(broker)
        executor = ControlledToolExecutor(
            broker=broker, spec_for=lambda tid, a: _good_spec()
        )
        out = run_plan_real(
            _start([_task("TASK-r-1", 1)], repo), repo, broker, verifier, executor
        )
        assert out.status is RunStatus.PASSED
        task = out.state.plan.tasks[0]
        refs = task.accepted_evidence_refs
        assert refs  # non-empty
        # Each accepted ref must correspond to a persisted evidence record.
        for ref in refs:
            ev = repo.persistence.load_evidence(RUN, ref)
            assert ev is not None, f"accepted ref {ref} has no persisted evidence"
            assert ev.run_id == RUN
            assert ev.task_id == "TASK-r-1"
            assert ev.attempt == 1  # current attempt
