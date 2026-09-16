"""Regression test for S2: initial persistence ordering & run log consistency.

Two confirmed problems:

A. `persist_initial_state_activity` persisted the initial `RunState` as
   `PLANNED` but wrote the `m4_run_started` log entry with
   `status=RunStatus.RUNNING.value`, contradicting the actually persisted
   initial state.

B. The previous worker-level test tried to observe the short-lived `PLANNED`
   state by polling `state.json` every 100 ms. The workflow transitions
   `PLANNED -> RUNNING` very quickly during `prepare_task_activity`, so
   missing `PLANNED` in the poll does NOT prove it was never persisted - it is
   a race.

This test is deterministic. It does not poll the transient `PLANNED` state.
Instead it relies on the append-only `run.log.jsonl`: the `m4_run_started`
entry is written by `persist_initial_state_activity` AFTER `save_run_state`
and `save_plan`, so its presence with the persisted status is durable proof
that initial persistence completed with that status. Reading the full log
after the run completes reconstructs the initialization ordering without
depending on a timing race.

Persistence is isolated to `tmp_path` via monkeypatch of `RuntimePersistence`
in the workflow module (and the executor/planner modules that the activities
import), so the global `./runtime` is never touched or cleaned up.
"""

import asyncio
import json
from datetime import timedelta

import pytest

from fsasm.persistence import RuntimePersistence
from fsasm.models import RunStatus, TaskStatus

import workflows.fsasm_milestone_four as m4_module
import fsasm.executor_activities as exec_module
import fsasm.planner_activities as plan_module

from workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    create_input_activity,
    validate_config_activity,
    persist_initial_state_activity,
    set_task_max_attempts_activity,
    find_next_ready_task_activity,
    prepare_task_activity,
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    finalize_task_activity,
    check_retry_budget_activity,
    persist_failure_state_activity,
    persist_retry_state_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    persist_final_m4_state_activity,
)
from fsasm.planner_activities import plan_activity

_M4_ACTIVITIES = [
    create_input_activity,
    validate_config_activity,
    plan_activity,
    persist_initial_state_activity,
    set_task_max_attempts_activity,
    find_next_ready_task_activity,
    prepare_task_activity,
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    finalize_task_activity,
    check_retry_budget_activity,
    persist_failure_state_activity,
    persist_retry_state_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    persist_final_m4_state_activity,
]


@pytest.fixture()
def isolated_runtime(tmp_path, monkeypatch):
    """Redirect ALL M4 persistence to an isolated tmp_path directory.

    The workflow activities instantiate `RuntimePersistence()` themselves, so
    the symbol is patched in every module that references it. The global
    `./runtime` is never touched or cleaned up.

    Additionally, every persistence instance is wrapped in a capture proxy
    that freezes an immutable copy of the FIRST `save_run_state` / `save_plan`
    argument (via JSON round-trip) for the test's run_id. The first writes in a
    worker run come from `persist_initial_state_activity` (PLANNED); later
    writes (RUNNING) do not overwrite the frozen snapshot. This lets the test
    prove the first durable snapshot of a real worker run is PLANNED without
    any timing race or polling.
    """
    runtime_dir = tmp_path / "runtime"
    original = RuntimePersistence
    captures = {
        "first_state": None,
        "first_plan": None,
        "first_state_run_id": None,
        "first_plan_run_id": None,
    }

    class _CapturingPersistence:
        """Delegating wrapper that captures the first successfully persisted
        state/plan snapshot by reading it back from disk, not by copying the
        in-memory argument."""

        def __init__(self, *args, **kwargs):
            kwargs.setdefault("runtime_dir", runtime_dir)
            self._inner = original(*args, **kwargs)

        def save_run_state(self, state):
            # 1. Perform the real write first.
            result = self._inner.save_run_state(state)
            # 2. Capture only after a successful write, only for the test run,
            #    only once, and read the persisted file back from disk.
            if (
                captures["first_state"] is None
                and state.run_id == captures.get("target_run_id")
            ):
                loaded = self._inner.load_run_state(state.run_id)
                if loaded is not None:
                    captures["first_state"] = type(loaded).model_validate_json(
                        loaded.model_dump_json()
                    )
                    captures["first_state_run_id"] = loaded.run_id
            return result

        def save_plan(self, plan):
            # 1. Perform the real write first.
            result = self._inner.save_plan(plan)
            # 2. Capture only after a successful write, only for the test run,
            #    only once, and read the persisted file back from disk.
            if (
                captures["first_plan"] is None
                and plan.run_id == captures.get("target_run_id")
            ):
                loaded = self._inner.load_plan(plan.run_id)
                if loaded is not None:
                    captures["first_plan"] = type(loaded).model_validate_json(
                        loaded.model_dump_json()
                    )
                    captures["first_plan_run_id"] = loaded.run_id
            return result

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(m4_module, "RuntimePersistence", _CapturingPersistence)
    monkeypatch.setattr(exec_module, "RuntimePersistence", _CapturingPersistence, raising=False)
    monkeypatch.setattr(plan_module, "RuntimePersistence", _CapturingPersistence, raising=False)
    return {"runtime_dir": runtime_dir, "captures": captures}


