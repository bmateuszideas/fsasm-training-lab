"""T04 — complete snapshot domain model (v1 state models).

Proves the v1 snapshot contract:
- one snapshot contains plan (Task Register), per-attempt dynamic state, gate,
  counters and accepted evidence refs;
- ``revision`` and ``schema_version`` are monotonic/versioned;
- round-trip serialization preserves the complete state;
- an inconsistent snapshot (duplicate IDs, missing references, dependency
  cycles, a gate not matching the needs_human set) is rejected;
- a plan of 1, 3 and N tasks is accepted (not limited to the historical 3);
- domain identity helpers are deterministic and collision-resistant.

This is the model-only contract; the clean apply_event path (T05) and the
single commit (T06) build on these invariants. The validator is intentionally
lenient about transitional M4 states (see models.py) until T07 adapts the
activities; the destructive invariants below are always enforced.
"""

import copy
import json

import pytest
from pydantic import ValidationError

from fsasm.models import (
    ChildTask,
    GateOccurrence,
    HumanDecisionAction,
    Plan,
    RunBudget,
    RunState,
    RunStatus,
    TaskBudget,
    VerificationSpec,
    VerificationType,
    artifact_id_for,
    decision_id_for,
    evidence_id_for,
    gate_id_for,
    operation_id_for,
    parent_id_for,
    task_id_for,
)


def _task(task_id: str, sequence: int, deps: list[str] | None = None) -> ChildTask:
    return ChildTask(
        task_id=task_id,
        sequence=sequence,
        title=f"Title {task_id}",
        description=f"Desc {task_id}",
        dependencies=list(deps) if deps else [],
        verification=VerificationSpec(type=VerificationType.SCHEMA, expected="ok"),
    )


def _plan(run_id: str, n: int = 3) -> Plan:
    tasks = [
        _task(f"TASK-{i}", i, deps=[f"TASK-{i - 1}"] if i > 1 else [])
        for i in range(1, n + 1)
    ]
    return Plan(plan_id=f"plan-{run_id}", run_id=run_id, goal="g", tasks=tasks)


# =============================================================================
# Schema version + revision
# =============================================================================


class TestSnapshotVersioning:
    def test_default_schema_version_and_revision(self):
        s = RunState(run_id="r1", goal="g")
        assert s.schema_version == 1
        assert s.revision == 0

    def test_revision_is_not_auto_incremented_by_touch(self):
        s = RunState(run_id="r1", goal="g", revision=4)
        s.touch()
        assert s.revision == 4, (
            "touch updates timestamp only; the Domain Core/T06 increments revision"
        )

    def test_schema_version_rejects_zero(self):
        with pytest.raises(ValidationError):
            RunState(run_id="r1", goal="g", schema_version=0)

    def test_new_fields_have_safe_defaults_for_legacy_snapshots(self):
        s = RunState(run_id="r1", goal="g")
        assert s.needs_human_task_ids == []
        assert s.gate is None
        assert s.budget is None
        assert s.plan is None


# =============================================================================
# Round-trip serialization
# =============================================================================


class TestRoundTrip:
    def _filled(self) -> RunState:
        plan = _plan("rt", 3)
        plan.tasks[0].accepted_evidence_refs = ["evidence-rt-TASK-1-attempt-1-diff"]
        return RunState(
            run_id="rt",
            goal="g",
            status=RunStatus.NEEDS_HUMAN,
            revision=7,
            plan=plan,
            active_task_id=None,
            completed_task_ids=["TASK-1"],
            failed_task_ids=[],
            needs_human_task_ids=["TASK-2"],
            gate=GateOccurrence(
                gate_id=gate_id_for("rt", "TASK-2", 2),
                task_id="TASK-2",
                attempt=2,
                accepted_decision_id=None,
                accepted_action=None,
                applied=False,
            ),
            budget=RunBudget(max_attempts_per_task=2, max_escalations=1),
        )

    def test_json_round_trip_preserves_full_state(self):
        s = self._filled()
        data = json.loads(s.model_dump_json())
        restored = RunState(**data)
        assert restored == s
        assert restored.revision == 7
        assert restored.needs_human_task_ids == ["TASK-2"]
        assert restored.gate is not None and restored.gate.task_id == "TASK-2"
        assert restored.budget is not None and restored.budget.max_escalations == 1
        assert restored.plan is not None and len(restored.plan.tasks) == 3
        assert restored.plan.tasks[0].accepted_evidence_refs == [
            "evidence-rt-TASK-1-attempt-1-diff"
        ]

    def test_legacy_snapshot_without_new_fields_loads_with_defaults(self):
        s = self._filled()
        data = json.loads(s.model_dump_json())
        for field in (
            "schema_version",
            "revision",
            "needs_human_task_ids",
            "gate",
            "budget",
        ):
            data.pop(field, None)
        legacy = RunState(**data)
        assert legacy.schema_version == 1
        assert legacy.revision == 0
        assert legacy.needs_human_task_ids == []
        assert legacy.gate is None
        assert legacy.budget is None

    def test_deep_copy_is_independent(self):
        s = self._filled()
        c = copy.deepcopy(s)
        c.plan.tasks[0].accepted_evidence_refs.append("extra")
        assert s.plan.tasks[0].accepted_evidence_refs == [
            "evidence-rt-TASK-1-attempt-1-diff"
        ], "input must not be mutated by a copied next state"


