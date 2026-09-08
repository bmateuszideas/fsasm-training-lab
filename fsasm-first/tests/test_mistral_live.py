"""Live Smoke Tests for Mistral Planner (Milestone 2) - OPT-IN ONLY."""

import os

import pytest


@pytest.mark.skipif(
    not os.environ.get("MISTRAL_API_KEY"),
    reason="MISTRAL_API_KEY not set - live test requires API key",
)
@pytest.mark.skipif(
    not os.environ.get("FSASM_ENABLE_LIVE_TESTS", "").lower() == "true",
    reason="Live tests disabled by default - set FSASM_ENABLE_LIVE_TESTS=true to enable",
)
@pytest.mark.slow
class TestMistralLiveSmoke:
    """
    Live smoke tests with real Mistral API calls.
    
    These tests are OPT-IN ONLY and require:
    1. MISTRAL_API_KEY environment variable to be set
    2. FSASM_ENABLE_LIVE_TESTS=true environment variable to be set
    
    They verify that the Mistral planner integration works with real API calls.
    """

    @pytest.mark.asyncio
    async def test_mistral_api_connection(self):
        """Test that Mistral API connection works."""
        from mistralai.client import Mistral

        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        response = await client.chat.complete_async(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": "Say 'ok'"}],
        )
        # Just verify we can call the API, don't assert on content
        assert response is not None
        assert response.id is not None

    @pytest.mark.asyncio
    async def test_plan_with_mistral_live(self):
        """Test live Mistral planning with real API call."""
        from fsasm.models import GoalInput, PlannerConfig, PlannerBackend
        from fsasm.planner_activities import plan_with_mistral

        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
            prompt_version="v1.0",
        )
        goal_input = GoalInput(goal="Napisz plan dla: Stwórz prostą funkcję Python do sortowania listy")

        output = await plan_with_mistral(goal_input, config)

        # Verify output structure
        assert output.proposal is not None
        assert len(output.proposal.tasks) == 3
        assert output.plan is not None
        assert len(output.plan.tasks) == 3
        assert output.metadata is not None

        # Verify metadata
        assert output.metadata.provider == "mistral"
        assert output.metadata.requested_model == "mistral-large-latest"
        assert output.metadata.resolved_model == "mistral-large-latest"
        assert output.metadata.model_call_count == 1
        assert output.metadata.planner_invocation_count == 1
        assert output.metadata.input_tokens is not None
        assert output.metadata.output_tokens is not None
        assert output.metadata.total_tokens is not None
        assert len(output.metadata.template_hash) == 64
        assert len(output.metadata.rendered_hash) == 64
        assert output.metadata.run_id is not None

        # Verify plan has runtime-owned fields
        assert output.plan.run_id is not None
        assert output.plan.plan_id.startswith("plan-")
        assert output.plan.goal == goal_input.goal
        for idx, task in enumerate(output.plan.tasks, start=1):
            assert task.task_id == f"TASK-{idx:03d}"
            assert task.sequence == idx
            assert task.status.value == "PENDING"

    @pytest.mark.asyncio
    async def test_mistral_proposal_goal_not_in_output(self):
        """Test that live Mistral response does not include goal in proposal."""
        from fsasm.models import GoalInput, PlannerConfig, PlannerBackend
        from fsasm.planner_activities import plan_with_mistral

        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
            prompt_version="v1.0",
        )
        goal_input = GoalInput(goal="Test goal for live API")

        output = await plan_with_mistral(goal_input, config)

        # Proposal should not have goal field
        assert not hasattr(output.proposal, "goal") or output.proposal.goal is None

        # But Plan should have goal from GoalInput
        assert output.plan.goal == goal_input.goal

    @pytest.mark.asyncio
    async def test_mistral_dependency_mapping_live(self):
        """Test that live Mistral dependencies are correctly mapped."""
        from fsasm.models import GoalInput, PlannerConfig, PlannerBackend
        from fsasm.planner_activities import plan_with_mistral

        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
            prompt_version="v1.0",
        )
        goal_input = GoalInput(goal="Napisz plan dla: Zrób porządki w projekcie")

        output = await plan_with_mistral(goal_input, config)

        # Verify dependencies are mapped from sequence numbers to task IDs
        # This depends on what the LLM returns, but we can verify the structure
        for task in output.plan.tasks:
            # All dependencies should be runtime task IDs (TASK-xxx format)
            for dep in task.dependencies:
                assert dep.startswith("TASK-")
                # Verify it's a valid task ID in the plan
                assert dep in [t.task_id for t in output.plan.tasks]

    @pytest.mark.asyncio
    async def test_full_workflow_with_mistral_live(self):
        """Test full workflow execution with live Mistral backend."""
        from src.workflows.fsasm_milestone_two import (
            FsasmMilestoneTwoWorkflow,
            WorkflowInput,
        )

        workflow = FsasmMilestoneTwoWorkflow()
        input_data = WorkflowInput(
            goal="Napisz plan dla: Zaimplementuj funkcję do obliczania silni",
            planner_backend="mistral",
            model_name="mistral-large-latest",
            prompt_version="v1.0",
        )

        result = await workflow.run(input_data)

        assert result["status"] == "PASSED"
        assert result["task_count"] == 3
        assert result["evidence_count"] > 0
        assert result["success"] is True
        assert result["planner_provider"] == "mistral"
        assert result["planner_model"] == "mistral-large-latest"
        assert result["planner_model_call_count"] == 1
        assert result["planner_input_tokens"] is not None
        assert result["planner_output_tokens"] is not None
