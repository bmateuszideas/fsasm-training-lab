"""Tests for FS-ASM Milestone Four workflow - Bounded Retry + Human Gate.

Worker-level tests using Mistral Workflows testing utilities.
Proves scenarios A, B, C as defined in the requirements using real workflow execution.

Scenario A: Autonomous retry then PASS
  - max_attempts=3, fail_first=1
  - attempt 1 FAIL -> durable FAILED -> READY
  - attempt 2 PASS
  - final attempt=2
  - TASK-001 PASSED, TASK-002/003 PENDING, run RUNNING, no Human Gate
  - evidence for both attempts persisted

Scenario B: Exhaustion -> Human Gate -> ABORT
  - max_attempts=2, fail_first=999
  - attempt 1 FAIL -> retry
  - attempt 2 FAIL -> NEEDS_HUMAN
  - TEST MUST observe persisted gate state before signal
  - send typed ABORT signal
  - final task FAILED, final run FAILED, active_task_id=None
  - structured human-decision audit evidence persisted

Scenario C: Exhaustion -> Human Gate -> RETRY_ONCE -> PASS
  - max_attempts=1, fail_first=1
  - attempt 1 FAIL -> NEEDS_HUMAN
  - TEST MUST observe persisted gate state before signal
  - send RETRY_ONCE
  - max_attempts becomes 2
  - attempt 2 PASS
  - final TASK-001 PASSED, run RUNNING, active_task_id=None
  - TASK-002/003 PENDING
  - human-decision audit persisted
"""

import asyncio
import json
import pytest

from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    ExecutorBackend,
    ExecutorConfig,
    GoalInput,
    HumanDecision,
    HumanDecisionAction,
    Plan,
    PlannerBackend,
    PlannerConfig,
    PlannerMetadata,
    PlannerOutput,
    PlannerProposal,
    RunState,
    RunStatus,
    TaskProposal,
    TaskStatus,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.errors import ConfigurationError
from fsasm.persistence import RuntimePersistence, DEFAULT_RUNTIME_DIR
from fsasm.transitions import transition_task, transition_run