def _read_log(runtime_dir, run_id):
    path = runtime_dir / "runs" / run_id / "run.log.jsonl"
    entries = []
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


@pytest.mark.asyncio
async def test_initial_persistence_ordering_and_log_consistency(
    isolated_runtime, temporal_env
):
    """S2: initial persistence ordering and m4_run_started log consistency.

    Proves, from durable artifacts (not transient polling):
      1. the initial plan has authoritative max_attempts before the first save;
      2. the first persisted state is PLANNED;
      3. active_task_id is None at initialization;
      4. all three tasks are PENDING at initialization;
      5. state.json.plan and plan.json agree at initialization time;
      6. PLANNED -> RUNNING happens later, during prepare_task_activity;
      7. the workflow still completes the success scenario.

    Deterministic because the append-only run log records `m4_run_started`
    (written after save_run_state/save_plan) with the persisted status.
    """
    from mistralai.workflows.testing import create_test_worker

    test_run_id = "test-s2-initial-persistence"
    # Tell the capture proxy to only freeze snapshots for this run.
    isolated_runtime["captures"]["target_run_id"] = test_run_id

    async with create_test_worker(
        temporal_env,
        workflows=[FsasmMilestoneFourWorkflow],
        activities=_M4_ACTIVITIES,
    ):
        handle = await temporal_env.client.start_workflow(
            "fsasm-milestone-four",
            {
                "goal": "Test S2 initial persistence ordering",
                "planner_backend": "stub",
                "executor_backend": "stub",
                "max_retries_per_task": 2,
                "stub_fail_first_n_attempts": 0,
                "run_id": test_run_id,
            },
            id=test_run_id,
            task_queue="test-task-queue",
            execution_timeout=timedelta(seconds=15),
        )
        # Let the workflow complete; the init record is durable in the log.
        result = await asyncio.wait_for(handle.result(), timeout=20)

    runtime_dir = isolated_runtime["runtime_dir"]
    captures = isolated_runtime["captures"]
    persistence = RuntimePersistence(runtime_dir=runtime_dir)
    log_entries = _read_log(runtime_dir, test_run_id)

    # --- The m4_run_started entry is the durable witness of initial persistence.
    started = [e for e in log_entries if e.get("event") == "m4_run_started"]
    assert started, "m4_run_started log entry was not persisted"
    assert len(started) == 1, f"expected exactly one m4_run_started, got {len(started)}"
    started_entry = started[0]

    # Problem A: the init log must report the actually persisted status, PLANNED.
    assert started_entry["status"] == RunStatus.PLANNED.value, (
        f"m4_run_started must report PLANNED (the persisted initial status), "
        f"got {started_entry['status']}"
    )

    # Ordering: m4_run_started is the FIRST log entry (init happens before
    # execution events). It must not declare RUNNING before execution prep.
    first_event = log_entries[0].get("event")
    assert first_event == "m4_run_started", (
        f"m4_run_started must be the first log entry, got {first_event}"
    )

    # --- Reconstruct the initial plan from plan.json (durable, written by
    # the same activity right before the log entry).
    loaded_plan = persistence.load_plan(test_run_id)
    assert loaded_plan is not None

    # Requirement 1: authoritative max_attempts (= max_retries_per_task + 1 = 3)
    # established BEFORE the first save.
    for t in loaded_plan.tasks:
        assert t.max_attempts == 3, (
            f"task {t.task_id} max_attempts must be 3 (2 retries + 1), got {t.max_attempts}"
        )

    # Requirement 4: at initialization all tasks are PENDING. The final plan
    # shows PASSED for TASK-001 (execution succeeded), so we cannot read the
    # initial task statuses from the final plan.json. Instead we assert it
    # from the m4_run_started witness + the contract: the initial state is
    # PLANNED with all tasks PENDING. We verify the initial-state contract
    # directly via a focused domain check below.

    # --- Worker-level capture of the FIRST durable snapshot (no polling).
    # The capture proxy froze an immutable copy at the first save_run_state /
    # save_plan call in the real worker run. Those first writes come from
    # persist_initial_state_activity (PLANNED); later RUNNING writes do NOT
    # overwrite the frozen snapshot. This is the worker-level proof that the
    # correct first snapshot is created in the real workflow run, not only via
    # a direct activity call.
    assert captures["first_state"] is not None, (
        "save_run_state was never called by the worker run"
    )
    assert captures["first_plan"] is not None, (
        "save_plan was never called by the worker run"
    )
    # Both first writes belong to the same worker run.
    assert captures["first_state_run_id"] == test_run_id
    assert captures["first_plan_run_id"] == test_run_id
    first_state = captures["first_state"]
    first_plan = captures["first_plan"]
    # Requirement 2: first persisted state in the real run is PLANNED.
    assert first_state.status == RunStatus.PLANNED, (
        f"first worker snapshot status must be PLANNED, got {first_state.status}"
    )
    # Requirement 3: active_task_id is None at initialization.
    assert first_state.active_task_id is None
    # Requirement 4: all three tasks PENDING at initialization.
    for t in first_plan.tasks:
        assert t.status == TaskStatus.PENDING, f"{t.task_id} must be PENDING in the first snapshot"
    # Requirement 1: authoritative max_attempts established before the first save.
    for t in first_plan.tasks:
        assert t.max_attempts == 3, f"{t.task_id} max_attempts must be 3 in the first snapshot"
    # Requirement 5: state.json.plan == plan.json at the first snapshot.
    for s_t, p_t in zip(first_state.plan.tasks, first_plan.tasks):
        assert s_t.status == p_t.status == TaskStatus.PENDING
        assert s_t.max_attempts == p_t.max_attempts == 3
        assert s_t.attempt == p_t.attempt == 0

    # --- Focused domain check of the initial persistence contract (no worker):
    # rebuild the exact initial state the activity produces and persist it
    # through the real activity in isolation, then read it back. This proves
    # requirements 2, 3, 4, 5 deterministically from durable files.
    await _assert_initial_contract_deterministic(runtime_dir)

    # Requirement 6: the run transitions to RUNNING later. The final state is
    # RUNNING (not PLANNED), proving PLANNED -> RUNNING happened after init.
    final_state = persistence.load_run_state(test_run_id)
    assert final_state is not None
    assert final_state.status == RunStatus.RUNNING, (
        f"final run status should be RUNNING after task execution, got {final_state.status}"
    )

    # Requirement 7: workflow completed successfully.
    assert isinstance(result, dict)
    assert result["success"] is True
    assert "TASK-001" in result["passed_task_ids"]


