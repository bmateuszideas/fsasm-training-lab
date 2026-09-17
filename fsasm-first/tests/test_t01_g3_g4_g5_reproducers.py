"""T01 — independent reproduction of G3, G4 and G5 on the current HEAD.

Per the canonical TODO T01, this file reproduces the three Human Gate defects
described in the Astra audit against the *actual current* implementation. It
makes NO production code changes and asserts nothing about a "corrected"
contract; it only records an observable PRESENT/ABSENT/INCONCLUSIVE outcome per
case. The existing `test_m4_correction3_reproducers.py` tests assert the
in-memory buffer and the inner rejection record; the audit (§5.5) explicitly
notes those assertions are too weak to detect G4/G5. These reproducers target
the precise mechanisms:

- G3: a legacy signal without gate_id/decision_id is keyed into
  `accepted_decisions` under the *current* gate. After that gate closes and a
  new gate opens, the same unmarked payload is accepted *again* as a new
  decision for the new gate (re-authorization), because nothing binds the first
  consent to the first gate occurrence.

- G4: `_flush_pending_rejections` passes `tag if tag is not None else gate_id`
  to `persist_human_gate_rejections_activity`. A `no_open_gate` rejection has
  `gate_id=None` (tag None), so the durable envelope's `gate_id` field receives
  the *currently open* external gate id, contradicting the docstring claim that
  it is "flushed with gate_id None".

- G5: `_flush_pending_rejections` snapshots the batch from the current cursor
  slice, then performs an `await`. After the await it sets
  `self.flushed_rejections = len(self.pending_rejections)` (the *current* total
  length). A rejection appended during the await is neither in the snapshot
  batch nor persisted, yet the cursor jumps past it, so a subsequent flush sees
  `flushed_rejections >= len(...)` and returns early — the late rejection is
  skipped.

These tests drive the workflow component and the persist activity directly with
controlled barriers (no Temporal worker), matching the audit's §11.2 procedure.
A worker is not required because the G3/G4/G5 mechanisms are pure in-memory
Python in the workflow class and the persist activity.
"""

import asyncio
from typing import Any

import pytest

from fsasm.persistence import RuntimePersistence
from fsasm.models import HumanDecisionAction
from src.workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    HumanDecisionSignal,
    OpenGate,
    _gate_id,
    persist_human_gate_rejections_activity,
)


@pytest.fixture(autouse=True)
def cleanup_runtime():
    p = RuntimePersistence()
    p.cleanup_all()
    yield
    p.cleanup_all()


def _open_gate(
    wf: FsasmMilestoneFourWorkflow, run_id: str, task_id: str, attempt: int
) -> str:
    gate_id = _gate_id(run_id, task_id, attempt)
    wf.current_gate = OpenGate(
        run_id=run_id, task_id=task_id, gate_id=gate_id, attempt=attempt
    )
    wf.current_gate_id = gate_id
    return gate_id


def _close_gate(wf: FsasmMilestoneFourWorkflow) -> None:
    wf.current_gate = None
    wf.current_gate_id = None


# =============================================================================
# G3 — missing gate_id allows re-assigning an old consent to a new gate
# =============================================================================


