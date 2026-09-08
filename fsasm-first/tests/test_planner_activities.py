"""Tests for FS-ASM Planner Activities (Milestone 2)."""

import pytest

from fsasm.models import (
    GoalInput,
    PlannerBackend,
    PlannerConfig,
    PlannerProposal,
    TaskProposal,
)
from fsasm.planner import assemble_plan, PlannerStub
from fsasm.planner_activities import (
    plan_with_stub,
    get_planner_prompt_template,
)
from fsasm.errors import ConfigurationError


class TestPlannerStub:
    """Tests for PlannerStub."""

    def test_create_proposal_returns_3_tasks(self):
        """Test that stub creates exactly 3 TaskProposal instances."""
        planner = PlannerStub()
        input_data = GoalInput(goal="Test goal")
        proposal = planner.create_proposal(input_data)

        assert isinstance(proposal, PlannerProposal)
        assert len(proposal.tasks) == 3

    def test_create_proposal_task_structure(self):
        """Test that stub creates valid TaskProposal structure."""
        planner = PlannerStub()
        input_data = GoalInput(goal="Test goal")
        proposal = planner.create_proposal(input_data)

        for task in proposal.tasks:
            assert isinstance(task, TaskProposal)
            assert task.title.strip()
            assert task.description.strip()
            assert task.verification_type.strip()
            assert task.verification_expected.strip()

    def test_create_proposal_dependencies_use_sequence_numbers(self):
        """Test that dependencies use proposal-local sequence numbers, not TASK-xxx IDs."""
        planner = PlannerStub()
        input_data = GoalInput(goal="Test goal")
        proposal = planner.create_proposal(input_data)

        # Task 1 should have no dependencies
        assert proposal.tasks[0].dependencies == []

        # Task 2 should depend on sequence 1
        assert proposal.tasks[1].dependencies == [1]

        # Task 3 should depend on sequence 2
        assert proposal.tasks[2].dependencies == [2]

    def test_create_proposal_goal_not_in_proposal(self):
        """Test that PlannerProposal does NOT contain goal field."""
        planner = PlannerStub()
        input_data = GoalInput(goal="Test goal")
        proposal = planner.create_proposal(input_data)

        # PlannerProposal should not have goal field
        assert not hasattr(proposal, "goal") or proposal.goal is None

    def test_create_plan_uses_assembler(self):
        """Test that create_plan uses the shared assembler."""
        planner = PlannerStub()
        input_data = GoalInput(goal="Test goal")
        plan = planner.create_plan(input_data)

        # Plan should have runtime-owned fields
        assert plan.run_id is not None
        assert plan.plan_id.startswith("plan-")
        assert len(plan.tasks) == 3
        assert all(t.task_id.startswith("TASK-") for t in plan.tasks)
        assert plan.goal == input_data.goal


class TestAssemblePlan:
    """Tests for the assemble_plan function."""

    def test_assemble_plan_assigns_runtime_fields(self):
        """Test that assembler assigns all runtime-owned fields."""
        goal_input = GoalInput(goal="Test goal", run_id=None)
        proposal = PlannerProposal(
            tasks=[
                TaskProposal(
                    title="Task 1",
                    description="Desc 1",
                    dependencies=[],
                    verification_type="schema",
                    verification_expected="expected 1",
                ),
                TaskProposal(
                    title="Task 2",
                    description="Desc 2",
                    dependencies=[1],
                    verification_type="exists",
                    verification_expected="expected 2",
                ),
                TaskProposal(
                    title="Task 3",
                    description="Desc 3",
                    dependencies=[2],
                    verification_type="custom",
                    verification_expected="expected 3",
                ),
            ]
        )

        plan = assemble_plan(goal_input, proposal)

        # Check runtime-owned fields
        assert plan.run_id is not None
        assert plan.plan_id.startswith("plan-")
        assert plan.goal == goal_input.goal
        assert len(plan.tasks) == 3

        # Check task runtime fields
        for idx, task in enumerate(plan.tasks, start=1):
            assert task.task_id == f"TASK-{idx:03d}"
            assert task.sequence == idx
            assert task.status.value == "PENDING"
            assert task.attempt == 0
            assert task.max_attempts == 3
            assert task.parent_id is None

    def test_assemble_plan_maps_dependencies(self):
        """Test that assembler maps proposal-local sequence numbers to runtime task IDs."""
        goal_input = GoalInput(goal="Test goal")
        proposal = PlannerProposal(
            tasks=[
                TaskProposal(
                    title="Task 1",
                    description="Desc 1",
                    dependencies=[],
                    verification_type="schema",
                    verification_expected="expected 1",
                ),
                TaskProposal(
                    title="Task 2",
                    description="Desc 2",
                    dependencies=[1],  # Depends on sequence 1
                    verification_type="exists",
                    verification_expected="expected 2",
                ),
                TaskProposal(
                    title="Task 3",
                    description="Desc 3",
                    dependencies=[1, 2],  # Depends on sequences 1 and 2
                    verification_type="custom",
                    verification_expected="expected 3",
                ),
            ]
        )

        plan = assemble_plan(goal_input, proposal)

        # Task 1 should have no dependencies
        assert plan.tasks[0].dependencies == []

        # Task 2 should depend on TASK-001
        assert plan.tasks[1].dependencies == ["TASK-001"]

        # Task 3 should depend on TASK-001 and TASK-002
        assert set(plan.tasks[2].dependencies) == {"TASK-001", "TASK-002"}

    def test_assemble_plan_authoritative_goal_from_input(self):
        """Test that Plan.goal comes from GoalInput, not from proposal."""
        goal_input = GoalInput(goal="Authoritative goal from input")
        proposal = PlannerProposal(
            tasks=[
                TaskProposal(
                    title="Task 1",
                    description="Desc 1",
                    dependencies=[],
                    verification_type="schema",
                    verification_expected="expected",
                ),
                TaskProposal(
                    title="Task 2",
                    description="Desc 2",
                    dependencies=[],
                    verification_type="schema",
                    verification_expected="expected",
                ),
                TaskProposal(
                    title="Task 3",
                    description="Desc 3",
                    dependencies=[],
                    verification_type="schema",
                    verification_expected="expected",
                ),
            ]
        )

        plan = assemble_plan(goal_input, proposal)
        assert plan.goal == "Authoritative goal from input"

    def test_assemble_plan_preserves_task_content(self):
        """Test that assembler preserves all content from TaskProposal."""
        goal_input = GoalInput(goal="Test")
        proposal = PlannerProposal(
            tasks=[
                TaskProposal(
                    title="Custom Title",
                    description="Custom Description",
                    dependencies=[],
                    verification_type="custom",
                    verification_expected="Custom Expected",
                    constraints=["constraint1", "constraint2"],
                    allowed_files=["*.py", "*.md"],
                    expected_evidence=["evidence1", "evidence2"],
                ),
                TaskProposal(
                    title="Title 2",
                    description="Desc 2",
                    dependencies=[],
                    verification_type="schema",
                    verification_expected="expected 2",
                ),
                TaskProposal(
                    title="Title 3",
                    description="Desc 3",
                    dependencies=[],
                    verification_type="exists",
                    verification_expected="expected 3",
                ),
            ]
        )

        plan = assemble_plan(goal_input, proposal)
        task = plan.tasks[0]

        assert task.title == "Custom Title"
        assert task.description == "Custom Description"
        assert task.verification.type == "custom"
        assert task.verification.expected == "Custom Expected"
        assert task.constraints == ["constraint1", "constraint2"]
        assert task.allowed_files == ["*.py", "*.md"]
        assert task.expected_evidence == ["evidence1", "evidence2"]


