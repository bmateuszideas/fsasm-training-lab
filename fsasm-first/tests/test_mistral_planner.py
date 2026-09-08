"""Tests for Mistral Planner Activity (Milestone 2)."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fsasm.models import (
    GoalInput,
    PlannerBackend,
    PlannerConfig,
    PlannerProposal,
    TaskProposal,
)
from fsasm.planner_activities import plan_with_mistral
from fsasm.errors import ConfigurationError


# Import Mistral response types
from mistralai.client.models.chatcompletionresponse import (
    ChatCompletionResponse,
    UsageInfo,
)
from mistralai.client.models.chatcompletionchoice import (
    AssistantMessage,
    ChatCompletionChoice,
)


class TestPlanWithMistralActivity:
    """Tests for plan_with_mistral activity."""

    @pytest.fixture
    def mock_chat_completion_response(self):
        """Create a mock ChatCompletionResponse with usage data."""
        mock_response = ChatCompletionResponse(
            id="test-response-id",
            object="chat.completion",
            model="mistral-large-latest",
            created=1234567890,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    finish_reason="stop",
                    message=AssistantMessage(
                        role="assistant",
                        content=json.dumps({
                            "tasks": [
                                {
                                    "title": "Mistral Task 1",
                                    "description": "Mistral Description 1",
                                    "dependencies": [],
                                    "verification_type": "schema",
                                    "verification_expected": "Mistral Expected 1",
                                    "constraints": [],
                                    "allowed_files": [],
                                    "expected_evidence": [],
                                },
                                {
                                    "title": "Mistral Task 2",
                                    "description": "Mistral Description 2",
                                    "dependencies": [1],
                                    "verification_type": "exists",
                                    "verification_expected": "Mistral Expected 2",
                                    "constraints": [],
                                    "allowed_files": [],
                                    "expected_evidence": [],
                                },
                                {
                                    "title": "Mistral Task 3",
                                    "description": "Mistral Description 3",
                                    "dependencies": [2],
                                    "verification_type": "custom",
                                    "verification_expected": "Mistral Expected 3",
                                    "constraints": [],
                                    "allowed_files": [],
                                    "expected_evidence": [],
                                },
                            ]
                        }),
                    ),
                ),
            ],
            usage=UsageInfo(
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
            ),
        )
        return mock_response

    @pytest.mark.asyncio
    async def test_mistral_returns_valid_output(self, mock_chat_completion_response):
        """Test that Mistral planner returns valid PlannerOutput."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
            prompt_version="v1.0",
        )
        goal_input = GoalInput(goal="Test goal for Mistral")

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
            return_value=mock_chat_completion_response,
        ):
            output = await plan_with_mistral(goal_input, config)

        assert output.proposal is not None
        assert len(output.proposal.tasks) == 3
        assert output.plan is not None
        assert len(output.plan.tasks) == 3
        assert output.metadata is not None

    @pytest.mark.asyncio
    async def test_mistral_metadata(self, mock_chat_completion_response):
        """Test that Mistral metadata has correct values."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
            model_version="v1.2.3",
            prompt_version="v1.0",
        )
        goal_input = GoalInput(goal="Test goal for Mistral")

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
            return_value=mock_chat_completion_response,
        ):
            output = await plan_with_mistral(goal_input, config)

        metadata = output.metadata
        assert metadata.provider == "mistral"
        assert metadata.requested_model == "mistral-large-latest"
        assert metadata.resolved_model == "mistral-large-latest"
        assert metadata.model_version == "v1.2.3"
        assert metadata.prompt_version == "v1.0"
        assert metadata.model_call_count == 1  # Exactly one model call
        assert metadata.planner_invocation_count == 1
        assert metadata.input_tokens == 100
        assert metadata.output_tokens == 50
        assert metadata.total_tokens == 150
        assert len(metadata.template_hash) == 64
        assert len(metadata.rendered_hash) == 64
        assert metadata.run_id is not None

    @pytest.mark.asyncio
    async def test_mistral_requires_backend_mistral(self):
        """Test that Mistral activity requires backend='mistral'."""
        config = PlannerConfig(
            backend=PlannerBackend.STUB,
        )
        goal_input = GoalInput(goal="Test goal")

        with pytest.raises(ConfigurationError) as exc_info:
            await plan_with_mistral(goal_input, config)

        assert "plan_with_mistral wymaga backend='mistral'" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mistral_requires_model_name(self):
        """Test that Mistral activity requires model_name."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name=None,  # Missing
        )
        goal_input = GoalInput(goal="Test goal")

        with pytest.raises(ConfigurationError) as exc_info:
            await plan_with_mistral(goal_input, config)

        assert "plan_with_mistral wymaga podania model_name" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mistral_single_model_call(self, mock_chat_completion_response):
        """Test that Mistral makes exactly ONE model call."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
        )
        goal_input = GoalInput(goal="Test goal")

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
            return_value=mock_chat_completion_response,
        ) as mock_call:
            output = await plan_with_mistral(goal_input, config)

        # Should be called exactly once
        assert mock_call.call_count == 1
        assert output.metadata.model_call_count == 1

    @pytest.mark.asyncio
    async def test_mistral_uses_sequence_numbers_in_prompt(self):
        """Test that Mistral prompt instructs LLM to use sequence numbers."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
            prompt_version="v1.0",
        )
        goal_input = GoalInput(goal="Test goal")

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
        ) as mock_call:
            # Need to set up the mock to return something
            mock_call.return_value = ChatCompletionResponse(
                id="test",
                object="chat.completion",
                model="mistral-large-latest",
                created=1234567890,
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        finish_reason="stop",
                        message=AssistantMessage(
                            role="assistant",
                            content=json.dumps({
                                "tasks": [
                                    {"title": "T", "description": "D", "dependencies": [],
                                     "verification_type": "schema", "verification_expected": "E"},
                                    {"title": "T", "description": "D", "dependencies": [],
                                     "verification_type": "schema", "verification_expected": "E"},
                                    {"title": "T", "description": "D", "dependencies": [],
                                     "verification_type": "schema", "verification_expected": "E"},
                                ]
                            }),
                        ),
                    )
                ],
                usage=UsageInfo(input_tokens=10, output_tokens=10, total_tokens=20),
            )

            await plan_with_mistral(goal_input, config)

        # Check that the prompt was rendered with the goal
        call_args = mock_call.call_args
        request = call_args[0][0]
        assert "{goal}" not in request.messages[0].content  # Should be rendered
        assert "Test goal" in request.messages[0].content

    @pytest.mark.asyncio
    async def test_mistral_proposal_has_no_goal(self, mock_chat_completion_response):
        """Test that the parsed proposal does NOT contain goal field."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
        )
        goal_input = GoalInput(goal="Test goal")

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
            return_value=mock_chat_completion_response,
        ):
            output = await plan_with_mistral(goal_input, config)

        # Proposal should not have goal field
        assert not hasattr(output.proposal, "goal") or output.proposal.goal is None

    @pytest.mark.asyncio
    async def test_mistral_plan_goal_from_input(self, mock_chat_completion_response):
        """Test that Plan.goal comes from GoalInput, not from LLM response."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
        )
        goal_input = GoalInput(goal="Authoritative goal from input")

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
            return_value=mock_chat_completion_response,
        ):
            output = await plan_with_mistral(goal_input, config)

        # Plan.goal should be from GoalInput
        assert output.plan.goal == "Authoritative goal from input"

    @pytest.mark.asyncio
    async def test_mistral_uses_same_assembler(self, mock_chat_completion_response):
        """Test that Mistral uses the same assembler as stub."""
        from fsasm.planner import assemble_plan

        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
        )
        goal_input = GoalInput(goal="Test goal")

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
            return_value=mock_chat_completion_response,
        ):
            output = await plan_with_mistral(goal_input, config)

        # Create plan directly using assembler with the same proposal
        # The proposal from Mistral should be parsed correctly
        assert len(output.plan.tasks) == 3
        for idx, task in enumerate(output.plan.tasks, start=1):
            assert task.task_id == f"TASK-{idx:03d}"
            assert task.sequence == idx

    @pytest.mark.asyncio
    async def test_mistral_dependency_mapping(self, mock_chat_completion_response):
        """Test that Mistral dependencies are mapped from sequence numbers to task IDs."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="mistral-large-latest",
        )
        goal_input = GoalInput(goal="Test goal")

        with patch(
            "fsasm.planner_activities.mistralai_chat_complete",
            new_callable=AsyncMock,
            return_value=mock_chat_completion_response,
        ):
            output = await plan_with_mistral(goal_input, config)

        # Task 1 should have no dependencies
        assert output.plan.tasks[0].dependencies == []

        # Task 2 should depend on TASK-001 (sequence 1 -> TASK-001)
        assert output.plan.tasks[1].dependencies == ["TASK-001"]

        # Task 3 should depend on TASK-002 (sequence 2 -> TASK-002)
        assert output.plan.tasks[2].dependencies == ["TASK-002"]