async def _assert_initial_contract_deterministic(runtime_dir):
    """Drive persist_initial_state_activity directly with independent arguments
    and read back the durable files. Proves the initial snapshot contract
    (PLANNED, active_task_id=None, all PENDING, max_attempts=3, state.json ==
    plan.json) without any worker timing race.

    The PlannerOutput is produced by the real stub planner so the metadata
    contract is not hand-rolled. The inputs are then independently serialized
    (JSON round-trip) to mimic the worker boundary before being passed to the
    activity. Uses a separate run_id so it does not collide with the worker run.
    """
    import pydantic

    from fsasm.models import GoalInput, PlannerBackend, PlannerConfig, RunStatus
    from fsasm.planner_activities import plan_activity

    run_id = "test-s2-domain-initial"
    goal_input = GoalInput(goal="Test S2 domain initial contract", run_id=run_id)
    config = PlannerConfig(backend=PlannerBackend.STUB)

    # Use the real stub planner to obtain a fully valid PlannerOutput.
    planner_output = await plan_activity(goal_input, config)
    # Authoritative max_attempts established before initial persistence.
    for t in planner_output.plan.tasks:
        t.max_attempts = 3

    # Independent serialized copies, as the worker delivers to the activity.
    po_indep = pydantic.TypeAdapter(type(planner_output)).validate_json(
        planner_output.model_dump_json()
    )
    gi_indep = pydantic.TypeAdapter(GoalInput).validate_json(
        goal_input.model_dump_json()
    )

    await persist_initial_state_activity(po_indep, gi_indep)

    persistence = RuntimePersistence(runtime_dir=runtime_dir)
    loaded_state = persistence.load_run_state(run_id)
    loaded_plan = persistence.load_plan(run_id)
    assert loaded_state is not None and loaded_plan is not None

    # Requirement 2: first persisted state is PLANNED.
    assert loaded_state.status == RunStatus.PLANNED
    # Requirement 3: active_task_id is None at initialization.
    assert loaded_state.active_task_id is None
    # Requirement 4: all tasks PENDING at initialization.
    for t in loaded_plan.tasks:
        assert t.status == TaskStatus.PENDING, f"{t.task_id} must be PENDING"
    # Requirement 1 (durable): authoritative max_attempts persisted.
    for t in loaded_plan.tasks:
        assert t.max_attempts == 3
    # Requirement 5: state.json.plan == plan.json at initialization.
    for s_t, p_t in zip(loaded_state.plan.tasks, loaded_plan.tasks):
        assert s_t.status == p_t.status == TaskStatus.PENDING
        assert s_t.max_attempts == p_t.max_attempts == 3
        assert s_t.attempt == p_t.attempt == 0

    # m4_run_started log entry must report PLANNED here too.
    log_entries = _read_log(runtime_dir, run_id)
    started = [e for e in log_entries if e.get("event") == "m4_run_started"]
    assert started and started[0]["status"] == RunStatus.PLANNED.value
