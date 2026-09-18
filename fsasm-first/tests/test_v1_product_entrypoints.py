"""T24 — Operational start_new, resume, status and signal.

Proves the four product commands over the authoritative snapshot (canonical
TODO T24; architecture §14) have stable contracts: JSON-by-default output, a
short human mode, exit codes 0/2/1, no command guesses a gate / overwrites a
run / reveals secrets, and the domain state of a run is distinguished from
the technical state of the Workflows service.

Coverage (acceptance: success, no-run, ID collision, inconsistent snapshot, no
open gate, service error):
- ``start_new``: creates a new run; refuses to overwrite; rejects blank goal /
  bad JSON; run_id optional (generated when omitted).
- ``resume``: loads an existing run; rejects a missing run; rejects a missing
  run_id; does NOT create a new run.
- ``status``: read-only projection; rejects a missing run; distinguishes
  domain status from service_status; never grants PASS.
- ``signal``: applies a complete Human Gate decision through the Domain Core;
  rejects incomplete identity, a non-existent run, no open gate, a wrong
  gate_id, an already-applied gate (no replay), an invalid action.
- Output: JSON is parseable and stable; human mode is a short readable block;
  exit codes match the contract (0 ok, 2 bad args/JSON, 1 other error).
"""

import io
import json
from pathlib import Path

from fsasm.cli import (
    CliExitCode,
    CliResult,
    dispatch,
    render_human,
    render_json,
    run_cli,
)
from fsasm.domain import TaskEscalated, TaskVerificationFailed
from fsasm.models import HumanDecisionAction, RunStatus
from fsasm.persistence import RuntimePersistence
from fsasm.state_repository import StateRepository

RUN = "run-1"
GOAL = "Fix the bug"


