"""Tests for FS-ASM Milestone One Workflow."""

import json
import tempfile
from pathlib import Path

import pytest

from fsasm.models import GoalInput, Plan
from fsasm.persistence import RuntimePersistence


class TestFsasmMilestoneOneWorkflow:
    """Tests for the FS-ASM milestone one workflow."""

    @pytest.fixture
    def workflow_module(self):
        """Import the workflow module."""
        from src.workflows import fsasm_milestone_one
        return fsasm_milestone_one

    @pytest.fixture
    def temp_persistence(self):
        """Create a temporary persistence instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            yield RuntimePersistence(runtime_dir=runtime_dir)

    # =========================================================================
    # BASIC WORKFLOW TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_workflow_returns_result(self, workflow_module):
        """Test that workflow returns a structured result."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Test goal for workflow")
        result = await workflow.run(input_data)
        assert isinstance(result, dict)
        assert "run_id" in result
        assert "goal" in result
        assert "status" in result
        assert "success" in result

    @pytest.mark.asyncio
    async def test_workflow_creates_run_id(self, workflow_module):
        """Test that workflow creates a run_id."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Test goal")
        result = await workflow.run(input_data)
        assert result["run_id"] is not None
        assert len(result["run_id"]) > 0

    @pytest.mark.asyncio
    async def test_workflow_uses_provided_run_id(self, workflow_module):
        """Test that workflow uses provided run_id."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(
            goal="Test goal", run_id="custom-workflow-run-id"
        )
        result = await workflow.run(input_data)
        assert result["run_id"] == "custom-workflow-run-id"

    @pytest.mark.asyncio
    async def test_workflow_creates_plan(self, workflow_module):
        """Test that workflow creates a plan."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Test goal")
        result = await workflow.run(input_data)
        assert "plan_id" in result
        assert result["plan_id"] is not None

    @pytest.mark.asyncio
    async def test_workflow_creates_3_tasks(self, workflow_module):
        """Test that workflow creates exactly 3 tasks."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Test goal")
        result = await workflow.run(input_data)
        assert "task_count" in result
        assert result["task_count"] == 3
        assert "task_ids" in result
        assert len(result["task_ids"]) == 3

    @pytest.mark.asyncio
    async def test_workflow_persists_state(self, workflow_module, temp_persistence):
        """Test that workflow persists state."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Test goal for persistence")
        result = await workflow.run(input_data)
        assert result["status"] in ["PASSED", "FAILED"]
        assert "created_at" in result
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_workflow_returns_pass_status(self, workflow_module):
        """Test that workflow returns PASS status for valid execution."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Test goal")
        result = await workflow.run(input_data)
        assert result["success"] is True
        assert result["status"] == "PASSED"
        assert result["verification_status"] == "PASS"
        assert result["evidence_count"] > 0

    @pytest.mark.asyncio
    async def test_workflow_creates_evidence(self, workflow_module):
        """Test that workflow creates evidence records."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Test goal")
        result = await workflow.run(input_data)
        assert "evidence_count" in result
        assert result["evidence_count"] > 0

    # =========================================================================
    # INPUT VALIDATION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_workflow_rejects_blank_goal(self, workflow_module):
        """Test that workflow rejects blank goal."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        with pytest.raises(Exception):
            await workflow.run(workflow_module.WorkflowInput(goal=""))

    @pytest.mark.asyncio
    async def test_workflow_accepts_minimal_input(self, workflow_module):
        """Test that workflow accepts minimal input (just goal)."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Minimal test")
        result = await workflow.run(input_data)
        assert result["success"] is True

    # =========================================================================
    # INTEGRATION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_workflow_full_integration(self, workflow_module):
        """Full integration test of the workflow."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Integrate all components")
        result = await workflow.run(input_data)
        expected_fields = [
            "run_id", "goal", "status", "plan_id", "task_count",
            "task_ids", "verification_status", "verification_message",
            "evidence_count", "created_at", "updated_at", "success",
        ]
        for field in expected_fields:
            assert field in result, f"Missing field: {field}"
        assert result["goal"] == "Integrate all components"
        assert result["task_count"] == 3
        assert result["success"] is True
        assert result["status"] == "PASSED"
        assert result["verification_status"] == "PASS"
        assert result["evidence_count"] > 0

    @pytest.mark.asyncio
    async def test_workflow_deterministic(self, workflow_module):
        """Test that workflow produces deterministic results."""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="Deterministic test")
        result1 = await workflow.run(input_data)
        result2 = await workflow.run(input_data)
        assert result1["task_count"] == result2["task_count"]
        assert result1["status"] == result2["status"]
        assert result1["success"] == result2["success"]

    # =========================================================================
    # ACTIVITY TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_input_activity(self, workflow_module):
        """Test the create_input_activity directly."""
        input_data = workflow_module.WorkflowInput(goal="Test goal", run_id="test-run-123")
        result = await workflow_module.create_input_activity(input_data)
        assert isinstance(result, GoalInput)
        assert result.goal == "Test goal"
        assert result.run_id == "test-run-123"

    @pytest.mark.asyncio
    async def test_plan_activity(self, workflow_module):
        """Test the plan_activity directly."""
        goal_input = GoalInput(goal="Test goal", run_id="test-run-456")
        result = await workflow_module.plan_activity(goal_input)
        assert isinstance(result, Plan)
        assert len(result.tasks) == 3
        assert result.run_id == "test-run-456"

    @pytest.mark.asyncio
    async def test_validate_plan_activity(self, workflow_module):
        """Test the validate_plan_activity directly."""
        goal_input = GoalInput(goal="Test goal")
        plan = await workflow_module.plan_activity(goal_input)
        result = await workflow_module.validate_plan_activity(plan)
        assert isinstance(result, Plan)
        assert len(result.tasks) == 3

    # =========================================================================
    # END-TO-END FILE SYSTEM TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_end_to_end_files_created(self, workflow_module):
        """Test that workflow creates all required files: state.json, plan.json, evidence/*.json"""
        workflow_class = workflow_module.FsasmMilestoneOneWorkflow
        workflow = workflow_class()
        input_data = workflow_module.WorkflowInput(goal="End-to-end file test")
        result = await workflow.run(input_data)

        # Check files in default runtime directory
        from src.fsasm.persistence import DEFAULT_RUNTIME_DIR, DEFAULT_STATE_FILE, DEFAULT_PLAN_FILE, DEFAULT_EVIDENCE_DIR, DEFAULT_RUN_LOG_FILE
        
        run_id = result["run_id"]
        run_dir = DEFAULT_RUNTIME_DIR / "runs" / run_id

        # Verify state.json exists and has correct content
        state_path = run_dir / DEFAULT_STATE_FILE
        assert state_path.exists(), "state.json should exist"
        with open(state_path) as f:
            state_data = json.load(f)
        assert state_data["run_id"] == run_id
        assert state_data["goal"] == result["goal"]
        assert state_data["status"] == result["status"]

        # Verify plan.json exists and has correct content
        plan_path = run_dir / DEFAULT_PLAN_FILE
        assert plan_path.exists(), "plan.json should exist"
        with open(plan_path) as f:
            plan_data = json.load(f)
        assert plan_data["run_id"] == run_id
        assert plan_data["plan_id"] == result["plan_id"]
        assert len(plan_data["tasks"]) == 3

        # Verify evidence directory exists and has files
        evidence_dir = run_dir / DEFAULT_EVIDENCE_DIR
        assert evidence_dir.exists(), "evidence directory should exist"
        evidence_files = list(evidence_dir.glob("*.json"))
        assert len(evidence_files) > 0, "evidence directory should have at least one file"
        
        # Verify evidence file content
        for evidence_file in evidence_files:
            with open(evidence_file) as f:
                evidence_data = json.load(f)
            assert "evidence_id" in evidence_data
            assert "run_id" in evidence_data
            assert evidence_data["run_id"] == run_id

        # Verify run log exists
        run_log_path = run_dir / DEFAULT_RUN_LOG_FILE
        assert run_log_path.exists(), "run.log.jsonl should exist"


