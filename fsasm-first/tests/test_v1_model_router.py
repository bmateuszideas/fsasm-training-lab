"""T21 — Model Router: deterministic consultation / handover routing.

Proves the Model Router distinguishes consultation (advice, owner unchanged)
from handover (explicit transfer, same/narrower scope, own budget), enforces
escalation/handover/cost limits, blocks ping-pong, routes the exhausted path
to the approved gate/stop, keeps the local backend as the default for a normal
Child Task, and never bypasses scope or adds a ``task_attempt``. The router is
a pure decision layer: it performs NO model call and NO I/O, and the same
inputs always yield the same decision (architecture §31–§32; canonical TODO
T21).
"""

import pytest

from fsasm.model_types import EscalationRequest
from fsasm.router import (
    DEFAULT_OWNER,
    ConsultRoute,
    HandoverRoute,
    LocalRoute,
    ModelRouter,
    RouteKind,
    RouteRejected,
    RouteToGate,
    RouterConfig,
    RouterState,
    apply_decision,
)


def _esc(kind: str, reason: str = "r", target: str | None = None) -> EscalationRequest:
    return EscalationRequest(kind=kind, reason=reason, target=target)


class TestLocalDefault:
    """Local backend is the default for a normal Child Task (no escalation)."""

    def test_no_escalation_returns_local_route(self) -> None:
        router = ModelRouter()
        decision = router.route(None, RouterState())
        assert isinstance(decision, LocalRoute)
        assert decision.owner == DEFAULT_OWNER
        assert decision.kind is RouteKind.LOCAL

    def test_local_route_keeps_current_owner(self) -> None:
        router = ModelRouter()
        state = RouterState(current_owner="api_a")
        decision = router.route(None, state)
        assert isinstance(decision, LocalRoute)
        assert decision.owner == "api_a"

    def test_router_performs_no_model_call(self) -> None:
        # The router has no gateway/backend attribute; it only decides.
        router = ModelRouter()
        assert not hasattr(router, "gateway")
        assert not hasattr(router, "backend")
        assert not hasattr(router, "generate")


class TestConsultation:
    """Consultation returns advice to context; the local Executor keeps ownership."""

    def test_consultation_returns_consult_route(self) -> None:
        router = ModelRouter()
        decision = router.route(
            _esc("consultation", "need help", "api_a"), RouterState()
        )
        assert isinstance(decision, ConsultRoute)
        assert decision.target_role == "api_a"
        # Owner unchanged: the local Executor remains the execution owner.
        assert decision.owner == DEFAULT_OWNER
        assert decision.kind is RouteKind.CONSULTATION

    def test_consultation_does_not_change_owner(self) -> None:
        router = ModelRouter()
        state = RouterState(current_owner="local")
        decision = router.route(_esc("consultation", "r", "api_a"), state)
        assert isinstance(decision, ConsultRoute)
        assert decision.owner == "local"

    def test_consultation_picks_first_allowed_non_self_target_when_unnamed(
        self,
    ) -> None:
        router = ModelRouter()
        decision = router.route(_esc("consultation", "r", None), RouterState())
        assert isinstance(decision, ConsultRoute)
        # api_a is the first allowed target alphabetically and != local.
        assert decision.target_role == "api_a"

    def test_consultation_disallowed_target_rejected(self) -> None:
        router = ModelRouter()
        decision = router.route(
            _esc("consultation", "r", "unknown_role"), RouterState()
        )
        assert isinstance(decision, RouteRejected)
        assert "not allowed" in decision.reason
        assert decision.owner == DEFAULT_OWNER

    def test_consultation_disallowed_by_policy(self) -> None:
        router = ModelRouter(config=RouterConfig(allow_consultation=False))
        decision = router.route(_esc("consultation", "r", "api_a"), RouterState())
        assert isinstance(decision, RouteRejected)
        assert "disallowed" in decision.reason

    def test_consultation_does_not_add_task_attempt(self) -> None:
        # The router returns a decision; it has no task_attempt field and never
        # bumps one. The decision carries no attempt concept.
        router = ModelRouter()
        decision = router.route(_esc("consultation", "r", "api_a"), RouterState())
        assert not hasattr(decision, "task_attempt")
        assert not hasattr(decision, "attempt")

    def test_consultation_does_not_widen_scope(self) -> None:
        router = ModelRouter()
        decision = router.route(
            _esc("consultation", "r", "api_a"), RouterState(), current_scope=["a.py"]
        )
        assert isinstance(decision, ConsultRoute)
        # Consultation carries no scope field at all: it never touches scope.
        assert not hasattr(decision, "scope")


