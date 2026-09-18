"""FS-ASM Runtime v1 (T26) — full acceptance E2E matrix on controlled backends.

Drives the *complete* Runtime v1 lifecycle over controlled (deterministic)
backends — no real 7B and no live Mistral API — covering every acceptance
scenario the canonical TODO T26 requires:

1. Human Goal → Planner stub → Compiler → authoritative snapshot → Scheduler
   → Context → Executor Loop → Broker → Verifier → Evidence → commit → next
   task → whole Plan PASSED.
2. FAIL → feedback → new attempt → PASS.
3. Consultation and explicit handover (ModelRouter).
4. Retry exhaustion → Human Gate → RETRY_ONCE and ABORT.
5. Crash / resume at defined checkpoints (recovery).
6. An operation outside allowed scope (Broker policy block).
7. False final without effect, stale evidence, foreign artifact (Verifier).
8. Plan 1/3/N, blocked dependency, completion of the whole Parent/run.

The harness wires the *real* components that earlier tasks built:
:func:`fsasm.scheduler.schedule`, :class:`fsasm.tool_broker.ToolBroker`,
:class:`fsasm.verifier.ArtifactVerifier`, :func:`fsasm.retry.classify_attempt`,
:class:`fsasm.router.ModelRouter`, :func:`fsasm.runtime.apply_human_gate` and
:class:`fsasm.state_repository.StateRepository`. It grants no PASS itself: only
the Domain Core (via ``StateRepository.advance``) commits transitions. Every
terminal state carries evidence and the proper reason.

This module is a test/acceptance harness (architecture §16–§18, §29, §30,
§34, §35; canonical TODO T26). It is not a second workflow engine and never
runs in production against a real model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fsasm.domain import (
    DomainEvent,
    EvidenceAccepted,
    RunFailed,
    RunPlanned,
    RunStarted,
    TaskActivated,
    TaskEscalated,
    TaskReadied,
    TaskRetried,
    TaskVerificationFailed,
    TaskVerificationPassed,
)
from fsasm.models import (
    CheckKind,
    ChildTask,
    EvidenceRecord,
    GoalInput,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.persistence import RuntimePersistence
from fsasm.planner import PlannerStub
from fsasm.recovery import (
    OperationBinding,
    RecoveryCheckpoint,
    reconcile_attempt,
)
from fsasm.retry import (
    RetryDecision,
    TransportRetryBudget,
    classify_attempt,
)
from fsasm.router import (
    ModelRouter,
    RouterDecision,
    RouterState,
    apply_decision,
)
from fsasm.runtime import apply_human_gate
from fsasm.scheduler import ScheduleOutcome, schedule
from fsasm.state_repository import StateRepository
from fsasm.tool_broker import ToolBroker
from fsasm.verifier import ArtifactVerifier, VerifyRequest


# -- outcome record ----------------------------------------------------------


@dataclass
class AcceptanceOutcome:
    """The terminal result of one acceptance run (audit + evidence).

    Carries the final authoritative ``RunState``, the ordered events the driver
    applied through the Domain Core, the per-attempt evidence records, and a
    human-readable ``reason`` for the terminal state. The driver grants no
    PASS: ``state.status`` reflects what the Domain Core decided.
    """

    run_id: str
    state: RunState
    events: list[DomainEvent] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    reason: str = ""
    escalation_decisions: list[RouterDecision] = field(default_factory=list)
    gate_decisions: list[str] = field(default_factory=list)


# -- effect specification ----------------------------------------------------


@dataclass
class AcceptanceEffectSpec:
    """One controlled effect the harness applies for a task attempt.

    ``patch`` writes ``new_content`` to ``artifact_path`` via the Broker; the
    ``check`` runs a real ``run_checks`` that verifies the effect. The harness
    never claims PASS; it produces a real patch + a real check observation that
    the :class:`ArtifactVerifier` inspects.
    """

    artifact_path: str
    new_content: str
    allowed_files: list[str]
    check_kind: CheckKind = CheckKind.CUSTOM
    check_args: list[str] = field(default_factory=list)


# -- harness -----------------------------------------------------------------


def _make_plan(
    run_id: str,
    goal: str,
    n_tasks: int,
    max_attempts: int,
    allowed_files: list[str],
    dependencies: dict[str, list[str]] | None = None,
) -> Plan:
    """Compile a deterministic plan via the Planner stub + manual rebuild.

    The Planner stub produces a 3-task plan; we replace its tasks with the
    requested number of tasks + dependencies so the acceptance matrix can test
    plan 1/3/N and blocked dependencies.
    """

    from fsasm.models import RunConstraints

    base = PlannerStub().create_plan(
        GoalInput(
            goal=goal,
            run_id=run_id,
            constraints=RunConstraints(allowed_files=allowed_files),
        )
    )
    tasks: list[ChildTask] = []
    for i in range(1, n_tasks + 1):
        tid = f"TASK-{i:03d}"
        deps = dependencies.get(tid, []) if dependencies else []
        tasks.append(
            ChildTask(
                task_id=tid,
                parent_id=run_id,
                title=f"Task {i}",
                description=f"acceptance task {i}",
                status=TaskStatus.PENDING,
                attempt=1,
                max_attempts=max_attempts,
                sequence=i,
                dependencies=deps,
                allowed_files=allowed_files or ["src/*"],
                allowed_tools=["read_file", "apply_patch", "run_checks", "list_files"],
                verification=VerificationSpec(
                    type=VerificationType.CUSTOM, expected=f"task {i} done"
                ),
            )
        )
    return base.model_copy(update={"tasks": tasks, "run_id": run_id})


@dataclass
class AcceptanceHarness:
    """Wires the real v1 components for an acceptance run.

    The harness owns the tool broker on an isolated fixture, the verifier, the
    router, the retry budget and the state repository. The driver methods
    (:meth:`start_plan`, :meth:`run`, :meth:`apply_gate`,
    :meth:`resume_from_checkpoint`) apply every transition through the Domain
    Core via the State Repository (the single authority). It never grants PASS
    and never widens scope.

    ``spec_for(task_id, attempt)`` returns an :class:`AcceptanceEffectSpec` for
    the real effect the harness applies via the Broker, or ``None`` for a
    "DONE" claim with no effect (must FAIL verification).
    """

    runs_dir: Path
    workspace_root: Path
    spec_for: Callable[[str, int], AcceptanceEffectSpec | None] = field(
        default_factory=lambda: lambda task_id, attempt: None
    )
    expected_artifact_contains: str = ""
    router: ModelRouter = field(default_factory=ModelRouter)
    router_state: RouterState = field(default_factory=RouterState)
    transport_budget: TransportRetryBudget = field(
        default_factory=lambda: TransportRetryBudget(max_transport_retries=3)
    )
    allowed_files: list[str] = field(default_factory=lambda: ["src/*"])
    max_attempts: int = 3

    broker: ToolBroker = field(init=False)
    verifier: ArtifactVerifier = field(init=False)
    repository: StateRepository = field(init=False)

    def __post_init__(self) -> None:
        self.broker = ToolBroker(workspace_root=self.workspace_root)
        self.verifier = ArtifactVerifier(
            broker=self.broker,
            allowed_files=self.allowed_files,
            expected_artifact_contains=self.expected_artifact_contains,
        )
        persistence = RuntimePersistence(runs_dir=self.runs_dir)
        self.repository = StateRepository(persistence)

    # -- plan bootstrap ----------------------------------------------------

    def start_plan(
        self,
        run_id: str = "RUN-ACC",
        goal: str = "acceptance goal",
        n_tasks: int = 1,
        dependencies: dict[str, list[str]] | None = None,
    ) -> RunState:
        """Reserve a run and compile a deterministic plan.

        Produces ``n_tasks`` Child Tasks with optional dependencies and a
        configurable ``max_attempts``. The plan is committed via the Domain
        Core (``init_snapshot`` + ``RunStarted``).
        """

        plan = _make_plan(
            run_id, goal, n_tasks, self.max_attempts, self.allowed_files, dependencies
        )
        initial = RunState(run_id=run_id, goal=goal, plan=plan)
        self.repository.create_run(run_id)
        state = self.repository.init_snapshot(initial)
        state = self.repository.advance(
            run_id, state.revision, RunPlanned(run_id=run_id, plan=plan)
        )
        state = self.repository.advance(
            run_id, state.revision, RunStarted(run_id=run_id)
        )
        return state

    # -- the main drive loop ------------------------------------------------

    def run(self, state: RunState) -> AcceptanceOutcome:
        """Drive the plan to a terminal state over controlled backends.

        One pass per active task: schedule → apply real effect via Broker →
        verify → retry classify → router (if escalation) → commit. The Domain
        Core owns every transition; this method only feeds it events via the
        State Repository.
        """

        run_id = state.run_id
        outcome = AcceptanceOutcome(run_id=run_id, state=state)
        current = state
        if current.status is RunStatus.PLANNED:
            current = self._advance(current, RunStarted(run_id=run_id), outcome)
        if current.status is not RunStatus.RUNNING:
            outcome.state = current
            outcome.reason = f"initial status {current.status.value}"
            return outcome
        if current.plan is None:
            outcome.state = current
            outcome.reason = "run has no plan"
            return outcome

        for _ in range(1000):  # safety cap
            result = schedule(current)
            if result.outcome is ScheduleOutcome.ALL_COMPLETE:
                outcome.state = current
                outcome.reason = "all required tasks complete"
                return outcome
            if result.outcome is ScheduleOutcome.BUSY:
                outcome.state = current
                outcome.reason = "run busy with an active task"
                return outcome
            if result.outcome is ScheduleOutcome.WAITING_ON_GATE:
                outcome.state = current
                outcome.reason = "waiting on human gate"
                return outcome
            if result.outcome is ScheduleOutcome.BLOCKED:
                current = self._advance(current, RunFailed(run_id=run_id), outcome)
                outcome.state = current
                outcome.reason = "plan blocked"
                return outcome
            if result.outcome is not ScheduleOutcome.NEXT_TASK or result.task is None:
                current = self._advance(current, RunFailed(run_id=run_id), outcome)
                outcome.state = current
                outcome.reason = "no eligible task"
                return outcome

            task_id = result.task.task_id
            candidate = self._find_task(current, task_id)
            if candidate.status is TaskStatus.PENDING:
                current = self._advance(
                    current, TaskReadied(run_id=run_id, task_id=task_id), outcome
                )
            current = self._advance(
                current, TaskActivated(run_id=run_id, task_id=task_id), outcome
            )
            active = self._find_task(current, task_id)
            attempt = active.attempt

            # Apply the real effect + check via the Broker.
            spec = self.spec_for(task_id, attempt)
            artifact_path = (
                spec.artifact_path if spec is not None else f"src/{task_id}.py"
            )
            if spec is not None:
                patch_obs = self.broker.apply_patch(
                    run_id,
                    task_id,
                    attempt,
                    1,
                    spec.artifact_path,
                    spec.new_content,
                    allowed_files=spec.allowed_files,
                )
                check_obs = self.broker.run_checks(
                    run_id,
                    task_id,
                    attempt,
                    2,
                    kind=spec.check_kind,
                    args=spec.check_args,
                )
                verify_req = VerifyRequest(
                    run_id=run_id,
                    task_id=task_id,
                    attempt=attempt,
                    artifact_path=artifact_path,
                    patch_observation_id=patch_obs.operation_id,
                    check_observation_id=check_obs.operation_id,
                    check_observation=check_obs,
                )
            else:
                # False final: no real effect → verifier reads an absent/wrong
                # artifact and FAILs (G2).
                check_obs = self.broker.run_checks(
                    run_id,
                    task_id,
                    attempt,
                    2,
                    CheckKind.CUSTOM,
                    ["python", "-c", "pass"],
                )
                verify_req = VerifyRequest(
                    run_id=run_id,
                    task_id=task_id,
                    attempt=attempt,
                    artifact_path=artifact_path,
                    patch_observation_id=f"op-false-final-{task_id}-{attempt}",
                    check_observation_id=check_obs.operation_id,
                    check_observation=check_obs,
                )

            result_v, evidence_records = self.verifier.verify(verify_req)
            for ev in evidence_records:
                self.repository.persistence.save_evidence(ev)
                outcome.evidence.append(ev)

            if result_v.status.value == "PASS" and result_v.evidence_refs:
                current = self._advance(
                    current,
                    EvidenceAccepted(
                        run_id=run_id,
                        task_id=task_id,
                        evidence_refs=result_v.evidence_refs,
                    ),
                    outcome,
                )
                current = self._advance(
                    current,
                    TaskVerificationPassed(
                        run_id=run_id, task_id=task_id, verification_passed=True
                    ),
                    outcome,
                )
                continue

            # FAIL → classify retry via the real T18 classifier.
            current = self._advance(
                current,
                TaskVerificationFailed(
                    run_id=run_id, task_id=task_id, verification_passed=False
                ),
                outcome,
            )
            failed_task = self._find_task(current, task_id)
            verdict = classify_attempt(
                _stub_outcome(task_id, attempt),  # type: ignore[arg-type]
                failed_task,
                self.transport_budget,
                verification_result=result_v,
            )
            if verdict.decision is RetryDecision.MERYTORYCZNA_RETRY:
                current = self._advance(
                    current, TaskRetried(run_id=run_id, task_id=task_id), outcome
                )
                continue
            # Escalate (max_attempts exhausted or non-retryable) → Human Gate.
            current = self._advance(
                current,
                TaskEscalated(
                    run_id=run_id, task_id=task_id, attempt=failed_task.attempt
                ),
                outcome,
            )
            outcome.state = current
            outcome.reason = "retry exhausted -> human gate"
            return outcome

        outcome.state = current
        outcome.reason = "iteration cap reached"
        return outcome

    # -- human gate --------------------------------------------------------

    def apply_gate(
        self,
        outcome: AcceptanceOutcome,
        task_id: str,
        decision_id: str,
        action: str,
    ) -> AcceptanceOutcome:
        """Apply a Human Gate decision (RETRY_ONCE/ABORT) and resume.

        Uses the authoritative ``gate_id`` stored on the snapshot (no guessing).
        RETRY_ONCE bumps ``max_attempts`` by one and resumes; ABORT fails the
        run. Returns the updated outcome with merged audit trail.
        """

        from fsasm.models import HumanDecisionAction

        state = outcome.state
        assert state.gate is not None, "no open gate on snapshot"
        gate = state.gate
        act = HumanDecisionAction(action)
        new_max = None
        if act is HumanDecisionAction.RETRY_ONCE:
            new_max = self._find_task(state, task_id).max_attempts + 1
        current, _ = apply_human_gate(
            state,
            self.repository,
            gate_id=gate.gate_id,
            task_id=task_id,
            decision_id=decision_id,
            attempt=self._find_task(state, task_id).attempt,
            action=act,
            new_max_attempts=new_max,
        )
        outcome.gate_decisions.append(action)
        if act is HumanDecisionAction.ABORT:
            outcome.state = current
            outcome.reason = "human gate ABORT"
            return outcome
        # RETRY_ONCE: resume the run from the gate.
        resumed = self.run(current)
        resumed.gate_decisions = outcome.gate_decisions + resumed.gate_decisions
        resumed.escalation_decisions = (
            outcome.escalation_decisions + resumed.escalation_decisions
        )
        resumed.evidence = outcome.evidence + resumed.evidence
        resumed.events = outcome.events + resumed.events
        return resumed

    # -- escalation routing (consultation/handover) ------------------------

    def route_escalation(
        self,
        outcome: AcceptanceOutcome,
        escalation: Any,
        current_scope: list[str] | None = None,
    ) -> RouterDecision:
        """Route a model escalation request through the real ModelRouter.

        Records the decision on the outcome and updates the router state. The
        router grants no PASS and adds no attempt; this is an audit of the
        routing decision only.
        """

        decision = self.router.route(
            escalation, self.router_state, current_scope=current_scope
        )
        outcome.escalation_decisions.append(decision)
        self.router_state = apply_decision(decision, self.router_state)
        return decision

    # -- recovery / resume -------------------------------------------------

    def resume_from_checkpoint(
        self,
        run_id: str,
        binding: OperationBinding,
        checkpoint: RecoveryCheckpoint,
    ) -> tuple[RunState, str]:
        """Resume a run after a crash at a defined recovery checkpoint.

        Loads the authoritative snapshot, reconciles the uncertain effect at
        ``checkpoint`` via :func:`fsasm.recovery.reconcile_attempt`, and returns
        the reconciled state + the reconcile decision (VERIFY/RETRY/STOP).
        """

        state = self.repository.load(run_id)
        artifact_obs = None
        if binding.artifact_path:
            try:
                obs = self.broker.inspect_changes(
                    run_id,
                    binding.task_id or "",
                    binding.attempt,
                    0,
                    binding.artifact_path,
                    allowed_files=self.allowed_files,
                )
            except Exception:
                obs = None
            if obs is not None and not getattr(obs, "blocked", False):
                artifact_obs = getattr(obs, "content", None) or None
        report = reconcile_attempt(state, binding, artifact_obs)
        return state, report.decision.value

    # -- internals ---------------------------------------------------------

    def _advance(
        self,
        state: RunState,
        event: DomainEvent,
        outcome: AcceptanceOutcome,
    ) -> RunState:
        next_state = self.repository.advance(state.run_id, state.revision, event)
        outcome.events.append(event)
        return next_state

    @staticmethod
    def _find_task(state: RunState, task_id: str) -> ChildTask:
        assert state.plan is not None
        for t in state.plan.tasks:
            if t.task_id == task_id:
                return t
        raise KeyError(f"task {task_id} not found")


# -- helpers -----------------------------------------------------------------


@dataclass
class _StubOutcome:
    """A minimal ExecutorAttemptOutcome stand-in for the retry classifier.

    The acceptance harness drives effects directly through the Broker (no
    Executor Loop model call), so it builds this minimal outcome to feed the
    real :func:`fsasm.retry.classify_attempt` classifier for the retry/gate
    decision. It carries only the fields the classifier reads (``reason``,
    ``task_id``, ``attempt``, ``observations``, ``transport_error``).
    """

    reason: Any = None
    task_id: str = ""
    attempt: int = 1
    observations: list[Any] = field(default_factory=list)
    transport_error: Any = None


def _stub_outcome(task_id: str, attempt: int) -> _StubOutcome:
    """Build a stub COMPLETED outcome for the retry classifier (FAIL path)."""

    from fsasm.model_types import ExecutorOutcomeReason

    return _StubOutcome(
        reason=ExecutorOutcomeReason.COMPLETED, task_id=task_id, attempt=attempt
    )
