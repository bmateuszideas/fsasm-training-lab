"""FS-ASM Runtime v1 (T25) — consistent trajectories over existing IDs.

Architecture §35 defines the target trajectory:

::

    task → context → model response → tool call → observation
        → independent verification → evidence → accepted result

T25 composes the *existing* identifiers that the runtime already produces
(``run_id`` / ``task_id`` / ``attempt`` / ``step`` / ``operation_id`` /
``artifact_id`` / ``evidence_id`` / verification status) into a single
correlatable, append-only :class:`Trajectory` record. The trajectory is an
**audit projection only** (architecture §35, canonical TODO T25): it is NOT a
second source of truth and never grants PASS, retry or gate. PASS lives
exclusively in the authoritative snapshot applied by the Domain Core. Losing
the auxiliary trajectory log must not change the accepted state — the
trajectory is reconstructable from the snapshot + evidence, and the snapshot
remains the single authority.

The trajectory records backend, counters, time and tokens/cost **only when
the provider reports them** (architecture §34: "jeśli backend je udostępnia").
Absence is honest (``None``), never fabricated. No separate monitoring
platform and no fine-tuning pipeline are built here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fsasm.models import EvidenceRecord, ToolObservation, VerificationResult
from fsasm.model_types import (
    BudgetUsage,
    EscalationRequest,
    ModelResult,
    ModelUsage,
)


class TrajectoryEventKind(str, Enum):
    """The kinds of events a trajectory records (architecture §35 sequence).

    These mirror the existing runtime boundaries; each carries only the
    identifiers the corresponding runtime component already produced. They are
    ordered to match the §35 sequence but a :class:`Trajectory` is append-only:
    ordering is the caller's responsibility (the driver emits events as they
    happen), not an enforced schema.
    """

    TASK_CONTEXT = "task_context"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"
    VERIFICATION = "verification"
    EVIDENCE = "evidence"
    STATE_TRANSITION = "state_transition"
    ESCALATION = "escalation"


@dataclass
class TrajectoryEvent:
    """One correlatable event in a task attempt's trajectory (audit only).

    Carries the identifiers that bind it to a single ``run_id`` / ``task_id`` /
    ``attempt`` (and ``step`` for model/tool calls), plus the event kind and a
    small structured payload. The payload is a plain dict of already-known
    values (no provider types, no PASS claim); it is never an authority for
    state. ``backend`` / ``usage`` / ``duration_ms`` are recorded only when
    available — ``None`` means "not reported", never fabricated.
    """

    run_id: str
    task_id: str
    attempt: int
    step: int
    kind: TrajectoryEventKind
    operation_id: str | None = None
    artifact_id: str | None = None
    evidence_id: str | None = None
    backend: str | None = None
    usage: ModelUsage | None = None
    duration_ms: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False

    def correlation_key(self) -> tuple[str, str, int]:
        """Stable key correlating events of one attempt."""

        return (self.run_id, self.task_id, self.attempt)


@dataclass
class Trajectory:
    """An append-only, correlatable trajectory for one run (audit only).

    The trajectory is a diagnostic projection: it never grants PASS and never
    substitutes for the snapshot. ``events`` are appended in occurrence order;
    ``usage_total`` aggregates tokens/cost across model calls only when the
    provider reported them (absent fields stay ``None``).
    """

    run_id: str
    events: list[TrajectoryEvent] = field(default_factory=list)

    def append(self, event: TrajectoryEvent) -> TrajectoryEvent:
        """Append one event (immutable view: returns the appended event)."""

        self.events.append(event)
        return event

    # -- aggregate counters (only when available) ---------------------------

    def model_calls(self) -> int:
        """Count of recorded model calls (when the backend reported them)."""

        return sum(1 for e in self.events if e.kind == TrajectoryEventKind.MODEL_CALL)

    def tool_calls(self) -> int:
        """Count of recorded tool calls."""

        return sum(1 for e in self.events if e.kind == TrajectoryEventKind.TOOL_CALL)

    def observations(self) -> int:
        """Count of recorded observations."""

        return sum(1 for e in self.events if e.kind == TrajectoryEventKind.OBSERVATION)

    def usage_total(self) -> ModelUsage:
        """Aggregate token/cost usage across model calls (None where absent).

        Fields are summed only across model calls that reported a value;
        a field stays ``None`` when no call reported it (honest absence).
        """

        prompt = completion = total = cost = None
        duration = None
        for e in self.events:
            if e.kind != TrajectoryEventKind.MODEL_CALL or e.usage is None:
                continue
            u = e.usage
            if u.prompt_tokens is not None:
                prompt = (prompt or 0) + u.prompt_tokens
            if u.completion_tokens is not None:
                completion = (completion or 0) + u.completion_tokens
            if u.total_tokens is not None:
                total = (total or 0) + u.total_tokens
            if u.cost is not None:
                cost = (cost or 0.0) + u.cost
            if u.duration_ms is not None:
                duration = (duration or 0) + u.duration_ms
        return ModelUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cost=cost,
            duration_ms=duration,
        )

    def for_attempt(self, task_id: str, attempt: int) -> list[TrajectoryEvent]:
        """Events of one attempt, in append order (correlation view)."""

        return [e for e in self.events if e.task_id == task_id and e.attempt == attempt]

    def backends(self) -> list[str]:
        """Distinct backends that reported at least one model call."""

        seen: list[str] = []
        for e in self.events:
            if e.kind == TrajectoryEventKind.MODEL_CALL and e.backend:
                if e.backend not in seen:
                    seen.append(e.backend)
        return seen

    def to_report(self) -> dict[str, Any]:
        """A serializable, PASS-free summary (machine-readable audit view).

        Never includes PASS authority: this is a diagnostic projection. The
        authoritative state lives in the snapshot. Callers should redact the
        serialized payload before writing it anywhere persistent (T25
        secret-redaction).
        """

        return {
            "run_id": self.run_id,
            "event_count": len(self.events),
            "model_calls": self.model_calls(),
            "tool_calls": self.tool_calls(),
            "observations": self.observations(),
            "backends": self.backends(),
            "usage_total": self.usage_total().model_dump(exclude_none=True),
            "events": [
                {
                    "run_id": e.run_id,
                    "task_id": e.task_id,
                    "attempt": e.attempt,
                    "step": e.step,
                    "kind": e.kind.value,
                    "operation_id": e.operation_id,
                    "artifact_id": e.artifact_id,
                    "evidence_id": e.evidence_id,
                    "backend": e.backend,
                    "duration_ms": e.duration_ms,
                    "redacted": e.redacted,
                }
                for e in self.events
            ],
        }


# -- builders that compose existing runtime objects into trajectory events --
#
# Each builder is a pure function that reads an existing runtime object and
# returns a TrajectoryEvent carrying only the identifiers that object already
# has. They never fabricate identifiers and never grant PASS.


def task_context_event(
    run_id: str, task_id: str, attempt: int, context_chars: int
) -> TrajectoryEvent:
    """Record the context built for an attempt (§35: task → context)."""

    return TrajectoryEvent(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        step=0,
        kind=TrajectoryEventKind.TASK_CONTEXT,
        payload={"context_chars": context_chars},
    )


def model_call_event(result: ModelResult) -> TrajectoryEvent:
    """Record one model call from a normalized :class:`ModelResult`.

    Records ``backend`` and ``usage`` only when the provider reported them
    (architecture §34). The response variant is recorded by kind only, never
    as a PASS claim.
    """

    kind_name = type(result.response).__name__
    usage = result.usage if _usage_reported(result.usage) else None
    return TrajectoryEvent(
        run_id=result.run_id,
        task_id=result.task_id,
        attempt=result.attempt,
        step=result.step,
        kind=TrajectoryEventKind.MODEL_CALL,
        backend=result.backend or None,
        usage=usage,
        payload={"response_kind": kind_name},
    )


def tool_call_event(
    run_id: str,
    task_id: str,
    attempt: int,
    step: int,
    operation_id: str,
    tool_name: str,
) -> TrajectoryEvent:
    """Record one tool call (§35: model response → tool call)."""

    return TrajectoryEvent(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        step=step,
        kind=TrajectoryEventKind.TOOL_CALL,
        operation_id=operation_id,
        payload={"tool_name": tool_name},
    )


def observation_event(
    run_id: str,
    task_id: str,
    attempt: int,
    step: int,
    observation: ToolObservation,
) -> TrajectoryEvent:
    """Record one tool observation (§35: tool call → observation).

    ``ToolObservation`` carries ``operation_id`` but not the run/task/attempt it
    belongs to (the Broker is scope-bound, not state-bound). The driver supplies
    the correlation identity so the event shares the attempt's key. The
    observation binds the event to its ``operation_id`` and records timing when
    the broker measured it. The observation body is not embedded in the payload
    (callers redact + serialize it separately) to keep the trajectory a compact
    correlation log.
    """

    return TrajectoryEvent(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        step=step,
        kind=TrajectoryEventKind.OBSERVATION,
        operation_id=observation.operation_id,
        duration_ms=observation.duration_ms,
        payload={"kind": observation.kind.value, "ok": observation.ok},
    )


def verification_event(
    run_id: str, task_id: str, attempt: int, result: VerificationResult
) -> TrajectoryEvent:
    """Record a verification result (§35: observation → verification).

    Records the verification status as a *fact*, not as authority: PASS here
    is an observed status, not a transition. The Domain Core is the only
    component that grants the PASS transition (recorded separately as
    STATE_TRANSITION).
    """

    evidence_refs = list(result.evidence_refs) if result.evidence_refs else []
    return TrajectoryEvent(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        step=0,
        kind=TrajectoryEventKind.VERIFICATION,
        artifact_id=result.artifact_id,
        payload={
            "status": result.status.value,
            "evidence_refs": evidence_refs,
            "message": result.message,
        },
    )


def evidence_event(run_id: str, evidence: EvidenceRecord) -> TrajectoryEvent:
    """Record one accepted evidence record (§35: verification → evidence)."""

    return TrajectoryEvent(
        run_id=run_id,
        task_id=evidence.task_id or "",
        attempt=evidence.attempt or 0,
        step=0,
        kind=TrajectoryEventKind.EVIDENCE,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        operation_id=evidence.operation_id,
        payload={"kind": evidence.kind, "source": evidence.source},
    )


def state_transition_event(
    run_id: str,
    task_id: str,
    attempt: int,
    event_name: str,
    *,
    passed: bool | None = None,
) -> TrajectoryEvent:
    """Record a Domain Core state transition (§35: evidence → accepted result).

    ``event_name`` is the domain event class name (e.g. ``TaskVerificationPassed``).
    ``passed`` records the observed outcome of the transition; this is the ONLY
    place the trajectory mentions a PASS *transition*, and it is a recorded
    fact about what the Domain Core decided — the authority remains the
    snapshot. The trajectory cannot grant or revoke a PASS.
    """

    payload: dict[str, Any] = {"event": event_name}
    if passed is not None:
        payload["passed"] = passed
    return TrajectoryEvent(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        step=0,
        kind=TrajectoryEventKind.STATE_TRANSITION,
        payload=payload,
    )


def escalation_event(
    run_id: str,
    task_id: str,
    attempt: int,
    escalation: EscalationRequest,
) -> TrajectoryEvent:
    """Record an escalation request (consultation/handover; audit only)."""

    return TrajectoryEvent(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        step=0,
        kind=TrajectoryEventKind.ESCALATION,
        payload={
            "kind": escalation.kind,
            "target": escalation.target,
            "reason": escalation.reason,
        },
    )


def from_budget_usage(usage: BudgetUsage) -> ModelUsage | None:
    """Project a :class:`BudgetUsage` (Executor counters) into trajectory usage.

    Returns ``None`` when the usage carries no token/cost information (a local
    backend may report none). Only the token/cost/time fields are projected;
    counters are recorded as event counts in :class:`Trajectory`.
    """

    if not _budget_has_usage(usage):
        return None
    # Project the Executor's live counters (tokens/cost/time) into the
    # trajectory's normalized usage. tokens are a cumulative attempt total;
    # prompt/completion split is not available from BudgetUsage, so it stays
    # honest None. counters (model_calls/tool_calls/agent_steps) are recorded
    # as event counts in :class:`Trajectory`, not duplicated here.
    return ModelUsage(
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=usage.tokens if usage.tokens else None,
        cost=usage.cost if usage.cost else None,
        duration_ms=usage.elapsed_ms if usage.elapsed_ms else None,
    )


def _usage_reported(usage: ModelUsage | None) -> bool:
    """True when a :class:`ModelUsage` actually reported any field."""

    if usage is None:
        return False
    return any(
        v is not None
        for v in (
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
            usage.cost,
            usage.duration_ms,
        )
    )


def _budget_has_usage(usage: BudgetUsage) -> bool:
    """True when a :class:`BudgetUsage` carries any token/cost/time value.

    Counters (model_calls/tool_calls/agent_steps) are always present; the
    diagnostic projection only matters when tokens, cost or elapsed time are
    non-zero.
    """

    return bool(usage.tokens or usage.cost or usage.elapsed_ms)