class TestHandover:
    """Handover explicitly transfers the task with same/narrower scope + own budget."""

    def test_handover_returns_handover_route(self) -> None:
        router = ModelRouter()
        decision = router.route(
            _esc("handover", "too hard", "api_b"), RouterState(), current_scope=["*.py"]
        )
        assert isinstance(decision, HandoverRoute)
        assert decision.target_role == "api_b"
        assert decision.previous_owner == DEFAULT_OWNER
        assert decision.kind is RouteKind.HANDOVER

    def test_handover_changes_owner(self) -> None:
        router = ModelRouter()
        decision = router.route(
            _esc("handover", "r", "api_b"), RouterState(), current_scope=["*.py"]
        )
        assert isinstance(decision, HandoverRoute)
        assert decision.target_role == "api_b"

    def test_handover_carries_same_scope_not_wider(self) -> None:
        router = ModelRouter()
        scope = ["src/a.py", "src/b.py"]
        decision = router.route(
            _esc("handover", "r", "api_b"), RouterState(), current_scope=scope
        )
        assert isinstance(decision, HandoverRoute)
        # The new owner gets the SAME scope, never wider (router invents none).
        assert decision.scope == scope
        # Crucially, the router never ADDS entries beyond the current scope.
        assert set(decision.scope).issubset(set(scope))

    def test_handover_has_own_budget(self) -> None:
        router = ModelRouter()
        decision = router.route(
            _esc("handover", "r", "api_b"), RouterState(), current_scope=["*.py"]
        )
        assert isinstance(decision, HandoverRoute)
        assert decision.budget is not None

    def test_handover_disallowed_target_rejected(self) -> None:
        router = ModelRouter()
        decision = router.route(
            _esc("handover", "r", "unknown"), RouterState(), current_scope=["*.py"]
        )
        assert isinstance(decision, RouteRejected)
        assert "not allowed" in decision.reason

    def test_handover_disallowed_by_policy(self) -> None:
        router = ModelRouter(config=RouterConfig(allow_handover=False))
        decision = router.route(
            _esc("handover", "r", "api_b"), RouterState(), current_scope=["*.py"]
        )
        assert isinstance(decision, RouteRejected)
        assert "disallowed" in decision.reason

    def test_handover_does_not_add_task_attempt(self) -> None:
        router = ModelRouter()
        decision = router.route(
            _esc("handover", "r", "api_b"), RouterState(), current_scope=["*.py"]
        )
        assert not hasattr(decision, "task_attempt")
        assert not hasattr(decision, "attempt")


class TestPingPongBlocked:
    """No infinite ping-pong between models."""

    def test_handover_to_current_owner_rejected(self) -> None:
        router = ModelRouter()
        # Current owner is already api_a; handing to api_a is a self-loop.
        state = RouterState(current_owner="api_a")
        decision = router.route(
            _esc("handover", "r", "api_a"), state, current_scope=["*.py"]
        )
        assert isinstance(decision, RouteRejected)
        assert "ping-pong" in decision.reason

    def test_handover_back_to_previous_owner_rejected(self) -> None:
        # api_a handed over to api_b; api_b now owns; handing back to api_a is
        # ping-pong. api_a IS an allowed handover target, so the only thing
        # blocking the handover is the ping-pong rule (not the allowed-target
        # rule).
        router = ModelRouter()
        state = RouterState(current_owner="api_b", last_handover_from="api_a")
        decision = router.route(
            _esc("handover", "r", "api_a"), state, current_scope=["*.py"]
        )
        assert isinstance(decision, RouteRejected)
        assert "ping-pong" in decision.reason

    def test_handover_to_a_third_role_allowed_after_handover(self) -> None:
        router = ModelRouter(
            config=RouterConfig(max_handovers_per_task=5, max_escalations_per_run=5)
        )
        # local -> api_b; api_b may hand to api_a (not the one it came from).
        state = RouterState(current_owner="api_b", last_handover_from="local")
        decision = router.route(
            _esc("handover", "r", "api_a"), state, current_scope=["*.py"]
        )
        assert isinstance(decision, HandoverRoute)
        assert decision.target_role == "api_a"