def _runs_dir(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    return runs


def _make_repository(runs_dir: Path) -> StateRepository:
    persistence = RuntimePersistence(runtime_dir=runs_dir.parent, runs_dir=runs_dir)
    return StateRepository(persistence)


def _start_run(runs_dir: Path, run_id: str = RUN, goal: str = GOAL) -> CliResult:
    return dispatch("start_new", {"goal": goal, "run_id": run_id}, runs_dir)


def _gate_open_state(runs_dir: Path, run_id: str = RUN) -> str:
    """Drive an existing run to a NEEDS_HUMAN (open gate) state on disk.

    Returns the task_id of the task at the open gate.
    """
    repository = _make_repository(runs_dir)
    state = repository.load(run_id)
    from fsasm.domain import RunPlanned, RunStarted, TaskActivated, TaskReadied

    # Pin the first task to max_attempts=1 so a single verification FAIL
    # exhausts the budget and opens the Human Gate (the PlannerStub default
    # is 3, which would leave retry budget and reject escalation).
    plan = state.plan.model_copy(deep=True)
    plan.tasks[0] = plan.tasks[0].model_copy(update={"max_attempts": 1})
    # CREATED -> PLANNED (attach the plan) -> RUNNING.
    state = repository.advance(
        run_id, state.revision, RunPlanned(run_id=run_id, plan=plan)
    )
    state = repository.advance(run_id, state.revision, RunStarted(run_id=run_id))
    # Use the first task in the plan (PlannerStub produces TASK-001/002/003).
    task_id = state.plan.tasks[0].task_id
    # Readied + Activated so the task is RUNNING.
    state = repository.advance(
        run_id, state.revision, TaskReadied(run_id=run_id, task_id=task_id)
    )
    state = repository.advance(
        run_id, state.revision, TaskActivated(run_id=run_id, task_id=task_id)
    )
    # Fail verification then escalate to open the gate.
    state = repository.advance(
        run_id,
        state.revision,
        TaskVerificationFailed(
            run_id=run_id, task_id=task_id, verification_passed=False
        ),
    )
    active_task = next(t for t in state.plan.tasks if t.task_id == task_id)
    state = repository.advance(
        run_id,
        state.revision,
        TaskEscalated(run_id=run_id, task_id=task_id, attempt=active_task.attempt),
    )
    assert state.gate is not None
    assert state.status == RunStatus.NEEDS_HUMAN
    return task_id


class TestStartNew:
    """start_new creates a new run; refuses to overwrite; validates input."""

    def test_creates_new_run(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = _start_run(runs)
        assert r.ok
        assert r.run_id == RUN
        assert r.domain_status == RunStatus.CREATED.value
        assert r.exit_code == CliExitCode.OK

    def test_generates_run_id_when_omitted(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = dispatch("start_new", {"goal": GOAL}, runs)
        assert r.ok
        assert r.run_id is not None and len(r.run_id) > 0
        assert r.run_id != RUN

    def test_refuses_to_overwrite_existing(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        first = _start_run(runs)
        assert first.ok
        second = _start_run(runs)
        assert not second.ok
        assert "already exists" in second.error
        assert second.exit_code == CliExitCode.ERROR

    def test_rejects_blank_goal(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = dispatch("start_new", {"goal": "   ", "run_id": RUN}, runs)
        assert not r.ok
        assert r.exit_code == CliExitCode.BAD_ARGS

    def test_rejects_bad_json(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        out = io.StringIO()
        rc = run_cli(
            ["start_new", "--input", "-", "--runs-dir", str(runs)],
            stdin=io.StringIO("{not json"),
            stdout=out,
            runs_dir=runs,
        )
        assert rc == CliExitCode.BAD_ARGS
        data = json.loads(out.getvalue())
        assert not data["ok"]


class TestResume:
    """resume loads an existing run; does not create a new one."""

    def test_loads_existing_run(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        r = dispatch("resume", {"run_id": RUN}, runs)
        assert r.ok
        assert r.run_id == RUN
        assert r.revision is not None

    def test_missing_run(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = dispatch("resume", {"run_id": "nope"}, runs)
        assert not r.ok
        assert r.exit_code == CliExitCode.ERROR

    def test_missing_run_id(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = dispatch("resume", {}, runs)
        assert not r.ok
        assert r.exit_code == CliExitCode.BAD_ARGS

    def test_does_not_create_run(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        # Resume of a non-existent run must NOT create it.
        dispatch("resume", {"run_id": "ghost"}, runs)
        assert not (runs / "ghost").exists()


class TestStatus:
    """status is read-only; distinguishes domain status from service status."""

    def test_read_only_success(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        r = dispatch("status", {"run_id": RUN}, runs)
        assert r.ok
        assert r.domain_status == RunStatus.CREATED.value
        # service_status is separate from domain_status and informational.
        assert r.service_status == "snapshot_ok"
        view = r.extra["view"]
        assert view["status"] == RunStatus.CREATED.value
        assert "tasks" in view

    def test_missing_run(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = dispatch("status", {"run_id": "nope"}, runs)
        assert not r.ok
        assert r.exit_code == CliExitCode.ERROR

    def test_missing_run_id(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = dispatch("status", {}, runs)
        assert not r.ok
        assert r.exit_code == CliExitCode.BAD_ARGS

    def test_status_reads_needs_human_without_error(self, tmp_path: Path) -> None:
        # A NEEDS_HUMAN run is still a successful read (exit 0); the domain
        # status is reported, not treated as an error.
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        _gate_open_state(runs)
        r = dispatch("status", {"run_id": RUN}, runs)
        assert r.ok
        assert r.domain_status == RunStatus.NEEDS_HUMAN.value
        assert r.gate is not None
        assert r.exit_code == CliExitCode.OK


class TestSignal:
    """signal applies a complete Human Gate decision via the Domain Core."""

    def test_applies_retry_once(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        _gate_open_state(runs)
        repo = _make_repository(runs)
        state = repo.load(RUN)
        gate = state.gate
        assert gate is not None
        from fsasm.models import decision_id_for

        d_id = decision_id_for(
            RUN, gate.task_id, gate.gate_id, HumanDecisionAction.RETRY_ONCE
        )
        r = dispatch(
            "signal",
            {
                "run_id": RUN,
                "task_id": gate.task_id,
                "gate_id": gate.gate_id,
                "decision_id": d_id,
                "action": "RETRY_ONCE",
            },
            runs,
        )
        assert r.ok
        assert r.domain_status == RunStatus.RUNNING.value

    def test_applies_abort(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        _gate_open_state(runs)
        repo = _make_repository(runs)
        state = repo.load(RUN)
        gate = state.gate
        from fsasm.models import decision_id_for

        d_id = decision_id_for(
            RUN, gate.task_id, gate.gate_id, HumanDecisionAction.ABORT
        )
        r = dispatch(
            "signal",
            {
                "run_id": RUN,
                "task_id": gate.task_id,
                "gate_id": gate.gate_id,
                "decision_id": d_id,
                "action": "ABORT",
            },
            runs,
        )
        assert r.ok
        assert r.domain_status == RunStatus.FAILED.value

    def test_rejects_incomplete_identity(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        _gate_open_state(runs)
        # missing gate_id
        r = dispatch(
            "signal",
            {
                "run_id": RUN,
                "task_id": "TASK-1",
                "decision_id": "d",
                "action": "RETRY_ONCE",
            },
            runs,
        )
        assert not r.ok
        assert r.exit_code == CliExitCode.BAD_ARGS

    def test_rejects_invalid_action(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        _gate_open_state(runs)
        r = dispatch(
            "signal",
            {
                "run_id": RUN,
                "task_id": "TASK-1",
                "gate_id": "g",
                "decision_id": "d",
                "action": "NOPE",
            },
            runs,
        )
        assert not r.ok
        assert r.exit_code == CliExitCode.BAD_ARGS
        assert "RETRY_ONCE or ABORT" in r.error

    def test_no_open_gate(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        # No gate opened; signal must be rejected.
        r = dispatch(
            "signal",
            {
                "run_id": RUN,
                "task_id": "TASK-1",
                "gate_id": "fake",
                "decision_id": "d",
                "action": "ABORT",
            },
            runs,
        )
        assert not r.ok
        assert "no open gate" in r.error

    def test_wrong_gate_id(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        _gate_open_state(runs)
        r = dispatch(
            "signal",
            {
                "run_id": RUN,
                "task_id": "TASK-1",
                "gate_id": "gate-wrong",
                "decision_id": "d",
                "action": "ABORT",
            },
            runs,
        )
        assert not r.ok
        assert "no open gate" in r.error

    def test_already_applied_no_replay(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        _gate_open_state(runs)
        repo = _make_repository(runs)
        state = repo.load(RUN)
        gate = state.gate
        from fsasm.models import decision_id_for

        d_id = decision_id_for(
            RUN, gate.task_id, gate.gate_id, HumanDecisionAction.RETRY_ONCE
        )
        first = dispatch(
            "signal",
            {
                "run_id": RUN,
                "task_id": gate.task_id,
                "gate_id": gate.gate_id,
                "decision_id": d_id,
                "action": "RETRY_ONCE",
            },
            runs,
        )
        assert first.ok
        # Replay the same decision on the (now closed) gate -> rejected.
        second = dispatch(
            "signal",
            {
                "run_id": RUN,
                "task_id": gate.task_id,
                "gate_id": gate.gate_id,
                "decision_id": d_id,
                "action": "RETRY_ONCE",
            },
            runs,
        )
        assert not second.ok

    def test_missing_run(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = dispatch(
            "signal",
            {
                "run_id": "ghost",
                "task_id": "TASK-1",
                "gate_id": "g",
                "decision_id": "d",
                "action": "ABORT",
            },
            runs,
        )
        assert not r.ok
        assert r.exit_code == CliExitCode.ERROR


class TestOutputAndExitCodes:
    """JSON is parseable/stable; human mode is short; exit codes match."""

    def test_json_output_parseable(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        out = io.StringIO()
        rc = run_cli(
            ["start_new", "--input", "-", "--runs-dir", str(runs)],
            stdin=io.StringIO(json.dumps({"goal": GOAL, "run_id": RUN})),
            stdout=out,
            runs_dir=runs,
        )
        data = json.loads(out.getvalue())
        assert rc == CliExitCode.OK
        assert data["ok"] is True
        assert data["operation"] == "start_new"

    def test_human_output_short(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        out = io.StringIO()
        rc = run_cli(
            ["status", "--input", "-", "--format", "human", "--runs-dir", str(runs)],
            stdin=io.StringIO(json.dumps({"run_id": "ghost"})),
            stdout=out,
            runs_dir=runs,
        )
        text = out.getvalue()
        assert rc == CliExitCode.ERROR
        assert "status: ERROR" in text or "status" in text

    def test_exit_code_0_on_success(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        out = io.StringIO()
        rc = run_cli(
            ["start_new", "--input", "-", "--runs-dir", str(runs)],
            stdin=io.StringIO(json.dumps({"goal": GOAL, "run_id": RUN})),
            stdout=out,
            runs_dir=runs,
        )
        assert rc == CliExitCode.OK

    def test_exit_code_2_bad_args(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        out = io.StringIO()
        rc = run_cli(
            ["resume", "--input", "-", "--runs-dir", str(runs)],
            stdin=io.StringIO(json.dumps({})),
            stdout=out,
            runs_dir=runs,
        )
        assert rc == CliExitCode.BAD_ARGS

    def test_exit_code_1_missing_run(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        out = io.StringIO()
        rc = run_cli(
            ["status", "--input", "-", "--runs-dir", str(runs)],
            stdin=io.StringIO(json.dumps({"run_id": "ghost"})),
            stdout=out,
            runs_dir=runs,
        )
        assert rc == CliExitCode.ERROR

    def test_exit_code_2_bad_json(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        out = io.StringIO()
        rc = run_cli(
            ["status", "--input", "-", "--runs-dir", str(runs)],
            stdin=io.StringIO("not json at all"),
            stdout=out,
            runs_dir=runs,
        )
        assert rc == CliExitCode.BAD_ARGS

    def test_no_secrets_in_output(self, tmp_path: Path) -> None:
        # A secret-like value in the goal must not leak into structured output
        # beyond the goal itself (the CLI never dumps env/secrets).
        runs = _runs_dir(tmp_path)
        out = io.StringIO()
        run_cli(
            ["start_new", "--input", "-", "--runs-dir", str(runs)],
            stdin=io.StringIO(json.dumps({"goal": "do task", "run_id": "r"})),
            stdout=out,
            runs_dir=runs,
        )
        text = out.getvalue()
        assert "MISTRAL_API_KEY" not in text
        assert "GH_TOKEN" not in text
        assert "password" not in text.lower()


class TestDomainVsServiceStatus:
    """domain_status is the authoritative run status; service_status is separate."""

    def test_status_distinguishes(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        r = dispatch("status", {"run_id": RUN}, runs)
        assert r.ok
        assert r.domain_status == RunStatus.CREATED.value
        assert r.service_status == "snapshot_ok"
        assert r.domain_status != r.service_status


class TestUnknownOperation:
    def test_unknown_op_rejected(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        r = dispatch("bogus", {}, runs)
        assert not r.ok
        assert r.exit_code == CliExitCode.BAD_ARGS


class TestRenderStability:
    def test_render_json_stable(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        r = dispatch("status", {"run_id": RUN}, runs)
        s1 = render_json(r)
        s2 = render_json(r)
        assert s1 == s2
        data = json.loads(s1)
        assert data["operation"] == "status"

    def test_render_human_ok(self, tmp_path: Path) -> None:
        runs = _runs_dir(tmp_path)
        _start_run(runs)
        r = dispatch("status", {"run_id": RUN}, runs)
        text = render_human(r)
        assert "status" in text
        assert RUN in text

    def test_render_human_error(self) -> None:
        r = CliResult(operation="status", ok=False, error="boom")
        text = render_human(r)
        assert "ERROR" in text
        assert "boom" in text