# =============================================================================
# Plan: 1, 3 and N tasks
# =============================================================================


class TestPlanSize:
    def test_single_task_plan_accepted(self):
        p = Plan(plan_id="p", run_id="r", goal="g", tasks=[_task("TASK-1", 1)])
        assert len(p.tasks) == 1

    def test_three_task_plan_accepted(self):
        p = _plan("r", 3)
        assert len(p.tasks) == 3

    def test_n_task_plan_accepted(self):
        p = _plan("r", 7)
        assert len(p.tasks) == 7

    def test_empty_plan_rejected(self):
        with pytest.raises(ValidationError, match="at least 1 ChildTask"):
            Plan(plan_id="p", run_id="r", goal="g", tasks=[])


# =============================================================================
# Structural corruption is rejected
# =============================================================================


class TestInconsistentSnapshot:
    def test_duplicate_task_ids_rejected(self):
        tasks = [_task("DUP", 1), _task("DUP", 2), _task("TASK-3", 3)]
        with pytest.raises(ValidationError, match="Task IDs must be unique"):
            Plan(plan_id="p", run_id="r", goal="g", tasks=tasks)

    def test_missing_dependency_rejected(self):
        tasks = [_task("TASK-1", 1, deps=["NOPE"])]
        with pytest.raises(ValidationError, match="depends on non-existent task"):
            Plan(plan_id="p", run_id="r", goal="g", tasks=tasks)

    def test_dependency_cycle_rejected(self):
        tasks = [_task("A", 1, deps=["B"]), _task("B", 2, deps=["A"])]
        with pytest.raises(ValidationError, match="Dependency cycle"):
            Plan(plan_id="p", run_id="r", goal="g", tasks=tasks)

    def test_active_task_id_must_exist_in_register(self):
        p = _plan("r", 2)
        with pytest.raises(ValidationError, match="active_task_id UNKNOWN not in plan"):
            RunState(run_id="r", goal="g", plan=p, active_task_id="UNKNOWN")

    def test_terminal_set_references_unknown_task_rejected(self):
        p = _plan("r", 2)
        with pytest.raises(
            ValidationError, match="completed_task_ids references unknown task"
        ):
            RunState(run_id="r", goal="g", plan=p, completed_task_ids=["GHOST"])

    def test_task_cannot_be_completed_and_failed(self):
        p = _plan("r", 2)
        with pytest.raises(ValidationError, match="both completed and failed"):
            RunState(
                run_id="r",
                goal="g",
                plan=p,
                completed_task_ids=["TASK-1"],
                failed_task_ids=["TASK-1"],
            )

    def test_needs_human_task_cannot_be_terminal(self):
        p = _plan("r", 2)
        with pytest.raises(
            ValidationError, match="needs_human task cannot be in a terminal set"
        ):
            RunState(
                run_id="r",
                goal="g",
                plan=p,
                needs_human_task_ids=["TASK-1"],
                completed_task_ids=["TASK-1"],
            )

    def test_gate_must_match_run_status(self):
        p = _plan("r", 2)
        with pytest.raises(
            ValidationError, match="gate set but run status is not NEEDS_HUMAN"
        ):
            RunState(
                run_id="r",
                goal="g",
                status=RunStatus.RUNNING,
                plan=p,
                needs_human_task_ids=["TASK-1"],
                gate=GateOccurrence(
                    gate_id=gate_id_for("r", "TASK-1", 1),
                    task_id="TASK-1",
                    attempt=1,
                ),
            )

    def test_gate_task_must_be_in_needs_human_set(self):
        p = _plan("r", 2)
        with pytest.raises(ValidationError, match="not in needs_human_task_ids"):
            RunState(
                run_id="r",
                goal="g",
                status=RunStatus.NEEDS_HUMAN,
                plan=p,
                needs_human_task_ids=["TASK-2"],
                gate=GateOccurrence(
                    gate_id=gate_id_for("r", "TASK-1", 1),
                    task_id="TASK-1",
                    attempt=1,
                ),
            )

    def test_plan_run_id_mismatch_rejected(self):
        p = _plan("other", 2)
        with pytest.raises(
            ValidationError, match="Plan run_id must match RunState run_id"
        ):
            RunState(run_id="r", goal="g", plan=p)


