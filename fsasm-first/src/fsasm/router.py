"""FS-ASM Model Router (T21) — deterministic consultation / handover routing.

The Model Router is the deterministic decision layer that turns a model
:class:`EscalationRequest` (or its absence) into a normalized routing decision.
It is NOT an adapter and holds NO model transport: it never calls a backend.
The Executor / driver applies the decision; the router only decides
(architecture §31–§32; canonical TODO T21).

Policy (canonical TODO T20 reception / T21):

- **Local backend is the default** for a normal Child Task. No escalation
  request means :class:`LocalRoute` (keep the local Executor as owner).
- **Consultation** (:class:`ConsultRoute`): a support model receives a limited
  context and returns *advice* that is fed back into the current attempt's
  context. The local Executor REMAINS the execution owner — consultation does
  NOT transfer the task and does NOT add a ``task_attempt``.
- **Handover** (:class:`HandoverRoute`): the runtime EXPLICITLY assigns the
  current Child Task to another adapter, with the SAME or NARROWER scope and
  its OWN budget. Handover changes the execution owner; it does not widen
  scope and does not add a ``task_attempt``.
- **Limits**: the number of escalations (consultations + handovers) per run,
  handovers per task, total cost, and allowed transitions are enforced and
  recorded. Exhaustion routes to the approved gate/stop path
  (:class:`RouteToGate`), never an infinite loop.
- **Ping-pong is blocked**: a role that just handed over cannot hand the task
  back to the role it received it from within the same run, and a handover to
  the current owner is rejected. ``ask_expert`` (consultation) cannot bypass
  scope, cannot add attempts, and cannot widen the allowed tool/file set.

The router is a pure function over ``(escalation, state, config)`` with no I/O:
the same inputs always yield the same decision. State (per-run / per-task
counters and the current owner) is carried in :class:`RouterState` and updated
by :func:`apply_decision`, which returns a NEW state (the input is never
mutated) — mirroring the Domain Core's immutability discipline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from fsasm.model_types import EscalationRequest, ModelCallBudget

# The logical role that owns execution of the current task. The local 7B is the
# default owner; Mistral roles A/B are the consultation/handover targets
# (architecture §26). Concrete model names are resolved in configuration (T29),
# not by the router.
DEFAULT_OWNER = "local"


class RouteKind(str, Enum):
    """The kind of routing decision the router returns (architecture §31–§32)."""

    LOCAL = "local"
    CONSULTATION = "consultation"
    HANDOVER = "handover"
    TO_GATE = "to_gate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class LocalRoute:
    """No escalation: keep the local backend as the execution owner (default).

    The router returns this for a normal Child Task with no escalation request.
    """

    kind: RouteKind = RouteKind.LOCAL
    owner: str = DEFAULT_OWNER
    reason: str = "no escalation; local backend is default"


@dataclass(frozen=True)
class ConsultRoute:
    """Consultation: a support model returns advice; the local Executor keeps ownership.

    ``target_role`` is the role consulted (API A / API B). ``advice_to_context``
    is a marker the driver uses to feed the support model's response back into
    the current attempt's context — consultation does NOT transfer the task and
    does NOT add a ``task_attempt``. The current owner (``owner``) is unchanged.
    """

    target_role: str
    owner: str
    budget: ModelCallBudget
    kind: RouteKind = RouteKind.CONSULTATION
    reason: str = "consultation: advice only, owner unchanged"


@dataclass(frozen=True)
class HandoverRoute:
    """Handover: explicitly assign the task to another adapter as the new owner.

    ``target_role`` is the new owner role. ``scope`` is the allowed file/tool
    scope for the new owner — it MUST be the same or a NARROWER subset of the
    current task scope (never wider). ``budget`` is the new owner's own budget.
    Handover changes the execution owner but does NOT add a ``task_attempt``.
    """

    target_role: str
    previous_owner: str
    scope: list[str]
    budget: ModelCallBudget
    kind: RouteKind = RouteKind.HANDOVER
    reason: str = "handover: explicit transfer, same/narrower scope, own budget"


@dataclass(frozen=True)
class RouteToGate:
    """Escalation limits exhausted: route to the approved gate/stop path.

    The router never loops infinitely: when the escalation/handover limits or
    the cost cap are exhausted, the task is routed to the approved Human Gate /
    stop path (consistent with the retry classifier, T18). This is NOT a PASS,
    a retry, or a scope widening.
    """

    reason: str
    kind: RouteKind = RouteKind.TO_GATE


@dataclass(frozen=True)
class RouteRejected:
    """The escalation request is rejected (no effect, no attempt added).

    Reasons: ping-pong (handing back to the role we just came from, or handing
    to the current owner), disallowed transition, disallowed target, scope
    bypass / widening, or a consultation that tries to widen allowed tools. A
    rejection is a no-op routing decision: the driver keeps the current owner
    and continues (or terminalizes per the retry policy); the rejection is
    auditable.
    """

    reason: str
    owner: str
    kind: RouteKind = RouteKind.REJECTED


RouterDecision = LocalRoute | ConsultRoute | HandoverRoute | RouteToGate | RouteRejected


@dataclass
class RouterConfig:
    """Configurable, conservative routing limits (canonical TODO §6, T21/T29).

    All limits are advisory caps; the router enforces them deterministically.
    ``allowed_handover_targets`` / ``allowed_consultation_targets`` are the
    logical role names the runtime permits (e.g. ``{"api_a", "api_b"}``). The
    concrete model per role is resolved elsewhere (T29). Defaults are
    conservative and overridable.
    """

    max_escalations_per_run: int = 2
    max_handovers_per_task: int = 1
    max_consultations_per_task: int = 2
    allow_consultation: bool = True
    allow_handover: bool = True
    allowed_consultation_targets: set[str] = field(
        default_factory=lambda: {"api_a", "api_b"}
    )
    allowed_handover_targets: set[str] = field(
        default_factory=lambda: {"api_a", "api_b"}
    )
    # Cost cap across all escalations in a run, if available (None = unbounded).
    max_escalation_cost: float | None = None
    # Default budgets handed to a consulted/handed-over adapter (own budget).
    consultation_budget: ModelCallBudget = field(default_factory=ModelCallBudget)
    handover_budget: ModelCallBudget = field(default_factory=ModelCallBudget)


@dataclass(frozen=True)
class RouterState:
    """Per-run / per-task routing state (counters + current owner).

    Immutable: :func:`apply_decision` returns a new state. The router reads
    this to enforce limits and block ping-pong; it never mutates it in place.
    ``current_owner`` is the role owning the current task's execution
    (``local`` by default). ``last_handover_from`` records the role a task was
    handed over FROM, so a handover back to it is blocked (ping-pong).
    """

    current_owner: str = DEFAULT_OWNER
    escalations_this_run: int = 0
    handovers_this_task: int = 0
    consultations_this_task: int = 0
    escalation_cost: float = 0.0
    last_handover_from: str | None = None
    last_handover_to: str | None = None


@dataclass
class ModelRouter:
    """Deterministic consultation/handover router (T21).

    A pure decision layer: :meth:`route` maps an :class:`EscalationRequest`
    (or its absence) plus the current :class:`RouterState` and
    :class:`RouterConfig` to a :class:`RouterDecision`. It performs NO model
    call and NO I/O. The driver applies the decision; :func:`apply_decision`
    updates the state (returning a new state). The router grants no PASS, adds
    no ``task_attempt``, and never widens scope.
    """

    config: RouterConfig = field(default_factory=RouterConfig)

    def route(
        self,
        escalation: EscalationRequest | None,
        state: RouterState,
        *,
        current_scope: list[str] | None = None,
    ) -> RouterDecision:
        """Decide how to route the current task given an escalation request.

        Args:
            escalation: The model's escalation request, or None for a normal
                step (local backend stays the default owner).
            state: The current :class:`RouterState` (counters + owner).
            current_scope: The current task's allowed scope (allowed files/tools).
                Used only to validate a handover does not WIDEN scope; the router
                never invents a wider scope.

        Returns:
            A :class:`RouterDecision` (LocalRoute / ConsultRoute / HandoverRoute
            / RouteToGate / RouteRejected). Deterministic, no I/O.
        """
        if escalation is None:
            return LocalRoute(owner=state.current_owner)

        # Exhaustion checks first: a run out of escalations or over cost goes to
        # the approved gate/stop path, never an infinite loop.
        if state.escalations_this_run >= self.config.max_escalations_per_run:
            return RouteToGate(reason="max_escalations_per_run exhausted")
        if (
            self.config.max_escalation_cost is not None
            and state.escalation_cost >= self.config.max_escalation_cost
        ):
            return RouteToGate(reason="max_escalation_cost exhausted")

        kind = escalation.kind.strip().lower()
        target = (escalation.target or "").strip().lower() or None

        if kind == "consultation":
            return self._route_consultation(escalation, state, target)
        if kind == "handover":
            return self._route_handover(escalation, state, target, current_scope)
        # Unknown escalation kind: reject (auditable), keep owner, no attempt.
        return RouteRejected(
            reason=f"unknown escalation kind '{escalation.kind}'",
            owner=state.current_owner,
        )

    # -- internals --------------------------------------------------------

    def _route_consultation(
        self,
        escalation: EscalationRequest,
        state: RouterState,
        target: str | None,
    ) -> RouterDecision:
        if not self.config.allow_consultation:
            return RouteRejected(
                reason="consultation disallowed by policy",
                owner=state.current_owner,
            )
        if state.consultations_this_task >= self.config.max_consultations_per_task:
            return RouteToGate(reason="max_consultations_per_task exhausted")
        target = self._resolve_target(
            target,
            self.config.allowed_consultation_targets,
            state,
            "consultation",
        )
        if target is None:
            return RouteRejected(
                reason=(
                    f"consultation target '{escalation.target}' not allowed"
                    if escalation.target
                    else "consultation has no allowed target"
                ),
                owner=state.current_owner,
            )
        # Consultation never changes the owner and never widens scope. The
        # support model's response is advice fed into the current context.
        return ConsultRoute(
            target_role=target,
            owner=state.current_owner,
            budget=self.config.consultation_budget,
            reason=f"consultation: {escalation.reason}",
        )

    def _route_handover(
        self,
        escalation: EscalationRequest,
        state: RouterState,
        target: str | None,
        current_scope: list[str] | None,
    ) -> RouterDecision:
        if not self.config.allow_handover:
            return RouteRejected(
                reason="handover disallowed by policy",
                owner=state.current_owner,
            )
        if state.handovers_this_task >= self.config.max_handovers_per_task:
            return RouteToGate(reason="max_handovers_per_task exhausted")
        target = self._resolve_target(
            target,
            self.config.allowed_handover_targets,
            state,
            "handover",
        )
        if target is None:
            return RouteRejected(
                reason=(
                    f"handover target '{escalation.target}' not allowed"
                    if escalation.target
                    else "handover has no allowed target"
                ),
                owner=state.current_owner,
            )
        # Ping-pong: cannot hand over to the current owner, nor back to the
        # role we just came from (within the same task chain).
        if target == state.current_owner:
            return RouteRejected(
                reason="handover to current owner rejected (ping-pong)",
                owner=state.current_owner,
            )
        if target == state.last_handover_from:
            return RouteRejected(
                reason=(
                    f"handover back to '{target}' rejected (ping-pong: came from there)"
                ),
                owner=state.current_owner,
            )
        # Scope: the new owner gets the SAME or a NARROWER scope, never wider.
        # We hand over the current scope unchanged (the driver/task scope is
        # the authority); the router never invents a wider scope.
        scope = list(current_scope) if current_scope is not None else []
        return HandoverRoute(
            target_role=target,
            previous_owner=state.current_owner,
            scope=scope,
            budget=self.config.handover_budget,
            reason=f"handover: {escalation.reason}",
        )

    def _resolve_target(
        self,
        target: str | None,
        allowed: set[str],
        state: RouterState,
        kind: str,
    ) -> str | None:
        """Resolve the escalation target to an allowed role name.

        If the escalation names a target, it must be in ``allowed``. If it
        names none, pick the first allowed target that is NOT the current owner
        (so a handover/consultation is never a self-loop). Returns None if no
        allowed, non-self target exists.
        """
        if target is not None:
            return target if target in allowed else None
        for cand in sorted(allowed):
            if cand != state.current_owner:
                return cand
        return None


def apply_decision(
    decision: RouterDecision, state: RouterState, *, cost: float = 0.0
) -> RouterState:
    """Return a NEW :class:`RouterState` reflecting an applied routing decision.

    Pure: the input ``state`` is never mutated. Only escalation-bearing
    decisions (ConsultRoute / HandoverRoute) bump counters; LocalRoute /
    RouteToGate / RouteRejected leave counters unchanged (a rejection or a
    gate routing consumes no escalation budget). The owner changes only on
    handover; consultation keeps the owner. ``last_handover_from/to`` track
    the most recent handover so ping-pong is detectable on the next decision.
    """
    if isinstance(decision, ConsultRoute):
        return RouterState(
            current_owner=decision.owner,
            escalations_this_run=state.escalations_this_run + 1,
            handovers_this_task=state.handovers_this_task,
            consultations_this_task=state.consultations_this_task + 1,
            escalation_cost=state.escalation_cost + cost,
            last_handover_from=state.last_handover_from,
            last_handover_to=state.last_handover_to,
        )
    if isinstance(decision, HandoverRoute):
        return RouterState(
            current_owner=decision.target_role,
            escalations_this_run=state.escalations_this_run + 1,
            handovers_this_task=state.handovers_this_task + 1,
            consultations_this_task=state.consultations_this_task,
            escalation_cost=state.escalation_cost + cost,
            last_handover_from=decision.previous_owner,
            last_handover_to=decision.target_role,
        )
    # LocalRoute / RouteToGate / RouteRejected: no counter/owner change.
    return state


__all__ = [
    "DEFAULT_OWNER",
    "ConsultRoute",
    "HandoverRoute",
    "LocalRoute",
    "ModelRouter",
    "RouteKind",
    "RouteRejected",
    "RouteToGate",
    "RouterConfig",
    "RouterDecision",
    "RouterState",
    "apply_decision",
]
