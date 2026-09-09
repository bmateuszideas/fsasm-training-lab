"""Tests for FS-ASM Milestone Three Workflow."""

import pytest
import asyncio

from fsasm.models import (
    ExecutorBackend,
    PlannerBackend,
    RunStatus,
    TaskStatus,
)
from fsasm.persistence import RuntimePersistence
from src.workflows import fsasm_milestone_three


class TestWorkflowInput:
    """Tests for WorkflowInput model."""

    def test_minimal_input(self):
        """Test minimal workflow input."""
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")
        assert input.goal == "Test goal"
        assert input.run_id is None
        assert input.planner_backend == PlannerBackend.STUB
        assert input.executor_backend == ExecutorBackend.STUB

    def test_full_input(self):
        """Test full workflow input."""
        input = fsasm_milestone_three.WorkflowInput(
            goal="Test goal",
            run_id="custom-run-id",
            planner_backend=PlannerBackend.STUB,
            planner_model_name="mistral-large",
            planner_prompt_version="v2.0",
            executor_backend=ExecutorBackend.STUB,
            executor_model_name="local-model",
        )
        assert input.goal == "Test goal"
        assert input.run_id == "custom-run-id"
        assert input.planner_backend == PlannerBackend.STUB
        assert input.executor_backend == ExecutorBackend.STUB


class TestWorkflowOutput:
    """Tests for WorkflowOutput model."""

    def test_workflow_output_structure(self):
        """Test WorkflowOutput has all required fields."""
        output = fsasm_milestone_three.WorkflowOutput(
            run_id="test-run",
            goal="Test goal",
            status="RUNNING",
            plan_id="test-plan",
            task_count=3,
            executed_task_id="TASK-001",
            executed_task_status="PASSED",
            verification_status="PASS",
            verification_message="All checks passed",
            evidence_count=5,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:01Z",
            success=True,
            planner_provider="stub",
            planner_model=None,
            planner_model_call_count=0,
            executor_provider="stub",
            executor_model_call_count=0,
        )
        assert output.run_id == "test-run"
        assert output.executed_task_id == "TASK-001"
        assert output.success is True


class TestWorkflowRegistration:
    """Tests for workflow registration."""

    def test_workflow_is_registered(self):
        """Test that the M3 workflow is registered."""
        from mistralai.workflows.core.definition.workflow_definition import (
            get_workflow_definition,
        )

        wf_def = get_workflow_definition(
            fsasm_milestone_three.FsasmMilestoneThreeWorkflow
        )
        assert wf_def.name == "fsasm-milestone-three"

    def test_workflow_has_entrypoint(self):
        """Test that the M3 workflow has an entrypoint."""
        assert hasattr(fsasm_milestone_three.FsasmMilestoneThreeWorkflow, "run")
        assert callable(fsasm_milestone_three.FsasmMilestoneThreeWorkflow.run)

    def test_workflow_description(self):
        """Test that the M3 workflow has proper description."""
        # Check description from workflow class docstring
        assert (
            "Milestone Three"
            in fsasm_milestone_three.FsasmMilestoneThreeWorkflow.__doc__
        )
        assert (
            "Exactly ONE task is executed"
            in fsasm_milestone_three.FsasmMilestoneThreeWorkflow.__doc__
        )


class TestWorkflowExecution:
    """Tests for workflow execution."""

    @pytest.mark.asyncio
    async def test_workflow_creates_run_id(self):
        """Test that workflow creates a run_id when not provided."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        # Result is a dict after crossing workflow boundary
        assert isinstance(result, dict)
        assert "run_id" in result
        assert result["run_id"] is not None
        assert len(result["run_id"]) > 0

    @pytest.mark.asyncio
    async def test_workflow_uses_provided_run_id(self):
        """Test that workflow uses provided run_id."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(
            goal="Test goal", run_id="my-custom-run-id"
        )

        result = await wf.run(input)

        assert result["run_id"] == "my-custom-run-id"

    @pytest.mark.asyncio
    async def test_workflow_creates_plan_with_3_tasks(self):
        """Test that workflow creates a plan with exactly 3 tasks."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        assert result["task_count"] == 3

    @pytest.mark.asyncio
    async def test_workflow_executes_one_task(self):
        """Test that workflow executes exactly one task."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        assert result["executed_task_id"] is not None
        assert result["executed_task_id"].startswith("TASK-")
        assert result["executed_task_status"] in ["PASSED", "FAILED"]

    @pytest.mark.asyncio
    async def test_workflow_returns_stub_metadata(self):
        """Test that workflow returns stub executor metadata."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        assert result["executor_provider"] == "stub"
        assert result["executor_model_call_count"] == 0
        assert result["planner_provider"] == "stub"
        assert result["planner_model_call_count"] == 0

    @pytest.mark.asyncio
    async def test_workflow_status_remains_running(self):
        """Test that run status remains RUNNING after M3 execution."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        assert result["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_workflow_persists_state(self):
        """Test that workflow persists state to filesystem."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        # Check that state was persisted
        persistence = RuntimePersistence()
        loaded_state = persistence.load_run_state(result["run_id"])
        assert loaded_state is not None
        assert loaded_state.run_id == result["run_id"]
        assert loaded_state.goal == result["goal"]

    @pytest.mark.asyncio
    async def test_workflow_persists_plan(self):
        """Test that workflow persists plan to filesystem."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        # Check that plan was persisted
        persistence = RuntimePersistence()
        loaded_plan = persistence.load_plan(result["run_id"])
        assert loaded_plan is not None
        assert loaded_plan.plan_id == result["plan_id"]
        assert len(loaded_plan.tasks) == 3

    @pytest.mark.asyncio
    async def test_workflow_persists_evidence(self):
        """Test that workflow persists evidence to filesystem."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        # Check that evidence was persisted
        persistence = RuntimePersistence()
        evidence = persistence.load_all_evidence(result["run_id"])
        assert len(evidence) > 0
        assert result["evidence_count"] == len(evidence)

    @pytest.mark.asyncio
    async def test_workflow_verification_result(self):
        """Test that workflow returns verification result."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(goal="Test goal")

        result = await wf.run(input)

        assert result["verification_status"] in ["PASS", "FAIL"]
        assert len(result["verification_message"]) > 0

    @pytest.mark.asyncio
    async def test_workflow_deterministic(self):
        """Test that workflow execution is deterministic."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(
            goal="Test goal", run_id="deterministic-run"
        )

        result1 = await wf.run(input)
        result2 = await wf.run(input)

        assert result1["run_id"] == result2["run_id"]
        assert result1["plan_id"] == result2["plan_id"]
        assert result1["task_count"] == result2["task_count"]

    @pytest.mark.asyncio
    async def test_workflow_accepts_stub_planner(self):
        """Test that workflow accepts STUB planner backend."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
        )

        result = await wf.run(input)
        assert result["planner_provider"] == "stub"

    @pytest.mark.asyncio
    async def test_workflow_requires_stub_executor(self):
        """Test that workflow requires STUB executor backend for M3."""
        wf = fsasm_milestone_three.FsasmMilestoneThreeWorkflow()
        input = fsasm_milestone_three.WorkflowInput(
            goal="Test goal",
            executor_backend=ExecutorBackend.MISTRAL,
        )
        from fsasm.errors import ConfigurationError

        with pytest.raises(ConfigurationError):
            await wf.run(input)