class TestWorkflowRegistration:
    """Tests for workflow registration and discovery."""

    def test_workflow_is_registered(self):
        """Test that the workflow is properly registered."""
        from src.workflows import fsasm_milestone_one
        assert hasattr(fsasm_milestone_one, "FsasmMilestoneOneWorkflow")

    def test_workflow_has_entrypoint(self):
        """Test that the workflow has an entrypoint."""
        from src.workflows import fsasm_milestone_one
        workflow_class = fsasm_milestone_one.FsasmMilestoneOneWorkflow
        assert hasattr(workflow_class, "run")


class TestWorkflowDefinition:
    """Tests for workflow definition metadata."""

    def test_workflow_name(self):
        """Test that workflow has correct name."""
        from src.workflows import fsasm_milestone_one
        temporal_def = getattr(
            fsasm_milestone_one.FsasmMilestoneOneWorkflow,
            "__temporal_workflow_definition",
            None,
        )
        if temporal_def is not None:
            assert "fsasm-milestone-one" in temporal_def.name
        else:
            workflow_def = getattr(
                fsasm_milestone_one.FsasmMilestoneOneWorkflow,
                "__workflows_workflow_def",
                None,
            )
            if workflow_def is not None:
                assert "fsasm-milestone-one" in workflow_def.name

    def test_workflow_description(self):
        """Test that workflow has description."""
        from src.workflows import fsasm_milestone_one
        workflow_class = fsasm_milestone_one.FsasmMilestoneOneWorkflow
        workflow_def = getattr(workflow_class, "__workflows_workflow_def", None)
        if workflow_def is not None:
            assert workflow_def.description is not None
            assert len(workflow_def.description) > 0
        else:
            assert len(workflow_class.__doc__ or "") > 0