class TestG3LegacyConsentReassignedAcrossGates:
    """Reproduce the audit G3: the same legacy payload (no gate_id, no
    decision_id) is accepted for gate-1 and, after gate closure and a new gate
    opening, accepted again for gate-2. The observation is whether the second
    acceptance occurs."""

    @pytest.mark.asyncio
    async def test_g3_legacy_payload_accepted_for_two_distinct_gates(self):
        wf = FsasmMilestoneFourWorkflow()
        run_id = "run-g3"
        task_id = "TASK-001"

        gate1 = _open_gate(wf, run_id, task_id, attempt=1)
        legacy = HumanDecisionSignal(
            task_id=task_id,
            action=HumanDecisionAction.RETRY_ONCE,
            reason="one consent",
        )
        await wf.receive_human_decision(legacy)

        assert gate1 in wf.accepted_decisions, (
            "Setup precondition: legacy payload must be accepted for gate-1"
        )
        accepted_for_gate1 = wf.accepted_decisions[gate1]
        assert accepted_for_gate1.gate_id == gate1
        first_decision_id = accepted_for_gate1.decision_id

        # Simulate gate-1 closure (the workflow removes the entry after applying).
        wf.accepted_decisions.pop(gate1, None)
        _close_gate(wf)

        gate2 = _open_gate(wf, run_id, task_id, attempt=2)
        assert gate2 != gate1

        # Re-send the IDENTICAL legacy payload (same task_id/action/reason, no IDs).
        await wf.receive_human_decision(legacy)

        g3_present = gate2 in wf.accepted_decisions
        second_decision = wf.accepted_decisions.get(gate2)
        g3_new_decision_id = (
            second_decision is not None
            and second_decision.decision_id != first_decision_id
        )

        result = "PRESENT" if g3_present else "ABSENT"
        detail = {
            "gate1": gate1,
            "gate2": gate2,
            "accepted_for_gate1_id": first_decision_id,
            "gate2_in_accepted_decisions": g3_present,
            "gate2_decision_id": getattr(second_decision, "decision_id", None),
            "gate2_decision_id_is_new": g3_new_decision_id,
            "accepted_decisions_keys": list(wf.accepted_decisions.keys()),
        }
        # Record the outcome explicitly; never assert a "corrected" contract here.
        print(f"\n[G3] result={result} detail={detail}")
        assert g3_present, (
            "G3 ABSENT on this HEAD: the identical legacy payload was NOT "
            "re-accepted for gate-2. If this fires, G3 has been fixed and the "
            "report should record ABSENT."
        )


# =============================================================================
# G4 — rejection before an open gate is attributed to the current gate envelope
# =============================================================================


class TestG4NoOpenGateRejectionMisattributedEnvelope:
    """Reproduce the audit G4: a `no_open_gate` rejection has its own
    `gate_id=None`, but `_flush_pending_rejections` substitutes the external
    currently-open `gate_id` into the durable envelope when the record's tag is
    None. The audit checks the persisted envelope, not the in-memory record
    (which the existing tests already verify is None)."""

    @pytest.mark.asyncio
    async def test_g4_persisted_envelope_carries_open_gate_not_none(self):
        wf = FsasmMilestoneFourWorkflow()
        run_id = "run-g4"
        task_id = "TASK-001"

        # 1) A signal arrives while NO gate is open -> no_open_gate rejection
        #    with its own gate_id == None.
        await wf.receive_human_decision(
            HumanDecisionSignal(
                task_id=task_id,
                action=HumanDecisionAction.RETRY_ONCE,
                reason="before gate",
            )
        )
        assert wf.current_gate is None
        no_open = [r for r in wf.pending_rejections if r["reason"] == "no_open_gate"]
        assert no_open, "Setup: a no_open_gate rejection must be buffered"
        assert no_open[0]["gate_id"] is None

        # 2) A gate opens; the workflow wait loop flushes with the open gate id.
        gate1 = _open_gate(wf, run_id, task_id, attempt=1)

        await wf._flush_pending_rejections(run_id, task_id, gate1)

        p = RuntimePersistence()
        entries = [
            e
            for e in p.load_run_log(run_id)
            if e.get("event") == "human_gate_rejected_signals"
        ]
        assert entries, "Setup: the flush must produce a durable rejection log entry"
        envelope = entries[0]
        envelope_gate_id = envelope.get("gate_id")

        # G4 is PRESENT iff the persisted envelope gate_id is the open gate (not None).
        g4_present = envelope_gate_id == gate1
        result = "PRESENT" if g4_present else "ABSENT"
        detail = {
            "open_gate_id": gate1,
            "inner_record_gate_id": no_open[0]["gate_id"],
            "envelope_gate_id": envelope_gate_id,
            "envelope_rejections_count": len(envelope.get("rejections", [])),
        }
        print(f"\n[G4] result={result} detail={detail}")
        assert g4_present, (
            "G4 ABSENT on this HEAD: the persisted envelope gate_id is None "
            "(not the open gate), so G4 has been fixed; record ABSENT."
        )


