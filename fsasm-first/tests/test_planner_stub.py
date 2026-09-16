"""Tests for FS-ASM Planner Stub."""

import pytest

from fsasm.models import GoalInput, Plan, TaskStatus
from fsasm.planner import PlannerStub, planner_stub


class TestPlannerStub:
    """Tests for the deterministic PlannerStub."""

    @pytest.fixture
    def planner(self) -> PlannerStub:
        """Create a PlannerStub instance."""
        return PlannerStub()

    @pytest.fixture
    def goal_input(self) -> GoalInput:
        """Create a sample GoalInput."""
        return GoalInput(goal="Test goal for planning")

    @pytest.fixture
    def goal_input_with_run_id(self) -> GoalInput:
        """Create a GoalInput with explicit run_id."""
        return GoalInput(goal="Test goal", run_id="custom-run-123")

    # =========================================================================
    # BASIC PLAN CREATION
    # =========================================================================

    def test_create_plan_returns_plan(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that create_plan returns a Plan object."""
        plan = planner.create_plan(goal_input)
        assert isinstance(plan, Plan)

    def test_create_plan_has_correct_goal(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that plan has the correct goal."""
        plan = planner.create_plan(goal_input)
        assert plan.goal == goal_input.goal

    def test_create_plan_generates_run_id(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that plan generates a run_id."""
        plan = planner.create_plan(goal_input)
        assert plan.run_id is not None
        assert len(plan.run_id) > 0

    def test_create_plan_uses_provided_run_id(
        self, planner: PlannerStub, goal_input_with_run_id: GoalInput
    ) -> None:
        """Test that plan uses provided run_id."""
        plan = planner.create_plan(goal_input_with_run_id)
        assert plan.run_id == goal_input_with_run_id.run_id

    # =========================================================================
    # EXACTLY 3 TASKS
    # =========================================================================

    def test_create_plan_has_exactly_3_tasks(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that plan has exactly 3 tasks."""
        plan = planner.create_plan(goal_input)
        assert len(plan.tasks) == 3

    def test_create_plan_task_count_invariant(self, planner: PlannerStub) -> None:
        """Test that plan always has exactly 3 tasks regardless of goal."""
        goals = [
            "Simple goal",
            "A much longer and more complex goal with many words",
            "x",
            "Goal with special chars: !@#$%^&*()",
            "",  # This will fail validation, but we test the pattern
        ]
        for goal in goals[:4]:  # Skip empty goal
            input = GoalInput(goal=goal)
            plan = planner.create_plan(input)
            assert len(plan.tasks) == 3, f"Expected 3 tasks for goal '{goal}'"

    # =========================================================================
    # TASK PROPERTIES
    # =========================================================================

    def test_task_ids_are_unique(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that all task IDs in the plan are unique."""
        plan = planner.create_plan(goal_input)
        task_ids = [t.task_id for t in plan.tasks]
        assert len(task_ids) == len(set(task_ids))

    def test_task_ids_follow_pattern(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that task IDs follow the expected pattern."""
        plan = planner.create_plan(goal_input)
        expected_ids = ["TASK-001", "TASK-002", "TASK-003"]
        actual_ids = [t.task_id for t in plan.tasks]
        assert actual_ids == expected_ids

    def test_tasks_have_correct_sequence(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that tasks have correct sequence numbers."""
        plan = planner.create_plan(goal_input)
        sequences = [t.sequence for t in plan.tasks]
        assert sequences == [1, 2, 3]

    def test_tasks_have_titles(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that all tasks have titles."""
        plan = planner.create_plan(goal_input)
        for task in plan.tasks:
            assert task.title is not None
            assert len(task.title) > 0

    def test_tasks_have_descriptions(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that all tasks have descriptions."""
        plan = planner.create_plan(goal_input)
        for task in plan.tasks:
            assert task.description is not None
            assert len(task.description) > 0

    def test_tasks_have_verification_spec(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that all tasks have verification specs."""
        plan = planner.create_plan(goal_input)
        for task in plan.tasks:
            assert task.verification is not None
            assert task.verification.type is not None
            assert task.verification.expected is not None

    # =========================================================================
    # TASK CONTENT
    # =========================================================================

    def test_task_001_content(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test TASK-001 has correct content."""
        plan = planner.create_plan(goal_input)
        task_001 = next(t for t in plan.tasks if t.task_id == "TASK-001")
        assert task_001.sequence == 1
        assert "Inspect" in task_001.title or "inspect" in task_001.title.lower()
        assert goal_input.goal in task_001.description
        assert task_001.dependencies == []

    def test_task_002_content(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test TASK-002 has correct content."""
        plan = planner.create_plan(goal_input)
        task_002 = next(t for t in plan.tasks if t.task_id == "TASK-002")
        assert task_002.sequence == 2
        assert "core" in task_002.title.lower() or "action" in task_002.title.lower()
        assert goal_input.goal in task_002.description
        assert "TASK-001" in task_002.dependencies

    def test_task_003_content(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test TASK-003 has correct content."""
        plan = planner.create_plan(goal_input)
        task_003 = next(t for t in plan.tasks if t.task_id == "TASK-003")
        assert task_003.sequence == 3
        assert "Verify" in task_003.title or "verify" in task_003.title.lower()
        assert goal_input.goal in task_003.description
        assert "TASK-002" in task_003.dependencies

    # =========================================================================
    # TASK STATES AND ATTEMPTS
    # =========================================================================

    def test_tasks_start_as_pending(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that all tasks start as PENDING."""
        plan = planner.create_plan(goal_input)
        for task in plan.tasks:
            assert task.status == TaskStatus.PENDING

    def test_tasks_start_at_attempt_0(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that all tasks start at attempt 0."""
        plan = planner.create_plan(goal_input)
        for task in plan.tasks:
            assert task.attempt == 0

    def test_tasks_have_max_attempts(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that all tasks have max_attempts set."""
        plan = planner.create_plan(goal_input)
        for task in plan.tasks:
            assert task.max_attempts >= 1

    # =========================================================================
    # PLAN PROPERTIES
    # =========================================================================

    def test_plan_has_plan_id(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that plan has a plan_id."""
        plan = planner.create_plan(goal_input)
        assert plan.plan_id is not None
        assert len(plan.plan_id) > 0
        assert plan.plan_id.startswith("plan-")

    def test_plan_id_contains_run_id(
        self, planner: PlannerStub, goal_input: GoalInput
    ) -> None:
        """Test that plan_id contains the run_id."""
        plan = planner.create_plan(goal_input)
        assert plan.run_id in plan.plan_id

    # =========================================================================
    # DETERMINISTIC BEHAVIOR
    # =========================================================================

    def test_same_goal_same_structure(self, planner: PlannerStub) -> None:
        """Test that same goal produces same structure (different run_ids)."""
        goal = GoalInput(goal="Deterministic test")
        plan1 = planner.create_plan(goal)
        plan2 = planner.create_plan(goal)

        # Structure should be the same
        assert len(plan1.tasks) == len(plan2.tasks)
        for t1, t2 in zip(plan1.tasks, plan2.tasks):
            assert t1.task_id == t2.task_id
            assert t1.sequence == t2.sequence
            assert t1.title == t2.title
            # Description contains goal, so will differ if run_id differs
            # But the pattern should be the same
            assert t1.verification.type == t2.verification.type

    def test_different_goals_same_structure(self, planner: PlannerStub) -> None:
        """Test that different goals produce same structure."""
        plan1 = planner.create_plan(GoalInput(goal="Goal A"))
        plan2 = planner.create_plan(GoalInput(goal="Goal B"))

        assert len(plan1.tasks) == len(plan2.tasks)
        for t1, t2 in zip(plan1.tasks, plan2.tasks):
            assert t1.task_id == t2.task_id
            assert t1.sequence == t2.sequence
            assert t1.title == t2.title

    # =========================================================================
    # SINGLETON INSTANCE
    # =========================================================================

    def test_planner_stub_singleton(self) -> None:
        """Test that planner_stub is a singleton instance."""
        assert isinstance(planner_stub, PlannerStub)
        # Should be able to use it directly
        plan = planner_stub.create_plan(GoalInput(goal="Test"))
        assert isinstance(plan, Plan)
