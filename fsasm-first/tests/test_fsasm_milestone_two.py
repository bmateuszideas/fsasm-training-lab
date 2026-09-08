"""Tests for FS-ASM Milestone Two Workflow."""

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from fsasm.models import (
    GoalInput,
    PlannerBackend,
    RunStatus,
)
from temporalio.testing import WorkflowEnvironment

# Import for workflow module loading
from src.workflows.fsasm_milestone_two import (
    FsasmMilestoneTwoWorkflow,
    WorkflowInput,
    WorkflowOutput,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def workflow_module():
    """Import the workflow module."""
    from src.workflows import fsasm_milestone_two

    return fsasm_milestone_two


# =============================================================================
# UNIT TESTS - Workflow Input Model
# =============================================================================


class TestWorkflowInput:
    """Tests for WorkflowInput model."""

    def test_backend_must_be_explicit(self):
        """Test that backend must be explicitly provided (no default)."""
        with pytest.raises(Exception) as exc_info:
            WorkflowInput(goal="Test goal")
        assert "required" in str(exc_info.value).lower() or "planner_backend" in str(exc_info.value).lower()

    def test_backend_can_be_stub(self):
        """Test that backend can be explicitly set to STUB."""
        input_data = WorkflowInput(goal="Test goal", planner_backend=PlannerBackend.STUB)
        assert input_data.planner_backend == PlannerBackend.STUB

    def test_custom_run_id(self):
        """Test that custom run_id is accepted."""
        input_data = WorkflowInput(
            goal="Test goal",
            run_id="my-custom-run-id",
            planner_backend=PlannerBackend.STUB,
        )
        assert input_data.run_id == "my-custom-run-id"

    def test_mistral_backend_with_model_name(self):
        """Test that mistral backend can be set with model_name."""
        input_data = WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
        )
        assert input_data.planner_backend == PlannerBackend.MISTRAL
        assert input_data.model_name == "mistral-large-latest"


# =============================================================================
# UNIT TESTS - Workflow Direct Execution
# =============================================================================


class TestFsasmMilestoneTwoWorkflow:
    """Tests for FS-ASM Milestone Two workflow."""

    @pytest.mark.asyncio
    async def test_workflow_creates_run_id_with_stub(self, workflow_module):
        """Test that workflow creates a run_id when none is provided."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
        )
        result = await workflow.run(input_data)

        assert result["run_id"] is not None
        assert len(result["run_id"]) > 0
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_workflow_uses_provided_run_id_with_stub(self, workflow_module):
        """Test that workflow uses provided run_id."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            run_id="my-custom-run-id-123",
            planner_backend=PlannerBackend.STUB,
        )
        result = await workflow.run(input_data)

        assert result["run_id"] == "my-custom-run-id-123"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_workflow_creates_plan_with_stub(self, workflow_module):
        """Test that workflow creates a plan with 3 tasks."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
        )
        result = await workflow.run(input_data)

        assert result["plan_id"] is not None
        assert result["task_count"] == 3
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_workflow_creates_3_tasks_with_stub(self, workflow_module):
        """Test that workflow creates exactly 3 tasks."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
        )
        result = await workflow.run(input_data)

        task_ids = result["task_ids"]
        assert len(task_ids) == 3
        for i, task_id in enumerate(task_ids, start=1):
            assert task_id == f"TASK-{i:03d}"

    @pytest.mark.asyncio
    async def test_workflow_persists_state_with_stub(self, workflow_module):
        """Test that workflow persists run state."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
        )
        result = await workflow.run(input_data)

        assert result["status"] == RunStatus.PASSED.value
        assert result["run_id"] is not None

    @pytest.mark.asyncio
    async def test_workflow_returns_result_with_stub(self, workflow_module):
        """Test that workflow returns complete result."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
        )
        result = await workflow.run(input_data)

        assert result["status"] == "PASSED"
        assert result["task_count"] == 3
        assert result["evidence_count"] > 0
        assert result["success"] is True
        assert result["planner_provider"] == "stub"
        assert result["planner_model_call_count"] == 0

    @pytest.mark.asyncio
    async def test_workflow_returns_planner_metadata_with_stub(self, workflow_module):
        """Test that workflow returns planner metadata for stub."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
        )
        result = await workflow.run(input_data)

        assert result["planner_provider"] == "stub"
        assert result["planner_model"] == "stub-planner"
        assert result["planner_model_call_count"] == 0
        assert result["planner_invocation_count"] == 1

    @pytest.mark.asyncio
    async def test_workflow_returns_planner_metadata_with_custom_prompt_version(self, workflow_module):
        """Test that workflow returns planner metadata with custom prompt version."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.STUB,
            prompt_version="v2.0",
        )
        result = await workflow.run(input_data)

        assert result["planner_prompt_version"] == "v2.0"

    @pytest.mark.asyncio
    async def test_workflow_requires_model_name_for_mistral(self, workflow_module):
        """Test that workflow requires model_name for mistral backend."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        input_data = workflow_module.WorkflowInput(
            goal="Test goal",
            planner_backend=PlannerBackend.MISTRAL,
            # model_name is missing
        )

        with pytest.raises(Exception) as exc_info:
            await workflow.run(input_data)

        # Should fail with configuration error
        error_str = str(exc_info.value)
        assert "wymaga" in error_str.lower() or "model_name" in error_str.lower()

    @pytest.mark.asyncio
    async def test_workflow_accepts_mistral_with_model_name(self, workflow_module):
        """Test that workflow accepts mistral backend with model_name."""
        workflow_class = workflow_module.FsasmMilestoneTwoWorkflow
        workflow = workflow_class()

        # Mock the Mistral API call
        from mistralai.client.models.chatcompletionresponse import (
            ChatCompletionResponse,
            UsageInfo,
        )
        from mistralai.client.models.chatcompletionchoice import (
            AssistantMessage,
            ChatCompletionChoice,
        )
        import json as json_module

        mock_response = ChatCompletionResponse(
            id="test-id",
            object="chat.completion",
            model="mistral-large-latest",
            created=1234567890,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    finish_reason="stop",
                    message=AssistantMessage(
                        role="assistant",
                        content=json_module.dumps({
                            "tasks": [
                                {"title": "T1", "description": "D1", "dependencies": [],
                                 "verification_type": "schema", "verification_expected": "E1",
                                 "constraints": [], "allowed_files": [], "expected_evidence": []},
                                {"title": "T2", "description": "D2", "dependencies": [1],
                                 "verification_type": "exists", "verification_expected": "E2",
                                 "constraints": [], "allowed_files": [], "expected_evidence": []},
                                {"title": "T3", "description": "D3", "dependencies": [2],
                                 "verification_type": "custom", "verification_expected": "E3",
                                 "constraints": [], "allowed_files": [], "expected_evidence": []},
                            ]
                        }),
                    ),
                )
            ],
            usage=UsageInfo(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            input_data = workflow_module.WorkflowInput(
                goal="Test goal",
                planner_backend=PlannerBackend.MISTRAL,
                model_name="mistral-large-latest",
            )
            result = await workflow.run(input_data)

        assert result["planner_provider"] == "mistral"
        assert result["planner_model"] == "mistral-large-latest"
        assert result["planner_model_call_count"] == 1
