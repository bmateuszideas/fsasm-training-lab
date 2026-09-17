"""T08 — Trusted Intake and Task Compiler.

Tests that the Task Compiler turns an untrusted ``PlannerProposal`` into a
runtime-owned, validated ``Plan`` and rejects anything that attempts to widen
privilege beyond the approved intake constraints. Plans of 1, 3 and N tasks
compile; an invalid DAG and scope outside Intake are rejected before a run is
created (architecture §16, §17; canonical TODO T08).
"""

import pytest

from fsasm.errors import PlanValidationError
from fsasm.models import (
    ChildTask,
    GoalInput,
    Plan,
    PlannerProposal,
    RunConstraints,
    TaskProposal,
    VerificationSpec,
    VerificationType,
)
from fsasm.task_compiler import compile_plan


def _proposal(*tasks: TaskProposal) -> PlannerProposal:
    return PlannerProposal(tasks=list(tasks))


def _tp(
    title: str = "t",
    dependencies: list[int] | None = None,
    verification_type: str = "schema",
    allowed_files: list[str] | None = None,
) -> TaskProposal:
    return TaskProposal(
        title=title,
        description="d",
        dependencies=dependencies or [],
        verification_type=verification_type,
        verification_expected="e",
        allowed_files=allowed_files or [],
    )


class TestCompileAcceptedSizes:
    """Plans of 1, 3 and N tasks compile to a valid Plan."""

    def test_one_task_compiles(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="r1"),
            _proposal(_tp()),
        )
        assert isinstance(plan, Plan)
        assert len(plan.tasks) == 1
        assert plan.goal == "g"
        assert plan.plan_id == "plan-r1"
        assert plan.run_id == "r1"

    def test_three_tasks_compiles(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="r3"),
            _proposal(_tp("a"), _tp("b", [1]), _tp("c", [1, 2])),
        )
        assert [t.task_id for t in plan.tasks] == [
            "TASK-r3-1",
            "TASK-r3-2",
            "TASK-r3-3",
        ]
        assert plan.tasks[2].dependencies == ["TASK-r3-1", "TASK-r3-2"]

    def test_n_tasks_compiles(self) -> None:
        proposal = _proposal(
            *[_tp(f"t{i}", [i - 1] if i > 1 else []) for i in range(1, 6)]
        )
        plan = compile_plan(GoalInput(goal="g", run_id="rn"), proposal)
        assert len(plan.tasks) == 5
        assert plan.tasks[4].dependencies == ["TASK-rn-4"]


class TestRuntimeOwnedIds:
    """IDs, parent, statuses and attempts are runtime-owned, not from the LLM."""

    def test_task_ids_are_runtime_owned(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="rid"),
            _proposal(_tp()),
        )
        assert plan.tasks[0].task_id == "TASK-rid-1"

    def test_parent_id_assigned(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="rid"),
            _proposal(_tp(), _tp("b", [1])),
        )
        for t in plan.tasks:
            assert t.parent_id == "PARENT-rid"

    def test_statuses_and_attempts_owned(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="rid"),
            _proposal(_tp()),
        )
        task = plan.tasks[0]
        assert task.status.value == "PENDING"
        assert task.attempt == 0
        assert task.max_attempts >= 1

    def test_proposal_cannot_propose_ids(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="rid"),
            _proposal(_tp()),
        )
        assert plan.tasks[0].task_id == "TASK-rid-1"


class TestDependencyValidation:
    """Cycles, missing, self and future dependencies are rejected."""

    def test_missing_dependency_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            compile_plan(
                GoalInput(goal="g", run_id="r"),
                _proposal(_tp("a", [2]), _tp("b")),
            )
        assert "invalid dependency sequence 2" in str(exc.value).lower()

    def test_self_dependency_rejected(self) -> None:
        with pytest.raises(PlanValidationError):
            compile_plan(
                GoalInput(goal="g", run_id="r"),
                _proposal(_tp("a", [1])),
            )

    def test_future_dependency_rejected(self) -> None:
        with pytest.raises(PlanValidationError):
            compile_plan(
                GoalInput(goal="g", run_id="r"),
                _proposal(_tp("a", [3]), _tp("b"), _tp("c")),
            )

    def test_zero_dependency_rejected(self) -> None:
        with pytest.raises(PlanValidationError):
            compile_plan(
                GoalInput(goal="g", run_id="r"),
                _proposal(_tp("a", [0]), _tp("b")),
            )

    def test_no_cycles_possible_in_dag(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="r"),
            _proposal(_tp("a"), _tp("b", [1]), _tp("c", [2])),
        )
        assert plan.tasks[2].dependencies == ["TASK-r-2"]


class TestDuplicateRejection:
    """Duplicate task IDs and proposal-local sequences are rejected."""

    def test_duplicate_task_ids_rejected_by_plan(self) -> None:
        with pytest.raises(ValueError, match="Task IDs must be unique"):
            Plan(
                plan_id="p",
                run_id="r",
                goal="g",
                tasks=[
                    ChildTask(
                        task_id="TASK-x",
                        sequence=1,
                        title="a",
                        description="d",
                        verification=VerificationSpec(
                            type=VerificationType.SCHEMA, expected="e"
                        ),
                    ),
                    ChildTask(
                        task_id="TASK-x",
                        sequence=2,
                        title="b",
                        description="d",
                        verification=VerificationSpec(
                            type=VerificationType.SCHEMA, expected="e"
                        ),
                    ),
                ],
            )