# Import workflow components
from workflows.fsasm_milestone_four import (
    FsasmMilestoneFourWorkflow,
    WorkflowInput,
    WorkflowOutput,
    HumanDecisionSignal,
    create_input_activity,
    validate_config_activity,
    find_next_ready_task_activity,
    set_task_max_attempts_activity,
    check_retry_budget_activity,
    persist_failure_state_activity,
    persist_retry_state_activity,
    transition_to_needs_human_activity,
    validate_and_apply_human_decision_activity,
    persist_initial_state_activity,
    persist_final_m4_state_activity,
)
from fsasm.planner_activities import plan_activity
from fsasm.executor_activities import (
    execute_task_activity,
    validate_executor_output_provenance_activity,
    convert_executor_output_to_evidence_activity,
    verify_task_execution_activity,
    prepare_task_activity,
    finalize_task_activity,
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_all_evidence_files(run_id: str) -> list:
    """Get all evidence JSON files for a run."""
    evidence_dir = DEFAULT_RUNTIME_DIR / "runs" / run_id / "evidence"
    if not evidence_dir.exists():
        return []
    return list(evidence_dir.glob("*.json"))


def load_json_file(path) -> dict:
    """Load and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def count_evidence_records(run_id: str) -> int:
    """Count evidence records for a run."""
    files = get_all_evidence_files(run_id)
    return len(files)


# =============================================================================
# UNIT TESTS - Models
# =============================================================================


class TestM4Models:
    """Tests for M4 model definitions."""

    def test_human_decision_action_enum(self):
        """Test HumanDecisionAction enum has required values."""
        assert HumanDecisionAction.RETRY_ONCE.value == "RETRY_ONCE"
        assert HumanDecisionAction.ABORT.value == "ABORT"

    def test_human_decision_model(self):
        """Test HumanDecision model."""
        decision = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="Testing retry",
        )
        assert decision.task_id == "TASK-001"
        assert decision.action == HumanDecisionAction.RETRY_ONCE
        assert decision.reason == "Testing retry"

    def test_workflow_input_stub_fail_config(self):
        """Test WorkflowInput has stub_fail_first_n_attempts."""
        input_data = WorkflowInput(
            goal="Test",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            stub_fail_first_n_attempts=1,
        )
        assert input_data.stub_fail_first_n_attempts == 1


# =============================================================================
# UNIT TESTS - Activities
# =============================================================================


class TestM4Activities:
    """Tests for M4 activities."""

    @pytest.fixture
    def sample_workflow_input(self) -> WorkflowInput:
        return WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=2,
            stub_fail_first_n_attempts=0,
        )

    @pytest.fixture
    def sample_plan(self) -> Plan:
        tasks = [
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Task 1",
                description="First task",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
                dependencies=[],
                max_attempts=3,
            ),
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Task 2",
                description="Second task",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
                dependencies=["TASK-001"],
                max_attempts=3,
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Task 3",
                description="Third task",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
                dependencies=["TASK-002"],
                max_attempts=3,
            ),
        ]
        return Plan(
            plan_id="plan-123",
            run_id="run-123",
            goal="Test goal",
            tasks=tasks,
        )

    @pytest.fixture
    def sample_state(self) -> RunState:
        return RunState(
            run_id="run-123",
            goal="Test goal",
            status=RunStatus.RUNNING,
            plan=None,
            active_task_id=None,
            completed_task_ids=[],
            failed_task_ids=[],
        )

    @pytest.mark.asyncio
    async def test_create_input_activity(self, sample_workflow_input):
        result = await create_input_activity(sample_workflow_input)
        assert isinstance(result, GoalInput)
        assert result.goal == sample_workflow_input.goal

    @pytest.mark.asyncio
    async def test_validate_config_activity(self, sample_workflow_input):
        planner_config, executor_config = await validate_config_activity(
            sample_workflow_input
        )
        assert isinstance(planner_config, PlannerConfig)
        assert isinstance(executor_config, ExecutorConfig)
        assert executor_config.stub_fail_first_n_attempts == 0

    @pytest.mark.asyncio
    async def test_find_next_ready_task_only_t001(self, sample_plan):
        """Test that find_next_ready_task only returns TASK-001."""
        result = await find_next_ready_task_activity(sample_plan, [])
        assert result is not None
        assert result.task_id == "TASK-001"
        assert result.status == TaskStatus.READY

    @pytest.mark.asyncio
    async def test_find_next_ready_task_skips_others(self, sample_plan):
        """Test that TASK-002 and TASK-003 are skipped."""
        result = await find_next_ready_task_activity(
            sample_plan, ["TASK-001"]
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_set_task_max_attempts(self, sample_plan):
        """Test set_task_max_attempts_activity sets max_attempts correctly."""
        result = await set_task_max_attempts_activity(
            sample_plan, max_retries_per_task=2
        )
        for task in result.tasks:
            assert task.max_attempts == 3  # 2 retries + 1 initial

    @pytest.mark.asyncio
    async def test_check_retry_budget(self):
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=1,
            max_attempts=3,
        )
        can_retry, reason = await check_retry_budget_activity(task)
        assert can_retry is True
        assert "2 retry attempts remaining" in reason

    @pytest.mark.asyncio
    async def test_check_retry_budget_exhausted(self):
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=2,
            max_attempts=2,
        )
        can_retry, reason = await check_retry_budget_activity(task)
        assert can_retry is False
        assert "exhausted all 2 attempts" in reason


# =============================================================================
# UNIT TESTS - Attempt Semantics
# =============================================================================


class TestAttemptSemantics:
    """Tests for proper attempt counting semantics."""

    def test_initial_attempt_is_zero(self):
        """Test that initial attempt is 0."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.READY,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=0,
            max_attempts=3,
        )
        assert task.attempt == 0

    def test_ready_to_running_increments_attempt(self):
        """Test that READY -> RUNNING increments attempt exactly once."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.READY,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=0,
            max_attempts=3,
        )
        assert task.attempt == 0
        task = transition_task(task, TaskStatus.RUNNING)
        assert task.attempt == 1

    def test_failed_to_ready_does_not_increment(self):
        """Test that FAILED -> READY does NOT increment attempt."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=1,
            max_attempts=3,
        )
        assert task.attempt == 1
        task = transition_task(task, TaskStatus.READY)
        assert task.attempt == 1

    def test_can_retry_logic(self):
        """Test can_retry() method with unified semantics."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=0,
            max_attempts=3,
        )
        assert task.can_retry() is True
        task.attempt = 3
        assert task.can_retry() is False

    def test_retry_count_remaining(self):
        """Test retry_count_remaining() method."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=1,
            max_attempts=3,
        )
        assert task.retry_count_remaining() == 2


# =============================================================================
# UNIT TESTS - State Persistence
# =============================================================================


