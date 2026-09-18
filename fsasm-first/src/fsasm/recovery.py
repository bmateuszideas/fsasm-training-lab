"""FS-ASM Recovery & Reconcile (T23) — partial and uncertain effects.

The runtime drives a Child Task attempt through a sequence of external effects
(patch via the Tool Broker, a real check, evidence persistence, a snapshot
commit). A crash can interrupt that sequence at four checkpoints. This module
is the **explicit reconcile** layer (architecture §15; canonical TODO T23):

1. ``BEFORE_EFFECT`` — the tool effect has NOT been applied yet.
2. ``EFFECT_APPLIED`` — the patch landed on disk, but no evidence was written
   and no commit happened.
3. ``EVIDENCE_PERSISTED`` — evidence was written to disk, but the authoritative
   snapshot commit did not happen.
4. ``COMMITTED`` — the snapshot was committed; only the activity response is
   outstanding.

At resume the runtime does NOT assume "nothing happened". It inspects the
real artifact and the committed snapshot, binds the in-flight operation to
``attempt`` / ``operation_id`` / ``artifact_id`` / evidence refs, and returns
an explicit decision: ``VERIFY`` (the real effect is present and bound — run
the verifier), ``RETRY`` (no usable effect, or a transport-level interruption
that is not a merytoryczny FAIL — try the attempt again), or ``STOP`` (the run
must halt: a committed FAIL/escalation/gate already owns the state).

This is NOT a second authoritative event store. The single authoritative
snapshot (``state.json``) plus the real artifact on disk are the only sources
of truth. The reconcile decision is diagnostic: it tells the driver what to do
next; only the Domain Core grants transitions. We do NOT declare exactly-once
execution of any external effect, and a transport error is NEVER an automatic
merytoryczny FAIL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from fsasm.models import (
    ChildTask,
    RunState,
    RunStatus,
    TaskStatus,
)

if TYPE_CHECKING:
    from fsasm.tool_broker import ToolBroker


class RecoveryCheckpoint(str, Enum):
    """The four reconcile checkpoints around one tool effect.

    The runtime records which checkpoint an in-flight attempt had reached
    before an interruption. The reconcile decision depends on the checkpoint
    AND the real on-disk state, never on the checkpoint alone.
    """

    BEFORE_EFFECT = "before_effect"
    EFFECT_APPLIED = "effect_applied"
    EVIDENCE_PERSISTED = "evidence_persisted"
    COMMITTED = "committed"


class ReconcileDecision(str, Enum):
    """The explicit outcome of reconciling an interrupted attempt.

    The driver acts on exactly one of:

    - ``VERIFY``: a real effect for the CURRENT attempt is present and bound to
      the attempt's identity. Run the independent verifier; the Domain Core
      then grants PASS/FAIL. This is the safe path that never grants PASS from
      a stale or foreign artifact.
    - ``RETRY``: no usable real effect is present (or the interruption was
      transport-level, not a merytoryczny FAIL). The attempt may be retried; it
      does NOT consume a new merytoryczna attempt by itself — the retry layer
      (T18) classifies transport vs merytoryczna separately.
    - ``STOP``: the authoritative snapshot already owns a terminal decision for
      the task/run (a committed FAIL, escalation to the Human Gate, ABORT, or
      the whole run reached a terminal state). The driver must stop; it must
      not replay a stale effect or a stale consent.
    """

    VERIFY = "verify"
    RETRY = "retry"
    STOP = "stop"


@dataclass
class OperationBinding:
    """Binds one in-flight operation to its domain identity.

    The binding ties an external effect to ``attempt`` + ``operation_id`` +
    ``artifact_id`` (+ evidence refs when evidence exists) WITHOUT creating a
    second authoritative event store. It is the provenance the reconcile layer
    reads alongside the real artifact and the snapshot.
    """

    run_id: str
    task_id: str
    attempt: int
    operation_id: str
    artifact_id: str
    artifact_path: str
    checkpoint: RecoveryCheckpoint
    evidence_refs: list[str] = field(default_factory=list)
    # True when the interruption that produced this binding was a transport
    # error (e.g. a model/HTTP failure), NOT a merytoryczna verification FAIL.
    # A transport error is never an automatic merytoryczny FAIL.
    transport_error: bool = False


@dataclass
class ReconcileReport:
    """The result of reconciling one interrupted attempt.

    Carries the explicit decision, the binding that produced it, and a
    short human-readable reason. The driver acts on ``decision``; the report
    itself grants no transitions.
    """

    decision: ReconcileDecision
    binding: OperationBinding
    reason: str
    # The real on-disk artifact content observed by the reconcile layer, when
    # an artifact was inspected. ``None`` when no artifact exists / was read.
    observed_artifact: str | None = None


def reconcile_attempt(
    state: RunState,
    binding: OperationBinding,
    observed_artifact: str | None,
) -> ReconcileReport:
    """Reconcile one interrupted attempt: inspect artifact + snapshot, decide.

    The single authoritative snapshot (``state``) and the real artifact are the
    only inputs. The reconcile layer NEVER grants PASS/retry/gate — it returns
    a diagnostic decision the driver acts on through the Domain Core.

    Decision rules (architecture §15; canonical TODO T23):

    - If the task is no longer RUNNING for this attempt in the committed
      snapshot, the snapshot already owns the outcome: ``STOP``. This covers a
      committed PASS, a committed FAIL that was retried/escalated, a Human Gate
      ABORT/RETRY, and any run-level terminal state. The driver must not replay
      a stale effect or a stale consent.
    - If the run itself is terminal (PASSED/FAILED), ``STOP`` regardless of the
      task's snapshot status.
    - Otherwise (the task is still RUNNING at this attempt in the snapshot):
      - ``EVIDENCE_PERSISTED`` / ``COMMITTED``: evidence or a commit landed for
        this attempt AND a real effect is present -> ``VERIFY`` (run the
        independent verifier on the real artifact). If the effect is absent
        despite the checkpoint, the binding is stale/inconsistent -> ``RETRY``
        (do not fabricate evidence or PASS).
      - ``EFFECT_APPLIED``: a real effect is present but no evidence/commit ->
        ``VERIFY`` (the artifact is real and bound to the attempt; the verifier
        decides). If the artifact is absent, the effect never landed -> ``RETRY``.
      - ``BEFORE_EFFECT``: the effect was never applied -> ``RETRY``. A transport
        error here is explicitly NOT a merytoryczny FAIL.

    The decision is deterministic given (state, binding, observed_artifact).
    """
    run_id = binding.run_id
    task_id = binding.task_id
    attempt = binding.attempt

    if state.run_id != run_id:
        return ReconcileReport(
            decision=ReconcileDecision.STOP,
            binding=binding,
            reason=(
                f"foreign run: binding run_id {run_id!r} does not match snapshot "
                f"run_id {state.run_id!r}"
            ),
            observed_artifact=observed_artifact,
        )

    if state.status in (RunStatus.PASSED, RunStatus.FAILED):
        return ReconcileReport(
            decision=ReconcileDecision.STOP,
            binding=binding,
            reason=f"run is terminal ({state.status.value}); snapshot owns outcome",
            observed_artifact=observed_artifact,
        )

    task = _find_task(state, task_id)
    if task is None:
        return ReconcileReport(
            decision=ReconcileDecision.STOP,
            binding=binding,
            reason=f"task {task_id!r} not in snapshot plan",
            observed_artifact=observed_artifact,
        )

    if task.status is not TaskStatus.RUNNING or task.attempt != attempt:
        return ReconcileReport(
            decision=ReconcileDecision.STOP,
            binding=binding,
            reason=(
                f"snapshot owns task outcome: {task.status.value} at attempt "
                f"{task.attempt} (binding attempt {attempt})"
            ),
            observed_artifact=observed_artifact,
        )

    effect_present = observed_artifact is not None and len(observed_artifact) > 0

    if binding.checkpoint is RecoveryCheckpoint.BEFORE_EFFECT:
        if binding.transport_error:
            return ReconcileReport(
                decision=ReconcileDecision.RETRY,
                binding=binding,
                reason=("transport error before any effect: not a merytoryczny FAIL"),
                observed_artifact=observed_artifact,
            )
        return ReconcileReport(
            decision=ReconcileDecision.RETRY,
            binding=binding,
            reason="no effect applied for this attempt",
            observed_artifact=observed_artifact,
        )

    if binding.checkpoint is RecoveryCheckpoint.EFFECT_APPLIED:
        if effect_present:
            return ReconcileReport(
                decision=ReconcileDecision.VERIFY,
                binding=binding,
                reason=(
                    f"real effect present for {binding.artifact_id}; verifier decides"
                ),
                observed_artifact=observed_artifact,
            )
        return ReconcileReport(
            decision=ReconcileDecision.RETRY,
            binding=binding,
            reason=(
                "checkpoint EFFECT_APPLIED but artifact absent; effect never landed"
            ),
            observed_artifact=observed_artifact,
        )

    # EVIDENCE_PERSISTED or COMMITTED: evidence/commit landed for this attempt.
    if not effect_present:
        return ReconcileReport(
            decision=ReconcileDecision.RETRY,
            binding=binding,
            reason=(
                f"checkpoint {binding.checkpoint.value} but no real effect "
                "present; binding is stale/inconsistent"
            ),
            observed_artifact=observed_artifact,
        )
    if not binding.evidence_refs:
        return ReconcileReport(
            decision=ReconcileDecision.RETRY,
            binding=binding,
            reason=(
                f"checkpoint {binding.checkpoint.value} but no evidence refs "
                "bound; do not fabricate evidence"
            ),
            observed_artifact=observed_artifact,
        )
    return ReconcileReport(
        decision=ReconcileDecision.VERIFY,
        binding=binding,
        reason=(
            f"real effect + evidence present for {binding.artifact_id} "
            f"({binding.checkpoint.value}); verifier decides"
        ),
        observed_artifact=observed_artifact,
    )


def _find_task(state: RunState, task_id: str) -> ChildTask | None:
    """Return the task with ``task_id`` from the run's plan, or None."""
    if state.plan is None:
        return None
    for task in state.plan.tasks:
        if task.task_id == task_id:
            return task
    return None


def inspect_artifact(
    broker: ToolBroker,
    binding: OperationBinding,
    allowed_files: list[str] | None = None,
) -> str | None:
    """Inspect the real on-disk artifact for a binding via the Tool Broker.

    Reads the actual artifact (scope-enforced by the Broker) bound to the
    attempt's ``artifact_id``/``artifact_path``. Returns the content, or ``None``
    when the artifact is absent / out of scope. This is the real inspection the
    reconcile layer performs before deciding — it never trusts a claim.
    """
    from fsasm.tool_broker import ToolBroker as _ToolBroker  # local import: avoid cycle

    if not isinstance(broker, _ToolBroker):  # pragma: no cover - defensive
        raise TypeError("broker must be a ToolBroker")
    observation = broker.inspect_changes(
        binding.run_id,
        binding.task_id,
        binding.attempt,
        step=0,
        path=binding.artifact_path,
        allowed_files=allowed_files,
    )
    if not observation.ok:
        return None
    return observation.content


__all__ = [
    "OperationBinding",
    "ReconcileDecision",
    "ReconcileReport",
    "RecoveryCheckpoint",
    "inspect_artifact",
    "reconcile_attempt",
]