class TestPlanSizeOverflow:
    """Plan-size overflow beyond the intake cap is rejected."""

    def test_max_tasks_overflow_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            compile_plan(
                GoalInput(
                    goal="g",
                    run_id="r",
                    constraints=RunConstraints(max_tasks=2),
                ),
                _proposal(_tp("a"), _tp("b", [1]), _tp("c", [2])),
            )
        assert "plan-size overflow" in str(exc.value).lower()

    def test_max_tasks_at_boundary_accepted(self) -> None:
        plan = compile_plan(
            GoalInput(
                goal="g",
                run_id="r",
                constraints=RunConstraints(max_tasks=2),
            ),
            _proposal(_tp("a"), _tp("b", [1])),
        )
        assert len(plan.tasks) == 2


class TestPrivilegeExtension:
    """Scope outside the approved Intake is rejected before a run is created."""

    def test_allowed_files_extension_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            compile_plan(
                GoalInput(
                    goal="g",
                    run_id="r",
                    constraints=RunConstraints(allowed_files=["src/a.py"]),
                ),
                _proposal(_tp(allowed_files=["src/b.py"])),
            )
        assert "privilege extension" in str(exc.value).lower()

    def test_allowed_files_subset_accepted(self) -> None:
        plan = compile_plan(
            GoalInput(
                goal="g",
                run_id="r",
                constraints=RunConstraints(
                    allowed_files=["src/a.py", "src/b.py", "src/c.py"]
                ),
            ),
            _proposal(_tp(allowed_files=["src/a.py", "src/c.py"])),
        )
        assert plan.tasks[0].allowed_files == ["src/a.py", "src/c.py"]

    def test_empty_intake_files_rejects_any_proposed_file(self) -> None:
        with pytest.raises(PlanValidationError):
            compile_plan(
                GoalInput(goal="g", run_id="r", constraints=RunConstraints()),
                _proposal(_tp(allowed_files=["any.py"])),
            )

    def test_no_files_proposed_accepted_under_empty_intake(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="r", constraints=RunConstraints()),
            _proposal(_tp()),
        )
        assert plan.tasks[0].allowed_files == []

    def test_tools_granted_from_intake(self) -> None:
        plan = compile_plan(
            GoalInput(
                goal="g",
                run_id="r",
                constraints=RunConstraints(
                    allowed_files=["src/a.py"], allowed_tools=["read_file"]
                ),
            ),
            _proposal(_tp(allowed_files=["src/a.py"])),
        )
        assert plan.tasks[0].allowed_tools == ["read_file"]

    def test_no_tools_intake_grants_no_tools(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="r", constraints=RunConstraints()),
            _proposal(_tp()),
        )
        assert plan.tasks[0].allowed_tools == []


class TestAttemptCap:
    """Per-task attempt cap is enforced from intake."""

    def test_max_attempts_capped_by_intake(self) -> None:
        plan = compile_plan(
            GoalInput(
                goal="g",
                run_id="r",
                constraints=RunConstraints(max_attempts_per_task=2),
            ),
            _proposal(_tp()),
        )
        assert plan.tasks[0].max_attempts == 2

    def test_max_attempts_default_when_no_intake_cap(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="r", constraints=RunConstraints()),
            _proposal(_tp()),
        )
        assert plan.tasks[0].max_attempts == 3


class TestVerificationSpec:
    """Verification spec is coerced and unknown types rejected."""

    def test_valid_verification_types(self) -> None:
        for vt in ["schema", "exists", "count", "custom"]:
            plan = compile_plan(
                GoalInput(goal="g", run_id="r"),
                _proposal(_tp(verification_type=vt)),
            )
            assert plan.tasks[0].verification.type == VerificationType(vt)

    def test_unknown_verification_type_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            compile_plan(
                GoalInput(goal="g", run_id="r"),
                _proposal(_tp(verification_type="bogus")),
            )
        assert "unknown verification_type" in str(exc.value).lower()


class TestAuthoritativeGoal:
    """Plan.goal comes from GoalInput, never from the proposal."""

    def test_goal_from_intake(self) -> None:
        plan = compile_plan(
            GoalInput(goal="authoritative goal", run_id="r"),
            _proposal(_tp()),
        )
        assert plan.goal == "authoritative goal"


class TestNoTransportTypesInDomain:
    """The compiler returns a pure Plan; no provider transport types leak in."""

    def test_plan_is_pure_domain_type(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="r"),
            _proposal(_tp()),
        )
        assert isinstance(plan, Plan)
        assert isinstance(plan.tasks[0], ChildTask)


class TestRoundTripSerialization:
    """The compiled plan round-trips through serialization."""

    def test_round_trip(self) -> None:
        plan = compile_plan(
            GoalInput(goal="g", run_id="r"),
            _proposal(_tp("a"), _tp("b", [1]), _tp("c", [1, 2])),
        )
        data = plan.model_dump()
        restored = Plan(**data)
        assert restored.tasks[2].dependencies == ["TASK-r-1", "TASK-r-2"]
        assert restored.run_id == plan.run_id


class TestEmptyProposalRejected:
    """An empty proposal is rejected before a run is created.

    Pydantic rejects an empty ``PlannerProposal.tasks`` at the model boundary
    (min_length=1); the compiler additionally guards against an empty list as
    defense-in-depth. Both rejections happen before a run is created.
    """

    def test_empty_proposal_rejected_at_model(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            PlannerProposal(tasks=[])

    def test_empty_proposal_rejected_by_compiler(self) -> None:
        proposal = PlannerProposal(tasks=[_tp()])
        proposal.tasks = []
        with pytest.raises(PlanValidationError) as exc:
            compile_plan(GoalInput(goal="g", run_id="r"), proposal)
        assert "empty proposal" in str(exc.value).lower()