class TestStatePersistence:
    """Tests for state persistence."""

    @pytest.fixture(autouse=True)
    def cleanup_runtime(self):
        """Clean up runtime directory before and after each test."""
        persistence = RuntimePersistence()
        persistence.cleanup_all()
        yield
        persistence.cleanup_all()

    @pytest.mark.asyncio
    async def test_persist_failure_state(self):
        """Test persist_failure_state_activity creates proper persisted state."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.RUNNING,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=1,
            max_attempts=3,
        )

        state = RunState(
            run_id="test-run-123",
            goal="Test",
            status=RunStatus.RUNNING,
            active_task_id="TASK-001",
            completed_task_ids=[],
            failed_task_ids=[],
        )

        verification_result = VerificationResult(
            run_id="test-run-123",
            task_id="TASK-001",
            status=VerificationResultStatus.FAIL,
            message="Test failure",
            checks=[],
        )

        evidence_records = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id="test-run-123",
                task_id="TASK-001",
                kind="executor_output",
                source="test",
                payload={"test": "data"},
            )
        ]

        task, state, _ = await persist_failure_state_activity(
            task, state, verification_result, evidence_records, attempt=1
        )

        assert task.status == TaskStatus.FAILED
        assert "TASK-001" not in state.failed_task_ids
        assert state.active_task_id is None

        persistence = RuntimePersistence()
        loaded_state = persistence.load_run_state("test-run-123")
        assert loaded_state is not None
        assert "TASK-001" not in loaded_state.failed_task_ids

    @pytest.mark.asyncio
    async def test_transition_to_needs_human_persists(self):
        """Test that transition_to_needs_human persists NEEDS_HUMAN state for BOTH task AND run."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=2,
            max_attempts=2,
        )

        tasks = [
            task,
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Test 2",
                description="Test 2",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Test 3",
                description="Test 3",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
        ]

        state = RunState(
            run_id="test-run-456",
            goal="Test",
            status=RunStatus.RUNNING,
            plan=Plan(
                plan_id="plan-456",
                run_id="test-run-456",
                goal="Test",
                tasks=tasks,
            ),
            active_task_id="TASK-001",
            completed_task_ids=[],
            failed_task_ids=[],
        )

        task, state = await transition_to_needs_human_activity(
            task, state, "Retry budget exhausted"
        )

        assert task.status == TaskStatus.NEEDS_HUMAN
        assert state.status == RunStatus.NEEDS_HUMAN
        assert state.active_task_id is None
        assert "TASK-001" in state.failed_task_ids

        persistence = RuntimePersistence()
        loaded_state = persistence.load_run_state("test-run-456")
        assert loaded_state is not None
        assert loaded_state.status == RunStatus.NEEDS_HUMAN

        loaded_plan = persistence.load_plan("test-run-456")
        assert loaded_plan is not None
        assert loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN

        log_entries = persistence.load_run_log("test-run-456")
        human_gate_entries = [
            e for e in log_entries if e.get("event") == "human_gate_invoked"
        ]
        assert len(human_gate_entries) > 0
        assert human_gate_entries[0]["task_status"] == "NEEDS_HUMAN"
        assert human_gate_entries[0]["run_status"] == "NEEDS_HUMAN"
        assert human_gate_entries[0]["active_task_id"] is None

    @pytest.mark.asyncio
    async def test_validate_and_apply_human_decision_retry_once(self):
        """Test validate_and_apply_human_decision for RETRY_ONCE."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.NEEDS_HUMAN,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=2,
            max_attempts=2,
        )

        tasks = [
            task,
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Test 2",
                description="Test 2",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Test 3",
                description="Test 3",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
        ]

        state = RunState(
            run_id="test-run-789",
            goal="Test",
            status=RunStatus.NEEDS_HUMAN,
            plan=Plan(
                plan_id="plan-789",
                run_id="test-run-789",
                goal="Test",
                tasks=tasks,
            ),
            active_task_id=None,
            completed_task_ids=[],
            failed_task_ids=["TASK-001"],
        )

        decision = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="Give it one more try",
        )

        task, state, applied_decision = (
            await validate_and_apply_human_decision_activity(
                decision, task, state
            )
        )

        assert task.status == TaskStatus.READY
        assert task.max_attempts == 3  # attempt was 2, so max_attempts = 2 + 1 = 3
        assert task.attempt == 2  # NOT reset
        assert state.status == RunStatus.RUNNING
        assert "TASK-001" not in state.failed_task_ids

    @pytest.mark.asyncio
    async def test_validate_and_apply_human_decision_abort(self):
        """Test validate_and_apply_human_decision for ABORT."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.NEEDS_HUMAN,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=2,
            max_attempts=2,
        )

        tasks = [
            task,
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Test 2",
                description="Test 2",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Test 3",
                description="Test 3",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
        ]

        state = RunState(
            run_id="test-run-abc",
            goal="Test",
            status=RunStatus.NEEDS_HUMAN,
            plan=Plan(
                plan_id="plan-abc",
                run_id="test-run-abc",
                goal="Test",
                tasks=tasks,
            ),
            active_task_id=None,
            completed_task_ids=[],
            failed_task_ids=["TASK-001"],
        )

        decision = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.ABORT,
            reason="This is not working",
        )

        task, state, applied_decision = (
            await validate_and_apply_human_decision_activity(
                decision, task, state
            )
        )

        assert task.status == TaskStatus.FAILED
        assert state.status == RunStatus.FAILED
        assert state.active_task_id is None

    @pytest.mark.asyncio
    async def test_validate_human_decision_task_id_mismatch(self):
        """Test that human decision validation fails on task_id mismatch."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.NEEDS_HUMAN,
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
            attempt=2,
            max_attempts=2,
        )

        state = RunState(
            run_id="test-run-xyz",
            goal="Test",
            status=RunStatus.NEEDS_HUMAN,
            active_task_id=None,
            completed_task_ids=[],
            failed_task_ids=["TASK-001"],
        )

        decision = HumanDecision(
            task_id="TASK-002",  # Wrong task_id
            action=HumanDecisionAction.RETRY_ONCE,
            reason="Test",
        )

        with pytest.raises(Exception) as exc_info:
            await validate_and_apply_human_decision_activity(
                decision, task, state
            )
        assert "does not match gated task" in str(exc_info.value)


# =============================================================================
# WORKER-LEVEL TESTS - Scenario A: Autonomous retry then PASS
# =============================================================================


class TestScenarioAWorker:
    """
    Scenario A - Autonomous retry then PASS using real Mistral Workflows test worker.

    max_attempts=3
    fail_first=1
    attempt 1 FAIL -> durable FAILED -> READY
    attempt 2 PASS
    final attempt=2
    TASK-001 PASSED
    TASK-002/003 PENDING
    run RUNNING
    no Human Gate
    evidence for both attempts persisted
    """

    @pytest.fixture(autouse=True)
    def cleanup_runtime(self):
        """Clean up runtime directory before and after each test."""
        persistence = RuntimePersistence()
        persistence.cleanup_all()
        yield
        persistence.cleanup_all()

    @pytest.mark.asyncio
    async def test_scenario_a_worker_level(
        self, temporal_env
    ):
        """
        Scenario A: Autonomous retry then PASS using real test worker.
        Uses mistralai.workflows.testing.create_test_worker.
        """
        from mistralai.workflows.testing import create_test_worker
        from datetime import timedelta

        WORKFLOW_EXECUTION_TIMEOUT = timedelta(seconds=15)

        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=[
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
            ],
        ):
            # Execute workflow with STUB backend, max_retries=2 (3 total attempts), fail_first=1
            handle = await temporal_env.client.start_workflow(
                "fsasm-milestone-four",
                {
                    "goal": "Test Scenario A",
                    "planner_backend": "stub",
                    "executor_backend": "stub",
                    "max_retries_per_task": 2,
                    "stub_fail_first_n_attempts": 1,
                },
                id="test-fsasm-m4-scenario-a",
                task_queue="test-task-queue",
                execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            )

            result = await asyncio.wait_for(
                handle.result(), timeout=20
            )

            # Verify structured result
            assert isinstance(result, dict)
            assert result["run_id"] is not None
            assert result["status"] == "RUNNING"
            assert result["task_count"] == 3
            assert "TASK-001" in result["executed_task_ids"]
            assert result["executed_task_ids"] == ["TASK-001"]
            assert result["human_gate_invoked"] is False

            # Verify TASK-001 PASSED
            assert "TASK-001" in result["passed_task_ids"]
            assert "TASK-001" not in result["failed_task_ids"]
            assert "TASK-001" not in result["needs_human_task_ids"]

            # Verify TASK-002 and TASK-003 remain PENDING
            assert "TASK-002" not in result["executed_task_ids"]
            assert "TASK-003" not in result["executed_task_ids"]

            # Verify success is True (TASK-001 PASSED)
            assert result["success"] is True

            # Verify evidence count is authoritative
            assert result["evidence_count"] > 0

            # Verify persisted state
            persistence = RuntimePersistence()
            loaded_state = persistence.load_run_state(result["run_id"])
            loaded_plan = persistence.load_plan(result["run_id"])

            assert loaded_state is not None
            assert loaded_state.status == RunStatus.RUNNING
            assert loaded_state.active_task_id is None

            assert loaded_plan is not None
            assert loaded_plan.tasks[0].status == TaskStatus.PASSED
            assert loaded_plan.tasks[1].status == TaskStatus.PENDING
            assert loaded_plan.tasks[2].status == TaskStatus.PENDING

            # Verify evidence for both attempts is persisted
            persisted_evidence = persistence.load_all_evidence(
                result["run_id"]
            )
            assert len(persisted_evidence) >= 2

            # Count per-attempt evidence (evidence has attempt in payload)
            attempt_1_evidence = [
                e
                for e in persisted_evidence
                if isinstance(e.payload, dict) and e.payload.get("attempt") == 1
            ]
            attempt_2_evidence = [
                e
                for e in persisted_evidence
                if isinstance(e.payload, dict) and e.payload.get("attempt") == 2
            ]
            # Prove evidence exists for both attempt 1 AND attempt 2, not either one
            assert len(attempt_1_evidence) > 0, "No evidence found for attempt 1"
            assert len(attempt_2_evidence) > 0, "No evidence found for attempt 2"

            # Verify verification results for both attempts
            # Verification results are saved as JSONL in run.log.jsonl
            run_log_path = DEFAULT_RUNTIME_DIR / "runs" / result["run_id"] / "run.log.jsonl"
            verification_count = 0
            if run_log_path.exists():
                with open(run_log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                if "status" in entry and entry.get("status") in ["PASS", "FAIL"]:
                                    verification_count += 1
                            except json.JSONDecodeError:
                                continue
            assert verification_count >= 2


# =============================================================================
# WORKER-LEVEL TESTS - Scenario B: Exhaustion -> Human Gate -> ABORT
# =============================================================================


class TestScenarioBWorker:
    """
    Scenario B - Exhaustion -> Human Gate -> ABORT using real Mistral Workflows test worker.

    max_attempts=2
    fail_first=999
    attempt 1 FAIL -> retry
    attempt 2 FAIL -> NEEDS_HUMAN
    TEST MUST observe persisted gate state before signal
    send typed ABORT signal
    final task FAILED, final run FAILED, active_task_id=None
    structured human-decision audit evidence persisted
    """

    @pytest.fixture(autouse=True)
    def cleanup_runtime(self):
        """Clean up runtime directory before and after each test."""
        persistence = RuntimePersistence()
        persistence.cleanup_all()
        yield
        persistence.cleanup_all()

    @pytest.mark.asyncio
    async def test_scenario_b_worker_level(
        self, temporal_env
    ):
        """
        Scenario B: Exhaustion -> Human Gate -> ABORT using real test worker.
        Tests observe NEEDS_HUMAN state before sending signal.
        """
        from mistralai.workflows.testing import create_test_worker
        from datetime import timedelta

        WORKFLOW_EXECUTION_TIMEOUT = timedelta(seconds=15)

        # Store run_id for later verification
        test_run_id = "test-fsasm-m4-scenario-b"

        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=[
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
            ],
        ):
            # Execute workflow with max_retries=1 (2 total attempts), always fail
            handle = await temporal_env.client.start_workflow(
                "fsasm-milestone-four",
                {
                    "goal": "Test Scenario B",
                    "planner_backend": "stub",
                    "executor_backend": "stub",
                    "max_retries_per_task": 1,
                    "stub_fail_first_n_attempts": 999,
                    "run_id": test_run_id,
                },
                id=test_run_id,
                task_queue="test-task-queue",
                execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            )

            # Wait for workflow to reach NEEDS_HUMAN state
            # Poll the persisted state to observe NEEDS_HUMAN
            persistence = RuntimePersistence()

            # Wait for human gate to be invoked
            max_wait = 10
            observed_needs_human = False
            for _ in range(max_wait * 10):  # 100ms intervals, 10s max
                await asyncio.sleep(0.1)
                try:
                    loaded_state = persistence.load_run_state(test_run_id)
                    loaded_plan = persistence.load_plan(test_run_id)
                    if (
                        loaded_state is not None
                        and loaded_state.status == RunStatus.NEEDS_HUMAN
                        and loaded_plan is not None
                        and loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
                        and loaded_state.active_task_id is None
                        and loaded_plan.tasks[0].attempt == 2
                    ):
                        observed_needs_human = True
                        break
                except Exception:
                    continue

            assert observed_needs_human, (
                "Human Gate state (NEEDS_HUMAN for both task and run) was not observed before signal"
            )

            # Now send ABORT signal
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001",
                    action=HumanDecisionAction.ABORT,
                    reason="Test ABORT",
                ),
            )

            # Wait for completion
            result = await asyncio.wait_for(
                handle.result(), timeout=10
            )

            # Verify structured result
            assert isinstance(result, dict)
            assert result["run_id"] == test_run_id
            assert result["status"] == "FAILED"
            assert result["human_gate_invoked"] is True
            assert result["success"] is False

            # Verify human decision was recorded
            assert result["human_decision"] is not None
            assert result["human_decision"]["task_id"] == "TASK-001"
            assert result["human_decision"]["action"] == "ABORT"

            # Verify TASK-001 FAILED
            assert "TASK-001" in result["failed_task_ids"]
            assert "TASK-001" not in result["passed_task_ids"]

            # Verify TASK-002 and TASK-003 remain PENDING
            assert "TASK-002" not in result["executed_task_ids"]
            assert "TASK-003" not in result["executed_task_ids"]

            # Verify final persisted state
            loaded_state = persistence.load_run_state(test_run_id)
            loaded_plan = persistence.load_plan(test_run_id)

            assert loaded_state is not None
            assert loaded_state.status == RunStatus.FAILED
            assert loaded_state.active_task_id is None
            assert "TASK-001" in loaded_state.failed_task_ids

            assert loaded_plan is not None
            assert loaded_plan.tasks[0].status == TaskStatus.FAILED
            assert loaded_plan.tasks[1].status == TaskStatus.PENDING
            assert loaded_plan.tasks[2].status == TaskStatus.PENDING

            # Verify Human Gate audit evidence persisted
            persisted_evidence = persistence.load_all_evidence(test_run_id)
            human_gate_audit = [
                e
                for e in persisted_evidence
                if e.kind == "human_gate_audit"
                and e.payload.get("action") == "ABORT"
            ]
            assert len(human_gate_audit) == 1
            assert human_gate_audit[0].payload["task_id"] == "TASK-001"
            assert human_gate_audit[0].payload["run_status_after"] == "FAILED"
            assert human_gate_audit[0].payload["task_status_after"] == "FAILED"

            # Verify evidence for both failed attempts is persisted
            # Verification results are saved as JSONL in run.log.jsonl
            run_log_path = DEFAULT_RUNTIME_DIR / "runs" / test_run_id / "run.log.jsonl"
            verification_count = 0
            if run_log_path.exists():
                with open(run_log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                if "status" in entry and entry.get("status") in ["PASS", "FAIL"]:
                                    verification_count += 1
                            except json.JSONDecodeError:
                                continue
            assert verification_count >= 2


# =============================================================================
# WORKER-LEVEL TESTS - Scenario C: Exhaustion -> Human Gate -> RETRY_ONCE -> PASS
# =============================================================================


class TestScenarioCWorker:
    """
    Scenario C - Exhaustion -> Human Gate -> RETRY_ONCE -> PASS using real Mistral Workflows test worker.

    max_attempts=1
    fail_first=1
    attempt 1 FAIL -> NEEDS_HUMAN
    TEST MUST observe persisted gate state before signal
    send RETRY_ONCE
    max_attempts becomes 2
    attempt 2 PASS
    final TASK-001 PASSED, run RUNNING, active_task_id=None
    TASK-002/003 PENDING
    human-decision audit persisted
    """

    @pytest.fixture(autouse=True)
    def cleanup_runtime(self):
        """Clean up runtime directory before and after each test."""
        persistence = RuntimePersistence()
        persistence.cleanup_all()
        yield
        persistence.cleanup_all()

    @pytest.mark.asyncio
    async def test_scenario_c_worker_level(
        self, temporal_env
    ):
        """
        Scenario C: Exhaustion -> Human Gate -> RETRY_ONCE -> PASS using real test worker.
        Tests observe NEEDS_HUMAN state before sending signal.
        """
        from mistralai.workflows.testing import create_test_worker
        from datetime import timedelta

        WORKFLOW_EXECUTION_TIMEOUT = timedelta(seconds=15)

        # Store run_id for later verification
        test_run_id = "test-fsasm-m4-scenario-c"

        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=[
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
            ],
        ):
            # Execute workflow with max_retries=0 (1 total attempt), fail first
            handle = await temporal_env.client.start_workflow(
                "fsasm-milestone-four",
                {
                    "goal": "Test Scenario C",
                    "planner_backend": "stub",
                    "executor_backend": "stub",
                    "max_retries_per_task": 0,
                    "stub_fail_first_n_attempts": 1,
                    "run_id": test_run_id,
                },
                id=test_run_id,
                task_queue="test-task-queue",
                execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            )

            # Wait for workflow to reach NEEDS_HUMAN state
            persistence = RuntimePersistence()

            max_wait = 10
            observed_needs_human = False
            for _ in range(max_wait * 10):
                await asyncio.sleep(0.1)
                try:
                    loaded_state = persistence.load_run_state(test_run_id)
                    loaded_plan = persistence.load_plan(test_run_id)
                    if (
                        loaded_state is not None
                        and loaded_state.status == RunStatus.NEEDS_HUMAN
                        and loaded_plan is not None
                        and loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
                        and loaded_state.active_task_id is None
                        and loaded_plan.tasks[0].attempt == 1
                    ):
                        observed_needs_human = True
                        break
                except Exception:
                    continue

            assert observed_needs_human, (
                "Human Gate state (NEEDS_HUMAN for both task and run) was not observed before signal"
            )

            # Now send RETRY_ONCE signal
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001",
                    action=HumanDecisionAction.RETRY_ONCE,
                    reason="Give it one more try",
                ),
            )

            # Wait for completion
            result = await asyncio.wait_for(
                handle.result(), timeout=10
            )

            # Verify structured result
            assert isinstance(result, dict)
            assert result["run_id"] == test_run_id
            assert result["status"] == "RUNNING"
            assert result["human_gate_invoked"] is True
            assert result["success"] is True

            # Verify human decision was recorded
            assert result["human_decision"] is not None
            assert result["human_decision"]["task_id"] == "TASK-001"
            assert result["human_decision"]["action"] == "RETRY_ONCE"

            # Verify TASK-001 PASSED
            assert "TASK-001" in result["passed_task_ids"]
            assert "TASK-001" not in result["failed_task_ids"]
            assert "TASK-001" not in result["needs_human_task_ids"]

            # Verify TASK-002 and TASK-003 remain PENDING
            assert "TASK-002" not in result["executed_task_ids"]
            assert "TASK-003" not in result["executed_task_ids"]

            # Verify final persisted state
            loaded_state = persistence.load_run_state(test_run_id)
            loaded_plan = persistence.load_plan(test_run_id)

            assert loaded_state is not None
            assert loaded_state.status == RunStatus.RUNNING
            assert loaded_state.active_task_id is None
            assert "TASK-001" in loaded_state.completed_task_ids
            assert "TASK-001" not in loaded_state.failed_task_ids

            assert loaded_plan is not None
            assert loaded_plan.tasks[0].status == TaskStatus.PASSED
            assert loaded_plan.tasks[1].status == TaskStatus.PENDING
            assert loaded_plan.tasks[2].status == TaskStatus.PENDING

            # Verify Human Gate audit evidence persisted
            persisted_evidence = persistence.load_all_evidence(test_run_id)
            human_gate_audit = [
                e
                for e in persisted_evidence
                if e.kind == "human_gate_audit"
                and e.payload.get("action") == "RETRY_ONCE"
            ]
            assert len(human_gate_audit) == 1
            assert human_gate_audit[0].payload["task_id"] == "TASK-001"
            assert human_gate_audit[0].payload["run_status_after"] == "RUNNING"
            assert human_gate_audit[0].payload["task_status_after"] == "READY"
            assert human_gate_audit[0].payload["max_attempts_after"] == 2

            # Verify evidence for both attempts is persisted
            # Verification results are saved as JSONL in run.log.jsonl
            run_log_path = DEFAULT_RUNTIME_DIR / "runs" / test_run_id / "run.log.jsonl"
            verification_count = 0
            if run_log_path.exists():
                with open(run_log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                if "status" in entry and entry.get("status") in ["PASS", "FAIL"]:
                                    verification_count += 1
                            except json.JSONDecodeError:
                                continue
            assert verification_count >= 2


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestEdgeCases:
    """Edge case tests for M4."""

    @pytest.fixture(autouse=True)
    def cleanup_runtime(self):
        persistence = RuntimePersistence()
        persistence.cleanup_all()
        yield
        persistence.cleanup_all()

    @pytest.mark.asyncio
    async def test_zero_retries_goes_straight_to_human_gate(self):
        """Test that with max_retries=0, failure goes straight to Human Gate."""
        persistence = RuntimePersistence()

        input_data = WorkflowInput(
            goal="Test zero retries",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=0,
            stub_fail_first_n_attempts=999,
        )

        planner_config = PlannerConfig(
            backend=PlannerBackend.STUB,
            max_tokens=4096,
            temperature=0.0,
        )
        executor_config = ExecutorConfig(
            backend=ExecutorBackend.STUB,
            max_tokens=4096,
            temperature=0.0,
            stub_fail_first_n_attempts=999,
        )

        goal_input = GoalInput(goal=input_data.goal)
        planner_output = await plan_activity(goal_input, planner_config)
        plan = planner_output.plan

        plan, state = await persist_initial_state_activity(
            planner_output, goal_input
        )
        # persist_initial_state_activity already transitions to RUNNING
        persistence.save_run_state(state)

        plan = await set_task_max_attempts_activity(
            plan, input_data.max_retries_per_task
        )
        persistence.save_plan(plan)

        task = await find_next_ready_task_activity(plan, [])
        assert task.task_id == "TASK-001"
        assert task.max_attempts == 1  # 0 retries + 1 initial

        # Execute first attempt
        state, task = await prepare_task_activity(state, task)
        assert task.attempt == 1

        executor_output = await execute_task_activity(
            task, state.run_id, executor_config, attempt=task.attempt
        )
        await validate_executor_output_provenance_activity(
            executor_output, task.task_id, state.run_id
        )

        task_evidence_records = await convert_executor_output_to_evidence_activity(
            executor_output, task, 0, attempt=task.attempt
        )

        verification_result = await verify_task_execution_activity(
            state.run_id, task, task_evidence_records
        )
        assert verification_result.status == VerificationResultStatus.FAIL

        task, state, _ = await persist_failure_state_activity(
            task, state, verification_result, task_evidence_records, task.attempt
        )

        can_retry, reason = await check_retry_budget_activity(task)
        assert can_retry is False  # max_attempts=1, attempt=1, exhausted

        # Should go straight to NEEDS_HUMAN
        task, state = await transition_to_needs_human_activity(
            task, state, reason
        )
        assert task.status == TaskStatus.NEEDS_HUMAN
        assert state.status == RunStatus.NEEDS_HUMAN
        assert state.active_task_id is None


# =============================================================================
# WORKER-LEVEL TESTS - Regression: RETRY_ONCE authorizes exactly one additional execution
# =============================================================================


class TestRetryOnceRegressionWorker:
    """
    Regression test: RETRY_ONCE authorizes exactly one additional execution.

    This is the critical test case from the external review.

    total initial max_attempts = 1
    Stub always fails
    attempt 1 FAIL -> Human Gate #1
    observe persisted NEEDS_HUMAN
    send RETRY_ONCE
    attempt 2 FAIL
    workflow MUST enter and remain at Human Gate #2
    verify attempt=2, max_attempts=2 and no attempt 3 occurs without another signal
    only then send a new ABORT signal to finish the test

    This proves RETRY_ONCE authorizes exactly one additional execution.
    """

    @pytest.fixture(autouse=True)
    def cleanup_runtime(self):
        """Clean up runtime directory before and after each test."""
        persistence = RuntimePersistence()
        persistence.cleanup_all()
        yield
        persistence.cleanup_all()

    @pytest.mark.asyncio
    async def test_retry_once_authorizes_exactly_one_additional_execution(
        self, temporal_env
    ):
        """
        Regression test: RETRY_ONCE authorizes exactly one additional execution.

        total initial max_attempts = 1
        Stub always fails
        attempt 1 FAIL -> Human Gate #1
        observe persisted NEEDS_HUMAN
        send RETRY_ONCE
        attempt 2 FAIL
        workflow MUST enter and remain at Human Gate #2
        verify attempt=2, max_attempts=2 and no attempt 3 occurs without another signal
        only then send a new ABORT signal to finish the test
        """
        from mistralai.workflows.testing import create_test_worker
        from datetime import timedelta

        WORKFLOW_EXECUTION_TIMEOUT = timedelta(seconds=15)
        test_run_id = "test-fsasm-m4-retry-once-regression"

        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneFourWorkflow],
            activities=[
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
            ],
        ):
            # Execute workflow with max_retries=0 (1 total attempt), always fail
            handle = await temporal_env.client.start_workflow(
                "fsasm-milestone-four",
                {
                    "goal": "Test RETRY_ONCE regression",
                    "planner_backend": "stub",
                    "executor_backend": "stub",
                    "max_retries_per_task": 0,
                    "stub_fail_first_n_attempts": 999,
                    "run_id": test_run_id,
                },
                id=test_run_id,
                task_queue="test-task-queue",
                execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            )

            # Wait for workflow to reach NEEDS_HUMAN state (Human Gate #1)
            persistence = RuntimePersistence()

            max_wait = 10
            observed_needs_human_1 = False
            for _ in range(max_wait * 10):
                await asyncio.sleep(0.1)
                try:
                    loaded_state = persistence.load_run_state(test_run_id)
                    loaded_plan = persistence.load_plan(test_run_id)
                    if (
                        loaded_state is not None
                        and loaded_state.status == RunStatus.NEEDS_HUMAN
                        and loaded_plan is not None
                        and loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
                        and loaded_state.active_task_id is None
                        and loaded_plan.tasks[0].attempt == 1
                        and loaded_plan.tasks[0].max_attempts == 1
                    ):
                        observed_needs_human_1 = True
                        break
                except Exception:
                    continue

            assert observed_needs_human_1, (
                "Human Gate #1 state was not observed before first signal"
            )

            # Send RETRY_ONCE signal
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001",
                    action=HumanDecisionAction.RETRY_ONCE,
                    reason="Give it one more try",
                ),
            )

            # Wait for workflow to reach NEEDS_HUMAN state again (Human Gate #2)
            # This proves RETRY_ONCE authorized exactly one additional execution
            observed_needs_human_2 = False
            for _ in range(max_wait * 10):
                await asyncio.sleep(0.1)
                try:
                    loaded_state = persistence.load_run_state(test_run_id)
                    loaded_plan = persistence.load_plan(test_run_id)
                    if (
                        loaded_state is not None
                        and loaded_state.status == RunStatus.NEEDS_HUMAN
                        and loaded_plan is not None
                        and loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
                        and loaded_state.active_task_id is None
                        and loaded_plan.tasks[0].attempt == 2
                        and loaded_plan.tasks[0].max_attempts == 2
                    ):
                        observed_needs_human_2 = True
                        break
                except Exception:
                    continue

            assert observed_needs_human_2, (
                "Human Gate #2 state was not observed after RETRY_ONCE - workflow did not enter NEEDS_HUMAN again"
            )

            # Verify that attempt=2 and max_attempts=2, and no attempt 3 occurred
            loaded_plan = persistence.load_plan(test_run_id)
            assert loaded_plan.tasks[0].attempt == 2, "Attempt should be exactly 2"
            assert loaded_plan.tasks[0].max_attempts == 2, "max_attempts should be exactly 2"

            # Now send ABORT signal to finish the test
            await handle.signal(
                FsasmMilestoneFourWorkflow.receive_human_decision,
                HumanDecisionSignal(
                    task_id="TASK-001",
                    action=HumanDecisionAction.ABORT,
                    reason="No more retries",
                ),
            )

            # Wait for completion
            result = await asyncio.wait_for(
                handle.result(), timeout=10
            )

            # Verify structured result
            assert isinstance(result, dict)
            assert result["run_id"] == test_run_id
            assert result["status"] == "FAILED"
            assert result["human_gate_invoked"] is True
            assert result["success"] is False

            # Verify TASK-001 FAILED
            assert "TASK-001" in result["failed_task_ids"]
            assert "TASK-001" not in result["passed_task_ids"]

            # Verify TASK-002 and TASK-003 remain PENDING
            assert "TASK-002" not in result["executed_task_ids"]
            assert "TASK-003" not in result["executed_task_ids"]

            # Verify final persisted state
            loaded_state = persistence.load_run_state(test_run_id)
            loaded_plan = persistence.load_plan(test_run_id)

            assert loaded_state is not None
            assert loaded_state.status == RunStatus.FAILED
            assert loaded_state.active_task_id is None
            assert "TASK-001" in loaded_state.failed_task_ids

            assert loaded_plan is not None
            assert loaded_plan.tasks[0].status == TaskStatus.FAILED
            assert loaded_plan.tasks[0].attempt == 2
            assert loaded_plan.tasks[0].max_attempts == 2
            assert loaded_plan.tasks[1].status == TaskStatus.PENDING
            assert loaded_plan.tasks[2].status == TaskStatus.PENDING

            # Verify Human Gate audit evidence persisted for both gates
            persisted_evidence = persistence.load_all_evidence(test_run_id)
            human_gate_audit = [
                e for e in persisted_evidence if e.kind == "human_gate_audit"
            ]
            # Should have 2 human gate audit entries: RETRY_ONCE and ABORT
            assert len(human_gate_audit) == 2

            retry_audit = [e for e in human_gate_audit if e.payload.get("action") == "RETRY_ONCE"]
            abort_audit = [e for e in human_gate_audit if e.payload.get("action") == "ABORT"]
            assert len(retry_audit) == 1
            assert len(abort_audit) == 1

            # Verify evidence for both failed attempts is persisted
            run_log_path = DEFAULT_RUNTIME_DIR / "runs" / test_run_id / "run.log.jsonl"
            verification_count = 0
            if run_log_path.exists():
                with open(run_log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                if "status" in entry and entry.get("status") == "FAIL":
                                    verification_count += 1
                            except json.JSONDecodeError:
                                continue
            # Should have 2 FAIL verification results (attempt 1 and attempt 2)
            assert verification_count >= 2


# =============================================================================
# IMPORT FOR VALIDATION ERROR
# =============================================================================

from pydantic import ValidationError