class TestLimitsEnforced:
    """Escalation/handover/cost limits enforced; exhaustion -> gate/stop."""

    def test_max_escalations_per_run_exhausted_routes_to_gate(self) -> None:
        router = ModelRouter(config=RouterConfig(max_escalations_per_run=2))
        state = RouterState(escalations_this_run=2)
        decision = router.route(_esc("consultation", "r", "api_a"), state)
        assert isinstance(decision, RouteToGate)
        assert "max_escalations_per_run" in decision.reason

    def test_max_handovers_per_task_exhausted_routes_to_gate(self) -> None:
        router = ModelRouter(
            config=RouterConfig(max_handovers_per_task=1, max_escalations_per_run=5)
        )
        state = RouterState(handovers_this_task=1, escalations_this_run=0)
        decision = router.route(
            _esc("handover", "r", "api_b"), state, current_scope=["*.py"]
        )
        assert isinstance(decision, RouteToGate)
        assert "max_handovers_per_task" in decision.reason

    def test_max_consultations_per_task_exhausted_routes_to_gate(self) -> None:
        router = ModelRouter(
            config=RouterConfig(max_consultations_per_task=1, max_escalations_per_run=5)
        )
        state = RouterState(consultations_this_task=1, escalations_this_run=0)
        decision = router.route(_esc("consultation", "r", "api_a"), state)
        assert isinstance(decision, RouteToGate)
        assert "max_consultations_per_task" in decision.reason

    def test_cost_cap_exhausted_routes_to_gate(self) -> None:
        router = ModelRouter(config=RouterConfig(max_escalation_cost=1.0))
        state = RouterState(escalation_cost=1.0)
        decision = router.route(_esc("consultation", "r", "api_a"), state)
        assert isinstance(decision, RouteToGate)
        assert "max_escalation_cost" in decision.reason

    def test_exhausted_path_is_not_pass_not_retry_not_scope_widening(self) -> None:
        router = ModelRouter(config=RouterConfig(max_escalations_per_run=1))
        state = RouterState(escalations_this_run=1)
        decision = router.route(
            _esc("handover", "r", "api_b"), state, current_scope=["*.py"]
        )
        assert isinstance(decision, RouteToGate)
        assert not hasattr(decision, "scope") or not getattr(decision, "scope", None)
        # RouteToGate is a terminal routing path, not a Consult/Handover.
        assert decision.kind is RouteKind.TO_GATE


class TestAllowedTransitions:
    """Allowed transitions / unknown kinds handled deterministically."""

    def test_unknown_escalation_kind_rejected(self) -> None:
        router = ModelRouter()
        decision = router.route(_esc("bogus", "r", "api_a"), RouterState())
        assert isinstance(decision, RouteRejected)
        assert "unknown escalation kind" in decision.reason
        assert decision.owner == DEFAULT_OWNER

    def test_no_allowed_non_self_target_rejected(self) -> None:
        # Only one allowed target and it is the current owner -> no valid target.
        router = ModelRouter(
            config=RouterConfig(allowed_consultation_targets={"local"})
        )
        state = RouterState(current_owner="local")
        decision = router.route(_esc("consultation", "r", None), state)
        assert isinstance(decision, RouteRejected)