class TestPlanWithStubActivity:
    """Tests for plan_with_stub activity."""

    @pytest.mark.asyncio
    async def test_stub_returns_valid_output(self):
        """Test that stub planner returns valid PlannerOutput."""
        config = PlannerConfig(
            backend=PlannerBackend.STUB,
            prompt_version="v1.0",
        )
        goal_input = GoalInput(goal="Test goal")

        output = await plan_with_stub(goal_input, config)

        assert output.proposal is not None
        assert len(output.proposal.tasks) == 3
        assert output.plan is not None
        assert len(output.plan.tasks) == 3
        assert output.metadata is not None

    @pytest.mark.asyncio
    async def test_stub_metadata(self):
        """Test that stub metadata has correct values."""
        config = PlannerConfig(
            backend=PlannerBackend.STUB,
            prompt_version="v1.0",
        )
        goal_input = GoalInput(goal="Test goal")

        output = await plan_with_stub(goal_input, config)

        metadata = output.metadata
        assert metadata.provider == "stub"
        assert metadata.requested_model == "stub-planner"
        assert metadata.resolved_model == "stub-planner"
        assert metadata.prompt_version == "v1.0"
        assert metadata.model_call_count == 0  # Stub makes 0 model calls
        assert metadata.planner_invocation_count == 1
        assert metadata.input_tokens is None
        assert metadata.output_tokens is None
        assert metadata.total_tokens is None
        assert len(metadata.template_hash) == 64
        assert len(metadata.rendered_hash) == 64
        assert metadata.run_id is not None

    @pytest.mark.asyncio
    async def test_stub_rejects_non_stub_backend(self):
        """Test that stub activity rejects non-stub backend."""
        config = PlannerConfig(
            backend=PlannerBackend.MISTRAL,
            model_name="test-model",
        )
        goal_input = GoalInput(goal="Test goal")

        with pytest.raises(ConfigurationError) as exc_info:
            await plan_with_stub(goal_input, config)

        assert "plan_with_stub wymaga backend='stub'" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_stub_uses_same_assembler(self):
        """Test that stub uses the same assembler as direct call."""
        config = PlannerConfig(backend=PlannerBackend.STUB)
        goal_input = GoalInput(goal="Test goal")

        output = await plan_with_stub(goal_input, config)

        # Create plan directly using assembler
        planner = PlannerStub()
        proposal = planner.create_proposal(goal_input)
        direct_plan = assemble_plan(goal_input, proposal)

        # Both should produce equivalent plans (same structure, task IDs, etc.)
        # Note: plan_id may differ because run_id is generated fresh each time
        # But the assembled plan structure should be identical
        assert output.plan.goal == direct_plan.goal
        assert len(output.plan.tasks) == len(direct_plan.tasks)
        # Check that task IDs match
        for i, (out_task, direct_task) in enumerate(zip(output.plan.tasks, direct_plan.tasks)):
            assert out_task.task_id == direct_task.task_id
            assert out_task.sequence == direct_task.sequence


class TestPromptTemplates:
    """Tests for prompt template registry."""

    def test_get_template_v1(self):
        """Test getting v1.0 template."""
        template, template_hash = get_planner_prompt_template("v1.0")

        assert isinstance(template, str)
        assert len(template) > 0
        assert len(template_hash) == 64
        assert "{goal}" in template

    def test_get_unknown_template_raises(self):
        """Test that unknown template version raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_planner_prompt_template("unknown")

        assert "Unknown prompt version" in str(exc_info.value)

    def test_template_contains_dependency_instructions(self):
        """Test that template instructs LLM to use sequence numbers for dependencies."""
        template, _ = get_planner_prompt_template("v1.0")

        assert "Dependencies u\u017cywaj\u0105 numer\u00f3w sekwencji" in template
        assert "TASK-001" not in template or "NIE u\u017cywaj TASK-001" in template
