"""Tests for FS-ASM Deterministic Verifier."""

import pytest

from fsasm.models import (
    ChildTask,
    EvidenceRecord,
    GoalInput,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationResult,
    VerificationResultStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.planner import PlannerStub
from fsasm.verifier import DeterministicVerifier, verifier


class TestDeterministicVerifier:
    """Tests for the DeterministicVerifier."""

    @pytest.fixture
    def verifier(self) -> DeterministicVerifier:
        """Create a DeterministicVerifier instance."""
        return DeterministicVerifier()

    @pytest.fixture
    def valid_plan(self) -> Plan:
        """Create a valid plan with exactly 3 tasks."""
        tasks = [
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Task 1",
                description="Description 1",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
                dependencies=[],
            ),
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Task 2",
                description="Description 2",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.EXISTS, expected="test"
                ),
                dependencies=["TASK-001"],
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Task 3",
                description="Description 3",
                status=TaskStatus.PENDING,
                verification=VerificationSpec(
                    type=VerificationType.COUNT, expected="test"
                ),
                dependencies=["TASK-002"],
            ),
        ]
        return Plan(
            plan_id="plan-123",
            run_id="run-123",
            goal="Test goal",
            tasks=tasks,
        )

    @pytest.fixture
    def valid_state(self, valid_plan: Plan) -> RunState:
        """Create a valid RunState."""
        return RunState(
            run_id=valid_plan.run_id,
            goal=valid_plan.goal,
            status=RunStatus.PLANNED,
            plan=valid_plan,
        )

    @pytest.fixture
    def invalid_plan_2_tasks(self) -> Plan:
        """Create an invalid plan with only 2 tasks."""
        tasks = [
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Task 1",
                description="Description 1",
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Task 2",
                description="Description 2",
                verification=VerificationSpec(
                    type=VerificationType.EXISTS, expected="test"
                ),
            ),
        ]
        # Bypass the validator for testing
        return Plan.model_construct(
            plan_id="plan-invalid",
            run_id="run-invalid",
            goal="Invalid goal",
            tasks=tasks,
        )

    @pytest.fixture
    def invalid_plan_duplicate_ids(self) -> Plan:
        """Create an invalid plan with duplicate task IDs."""
        tasks = [
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Task 1",
                description="Description 1",
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
            ),
            ChildTask(
                task_id="TASK-001",  # Duplicate!
                sequence=2,
                title="Task 2",
                description="Description 2",
                verification=VerificationSpec(
                    type=VerificationType.EXISTS, expected="test"
                ),
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Task 3",
                description="Description 3",
                verification=VerificationSpec(
                    type=VerificationType.COUNT, expected="test"
                ),
            ),
        ]
        return Plan.model_construct(
            plan_id="plan-dup",
            run_id="run-dup",
            goal="Dup goal",
            tasks=tasks,
        )

    @pytest.fixture
    def invalid_plan_bad_deps(self) -> Plan:
        """Create an invalid plan with invalid dependencies."""
        tasks = [
            ChildTask(
                task_id="TASK-001",
                sequence=1,
                title="Task 1",
                description="Description 1",
                verification=VerificationSpec(
                    type=VerificationType.SCHEMA, expected="test"
                ),
                dependencies=["NONEXISTENT"],
            ),
            ChildTask(
                task_id="TASK-002",
                sequence=2,
                title="Task 2",
                description="Description 2",
                verification=VerificationSpec(
                    type=VerificationType.EXISTS, expected="test"
                ),
            ),
            ChildTask(
                task_id="TASK-003",
                sequence=3,
                title="Task 3",
                description="Description 3",
                verification=VerificationSpec(
                    type=VerificationType.COUNT, expected="test"
                ),
            ),
        ]
        return Plan.model_construct(
            plan_id="plan-bad-deps",
            run_id="run-bad-deps",
            goal="Bad deps goal",
            tasks=tasks,
        )

    # =========================================================================
    # verify_plan TESTS
    # =========================================================================

    def test_verify_plan_pass(
        self, verifier: DeterministicVerifier, valid_plan: Plan
    ) -> None:
        """Test that valid plan verification passes."""
        result = verifier.verify_plan(valid_plan)
        assert result.status == VerificationResultStatus.PASS
        assert result.run_id == valid_plan.run_id
        assert len(result.checks) > 0

    def test_verify_plan_fail_2_tasks(
        self, verifier: DeterministicVerifier, invalid_plan_2_tasks: Plan
    ) -> None:
        """Test that plan with 2 tasks fails verification."""
        result = verifier.verify_plan(invalid_plan_2_tasks)
        assert result.status == VerificationResultStatus.FAIL
        # Find the task count check
        count_check = next(
            (c for c in result.checks if "3 tasks" in c.check_name),
            None,
        )
        assert count_check is not None
        assert count_check.passed is False

    def test_verify_plan_fail_duplicate_ids(
        self, verifier: DeterministicVerifier, invalid_plan_duplicate_ids: Plan
    ) -> None:
        """Test that plan with duplicate IDs fails verification."""
        result = verifier.verify_plan(invalid_plan_duplicate_ids)
        assert result.status == VerificationResultStatus.FAIL
        # Find the unique IDs check
        unique_check = next(
            (c for c in result.checks if "unique" in c.check_name.lower()),
            None,
        )
        assert unique_check is not None
        assert unique_check.passed is False

    def test_verify_plan_fail_bad_deps(
        self, verifier: DeterministicVerifier, invalid_plan_bad_deps: Plan
    ) -> None:
        """Test that plan with invalid dependencies fails verification."""
        result = verifier.verify_plan(invalid_plan_bad_deps)
        assert result.status == VerificationResultStatus.FAIL
        # Find a dependency check that failed
        dep_checks = [c for c in result.checks if "dependency" in c.check_name.lower()]
        assert len(dep_checks) > 0
        assert any(not c.passed for c in dep_checks)

    def test_verify_plan_checks_count(
        self, verifier: DeterministicVerifier, valid_plan: Plan
    ) -> None:
        """Test that plan verification includes task count check."""
        result = verifier.verify_plan(valid_plan)
        count_check = next(
            (c for c in result.checks if "3 tasks" in c.check_name),
            None,
        )
        assert count_check is not None
        assert count_check.passed is True

    def test_verify_plan_checks_unique_ids(
        self, verifier: DeterministicVerifier, valid_plan: Plan
    ) -> None:
        """Test that plan verification includes unique IDs check."""
        result = verifier.verify_plan(valid_plan)
        unique_check = next(
            (c for c in result.checks if "unique" in c.check_name.lower()),
            None,
        )
        assert unique_check is not None
        assert unique_check.passed is True

    def test_verify_plan_checks_dependencies(
        self, verifier: DeterministicVerifier, valid_plan: Plan
    ) -> None:
        """Test that plan verification includes dependency check."""
        result = verifier.verify_plan(valid_plan)
        dep_check = next(
            (c for c in result.checks if "dependency" in c.check_name.lower()),
            None,
        )
        assert dep_check is not None
        assert dep_check.passed is True

    def test_verify_plan_checks_sequencing(
        self, verifier: DeterministicVerifier, valid_plan: Plan
    ) -> None:
        """Test that plan verification includes sequencing check."""
        result = verifier.verify_plan(valid_plan)
        seq_check = next(
            (c for c in result.checks if "sequenc" in c.check_name.lower()),
            None,
        )
        assert seq_check is not None
        assert seq_check.passed is True

    # =========================================================================
    # verify_run_state TESTS
    # =========================================================================

    def test_verify_run_state_pass(
        self, verifier: DeterministicVerifier, valid_state: RunState
    ) -> None:
        """Test that valid run state verification passes."""
        result = verifier.verify_run_state(valid_state)
        assert result.status == VerificationResultStatus.PASS
        assert result.run_id == valid_state.run_id

    def test_verify_run_state_checks_goal(
        self, verifier: DeterministicVerifier, valid_state: RunState
    ) -> None:
        """Test that run state verification checks goal."""
        result = verifier.verify_run_state(valid_state)
        goal_check = next(
            (c for c in result.checks if "goal" in c.check_name.lower()),
            None,
        )
        assert goal_check is not None
        assert goal_check.passed is True

    def test_verify_run_state_checks_plan_match(
        self, verifier: DeterministicVerifier, valid_state: RunState
    ) -> None:
        """Test that run state verification checks plan run_id match."""
        result = verifier.verify_run_state(valid_state)
        plan_check = next(
            (c for c in result.checks if "run_id" in c.check_name.lower()),
            None,
        )
        assert plan_check is not None
        assert plan_check.passed is True

    def test_verify_run_state_no_plan_fails(self) -> None:
        """Test that run state without plan fails verification."""
        verifier = DeterministicVerifier()
        state = RunState(
            run_id="run-no-plan",
            goal="Test goal",
            status=RunStatus.CREATED,
            plan=None,
        )
        result = verifier.verify_run_state(state)
        assert result.status == VerificationResultStatus.FAIL
        plan_check = next(
            (
                c
                for c in result.checks
                if "plan" in c.check_name.lower() and "exist" in c.check_name.lower()
            ),
            None,
        )
        assert plan_check is not None
        assert plan_check.passed is False

    # =========================================================================
    # verify_task TESTS
    # =========================================================================

    def test_verify_task_pass(self, verifier: DeterministicVerifier) -> None:
        """Test that valid task verification passes."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test task",
            description="Test description",
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
        )
        result = verifier.verify_task(task)
        assert result.status == VerificationResultStatus.PASS
        assert result.task_id == task.task_id

    def test_verify_task_checks_id(self, verifier: DeterministicVerifier) -> None:
        """Test that task verification checks task ID."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test task",
            description="Test description",
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
        )
        result = verifier.verify_task(task)
        id_check = next(
            (c for c in result.checks if "ID" in c.check_name),
            None,
        )
        assert id_check is not None
        assert id_check.passed is True

    def test_verify_task_checks_title_and_description(
        self, verifier: DeterministicVerifier
    ) -> None:
        """Test that task verification checks title and description."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test task",
            description="Test description",
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
        )
        result = verifier.verify_task(task)
        title_check = next(
            (c for c in result.checks if "title" in c.check_name.lower()),
            None,
        )
        assert title_check is not None
        assert title_check.passed is True

    def test_verify_task_checks_verification_spec(
        self, verifier: DeterministicVerifier
    ) -> None:
        """Test that task verification checks verification spec."""
        task = ChildTask(
            task_id="TASK-001",
            sequence=1,
            title="Test task",
            description="Test description",
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="test"
            ),
        )
        result = verifier.verify_task(task)
        spec_check = next(
            (c for c in result.checks if "verification" in c.check_name.lower()),
            None,
        )
        assert spec_check is not None
        assert spec_check.passed is True

    # =========================================================================
    # verify_full_run TESTS
    # =========================================================================

    def test_verify_full_run_pass(
        self, verifier: DeterministicVerifier, valid_state: RunState
    ) -> None:
        """Test that full run verification passes for valid run."""
        # Test with empty list - should FAIL now
        result = verifier.verify_full_run(valid_state, valid_state.plan, [])
        assert result.status == VerificationResultStatus.FAIL
        assert result.run_id == valid_state.run_id

    def test_verify_full_run_with_evidence_pass(
        self, verifier: DeterministicVerifier, valid_state: RunState
    ) -> None:
        """Test that full run verification passes with evidence."""
        evidence = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id=valid_state.run_id,
                kind="test",
                source="test",
                payload={},
            )
        ]
        result = verifier.verify_full_run(valid_state, valid_state.plan, evidence)
        assert result.status == VerificationResultStatus.PASS
        # Check that evidence check passed
        evidence_check = next(
            (c for c in result.checks if "evidence" in c.check_name.lower()),
            None,
        )
        assert evidence_check is not None
        assert evidence_check.passed is True

    def test_verify_full_run_no_evidence_fails(
        self, verifier: DeterministicVerifier, valid_state: RunState
    ) -> None:
        """Test that full run verification fails when evidence list is empty.
        
        Verifier should FAIL when evidence_records is None or empty list.
        """
        result = verifier.verify_full_run(valid_state, valid_state.plan, None)
        # With our current implementation, None/empty evidence should FAIL
        assert result.status == VerificationResultStatus.FAIL
        
        # Also test with empty list
        result2 = verifier.verify_full_run(valid_state, valid_state.plan, [])
        assert result2.status == VerificationResultStatus.FAIL

    def test_verify_full_run_no_plan_fails(
        self, verifier: DeterministicVerifier
    ) -> None:
        """Test that full run verification fails without plan."""
        state = RunState(
            run_id="run-no-plan",
            goal="Test goal",
            status=RunStatus.CREATED,
            plan=None,
        )
        result = verifier.verify_full_run(state, None, [])
        assert result.status == VerificationResultStatus.FAIL

    # =========================================================================
    # INTEGRATION WITH PLANNER
    # =========================================================================

    def test_verify_planner_output(self, verifier: DeterministicVerifier) -> None:
        """Test that verifier can verify planner output."""
        planner = PlannerStub()
        goal_input = GoalInput(goal="Test goal for verification")
        plan = planner.create_plan(goal_input)

        result = verifier.verify_plan(plan)
        assert result.status == VerificationResultStatus.PASS
        assert result.run_id == plan.run_id

    def test_verify_planner_output_full_run(
        self, verifier: DeterministicVerifier
    ) -> None:
        """Test full verification of planner output."""
        planner = PlannerStub()
        goal_input = GoalInput(goal="Test goal")
        plan = planner.create_plan(goal_input)
        state = RunState(
            run_id=plan.run_id,
            goal=plan.goal,
            status=RunStatus.PLANNED,
            plan=plan,
        )

        evidence = [
            EvidenceRecord(
                evidence_id="evidence-1",
                run_id=state.run_id,
                kind="plan",
                source="planner",
                payload={},
            )
        ]

        result = verifier.verify_full_run(state, plan, evidence)
        assert result.status == VerificationResultStatus.PASS

    # =========================================================================
    # SINGLETON INSTANCE
    # =========================================================================

    def test_verifier_singleton(self) -> None:
        """Test that verifier module exports a singleton instance."""
        from fsasm.verifier import verifier
        assert isinstance(verifier, DeterministicVerifier)
        # Should be able to use it directly
        valid_plan = Plan(
            plan_id="test-plan",
            run_id="test-run",
            goal="Test goal",
            tasks=[
                ChildTask(
                    task_id=f"TASK-00{i}",
                    sequence=i,
                    title=f"Task {i}",
                    description=f"Desc {i}",
                    status=TaskStatus.PENDING,
                    verification=VerificationSpec(type=VerificationType.SCHEMA, expected="test"),
                )
                for i in range(1, 4)
            ],
        )
        result = verifier.verify_plan(valid_plan)
        assert isinstance(result, VerificationResult)
