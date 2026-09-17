"""FS-ASM Runtime v1 (T18) — retry merytoryczne i feedback poprzedniej próby.

Owns the retry decision AFTER an Executor attempt terminates, separating the
three retry measures the architecture keeps distinct (§24, §42):

- ``task_attempt`` — a full re-execution of the task. Only the Domain Core
  grants it, and only after a merytoryczna verification FAIL (not a transport
  error). The next attempt's Context carries concrete feedback from the prior
  failure.
- ``technical retry`` — re-running the SAME attempt after a transport error
  (:class:`ModelError`). It does NOT bump ``task_attempt`` and does NOT repeat
  a non-idempotent effect blindly; it is bounded by a small transport retry
  budget so a persistently failing backend cannot loop forever.
- ``agent_step`` — handled inside the Executor Loop (T17); never reaches here.

Exhaustion of ``max_attempts`` routes to the approved escalation/Human Gate
path (``TaskEscalated``), never to an infinite loop. A transport retry never
consumes a merytoryczna attempt; a tool call never consumes an attempt. The
retry layer grants no PASS and no transition itself: it returns a decision the
driver (workflow / real_effects-style driver) applies through the Domain Core
(architecture §24, §42; canonical TODO T18).

The feedback builder produces concrete, honest strings for the next attempt's
Context Builder: the prior verification failure message plus a summary of the
failed observations and the current artifact content (read via the Broker, so
the boundary stays enforced).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from fsasm.executor_loop import ExecutorAttemptOutcome
from fsasm.models import ChildTask, VerificationResult, VerificationResultStatus
from fsasm.tool_broker import ToolBroker


class RetryDecision(str, Enum):
    """What the retry layer decided after one Executor attempt.

    These are decisions for the driver to apply THROUGH the Domain Core; the
    retry layer grants no transition itself. ``TRANSPORT_RETRY`` re-runs the
    SAME attempt (no ``task_attempt`` bump); ``MERYTORYCZNA_RETRY`` requests a
    new ``task_attempt`` (Domain Core bumps it via ``TaskRetried``);
    ``ESCALATE`` requests the Human Gate (``TaskEscalated``) when the merytoryczna
    budget is exhausted; ``STOP`` ends the task (terminal outcome that is not a
    retry, e.g. ``COMPLETED``/``ESCALATION_REQUESTED``/``POLICY_BLOCKED``).
    """

    TRANSPORT_RETRY = "transport_retry"
    MERYTORYCZNA_RETRY = "merytoryczna_retry"
    ESCALATE = "escalate"
    STOP = "stop"


@dataclass
class RetryVerdict:
    """The retry layer's verdict for one Executor attempt.

    Carries the :class:`RetryDecision`, the concrete feedback for the next
    attempt (``prior_observations`` / ``prior_verification``), and the transport
    retry counter so a persistently failing backend is bounded. The driver
    applies the decision through the Domain Core; the verdict grants no PASS
    and no transition.
    """

    decision: RetryDecision
    prior_observations: list[str] = field(default_factory=list)
    prior_verification: str = ""
    transport_retries: int = 0
    note: str = ""


@dataclass
class TransportRetryBudget:
    """Bounded counter for transport retries of the SAME attempt.

    A transport retry re-runs the same ``task_attempt`` after a
    :class:`ModelError`; it must be bounded so a persistently failing backend
    cannot loop forever. It never touches ``task_attempt``. When exhausted,
    the retry layer escalates (transport failure is not a merytoryczna FAIL,
    but the run cannot proceed; the driver routes to the gate/stop).
    """

    max_transport_retries: int = 2
    _used: int = 0

    def can_retry(self) -> bool:
        return self._used < self.max_transport_retries

    def consume(self) -> None:
        self._used += 1

    @property
    def used(self) -> int:
        return self._used


def classify_attempt(
    outcome: ExecutorAttemptOutcome,
    task: ChildTask,
    transport_budget: TransportRetryBudget,
    *,
    verification_result: VerificationResult | None = None,
) -> RetryVerdict:
    """Decide the retry action after one Executor attempt.

    Decision order (architecture §24, §42):

    1. Terminal non-error outcomes (``COMPLETED``, ``ESCALATION_REQUESTED``,
       ``POLICY_BLOCKED``) are ``STOP`` — the driver hands ``COMPLETED`` to the
       Verification Plane; the others are already terminal.
    2. A transport error (``TOOL_ERROR`` carrying a :class:`ModelError`) is a
       ``TRANSPORT_RETRY`` of the SAME attempt if the transport budget remains;
       otherwise ``ESCALATE`` (transport failure cannot loop forever and is
       not a merytoryczna FAIL).
    3. A ``TOOL_ERROR`` without a transport error (e.g. persistent invalid
       output) is treated as a merytoryczna failure: retry if the task budget
       remains, else escalate.
    4. A verification FAIL (``verification_result.status == FAIL``) is a
       ``MERYTORYCZNA_RETRY`` if ``task.can_retry()``, else ``ESCALATE``.

    A transport retry never consumes a ``task_attempt``; a tool call never
    consumes an attempt. The verdict grants no PASS.
    """
    reason = outcome.reason

    # 1. A verification FAIL is a merytoryczna failure regardless of the
    #    Executor terminal reason (a COMPLETED outcome requests verification;
    #    if the Verifier FAILs, the Domain Core owns the retry decision).
    if (
        verification_result is not None
        and verification_result.status == VerificationResultStatus.FAIL
    ):
        if task.can_retry():
            prior_obs, prior_ver = build_retry_feedback(outcome, verification_result)
            return RetryVerdict(
                decision=RetryDecision.MERYTORYCZNA_RETRY,
                prior_observations=prior_obs,
                prior_verification=prior_ver,
                note="merytoryczna verification FAIL; retry with prior feedback",
            )
        return RetryVerdict(
            decision=RetryDecision.ESCALATE,
            note="max_attempts exhausted after verification FAIL -> human gate",
        )

    # 2. Transport error: bounded retry of the SAME attempt (no attempt bump).
    if reason.value == "tool_error" and outcome.transport_error is not None:
        if transport_budget.can_retry():
            transport_budget.consume()
            return RetryVerdict(
                decision=RetryDecision.TRANSPORT_RETRY,
                transport_retries=transport_budget.used,
                note=f"transport error: {outcome.transport_error.kind.value}",
            )
        return RetryVerdict(
            decision=RetryDecision.ESCALATE,
            transport_retries=transport_budget.used,
            note="transport retry budget exhausted",
        )

    # 3. Terminal non-error outcomes: stop (the driver routes COMPLETED to
    #    verification; the others are already terminal).
    if reason.value in ("completed", "escalation_requested", "policy_blocked"):
        return RetryVerdict(
            decision=RetryDecision.STOP, note=f"terminal {reason.value}"
        )

    # 4. Non-transport TOOL_ERROR / STEP_LIMIT_REACHED: a merytoryczna failure
    #    (e.g. persistent invalid output, or step-budget exhaustion). Retry if
    #    the task budget remains, else escalate.
    if task.can_retry():
        prior_obs, prior_ver = build_retry_feedback(outcome, verification_result)
        return RetryVerdict(
            decision=RetryDecision.MERYTORYCZNA_RETRY,
            prior_observations=prior_obs,
            prior_verification=prior_ver,
            note=f"merytoryczna failure ({reason.value}); retry with prior feedback",
        )
    return RetryVerdict(
        decision=RetryDecision.ESCALATE,
        note="max_attempts exhausted -> human gate",
    )


def build_retry_feedback(
    outcome: ExecutorAttemptOutcome,
    verification_result: VerificationResult | None,
    *,
    broker: ToolBroker | None = None,
    artifact_path: str | None = None,
    allowed_files: list[str] | None = None,
) -> tuple[list[str], str]:
    """Build concrete feedback for the next attempt's Context Builder.

    Returns ``(prior_observations, prior_verification)``:

    - ``prior_observations``: a concise, honest summary of the failed
      attempt's tool observations (what the model did and what the tools
      reported), so the next attempt knows the prior concrete failure.
    - ``prior_verification``: the verification failure message (the Verifier's
      reason the artifact/check did not PASS), plus the current artifact
      content when a Broker and artifact path are supplied (read through the
      Broker so the scope boundary stays enforced).

    The feedback is honest: it never claims success and never invents an
    artifact. Missing observations/verification yield empty strings, not
    fabricated content.
    """
    prior_observations: list[str] = []
    for obs in outcome.observations:
        if obs.blocked:
            prior_observations.append(
                f"prior tool {obs.kind.value} BLOCKED: {obs.reason}"
            )
        elif not obs.ok:
            prior_observations.append(
                f"prior tool {obs.kind.value} ERROR: {obs.reason}"
            )
        else:
            summary = f"prior tool {obs.kind.value} OK"
            if obs.artifact_path:
                summary += f" on {obs.artifact_path}"
            if obs.exit_code is not None:
                summary += f" (exit {obs.exit_code})"
            prior_observations.append(summary)

    parts: list[str] = []
    if verification_result is not None:
        status = (
            verification_result.status.value
            if isinstance(verification_result.status, VerificationResultStatus)
            else str(verification_result.status)
        )
        msg = f"prior verification {status}"
        if verification_result.message:
            msg += f": {verification_result.message}"
        parts.append(msg)
    else:
        # No verification result (e.g. transport/invalid terminal): report the
        # terminal reason honestly as the failure cause.
        parts.append(f"prior attempt terminated: {outcome.reason.value}")

    # Current artifact content, read via the Broker so scope stays enforced.
    if broker is not None and artifact_path is not None:
        obs = broker.inspect_changes(
            outcome.run_id,
            outcome.task_id,
            outcome.attempt,
            step=0,
            path=artifact_path,
            allowed_files=allowed_files,
        )
        if obs.ok and obs.content:
            parts.append(f"current artifact {obs.artifact_path}:\n{obs.content}")
        elif obs.blocked:
            parts.append(f"current artifact {artifact_path} unreadable: {obs.reason}")

    prior_verification = "; ".join(parts)
    return prior_observations, prior_verification


__all__ = [
    "RetryDecision",
    "RetryVerdict",
    "TransportRetryBudget",
    "build_retry_feedback",
    "classify_attempt",
]
