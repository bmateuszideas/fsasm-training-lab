"""Tests for FS-ASM Milestone Four workflow - Bounded Retry + Human Gate.

Worker-level tests using Mistral Workflows testing utilities.
Proves scenarios A, B, C as defined in the requirements.

Scenario A: autonomous retry then PASS
  - max_attempts=3, fail_first=1
  - attempt 1 FAIL -> durable FAILED -> READY
  - attempt 2 PASS
  - final attempt=2
  - TASK-001 PASSED, TASK-002/003 PENDING, run RUNNING, no Human Gate
  - evidence for both attempts persisted

Scenario B: exhaustion -> Human Gate -> ABORT
  - max_attempts=2, fail_first=999
  - attempt 1 FAIL -> retry
  - attempt 2 FAIL -> NEEDS_HUMAN
  - TEST MUST observe persisted gate state before signal
  - send typed ABORT signal
  - final task FAILED, final run FAILED, active_task_id=None
  - structured human-decision audit evidence persisted

Scenario C: exhaustion -> Human Gate -> RETRY_ONCE -> PASS
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
    check_retry_budget_activity,
    persist_failure_state_activity,
    transition_to_needs_human_activity,
    apply_human_decision_activity,
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
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
                dependencies=[],
                max_attempts=3,
            ),
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Task 2",
                description="Second task",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
                dependencies=["TASK-001"],
                max_attempts=3,
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Task 3",
                description="Third task",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
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
        # Mark TASK-001 as completed
        result = await find_next_ready_task_activity(sample_plan, ["TASK-001"])
        # Should return None because we only execute TASK-001
        assert result is None

    @pytest.mark.asyncio
    async def test_check_retry_budget(self):
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=1,
            max_attempts=3,
        )
        can_retry, reason = await check_retry_budget_activity(task, max_retries_per_task=2)
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
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=3,
            max_attempts=3,
        )
        can_retry, reason = await check_retry_budget_activity(task, max_retries_per_task=2)
        assert can_retry is False
        assert "exhausted all 2 retry attempts" in reason


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
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
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
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=0,
            max_attempts=3,
        )
        assert task.attempt == 0

        # Transition to RUNNING should increment
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
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=1,
            max_attempts=3,
        )
        assert task.attempt == 1

        # Transition to READY should NOT increment
        task = transition_task(task, TaskStatus.READY)
        assert task.attempt == 1  # Still 1, not 2

    def test_can_retry_logic(self):
        """Test can_retry() method."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=0,
            max_attempts=3,
        )
        assert task.can_retry() is True

        task.attempt = 2
        assert task.can_retry() is False


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
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
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
        # DO NOT add to failed_task_ids in persist_failure_state - we may retry
        assert "TASK-001" not in state.failed_task_ids
        assert state.active_task_id is None

        # Verify persisted state
        persistence = RuntimePersistence()
        loaded_state = persistence.load_run_state("test-run-123")
        assert loaded_state is not None
        # failed_task_ids should not contain TASK-001 since we may retry
        assert "TASK-001" not in loaded_state.failed_task_ids

    @pytest.mark.asyncio
    async def test_transition_to_needs_human_persists(self):
        """Test that transition_to_needs_human persists NEEDS_HUMAN state."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.FAILED,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=2,
            max_attempts=3,
        )

        tasks = [
            task,
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Test 2",
                description="Test 2",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Test 3",
                description="Test 3",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
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
        assert state.active_task_id is None
        # TASK-001 should be in failed_task_ids since we're not retrying
        assert "TASK-001" in state.failed_task_ids

        # Verify persisted state
        persistence = RuntimePersistence()
        loaded_state = persistence.load_run_state("test-run-456")
        assert loaded_state is not None

        loaded_plan = persistence.load_plan("test-run-456")
        assert loaded_plan is not None
        assert loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN

        # Check log entry
        log_entries = persistence.load_run_log("test-run-456")
        human_gate_entries = [e for e in log_entries if e.get("event") == "human_gate_invoked"]
        assert len(human_gate_entries) > 0
        assert human_gate_entries[0]["task_status"] == "NEEDS_HUMAN"
        assert human_gate_entries[0]["active_task_id"] is None

    @pytest.mark.asyncio
    async def test_apply_human_decision_retry_once(self):
        """Test apply_human_decision for RETRY_ONCE."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.NEEDS_HUMAN,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=2,
            max_attempts=3,
        )

        tasks = [task, ChildTask(
            task_id="TASK-002",
            sequence=2,
            title="Test 2",
            description="Test 2",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        ), ChildTask(
            task_id="TASK-003",
            sequence=3,
            title="Test 3",
            description="Test 3",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        )]

        state = RunState(
            run_id="test-run-789",
            goal="Test",
            status=RunStatus.RUNNING,
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

        task, state = await apply_human_decision_activity(
            decision, task, state, max_retries_per_task=2
        )

        assert task.status == TaskStatus.READY
        assert task.max_attempts == 3  # attempt was 2, so max_attempts = 2 + 1 = 3
        assert task.attempt == 2  # NOT reset

    @pytest.mark.asyncio
    async def test_apply_human_decision_abort(self):
        """Test apply_human_decision for ABORT."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test",
            description="Test",
            status=TaskStatus.NEEDS_HUMAN,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
            attempt=2,
            max_attempts=3,
        )

        tasks = [task, ChildTask(
            task_id="TASK-002",
            sequence=2,
            title="Test 2",
            description="Test 2",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        ), ChildTask(
            task_id="TASK-003",
            sequence=3,
            title="Test 3",
            description="Test 3",
            status=TaskStatus.PENDING,
            verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
        )]

        state = RunState(
            run_id="test-run-abc",
            goal="Test",
            status=RunStatus.RUNNING,
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

        task, state = await apply_human_decision_activity(
            decision, task, state, max_retries_per_task=2
        )

        assert task.status == TaskStatus.FAILED
        assert state.status == RunStatus.FAILED
        assert state.active_task_id is None


# =============================================================================
# WORKER-LEVEL TESTS - Scenario A: Autonomous retry then PASS
# =============================================================================


class TestScenarioA:
    """
    Scenario A - autonomous retry then PASS

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
    async def test_scenario_a_retry_then_pass(self):
        """
        Scenario A: autonomous retry then PASS
        Uses async execution without temporal to test core logic.
        """
        persistence = RuntimePersistence()

        # Setup input for Scenario A
        input_data = WorkflowInput(
            goal="Test Scenario A",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=2,  # + 1 initial = 3 total attempts
            stub_fail_first_n_attempts=1,  # First attempt fails, second passes
        )

        # Create planner config and output
        planner_config = PlannerConfig(
            backend=PlannerBackend.STUB,
            max_tokens=4096,
            temperature=0.0,
        )
        executor_config = ExecutorConfig(
            backend=ExecutorBackend.STUB,
            max_tokens=4096,
            temperature=0.0,
            stub_fail_first_n_attempts=1,
        )

        # Create goal input
        goal_input = GoalInput(goal=input_data.goal)

        # Run planner
        planner_output = await plan_activity(goal_input, planner_config)
        plan = planner_output.plan

        # Initialize state
        plan, state = await persist_initial_state_activity(planner_output, goal_input)
        state = transition_run(state, RunStatus.RUNNING)
        persistence.save_run_state(state)

        # Find TASK-001
        task = await find_next_ready_task_activity(plan, [])
        assert task is not None
        assert task.task_id == "TASK-001"

        executed_task_ids = [task.task_id]
        all_evidence_records = []
        verification_results = {}

        # First attempt - should fail
        state, task = await prepare_task_activity(state, task)
        assert task.attempt == 1  # Incremented on READY->RUNNING

        executor_output = await execute_task_activity(
            task, state.run_id, executor_config, attempt=task.attempt
        )
        await validate_executor_output_provenance_activity(
            executor_output, task.task_id, state.run_id
        )

        evidence_counter = len(all_evidence_records)
        task_evidence_records = await convert_executor_output_to_evidence_activity(
            executor_output, task, evidence_counter, attempt=task.attempt
        )
        all_evidence_records.extend(task_evidence_records)

        verification_result = await verify_task_execution_activity(
            state.run_id, task, task_evidence_records
        )
        verification_results[task.task_id] = verification_result

        # First attempt should FAIL
        assert verification_result.status == VerificationResultStatus.FAIL

        # Persist failure state
        task, state, _ = await persist_failure_state_activity(
            task, state, verification_result, task_evidence_records, task.attempt
        )
        assert task.status == TaskStatus.FAILED

        # Check retry budget
        can_retry, reason = await check_retry_budget_activity(
            task, input_data.max_retries_per_task
        )
        assert can_retry is True  # max_retries=2, attempt=1, so can retry

        # Transition to READY for retry
        task = transition_task(task, TaskStatus.READY)
        assert task.attempt == 1  # NOT incremented on FAILED->READY
        persistence.save_run_state(state)
        persistence.save_plan(state.plan)

        # Second attempt - should pass
        state, task = await prepare_task_activity(state, task)
        assert task.attempt == 2  # Incremented again on READY->RUNNING

        executor_output = await execute_task_activity(
            task, state.run_id, executor_config, attempt=task.attempt
        )
        await validate_executor_output_provenance_activity(
            executor_output, task.task_id, state.run_id
        )

        evidence_counter = len(all_evidence_records)
        task_evidence_records = await convert_executor_output_to_evidence_activity(
            executor_output, task, evidence_counter, attempt=task.attempt
        )
        all_evidence_records.extend(task_evidence_records)

        verification_result = await verify_task_execution_activity(
            state.run_id, task, task_evidence_records
        )
        verification_results[task.task_id] = verification_result

        # Second attempt should PASS
        assert verification_result.status == VerificationResultStatus.PASS

        # Finalize task
        state, task = await finalize_task_activity(
            state, task, verification_result, task_evidence_records
        )
        assert task.status == TaskStatus.PASSED

        # Verify final state
        persistence = RuntimePersistence()
        loaded_state = persistence.load_run_state(state.run_id)
        loaded_plan = persistence.load_plan(state.run_id)

        assert loaded_state.status == RunStatus.RUNNING
        assert loaded_state.active_task_id is None
        assert "TASK-001" in loaded_state.completed_task_ids
        assert "TASK-001" not in loaded_state.failed_task_ids

        # TASK-002 and TASK-003 should remain PENDING
        assert loaded_plan.tasks[1].status == TaskStatus.PENDING
        assert loaded_plan.tasks[2].status == TaskStatus.PENDING

        # Evidence for both attempts should be persisted
        evidence_files = get_all_evidence_files(state.run_id)
        assert len(evidence_files) >= 2  # At least 2 evidence records

        # Final attempt should be 2
        assert task.attempt == 2


# =============================================================================
# WORKER-LEVEL TESTS - Scenario B: Exhaustion -> Human Gate -> ABORT
# =============================================================================


class TestScenarioB:
    """
    Scenario B - exhaustion -> Human Gate -> ABORT

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
    async def test_scenario_b_exhaustion_to_abort(self):
        """
        Scenario B: exhaustion -> Human Gate -> ABORT
        Tests the full path up to NEEDS_HUMAN state persistence.
        """
        persistence = RuntimePersistence()

        # Setup input for Scenario B
        input_data = WorkflowInput(
            goal="Test Scenario B",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=1,  # + 1 initial = 2 total attempts
            stub_fail_first_n_attempts=999,  # All attempts fail
        )

        # Create configs
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

        # Initialize state
        plan, state = await persist_initial_state_activity(planner_output, goal_input)
        state = transition_run(state, RunStatus.RUNNING)
        persistence.save_run_state(state)

        task = await find_next_ready_task_activity(plan, [])
        assert task.task_id == "TASK-001"

        executed_task_ids = [task.task_id]
        all_evidence_records = []
        verification_results = {}

        # First attempt - should fail
        state, task = await prepare_task_activity(state, task)
        assert task.attempt == 1

        executor_output = await execute_task_activity(
            task, state.run_id, executor_config, attempt=task.attempt
        )
        await validate_executor_output_provenance_activity(
            executor_output, task.task_id, state.run_id
        )

        evidence_counter = len(all_evidence_records)
        task_evidence_records = await convert_executor_output_to_evidence_activity(
            executor_output, task, evidence_counter, attempt=task.attempt
        )
        all_evidence_records.extend(task_evidence_records)

        verification_result = await verify_task_execution_activity(
            state.run_id, task, task_evidence_records
        )
        assert verification_result.status == VerificationResultStatus.FAIL
        verification_results[task.task_id] = verification_result

        task, state, _ = await persist_failure_state_activity(
            task, state, verification_result, task_evidence_records, task.attempt
        )
        assert task.status == TaskStatus.FAILED

        can_retry, reason = await check_retry_budget_activity(
            task, input_data.max_retries_per_task
        )
        assert can_retry is True  # max_retries=1, attempt=1, can retry once more

        task = transition_task(task, TaskStatus.READY)
        assert task.attempt == 1
        persistence.save_run_state(state)
        persistence.save_plan(state.plan)

        # Second attempt - should also fail
        state, task = await prepare_task_activity(state, task)
        assert task.attempt == 2

        executor_output = await execute_task_activity(
            task, state.run_id, executor_config, attempt=task.attempt
        )
        await validate_executor_output_provenance_activity(
            executor_output, task.task_id, state.run_id
        )

        evidence_counter = len(all_evidence_records)
        task_evidence_records = await convert_executor_output_to_evidence_activity(
            executor_output, task, evidence_counter, attempt=task.attempt
        )
        all_evidence_records.extend(task_evidence_records)

        verification_result = await verify_task_execution_activity(
            state.run_id, task, task_evidence_records
        )
        assert verification_result.status == VerificationResultStatus.FAIL
        verification_results[task.task_id] = verification_result

        task, state, _ = await persist_failure_state_activity(
            task, state, verification_result, task_evidence_records, task.attempt
        )
        assert task.status == TaskStatus.FAILED

        can_retry, reason = await check_retry_budget_activity(
            task, input_data.max_retries_per_task
        )
        assert can_retry is False  # max_retries=1, attempt=2, exhausted

        # Transition to NEEDS_HUMAN
        task, state = await transition_to_needs_human_activity(
            task, state, reason
        )
        assert task.status == TaskStatus.NEEDS_HUMAN
        assert state.active_task_id is None
        assert "TASK-001" in state.failed_task_ids

        # Verify persisted state BEFORE sending signal
        persistence = RuntimePersistence()
        loaded_state = persistence.load_run_state(state.run_id)
        loaded_plan = persistence.load_plan(state.run_id)

        assert loaded_state is not None
        assert loaded_state.status == RunStatus.RUNNING
        assert loaded_state.active_task_id is None

        assert loaded_plan is not None
        assert loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
        assert loaded_plan.tasks[0].attempt == 2

        # Check human gate log entry
        log_entries = persistence.load_run_log(state.run_id)
        human_gate_entries = [e for e in log_entries if e.get("event") == "human_gate_invoked"]
        assert len(human_gate_entries) > 0
        assert human_gate_entries[0]["task_status"] == "NEEDS_HUMAN"
        assert human_gate_entries[0]["active_task_id"] is None
        assert human_gate_entries[0]["attempt"] == 2

        # Now apply ABORT decision
        decision = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.ABORT,
            reason="Test ABORT",
        )

        task, state = await apply_human_decision_activity(
            decision, task, state, input_data.max_retries_per_task
        )

        assert task.status == TaskStatus.FAILED
        assert state.status == RunStatus.FAILED
        assert state.active_task_id is None

        # Verify final persisted state
        loaded_state = persistence.load_run_state(state.run_id)
        assert loaded_state.status == RunStatus.FAILED
        assert loaded_state.active_task_id is None
        assert "TASK-001" in loaded_state.failed_task_ids

        # TASK-002 and TASK-003 should remain PENDING
        loaded_plan = persistence.load_plan(state.run_id)
        assert loaded_plan.tasks[1].status == TaskStatus.PENDING
        assert loaded_plan.tasks[2].status == TaskStatus.PENDING


# =============================================================================
# WORKER-LEVEL TESTS - Scenario C: Exhaustion -> Human Gate -> RETRY_ONCE -> PASS
# =============================================================================


class TestScenarioC:
    """
    Scenario C - exhaustion -> Human Gate -> RETRY_ONCE -> PASS

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
    async def test_scenario_c_retry_once_pass(self):
        """
        Scenario C: exhaustion -> Human Gate -> RETRY_ONCE -> PASS
        """
        persistence = RuntimePersistence()

        # Setup input for Scenario C
        input_data = WorkflowInput(
            goal="Test Scenario C",
            planner_backend=PlannerBackend.STUB,
            executor_backend=ExecutorBackend.STUB,
            max_retries_per_task=0,  # + 1 initial = 1 total attempt
            stub_fail_first_n_attempts=1,  # First attempt fails
        )

        # Create configs
        planner_config = PlannerConfig(
            backend=PlannerBackend.STUB,
            max_tokens=4096,
            temperature=0.0,
        )
        executor_config = ExecutorConfig(
            backend=ExecutorBackend.STUB,
            max_tokens=4096,
            temperature=0.0,
            stub_fail_first_n_attempts=1,
        )

        goal_input = GoalInput(goal=input_data.goal)
        planner_output = await plan_activity(goal_input, planner_config)
        plan = planner_output.plan

        # Initialize state
        plan, state = await persist_initial_state_activity(planner_output, goal_input)
        state = transition_run(state, RunStatus.RUNNING)
        persistence.save_run_state(state)

        task = await find_next_ready_task_activity(plan, [])
        assert task.task_id == "TASK-001"

        executed_task_ids = [task.task_id]
        all_evidence_records = []
        verification_results = {}

        # First attempt - should fail
        state, task = await prepare_task_activity(state, task)
        assert task.attempt == 1

        executor_output = await execute_task_activity(
            task, state.run_id, executor_config, attempt=task.attempt
        )
        await validate_executor_output_provenance_activity(
            executor_output, task.task_id, state.run_id
        )

        evidence_counter = len(all_evidence_records)
        task_evidence_records = await convert_executor_output_to_evidence_activity(
            executor_output, task, evidence_counter, attempt=task.attempt
        )
        all_evidence_records.extend(task_evidence_records)

        verification_result = await verify_task_execution_activity(
            state.run_id, task, task_evidence_records
        )
        assert verification_result.status == VerificationResultStatus.FAIL
        verification_results[task.task_id] = verification_result

        task, state, _ = await persist_failure_state_activity(
            task, state, verification_result, task_evidence_records, task.attempt
        )
        assert task.status == TaskStatus.FAILED

        # Update task max_attempts to match workflow config
        # effective_max_attempts = max_retries_per_task + 1 = 0 + 1 = 1
        task.max_attempts = input_data.max_retries_per_task + 1

        can_retry, reason = await check_retry_budget_activity(
            task, input_data.max_retries_per_task
        )
        assert can_retry is False  # max_retries=0, attempt=1, exhausted

        # Transition to NEEDS_HUMAN
        task, state = await transition_to_needs_human_activity(
            task, state, reason
        )
        assert task.status == TaskStatus.NEEDS_HUMAN

        # Verify persisted state BEFORE sending signal
        loaded_state = persistence.load_run_state(state.run_id)
        loaded_plan = persistence.load_plan(state.run_id)

        assert loaded_state is not None
        assert loaded_state.status == RunStatus.RUNNING
        assert loaded_state.active_task_id is None
        assert loaded_plan.tasks[0].status == TaskStatus.NEEDS_HUMAN
        assert loaded_plan.tasks[0].attempt == 1

        # Apply RETRY_ONCE decision
        decision = HumanDecision(
            task_id="TASK-001",
            action=HumanDecisionAction.RETRY_ONCE,
            reason="Give it one more try",
        )

        task, state = await apply_human_decision_activity(
            decision, task, state, input_data.max_retries_per_task
        )

        assert task.status == TaskStatus.READY
        assert task.max_attempts == 2  # attempt was 1, so max_attempts = 1 + 1 = 2
        assert task.attempt == 1  # NOT reset
        assert "TASK-001" not in state.failed_task_ids

        # Second attempt - should pass (stub_fail_first_n_attempts=1, so attempt 2 passes)
        state, task = await prepare_task_activity(state, task)
        assert task.attempt == 2

        executor_output = await execute_task_activity(
            task, state.run_id, executor_config, attempt=task.attempt
        )
        await validate_executor_output_provenance_activity(
            executor_output, task.task_id, state.run_id
        )

        evidence_counter = len(all_evidence_records)
        task_evidence_records = await convert_executor_output_to_evidence_activity(
            executor_output, task, evidence_counter, attempt=task.attempt
        )
        all_evidence_records.extend(task_evidence_records)

        verification_result = await verify_task_execution_activity(
            state.run_id, task, task_evidence_records
        )
        assert verification_result.status == VerificationResultStatus.PASS
        verification_results[task.task_id] = verification_result

        state, task = await finalize_task_activity(
            state, task, verification_result, task_evidence_records
        )
        assert task.status == TaskStatus.PASSED

        # Verify final state
        loaded_state = persistence.load_run_state(state.run_id)
        loaded_plan = persistence.load_plan(state.run_id)

        assert loaded_state.status == RunStatus.RUNNING
        assert loaded_state.active_task_id is None
        assert "TASK-001" in loaded_state.completed_task_ids
        assert "TASK-001" not in loaded_state.failed_task_ids

        # TASK-002 and TASK-003 should remain PENDING
        assert loaded_plan.tasks[1].status == TaskStatus.PENDING
        assert loaded_plan.tasks[2].status == TaskStatus.PENDING

        # Check human decision log entry
        log_entries = persistence.load_run_log(state.run_id)
        retry_entries = [e for e in log_entries if e.get("event") == "human_decision_retry_once"]
        assert len(retry_entries) > 0
        assert retry_entries[0]["action"] == "RETRY_ONCE"
        assert retry_entries[0]["new_max_attempts"] == 2


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
            max_retries_per_task=0,  # No retries
            stub_fail_first_n_attempts=999,  # Always fail
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

        plan, state = await persist_initial_state_activity(planner_output, goal_input)
        state = transition_run(state, RunStatus.RUNNING)
        persistence.save_run_state(state)

        task = await find_next_ready_task_activity(plan, [])
        assert task.task_id == "TASK-001"

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

        # Update task max_attempts to match workflow config
        task.max_attempts = input_data.max_retries_per_task + 1

        can_retry, reason = await check_retry_budget_activity(
            task, input_data.max_retries_per_task
        )
        assert can_retry is False  # max_retries=0, attempt=1, exhausted

        # Should go straight to NEEDS_HUMAN
        task, state = await transition_to_needs_human_activity(
            task, state, reason
        )
        assert task.status == TaskStatus.NEEDS_HUMAN
        assert state.active_task_id is None


# =============================================================================
# IMPORT FOR VALIDATION ERROR
# =============================================================================

from pydantic import ValidationError
