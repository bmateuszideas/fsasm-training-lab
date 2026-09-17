"""M4-07 cross-component regression and fault-injection integration matrix.

Tests the complete stabilized M4 together using isolated persistence and
worker-level workflow runs, then inspects the persisted artifacts. Also
re-runs the S0/F2/S1/S2/S3-relevant invariants in the integrated context.

Explicitly verifies that M4 still executes only TASK-001; TASK-002 and
TASK-003 remain PENDING. A successful M4 path must not be presented as
completion of all three tasks or the user's original goal.
"""

import asyncio
import json
from datetime import timedelta

import pytest
from mistralai.workflows.testing import create_test_worker

from fsasm.errors import InvalidIdentifierError
from fsasm.models import RunStatus, TaskStatus
from fsasm.persistence import RuntimePersistence
from src.workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    HumanDecisionSignal,
    check_retry_budget_activity,
    create_input_activity,
    find_next_ready_task_activity,
    persist_failure_state_activity,
    persist_final_m4_state_activity,
    persist_human_gate_rejections_activity,
    persist_initial_state_activity,
    persist_retry_state_activity,
    set_task_max_attempts_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    validate_config_activity,
)
from fsasm.planner_activities import plan_activity
from fsasm.executor_activities import (
    convert_executor_output_to_evidence_activity,
    execute_task_activity,
    finalize_task_activity,
    prepare_task_activity,
    validate_executor_output_provenance_activity,
    verify_task_execution_activity,
)

_M4_ACTIVITIES = [
    create_input_activity,
    validate_config_activity,
    plan_activity,
    set_task_max_attempts_activity,
    persist_initial_state_activity,
    find_next_ready_task_activity,
    prepare_task_activity,
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    finalize_task_activity,
    persist_failure_state_activity,
    check_retry_budget_activity,
    persist_retry_state_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    persist_final_m4_state_activity,
    persist_human_gate_rejections_activity,
]


@pytest.fixture(autouse=True)
def cleanup_runtime():
    p = RuntimePersistence()
    p.cleanup_all()
    yield
    p.cleanup_all()


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _start(temporal_env, run_id, max_retries, fail_n):
    return temporal_env.client.start_workflow(
        "fsasm-milestone-four",
        {
            "goal": "M4 cross-component integration",
            "planner_backend": "stub",
            "executor_backend": "stub",
            "max_retries_per_task": max_retries,
            "stub_fail_first_n_attempts": fail_n,
            "run_id": run_id,
        },
        id=run_id,
        task_queue="test-task-queue",
        execution_timeout=timedelta(seconds=20),
    )


async def _wait_needs_human(run_id, timeout=20):
    p = RuntimePersistence()
    for _ in range(timeout * 10):
        await asyncio.sleep(0.1)
        try:
            s = p.load_run_state(run_id)
            if s is not None and s.status == RunStatus.NEEDS_HUMAN:
                return s
        except Exception:
            continue
    return p.load_run_state(run_id)


