"""FS-ASM operational CLI (T24) — start_new, resume, status, signal.

The four product commands over the authoritative snapshot, with a stable
JSON-by-default output contract and a short human mode (canonical TODO T24;
architecture §14). Each command is a thin adapter over the existing domain
contracts (``RuntimeLifecycle`` / ``StateRepository`` / ``apply_event``); it
introduces NO competing state scheme and grants NO PASS/retry/gate of its own.

Contract (user-approved):

- Input: JSON (one positional arg or ``--input -`` for stdin). Existing schemas
  (``GoalInput``) and validation are reused; no new mandatory data format.
- Output: stable JSON for automation (default) or a short human mode (``--format
  human``). The domain state of a run is distinguished from the technical
  state of the Workflows service (``service_status`` is reported separately
  and is informational; it never competes with the snapshot).
- Exit codes: ``0`` command OK (regardless of the read domain status —
  PASSED/FAILED/NEEDS_HUMAN all read successfully), ``2`` bad arguments / bad
  JSON input, ``1`` other execution error (detail in the structured JSON).
- No command guesses a gate, overwrites a run, or reveals secrets.

The CLI holds no domain authority: ``start_new`` reserves a run and writes the
initial snapshot; ``resume`` loads an existing run (reconcile is T23); ``status``
is read-only; ``signal`` validates full gate identity and applies a
``HumanGateDecisionApplied`` event through the Domain Core. The CLI never
fabricates a ``gate_id``/``decision_id`` — the caller must supply the full
identity of the current gate.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TextIO

from fsasm.domain import HumanGateDecisionApplied
from fsasm.errors import FSASMError, InvalidTransitionError, PersistenceError
from fsasm.models import (
    GateOccurrence,
    GoalInput,
    HumanDecisionAction,
    Plan,
    RunState,
)
from fsasm.persistence import RuntimePersistence
from fsasm.runtime_lifecycle import RuntimeLifecycle
from fsasm.state_repository import StateRepository


class CliExitCode:
    """Stable exit codes (canonical TODO T24)."""

    OK = 0
    BAD_ARGS = 2
    ERROR = 1


@dataclass
class CliResult:
    """The structured result of one CLI command.

    Carries the machine-readable operation outcome, the relevant run identity
    and status, a separate (informational) service status, and the error detail
    when the command failed. Serialized to JSON for the default output mode and
    rendered shortly for the human mode.
    """

    operation: str
    ok: bool
    run_id: str | None = None
    domain_status: str | None = None
    revision: int | None = None
    gate: dict[str, Any] | None = None
    service_status: str = "unavailable"
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        if (
            not self.ok
            and self.error is not None
            and self.error.startswith(
                ("invalid arguments", "invalid input", "missing", "bad arguments")
            )
        ):
            return CliExitCode.BAD_ARGS
        return CliExitCode.OK if self.ok else CliExitCode.ERROR


def _gate_dict(gate: GateOccurrence | None) -> dict[str, Any] | None:
    if gate is None:
        return None
    return {
        "gate_id": gate.gate_id,
        "task_id": gate.task_id,
        "attempt": gate.attempt,
        "applied": gate.applied,
    }


def _run_status_view(state: RunState) -> dict[str, Any]:
    """Domain status projection (read-only) distinguishing run from tasks."""
    view: dict[str, Any] = {
        "run_id": state.run_id,
        "status": state.status.value,
        "revision": state.revision,
        "active_task_id": state.active_task_id,
        "completed": list(state.completed_task_ids),
        "failed": list(state.failed_task_ids),
        "needs_human": list(state.needs_human_task_ids),
        "gate": _gate_dict(state.gate),
    }
    if state.plan is not None:
        view["tasks"] = [
            {
                "task_id": t.task_id,
                "status": t.status.value,
                "attempt": t.attempt,
                "max_attempts": t.max_attempts,
            }
            for t in state.plan.tasks
        ]
    return view


def _ok_result(operation: str, state: RunState) -> CliResult:
    return CliResult(
        operation=operation,
        ok=True,
        run_id=state.run_id,
        domain_status=state.status.value,
        revision=state.revision,
        gate=_gate_dict(state.gate),
        service_status="snapshot_ok",
    )


def _error_result(operation: str, message: str, *, bad_args: bool = False) -> CliResult:
    return CliResult(
        operation=operation,
        ok=False,
        service_status="error",
        error=("invalid arguments: " + message) if bad_args else message,
    )


def handle_start_new(
    payload: dict[str, Any],
    lifecycle: RuntimeLifecycle,
    planner: Any | None = None,
) -> CliResult:
    """Create a NEW run; refuse to overwrite an existing one.

    The input is JSON validated as ``GoalInput``. ``run_id`` is optional; if
    omitted, the runtime generates one. The plan is produced by the existing
    Planner contract (``PlannerStub.create_plan`` by default); the CLI never
    widens constraints or assigns PASS. An existing ``run_id``/target is never
    overwritten (F4 / §14).
    """
    operation = "start_new"
    try:
        goal_input = GoalInput.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        return _error_result(operation, f"invalid input: {exc}", bad_args=True)
    run_id = goal_input.generate_run_id()
    if lifecycle.repository.is_run_initialized(run_id):
        return _error_result(operation, f"run already exists: {run_id}")
    plan = _build_plan(goal_input, run_id, planner)
    if plan is None:
        return _error_result(operation, "planner produced no plan")
    try:
        state = lifecycle.start_new(run_id, goal_input.goal, plan)
    except PersistenceError as exc:
        return _error_result(operation, str(exc))
    result = _ok_result(operation, state)
    result.extra["goal"] = goal_input.goal
    return result


def _build_plan(goal_input: GoalInput, run_id: str, planner: Any | None) -> Plan | None:
    """Produce the runtime-owned Plan via the existing Planner contract.

    Defaults to ``PlannerStub`` (deterministic). The Task Compiler (T08) owns
    the untrusted→authoritative boundary; the CLI never widens constraints.
    """
    from fsasm.planner import PlannerStub

    active = planner if planner is not None else PlannerStub()
    # PlannerStub.create_plan already runs the Task Compiler via assemble_plan.
    plan = active.create_plan(goal_input)
    # Pin the runtime-owned run_id onto the plan (the stub uses its own id).
    if plan.run_id != run_id:
        plan = plan.model_copy(update={"run_id": run_id, "plan_id": f"plan-{run_id}"})
    return plan


def handle_resume(
    payload: dict[str, Any],
    lifecycle: RuntimeLifecycle,
) -> CliResult:
    """Load an existing run's authoritative snapshot (read + validate).

    Resume does NOT create a new run and does NOT promise to reconcile real
    tool effects here — that is the T23 reconcile layer, which the driver
    invokes after resume loads the snapshot. The CLI surface returns the
    validated snapshot so an operator can resume safely.
    """
    operation = "resume"
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return _error_result(operation, "missing or invalid 'run_id'", bad_args=True)
    try:
        state, revision = lifecycle.resume(run_id)
    except PersistenceError as exc:
        return _error_result(operation, str(exc))
    result = _ok_result(operation, state)
    result.revision = revision
    result.service_status = "snapshot_ok"
    result.extra["resume"] = "snapshot loaded; reconcile via driver (T23)"
    return result


def handle_status(
    payload: dict[str, Any],
    repository: StateRepository,
) -> CliResult:
    """Read-only projection of the authoritative snapshot.

    ``service_status`` is informational only (Workflows technical state) and is
    reported separately from the domain ``status``; it never competes with the
    snapshot and never grants PASS.
    """
    operation = "status"
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return _error_result(operation, "missing or invalid 'run_id'", bad_args=True)
    try:
        state = repository.load(run_id)
    except PersistenceError as exc:
        return _error_result(operation, str(exc))
    result = _ok_result(operation, state)
    result.extra["view"] = _run_status_view(state)
    result.service_status = "snapshot_ok"
    return result


def handle_signal(
    payload: dict[str, Any],
    repository: StateRepository,
) -> CliResult:
    """Apply a complete Human Gate decision to the current open gate.

    The caller must supply the FULL identity: ``run_id``, ``task_id``,
    ``gate_id``, ``decision_id`` and ``action`` (RETRY_ONCE/ABORT). The CLI does
    NOT guess a gate, does NOT fabricate a ``decision_id``/``gate_id`` and does
    NOT create an extra authority. The decision is applied through the Domain
    Core via ``advance`` (load → apply_event → commit) with the optimistic
    revision guard.
    """
    operation = "signal"
    run_id = payload.get("run_id")
    task_id = payload.get("task_id")
    gate_id = payload.get("gate_id")
    decision_id = payload.get("decision_id")
    action_raw = payload.get("action")
    if not isinstance(run_id, str) or not run_id.strip():
        return _error_result(operation, "missing or invalid 'run_id'", bad_args=True)
    if not isinstance(task_id, str) or not task_id.strip():
        return _error_result(operation, "missing or invalid 'task_id'", bad_args=True)
    if not isinstance(gate_id, str) or not gate_id.strip():
        return _error_result(operation, "missing or invalid 'gate_id'", bad_args=True)
    if not isinstance(decision_id, str) or not decision_id.strip():
        return _error_result(
            operation, "missing or invalid 'decision_id'", bad_args=True
        )
    if not isinstance(action_raw, str):
        return _error_result(operation, "missing or invalid 'action'", bad_args=True)
    try:
        action = HumanDecisionAction(action_raw)
    except ValueError:
        return _error_result(
            operation,
            f"invalid action {action_raw!r}: must be RETRY_ONCE or ABORT",
            bad_args=True,
        )
    # Load the current snapshot to resolve the open gate and the attempt; the
    # CLI never guesses — it reads the authoritative gate occurrence.
    try:
        state = repository.load(run_id)
    except PersistenceError as exc:
        return _error_result(operation, str(exc))
    gate = state.gate
    if gate is None or gate.gate_id != gate_id:
        return _error_result(operation, "no open gate matches the supplied gate_id")
    # Validate the supplied identity against the open gate before applying.
    if gate.task_id != task_id:
        return _error_result(
            operation, "task_id does not match the open gate", bad_args=True
        )
    if gate.applied:
        return _error_result(operation, "gate already applied; no replay")
    # Resolve the gate's task (by gate.task_id) to read its attempt — the CLI
    # never guesses; it reads the authoritative gate occurrence + task.
    gate_task = None
    if state.plan is not None:
        for t in state.plan.tasks:
            if t.task_id == gate.task_id:
                gate_task = t
                break
    if gate_task is None:
        return _error_result(operation, "gate task not found in snapshot plan")
    new_max_attempts = gate_task.attempt + 1
    if action is HumanDecisionAction.RETRY_ONCE:
        if new_max_attempts is None:
            return _error_result(operation, "cannot resolve attempt for RETRY_ONCE")
    event = HumanGateDecisionApplied(
        run_id=run_id,
        task_id=task_id,
        gate_id=gate_id,
        decision_id=decision_id,
        action=action,
        attempt=gate.attempt,
        new_max_attempts=new_max_attempts
        if action is HumanDecisionAction.RETRY_ONCE
        else None,
    )
    try:
        next_state = repository.advance(run_id, state.revision, event)
    except InvalidTransitionError as exc:
        return _error_result(operation, str(exc))
    except PersistenceError as exc:
        return _error_result(operation, str(exc))
    except FSASMError as exc:
        return _error_result(operation, str(exc))
    result = _ok_result(operation, next_state)
    result.extra["decision"] = {
        "gate_id": gate_id,
        "decision_id": decision_id,
        "action": action.value,
    }
    return result


def _make_lifecycle(
    runs_dir: Path | str,
) -> tuple[RuntimePersistence, StateRepository, RuntimeLifecycle]:
    persistence = RuntimePersistence(
        runtime_dir=Path(runs_dir).parent, runs_dir=runs_dir
    )
    repository = StateRepository(persistence)
    lifecycle = RuntimeLifecycle(repository)
    return persistence, repository, lifecycle


def dispatch(
    operation: str,
    payload: dict[str, Any],
    runs_dir: Path | str,
) -> CliResult:
    """Dispatch one operation to its handler with a fresh repository/lifecycle.

    This is the single entry used by both the JSON and human render paths; it
    keeps side effects inside the domain contracts and never reads secrets.
    """
    _persistence, repository, lifecycle = _make_lifecycle(runs_dir)
    if operation == "start_new":
        return handle_start_new(payload, lifecycle)
    if operation == "resume":
        return handle_resume(payload, lifecycle)
    if operation == "status":
        return handle_status(payload, repository)
    if operation == "signal":
        return handle_signal(payload, repository)
    return _error_result(operation, f"unknown operation: {operation}", bad_args=True)


def render_json(result: CliResult) -> str:
    data = asdict(result)
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def render_human(result: CliResult) -> str:
    if result.ok:
        head = f"{result.operation}: ok (run {result.run_id})"
        parts = [head, f"  status: {result.domain_status}"]
        if result.revision is not None:
            parts.append(f"  revision: {result.revision}")
        if result.gate is not None:
            parts.append(f"  gate: {result.gate.get('gate_id')}")
        return "\n".join(parts)
    return f"{result.operation}: ERROR\n  {result.error}"


def run_cli(
    argv: list[str],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    runs_dir: Path | str | None = None,
) -> int:
    """Run the CLI from parsed argv. Returns the exit code and writes output.

    Usage (per operation): ``fsasm <operation> [--input <json> | --input -]``
    plus ``--format human|json`` (default json) and ``--runs-dir <path>``.
    ``--input -`` reads JSON from stdin. Bad arguments/JSON exit 2; other
    execution errors exit 1; success exits 0 regardless of the read domain
    status.
    """
    out = stdout or sys.stdout
    if not argv:
        out.write(render_json(_error_result("cli", "missing operation", bad_args=True)))
        return CliExitCode.BAD_ARGS
    operation = argv[0]
    rest = argv[1:]
    fmt = "json"
    input_path: str | None = None
    read_stdin = False
    resolved_runs_dir = (
        Path(runs_dir) if runs_dir is not None else Path("./runtime/runs")
    )
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("--format", "-f"):
            i += 1
            if i >= len(rest):
                out.write(
                    render_json(
                        _error_result(
                            operation, "missing --format value", bad_args=True
                        )
                    )
                )
                return CliExitCode.BAD_ARGS
            fmt = rest[i]
        elif arg in ("--input", "-i"):
            i += 1
            if i >= len(rest):
                out.write(
                    render_json(
                        _error_result(operation, "missing --input value", bad_args=True)
                    )
                )
                return CliExitCode.BAD_ARGS
            input_path = rest[i]
            if input_path == "-":
                read_stdin = True
        elif arg in ("--runs-dir",):
            i += 1
            if i >= len(rest):
                out.write(
                    render_json(
                        _error_result(
                            operation, "missing --runs-dir value", bad_args=True
                        )
                    )
                )
                return CliExitCode.BAD_ARGS
            resolved_runs_dir = Path(rest[i])
        else:
            out.write(
                render_json(
                    _error_result(operation, f"unknown argument: {arg}", bad_args=True)
                )
            )
            return CliExitCode.BAD_ARGS
        i += 1
    if fmt not in ("json", "human"):
        out.write(
            render_json(
                _error_result(operation, f"invalid format: {fmt}", bad_args=True)
            )
        )
        return CliExitCode.BAD_ARGS
    # Read the JSON payload.
    if read_stdin:
        stream = stdin or sys.stdin
        raw = stream.read()
    elif input_path is not None:
        try:
            raw = Path(input_path).read_text(encoding="utf-8")
        except OSError as exc:
            out.write(
                render_json(
                    _error_result(operation, f"cannot read input: {exc}", bad_args=True)
                )
            )
            return CliExitCode.BAD_ARGS
    else:
        raw = "{}"
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        out.write(
            render_json(
                _error_result(operation, f"invalid JSON input: {exc}", bad_args=True)
            )
        )
        return CliExitCode.BAD_ARGS
    if not isinstance(payload, dict):
        out.write(
            render_json(
                _error_result(operation, "input must be a JSON object", bad_args=True)
            )
        )
        return CliExitCode.BAD_ARGS
    result = dispatch(operation, payload, resolved_runs_dir)
    out.write(render_json(result) if fmt == "json" else render_human(result))
    out.write("\n")
    return result.exit_code


__all__ = [
    "CliExitCode",
    "CliResult",
    "dispatch",
    "handle_resume",
    "handle_signal",
    "handle_start_new",
    "handle_status",
    "render_human",
    "render_json",
    "run_cli",
]