class TestApplyDecision:
    """apply_decision returns a NEW state; counters/owner update correctly."""

    def test_apply_decision_does_not_mutate_input(self) -> None:
        router = ModelRouter()
        state = RouterState()
        decision = router.route(_esc("consultation", "r", "api_a"), state)
        new_state = apply_decision(decision, state)
        assert state.escalations_this_run == 0
        assert state.consultations_this_task == 0
        assert new_state.escalations_this_run == 1
        assert new_state.consultations_this_task == 1

    def test_apply_consultation_keeps_owner(self) -> None:
        router = ModelRouter()
        state = RouterState(current_owner="local")
        decision = router.route(_esc("consultation", "r", "api_a"), state)
        new_state = apply_decision(decision, state)
        assert new_state.current_owner == "local"

    def test_apply_handover_changes_owner_and_tracks_from(self) -> None:
        router = ModelRouter()
        state = RouterState(current_owner="local")
        decision = router.route(
            _esc("handover", "r", "api_b"), state, current_scope=["*.py"]
        )
        new_state = apply_decision(decision, state)
        assert new_state.current_owner == "api_b"
        assert new_state.last_handover_from == "local"
        assert new_state.last_handover_to == "api_b"
        assert new_state.handovers_this_task == 1
        assert new_state.escalations_this_run == 1

    def test_apply_rejection_no_counter_change(self) -> None:
        router = ModelRouter(config=RouterConfig(allow_handover=False))
        state = RouterState()
        decision = router.route(
            _esc("handover", "r", "api_b"), state, current_scope=["*.py"]
        )
        assert isinstance(decision, RouteRejected)
        new_state = apply_decision(decision, state)
        assert new_state.escalations_this_run == 0
        assert new_state.current_owner == "local"

    def test_apply_to_gate_no_counter_change(self) -> None:
        router = ModelRouter(config=RouterConfig(max_escalations_per_run=1))
        state = RouterState(escalations_this_run=1)
        decision = router.route(_esc("consultation", "r", "api_a"), state)
        assert isinstance(decision, RouteToGate)
        new_state = apply_decision(decision, state)
        assert new_state.escalations_this_run == 1

    def test_apply_accumulates_cost(self) -> None:
        router = ModelRouter()
        state = RouterState(escalation_cost=0.5)
        decision = router.route(_esc("consultation", "r", "api_a"), state)
        new_state = apply_decision(decision, state, cost=0.3)
        assert new_state.escalation_cost == pytest.approx(0.8)


class TestDeterminism:
    """Same inputs -> same decision; the router is a pure function."""

    def test_same_inputs_same_decision(self) -> None:
        router = ModelRouter()
        s = RouterState()
        d1 = router.route(_esc("handover", "r", "api_b"), s, current_scope=["*.py"])
        d2 = router.route(_esc("handover", "r", "api_b"), s, current_scope=["*.py"])
        assert type(d1) is type(d2)
        assert isinstance(d1, HandoverRoute) and isinstance(d2, HandoverRoute)
        assert d1 == d2

    def test_consultation_then_handover_chain_respects_limits(self) -> None:
        router = ModelRouter(
            config=RouterConfig(max_escalations_per_run=3, max_handovers_per_task=2)
        )
        state = RouterState()
        # consultation local->advice
        c = router.route(_esc("consultation", "r", "api_a"), state)
        state = apply_decision(c, state)
        assert state.current_owner == "local"
        # handover local->api_b
        h = router.route(_esc("handover", "r", "api_b"), state, current_scope=["*.py"])
        assert isinstance(h, HandoverRoute)
        state = apply_decision(h, state)
        assert state.current_owner == "api_b"
        # api_b tries to hand back to local -> ping-pong rejected
        back = router.route(
            _esc("handover", "r", "local"), state, current_scope=["*.py"]
        )
        assert isinstance(back, RouteRejected)
        # third escalation would exceed max_escalations_per_run=3 (already 2 used)
        state = apply_decision(back, state)  # rejection changes nothing
        third = router.route(_esc("consultation", "r", "api_a"), state)
        # 2 escalations used, one more allowed (cap 3)
        assert isinstance(third, ConsultRoute)
        state = apply_decision(third, state)
        # 4th escalation -> gate
        fourth = router.route(_esc("consultation", "r", "api_a"), state)
        assert isinstance(fourth, RouteToGate)