# =============================================================================
# Parent/Child + budgets
# =============================================================================


class TestParentChildAndBudgets:
    def test_parent_id_is_runtime_owned(self):
        # Parent is derived from run_id; a Child carries parent_id. The plan is
        # flat; the Scheduler computes Parent/run from required Child tasks.
        parent = parent_id_for("run-1")
        assert parent == "PARENT-run-1"
        child = _task("TASK-1", 1)
        child.parent_id = parent
        assert child.parent_id == parent

    def test_task_budget_overrides_run_budget(self):
        tb = TaskBudget(max_model_calls=5, max_attempts=2)
        child = _task("TASK-1", 1)
        child.budget = tb
        p = Plan(plan_id="p", run_id="r", goal="g", tasks=[child])
        s = RunState(
            run_id="r",
            goal="g",
            plan=p,
            budget=RunBudget(max_model_calls=10, max_attempts_per_task=3),
        )
        assert (
            s.plan.tasks[0].budget is not None
            and s.plan.tasks[0].budget.max_model_calls == 5
        )
        assert s.budget is not None and s.budget.max_attempts_per_task == 3


# =============================================================================
# Accepted evidence refs live on the task (single authority)
# =============================================================================


class TestAcceptedEvidenceRefs:
    def test_evidence_refs_are_per_attempt_on_task(self):
        child = _task("TASK-1", 1)
        child.attempt = 2
        child.accepted_evidence_refs = ["evidence-r-TASK-1-attempt-2-diff"]
        p = Plan(plan_id="p", run_id="r", goal="g", tasks=[child])
        s = RunState(run_id="r", goal="g", plan=p)
        assert s.plan.tasks[0].accepted_evidence_refs == [
            "evidence-r-TASK-1-attempt-2-diff"
        ]

    def test_clearing_refs_on_new_attempt_is_explicit(self):
        child = _task("TASK-1", 1)
        child.attempt = 1
        child.accepted_evidence_refs = ["old"]
        child.attempt = 2
        # The Domain Core (T05) clears refs on a new attempt; the model only
        # stores them. Here we prove the snapshot reflects the cleared state.
        child.accepted_evidence_refs = []
        p = Plan(plan_id="p", run_id="r", goal="g", tasks=[child])
        assert p.tasks[0].accepted_evidence_refs == []


# =============================================================================
# Domain identity helpers
# =============================================================================


class TestDomainIdentities:
    def test_task_id_deterministic(self):
        assert task_id_for("run-1", 3) == "TASK-run-1-3"

    def test_operation_id_deterministic(self):
        assert (
            operation_id_for("run-1", "TASK-1", 1, 4)
            == "op-run-1-TASK-1-attempt-1-step-4"
        )

    def test_artifact_id_deterministic(self):
        assert (
            artifact_id_for("run-1", "TASK-1", 2) == "artifact-run-1-TASK-1-attempt-2"
        )

    def test_evidence_id_deterministic(self):
        assert (
            evidence_id_for("run-1", "TASK-1", 1, "diff")
            == "evidence-run-1-TASK-1-attempt-1-diff"
        )

    def test_gate_id_matches_workflow_convention(self):
        # The snapshot gate id must match the workflow-level _gate_id so the
        # signal handler and the snapshot agree without a second authority.
        from src.workflows.fsasm_milestone_four import _gate_id

        assert gate_id_for("run-1", "TASK-1", 2) == _gate_id("run-1", "TASK-1", 2)
        assert gate_id_for("run-1", "TASK-1", 2) == "gate-run-1-TASK-1-attempt-2"

    def test_decision_id_matches_workflow_convention(self):
        from src.workflows.fsasm_milestone_four import _decision_id

        g = gate_id_for("run-1", "TASK-1", 1)
        assert decision_id_for(
            "run-1", "TASK-1", g, HumanDecisionAction.RETRY_ONCE
        ) == _decision_id("run-1", "TASK-1", g, HumanDecisionAction.RETRY_ONCE)

    def test_identities_are_collision_resistant_across_attempts(self):
        g1 = gate_id_for("r", "TASK-1", 1)
        g2 = gate_id_for("r", "TASK-1", 2)
        assert g1 != g2
        d_abort = decision_id_for("r", "TASK-1", g1, HumanDecisionAction.ABORT)
        d_retry = decision_id_for("r", "TASK-1", g1, HumanDecisionAction.RETRY_ONCE)
        assert d_abort != d_retry