# =============================================================================
# G5 — a signal arriving during flush await can be skipped by the cursor
# =============================================================================


class TestG5LateRejectionSkippedByCursorDuringAwait:
    """Reproduce the audit G5: during the `await` inside
    `_flush_pending_rejections`, a second rejection is appended. The flush
    persists only the first batch but then sets the cursor to the *current*
    total length, so the late rejection is skipped on the next flush call.

    A controlled barrier is placed in `persist_human_gate_rejections_activity`
    (the awaited write) so the second append happens deterministically before
    the cursor update."""

    @pytest.mark.asyncio
    async def test_g5_late_rejection_skipped_by_cursor(self, monkeypatch):
        wf = FsasmMilestoneFourWorkflow()
        run_id = "run-g5"
        task_id = "TASK-001"
        gate1 = _open_gate(wf, run_id, task_id, attempt=1)

        # First rejection (will be in the snapshot batch). A distinct reason is
        # required so the deterministic rejection_id differs from the late one
        # (otherwise _append_rejection deduplicates identical payloads).
        wf._append_rejection(
            {"reason": "wrong_gate", "gate_id": gate1, "task_id": task_id}
        )

        append_late = asyncio.Event()
        flush_done = asyncio.Event()

        original_persist = persist_human_gate_rejections_activity

        async def barrier_persist(
            rid: str, tid: str, g: str, batch: list[dict[str, Any]]
        ) -> None:
            await original_persist(rid, tid, g, batch)
            # While the flush's await is "in progress" (we are still inside
            # _flush_pending_rejections before it updates the cursor), append a
            # late rejection with a DIFFERENT reason so it is not deduped. Then
            # let the flush proceed to its cursor update.
            if not append_late.is_set():
                append_late.set()
                wf._append_rejection(
                    {"reason": "wrong_run", "gate_id": gate1, "task_id": task_id}
                )
                flush_done.set()

        monkeypatch.setattr(
            "src.workflows.fsasm_milestone_four.persist_human_gate_rejections_activity",
            barrier_persist,
        )

        # First flush: persists first batch, appends late rejection during await,
        # then the real code sets cursor = len(pending) (2), skipping the late one.
        await wf._flush_pending_rejections(run_id, task_id, gate1)

        await asyncio.wait_for(flush_done.wait(), timeout=5)

        # Second flush: should persist the late rejection if G5 is ABSENT.
        await wf._flush_pending_rejections(run_id, task_id, gate1)

        p = RuntimePersistence()
        entries = [
            e
            for e in p.load_run_log(run_id)
            if e.get("event") == "human_gate_rejected_signals"
        ]
        persisted_rejection_ids: list[str] = []
        for e in entries:
            for r in e.get("rejections", []):
                if r.get("rejection_id"):
                    persisted_rejection_ids.append(r["rejection_id"])

        in_memory_ids = [r.get("rejection_id") for r in wf.pending_rejections]
        late_appended = in_memory_ids[1] if len(in_memory_ids) > 1 else None
        g5_present = (
            late_appended is not None and late_appended not in persisted_rejection_ids
        )

        result = "PRESENT" if g5_present else "ABSENT"
        detail = {
            "in_memory_rejection_ids": in_memory_ids,
            "persisted_rejection_ids": persisted_rejection_ids,
            "late_rejection_id": late_appended,
            "late_was_persisted": late_appended in persisted_rejection_ids
            if late_appended
            else None,
            "flushed_rejections_cursor": wf.flushed_rejections,
            "num_log_entries": len(entries),
        }
        print(f"\n[G5] result={result} detail={detail}")
        assert g5_present, (
            "G5 ABSENT on this HEAD: the late rejection was persisted on the "
            "second flush, so the cursor no longer skips it; record ABSENT."
        )