class TestWorkflowLevelExecution:
    """Workflow-level tests using create_test_worker."""

    @pytest.mark.asyncio
    async def test_workflow_level_execution_with_test_worker(self, temporal_env):
        """Test M3 workflow execution with real worker."""
        from mistralai.workflows.testing import create_test_worker
        from src.workflows.fsasm_milestone_three import (
            FsasmMilestoneThreeWorkflow,
            WorkflowInput,
            create_input_activity,
            validate_config_activity,
            plan_activity,
            persist_initial_state_activity,
            find_first_ready_task_activity,
            prepare_task_activity,
            execute_task_activity,
            validate_executor_output_provenance_activity,
            convert_executor_output_to_evidence_activity,
            verify_task_execution_activity,
            finalize_task_activity,
            persist_final_m3_state_activity,
        )
        from datetime import timedelta

        WORKFLOW_EXECUTION_TIMEOUT = timedelta(seconds=10)

        async with create_test_worker(
            temporal_env,
            workflows=[FsasmMilestoneThreeWorkflow],
            activities=[
                create_input_activity,
                validate_config_activity,
                plan_activity,
                persist_initial_state_activity,
                find_first_ready_task_activity,
                prepare_task_activity,
                execute_task_activity,
                validate_executor_output_provenance_activity,
                convert_executor_output_to_evidence_activity,
                verify_task_execution_activity,
                finalize_task_activity,
                persist_final_m3_state_activity,
            ],
        ):
            # Execute workflow through the client API with STUB backend
            handle = await temporal_env.client.start_workflow(
                "fsasm-milestone-three",
                {
                    "goal": "Test workflow level execution M3",
                    "executor_backend": "stub",
                },
                id="test-fsasm-m3-workflow-level",
                task_queue="test-task-queue",
                execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            )

            # Wait for result with client-side timeout as fallback
            result = await asyncio.wait_for(handle.result(), timeout=15)

            # Verify structured result
            assert isinstance(result, dict)
            assert "run_id" in result
            assert "goal" in result
            assert result["run_id"] is not None
            assert result["status"] == "RUNNING"
            assert result["task_count"] == 3
            assert result["executed_task_id"] is not None
            assert result["executed_task_status"] in ["PASSED", "FAILED"]
            assert result["success"] is not None
            assert result["executor_provider"] == "stub"
            assert result["executor_model_call_count"] == 0

            # Issue 1: FINAL PLAN STALENESS - verify state.json and plan.json are consistent
            from fsasm.persistence import RuntimePersistence
            from fsasm.models import TaskStatus

            persistence = RuntimePersistence()
            loaded_state = persistence.load_run_state(result["run_id"])
            loaded_plan = persistence.load_plan(result["run_id"])

            # Verify state.json and plan.json contain identical task statuses
            assert loaded_state is not None
            assert loaded_plan is not None

            # Check that executed task is PASSED/FAILED in both
            executed_task_id = result["executed_task_id"]
            executed_task_status = result["executed_task_status"]

            # Find the executed task in both state and plan
            state_task = next(
                (t for t in loaded_state.plan.tasks if t.task_id == executed_task_id),
                None,
            )
            plan_task = next(
                (t for t in loaded_plan.tasks if t.task_id == executed_task_id), None
            )

            assert state_task is not None
            assert plan_task is not None
            assert state_task.status.value == executed_task_status
            assert plan_task.status.value == executed_task_status

            # Check that other tasks remain PENDING in both
            other_tasks_state = [
                t for t in loaded_state.plan.tasks if t.task_id != executed_task_id
            ]
            other_tasks_plan = [
                t for t in loaded_plan.tasks if t.task_id != executed_task_id
            ]

            for task in other_tasks_state:
                assert task.status == TaskStatus.PENDING, (
                    f"Task {task.task_id} should be PENDING in state.plan but is {task.status}"
                )

            for task in other_tasks_plan:
                assert task.status == TaskStatus.PENDING, (
                    f"Task {task.task_id} should be PENDING in plan.json but is {task.status}"
                )