class TestM4IntegrationMatrix:
    """The required integration matrix as worker-level tests with persisted
    artifact inspection."""

    @pytest.mark.asyncio
    async def test_fresh_run_id_successful_init(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-int-fresh", 2, 0)
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        p = RuntimePersistence()
        assert p.is_run_initialized("run-int-fresh")
        state = p.load_run_state("run-int-fresh")
        assert state is not None
        # M4 only executes TASK-001; TASK-002/003 stay PENDING.
        for t in state.plan.tasks:
            if t.task_id == "TASK-001":
                assert t.status == TaskStatus.PASSED
            else:
                assert t.status == TaskStatus.PENDING, (
                    f"{t.task_id} must remain PENDING, got {t.status}"
                )

    @pytest.mark.asyncio
    async def test_duplicate_run_id_no_silent_overwrite(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-int-dup", 2, 0)
            await asyncio.wait_for(handle.result(), timeout=30)
        # Second workflow with the same run_id must fail at the creation boundary.
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            with pytest.raises(Exception):
                handle2 = await _start(temporal_env, "run-int-dup", 2, 0)
                await asyncio.wait_for(handle2.result(), timeout=30)
        # The activity raises RunAlreadyExistsError (surfaced as a workflow
        # failure); the first run's artifacts remain intact.
        p = RuntimePersistence()
        state = p.load_run_state("run-int-dup")
        assert state is not None
        assert state.plan.tasks[0].status == TaskStatus.PASSED

    @pytest.mark.asyncio
    async def test_normal_first_attempt_pass_persisted(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-int-pass", 2, 0)
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        p = RuntimePersistence()
        state = p.load_run_state("run-int-pass")
        plan = p.load_plan("run-int-pass")
        # Authoritative state and derived plan agree (F3).
        assert state.plan.tasks[0].status == plan.tasks[0].status == TaskStatus.PASSED
        assert state.plan.tasks[0].attempt == plan.tasks[0].attempt == 1

    @pytest.mark.asyncio
    async def test_automatic_retry_correct_attempt_counter(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-int-retry", 2, 1)
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        p = RuntimePersistence()
        state = p.load_run_state("run-int-retry")
        # attempt counter = 2 (first failed, second passed); max_attempts = 3.
        assert state.plan.tasks[0].attempt == 2
        assert state.plan.tasks[0].max_attempts == 3
        assert state.plan.tasks[0].status == TaskStatus.PASSED

    @pytest.mark.asyncio
    async def test_retry_exhaustion_durable_needs_human(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            await _start(temporal_env, "run-int-exhaust", 0, 999)
            await _wait_needs_human("run-int-exhaust")
        p = RuntimePersistence()
        state = p.load_run_state("run-int-exhaust")
        assert state.status == RunStatus.NEEDS_HUMAN
        assert state.plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
        # The NEEDS_HUMAN state is durable BEFORE waiting for a signal.
        plan = p.load_plan("run-int-exhaust")
        assert plan.tasks[0].status == TaskStatus.NEEDS_HUMAN

    @pytest.mark.asyncio
    async def test_human_abort_correct_failed_result_and_audit(self, temporal_env):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-int-abort", 0, 999)
            await _wait_needs_human("run-int-abort")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(task_id="TASK-001", action="ABORT"),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["status"] == "FAILED"
        assert result["human_decision"]["action"] == "ABORT"
        p = RuntimePersistence()
        evidence = p.load_all_evidence("run-int-abort")
        abort_audits = [
            e
            for e in evidence
            if e.kind == "human_gate_audit" and e.payload.get("action") == "ABORT"
        ]
        assert len(abort_audits) == 1
        audit = abort_audits[0].payload
        # Audit reconstructs run/task/gate/decision/action/reason/statuses.
        assert audit["run_id"] == "run-int-abort"
        assert audit["task_id"] == "TASK-001"
        assert audit["gate_id"] is not None
        assert audit["decision_id"] is not None
        assert audit["task_status_before"] == "NEEDS_HUMAN"
        assert audit["task_status_after"] == "FAILED"
        assert audit["run_status_before"] == "NEEDS_HUMAN"
        assert audit["run_status_after"] == "FAILED"

    @pytest.mark.asyncio
    async def test_human_retry_once_exactly_one_additional_execution(
        self, temporal_env
    ):
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-int-retry1", 0, 1)
            await _wait_needs_human("run-int-retry1")
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(task_id="TASK-001", action="RETRY_ONCE"),
            )
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        p = RuntimePersistence()
        state = p.load_run_state("run-int-retry1")
        # Exactly one additional execution authorized: attempt 2, max_attempts 2.
        assert state.plan.tasks[0].attempt == 2
        assert state.plan.tasks[0].max_attempts == 2
        assert state.plan.tasks[0].status == TaskStatus.PASSED

    @pytest.mark.asyncio
    async def test_crash_recovery_state_plan_consistency(self, tmp_path):
        """Crash between state/plan writes: authoritative state.json is the
        source of truth; the derived plan.json is repaired on recovery."""
        p = RuntimePersistence(runtime_dir=tmp_path / "runtime")
        p.create_run("run-int-crash")
        from fsasm.models import (
            ChildTask,
            Plan,
            RunState,
            VerificationSpec,
            VerificationType,
        )

        plan = Plan(
            plan_id="plan-run-int-crash",
            run_id="run-int-crash",
            goal="crash",
            tasks=[
                ChildTask(
                    task_id="TASK-001",
                    sequence=1,
                    title="T",
                    description="d",
                    status=TaskStatus.PASSED,
                    attempt=1,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
                ChildTask(
                    task_id="TASK-002",
                    sequence=2,
                    title="T2",
                    description="d",
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
                ChildTask(
                    task_id="TASK-003",
                    sequence=3,
                    title="T3",
                    description="d",
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
            ],
        )
        state = RunState(
            run_id="run-int-crash",
            goal="crash",
            status=RunStatus.RUNNING,
            plan=plan,
        )
        p.commit_run_state(state)
        # Simulate a crash: leave plan.json stale (task PENDING).
        stale_plan = plan.model_copy()
        stale_plan.tasks[0].status = TaskStatus.PENDING
        p.save_plan(stale_plan)
        # load_plan returns authoritative (PASSED), not stale (PENDING).
        assert p.load_plan("run-int-crash").tasks[0].status == TaskStatus.PASSED
        # Recovery repairs the derived view.
        recovered = p.recover_run("run-int-crash")
        assert recovered.plan.tasks[0].status == TaskStatus.PASSED
        assert p.load_plan("run-int-crash").tasks[0].status == TaskStatus.PASSED
        # Idempotent recovery.
        p.recover_run("run-int-crash")
        assert p.load_plan("run-int-crash").tasks[0].status == TaskStatus.PASSED

    def test_unsafe_run_evidence_identifiers_f5_effective(self, tmp_path):
        """F5 remains effective: unsafe run/evidence identifiers are rejected."""
        p = RuntimePersistence(runtime_dir=tmp_path / "runtime")
        with pytest.raises(InvalidIdentifierError):
            p.create_run("../escape")
        with pytest.raises(InvalidIdentifierError):
            p.create_run("run/with/slash")

    @pytest.mark.asyncio
    async def test_contradictory_verification_pass_f8_effective(self, tmp_path):
        """F8 remains effective: a contradictory PASS (NEEDS_HUMAN context) is
        rejected by the finalizer."""
        from fsasm.executor_activities import _validate_finalization_inputs
        from fsasm.errors import ValidationError
        from fsasm.models import (
            ChildTask,
            Plan,
            RunState,
            VerificationResult,
            VerificationResultStatus,
            VerificationCheck,
            VerificationSpec,
            VerificationType,
        )

        p = RuntimePersistence(runtime_dir=tmp_path / "runtime")
        p.create_run("run-int-f8")
        plan = Plan(
            plan_id="plan-run-int-f8",
            run_id="run-int-f8",
            goal="f8",
            tasks=[
                ChildTask(
                    task_id="TASK-001",
                    sequence=1,
                    title="T",
                    description="d",
                    status=TaskStatus.NEEDS_HUMAN,
                    attempt=1,
                    max_attempts=1,
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
                ChildTask(
                    task_id="TASK-002",
                    sequence=2,
                    title="T2",
                    description="d",
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
                ChildTask(
                    task_id="TASK-003",
                    sequence=3,
                    title="T3",
                    description="d",
                    verification=VerificationSpec(
                        type=VerificationType.SCHEMA, expected="ok"
                    ),
                ),
            ],
        )
        state = RunState(
            run_id="run-int-f8",
            goal="f8",
            status=RunStatus.NEEDS_HUMAN,
            plan=plan,
        )
        p.commit_run_state(state)
        loaded = p.load_run_state("run-int-f8")
        task = loaded.plan.tasks[0]
        vr = VerificationResult(
            run_id="run-int-f8",
            task_id=task.task_id,
            status=VerificationResultStatus.PASS,
            checks=[VerificationCheck(check_name="ok", passed=True)],
        )
        with pytest.raises(ValidationError):
            _validate_finalization_inputs(loaded, task, vr, [])

    @pytest.mark.asyncio
    async def test_m4_only_executes_task_001_others_pending(self, temporal_env):
        """M4 must execute only TASK-001; TASK-002 and TASK-003 remain PENDING.
        A successful M4 path is not completion of all three tasks or the goal."""
        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=_M4_ACTIVITIES,
        ):
            handle = await _start(temporal_env, "run-int-scope", 2, 0)
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result["success"] is True
        assert result["executed_task_ids"] == ["TASK-001"]
        assert result["passed_task_ids"] == ["TASK-001"]
        p = RuntimePersistence()
        state = p.load_run_state("run-int-scope")
        statuses = {t.task_id: t.status for t in state.plan.tasks}
        assert statuses == {
            "TASK-001": TaskStatus.PASSED,
            "TASK-002": TaskStatus.PENDING,
            "TASK-003": TaskStatus.PENDING,
        }
        # The run is not PASSED (only one task done); success means the M4
        # task path completed, not the whole goal.
        assert result["status"] != "PASSED"
