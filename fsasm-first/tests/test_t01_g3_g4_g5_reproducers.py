"""T01 — independent reproduction of G3, G4 and G5 on the current HEAD.

Per the canonical TODO T01, this file reproduces the three Human Gate defects
described in the Astra audit against the *actual current* implementation. It
makes NO production code changes and asserts nothing about a "corrected"
contract; it only records an observable PRESENT/ABSENT/INCONCLUSIVE outcome per
case. The existing `test_m4_correction3_reproducers.py` tests assert the
in-memory buffer and the inner rejection record; the audit (§5.5) explicitly
notes those assertions are too weak to detect G4/G5. These reproducers target
the precise mechanisms:

- G3: a legacy signal without gate_id/decision_id was keyed into
  `accepted_decisions` under the *current* gate. After that gate closed and a
  new gate opened, the same unmarked payload was accepted *again* as a new
  decision for the new gate (re-authorization), because nothing binds the first
  consent to the first gate occurrence. **Fixed by T03 / policy 1** — the handler
  now rejects any payload missing run_id/gate_id/decision_id as
  `incomplete_payload` before reserving a gate, so an unmarked consent can
  never authorize any gate occurrence. The G3 reproducer below asserts the
  FIXED contract (ABSENT) and is a regression guard; a complete-ID payload for
  the open gate is still accepted.

- G4: `_flush_pending_rejections` previously passed
  `tag if tag is not None else gate_id` to
  `persist_human_gate_rejections_activity`, so a `no_open_gate` rejection
  (gate_id None) was flushed under the currently open gate id in the durable
  envelope. **Fixed by T02** — the record's own tag (None) is now passed and the
  envelope carries None. The G4 reproducer below asserts the FIXED contract
  (ABSENT) and is a regression guard.

- G5: `_flush_pending_rejections` previously set
  `self.flushed_rejections = len(self.pending_rejections)` after the awaits, so a
  rejection appended during an await was skipped by the cursor jump. **Fixed by
  T02** — the cursor now advances only over the slice snapshot before the
  awaits, leaving late records for the next drain. The G5 reproducer below
  asserts the FIXED contract (ABSENT) and is a regression guard.

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
    """G3 regression guard (fixed by T03 / policy 1): a legacy payload without
    gate_id/decision_id/run_id is rejected as ``incomplete_payload`` for BOTH
    gate-1 and gate-2, so an unmarked consent can never authorize (or
    re-authorize) any gate occurrence. PRESENT would mean the legacy consent
    was accepted/re-assigned again. A complete-ID payload for the open gate is
    still accepted (legitimate path preserved)."""

    @pytest.mark.asyncio
    async def test_g3_legacy_payload_rejected_for_both_gates(self):
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

        # Legacy payload must NOT be accepted for gate-1 (incomplete_payload).
        gate1_accepted = gate1 in wf.accepted_decisions
        gate1_rejected = any(
            r.get("reason") == "incomplete_payload" for r in wf.pending_rejections
        )

        # Simulate gate-1 closure and gate-2 opening.
        wf.accepted_decisions.pop(gate1, None)
        _close_gate(wf)
        gate2 = _open_gate(wf, run_id, task_id, attempt=2)
        assert gate2 != gate1

        # Re-send the IDENTICAL legacy payload (no IDs).
        await wf.receive_human_decision(legacy)
        gate2_accepted = gate2 in wf.accepted_decisions
        gate2_rejected_after = any(
            r.get("reason") == "incomplete_payload" for r in wf.pending_rejections
        )

        # A complete-ID payload for the open gate-2 is still accepted.
        complete = HumanDecisionSignal(
            run_id=run_id,
            task_id=task_id,
            action=HumanDecisionAction.RETRY_ONCE,
            reason="complete consent",
            gate_id=gate2,
            decision_id=f"decision-{run_id}-{task_id}-{gate2}-RETRY_ONCE",
        )
        await wf.receive_human_decision(complete)
        complete_accepted = gate2 in wf.accepted_decisions

        g3_absent = (
            not gate1_accepted
            and not gate2_accepted
            and gate1_rejected
            and gate2_rejected_after
            and complete_accepted
        )
        result = "ABSENT" if g3_absent else "PRESENT"
        detail = {
            "gate1": gate1,
            "gate2": gate2,
            "gate1_accepted": gate1_accepted,
            "gate2_accepted": gate2_accepted,
            "gate1_incomplete_rejected": gate1_rejected,
            "gate2_incomplete_rejected": gate2_rejected_after,
            "complete_payload_accepted": complete_accepted,
            "accepted_decisions_keys": list(wf.accepted_decisions.keys()),
        }
        print(f"\n[G3] result={result} detail={detail}")
        assert g3_absent, (
            "G3 PRESENT on this HEAD: a legacy payload without IDs was "
            "accepted (or re-accepted) for a gate, or the complete-ID path "
            "broke."
        )


# =============================================================================
# G4 — rejection before an open gate is attributed to the current gate envelope
# =============================================================================


class TestG4NoOpenGateRejectionMisattributedEnvelope:
    """G4 regression guard (fixed by T02): a `no_open_gate` rejection has its own
    `gate_id=None`. `_flush_pending_rejections` must pass the record's own tag
    (None) to the persist activity so the durable envelope's `gate_id` is None,
    not the currently open gate id. PRESENT means the misattribution returned."""

    @pytest.mark.asyncio
    async def test_g4_persisted_envelope_carries_open_gate_not_none(self):
        wf = FsasmMilestoneFourWorkflow()
        run_id = "run-g4"
        task_id = "TASK-001"

        # 1) A complete-ID signal arrives while NO gate is open. It passes the
        #    incomplete_payload check (full IDs) but is rejected as no_open_gate
        #    (current_gate is None); the rejection is recorded with its own gate
        #    tag None (current_gate_id is None when no gate is open).
        future_gate = _gate_id(run_id, task_id, 1)
        await wf.receive_human_decision(
            HumanDecisionSignal(
                run_id=run_id,
                task_id=task_id,
                action=HumanDecisionAction.RETRY_ONCE,
                reason="before gate",
                gate_id=future_gate,
                decision_id=f"decision-{run_id}-{task_id}-{future_gate}-RETRY_ONCE",
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

        # G4 (fixed by T02): the persisted envelope gate_id MUST be None (the
        # rejection's own tag), never the currently open gate id. PRESENT would
        # mean the misattribution regression returned.
        g4_absent = envelope_gate_id is None
        result = "ABSENT" if g4_absent else "PRESENT"
        detail = {
            "open_gate_id": gate1,
            "inner_record_gate_id": no_open[0]["gate_id"],
            "envelope_gate_id": envelope_gate_id,
            "envelope_rejections_count": len(envelope.get("rejections", [])),
        }
        print(f"\n[G4] result={result} detail={detail}")
        assert g4_absent, (
            "G4 PRESENT on this HEAD: a no_open_gate rejection was flushed "
            "under the open gate id in the durable envelope instead of None."
        )


# =============================================================================
# G5 — a signal arriving during flush await can be skipped by the cursor
# =============================================================================


class TestG5LateRejectionSkippedByCursorDuringAwait:
    """G5 regression guard (fixed by T02): during the `await` inside
    `_flush_pending_rejections`, a second rejection is appended. The cursor must
    advance only over the slice snapshot before the awaits, so the late
    rejection is persisted on a subsequent flush. PRESENT means the cursor-skip
    returned.

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
        # G5 (fixed by T02): the late rejection appended during the persist
        # await MUST be persisted on a subsequent flush. PRESENT would mean the
        # cursor-skip regression returned.
        g5_absent = (
            late_appended is not None and late_appended in persisted_rejection_ids
        )

        result = "ABSENT" if g5_absent else "PRESENT"
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
        assert g5_absent, (
            "G5 PRESENT on this HEAD: a rejection appended during the flush "
            "await was skipped by the cursor and never persisted."
        )
