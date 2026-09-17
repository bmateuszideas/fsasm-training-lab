"""FS-ASM Task Compiler (T08) - trusted compilation of untrusted proposals.

The Task Compiler is the SINGLE boundary that turns an untrusted
``PlannerProposal`` (semantic content from the LLM) into a runtime-owned
``Plan`` (the authoritative Task Register). It does NOT trust the proposal for
identity, scope, limits or structure; it assigns every runtime-owned field and
rejects anything that attempts to widen privilege beyond the approved intake
constraints (``GoalInput.constraints``).

Design (architecture §16, §17):
- ``PlannerProposal`` is untrusted semantic input. Only its content fields
  (title, description, verification spec, expected evidence, constraints
  text) are carried forward.
- Runtime-owned IDs (``task_id``, ``parent_id``, ``plan_id``), statuses,
  attempts and the dependency graph are assigned by the compiler.
- ``allowed_files``/``allowed_tools`` proposed per task must be a subset of the
  approved intake scope; a superset is rejected as privilege extension.
- Cycles, missing/duplicate dependencies, plan-size overflow and attempt-cap
  overflow are rejected BEFORE a run is created.
- The compiler returns a pure ``Plan`` (Domain Core type); no provider
  transport types cross this boundary.

This module is independent of Mistral Workflows and the LLM transport; the
existing ``assemble_plan``/``PlannerStub`` M1-M4 path is preserved unchanged.
"""

from fsasm.errors import PlanValidationError
from fsasm.models import (
    ChildTask,
    GoalInput,
    Plan,
    PlannerProposal,
    TaskBudget,
    TaskProposal,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.models import parent_id_for, task_id_for

DEFAULT_MAX_ATTEMPTS = 3


def _subset(proposed: list[str], allowed: list[str]) -> bool:
    """Return True iff every proposed glob appears verbatim in allowed.

    Intake-approved scope is an allowlist carried as literal globs; the
    compiler does not perform glob pattern-subset reasoning (a proposed
    ``*.py`` is wider than an approved ``src/*.py``), so it matches by exact
    membership. Empty ``allowed`` means "nothing approved" -> any proposed
    entry is a privilege extension. Empty ``proposed`` is always a subset
    (a task that modifies nothing does not widen scope).
    """
    if not proposed:
        return True
    allowed_set = set(allowed)
    return all(p in allowed_set for p in proposed)


def compile_plan(goal_input: GoalInput, proposal: PlannerProposal) -> Plan:
    """Compile an untrusted proposal into a runtime-owned, validated Plan.

    The proposal is treated as untrusted semantic input. All runtime-owned
    fields (IDs, parent, statuses, attempts, dependencies, scope enforcement)
    are assigned here. Anything that attempts to widen privilege beyond the
    approved ``goal_input.constraints`` is rejected with ``PlanValidationError``.

    Args:
        goal_input: The trusted intake with the authoritative goal, run_id and
            approved constraints (the only source of privilege).
        proposal: The untrusted semantic proposal from the Planner/LLM.

    Returns:
        A fully assembled, validated ``Plan`` (Domain Core type).

    Raises:
        PlanValidationError: on empty proposal, plan-size overflow, duplicate
            proposal-local sequence, missing/invalid dependencies, cycle,
            privilege extension (allowed_files/allowed_tools beyond intake),
            or attempt-cap overflow.
    """
    if not proposal.tasks:
        raise PlanValidationError(
            "Task Compiler rejected empty proposal: at least 1 task required"
        )

    run_id = goal_input.generate_run_id()
    constraints = goal_input.constraints

    # Intake cap: maximum number of Child Tasks.
    if (
        constraints.max_tasks is not None
        and len(proposal.tasks) > constraints.max_tasks
    ):
        raise PlanValidationError(
            f"Task Compiler rejected plan-size overflow: proposal has "
            f"{len(proposal.tasks)} tasks, intake max_tasks={constraints.max_tasks}"
        )

    # Deterministic runtime-owned IDs and per-task validation. Proposal-local
    # sequence numbers are 1-indexed positions; the compiler is the only entity
    # that maps them to runtime task IDs (the LLM never proposes its own IDs).
    task_id_map: dict[int, str] = {}
    seen_sequences: set[int] = set()
    tasks: list[ChildTask] = []

    for idx, task_proposal in enumerate(proposal.tasks, start=1):
        seq = idx
        if seq in seen_sequences:
            raise PlanValidationError(
                f"Task Compiler rejected duplicate proposal-local sequence {seq}"
            )
        seen_sequences.add(seq)

        task_id = task_id_for(run_id, seq)
        task_id_map[seq] = task_id

        # Validate proposal-local dependencies: 1 <= dep_seq < seq (no 0,
        # no self, no future, no missing). The LLM may not reference a task it
        # has not yet defined.
        runtime_dependencies: list[str] = []
        for dep_seq in task_proposal.dependencies:
            if not (1 <= dep_seq < seq):
                raise PlanValidationError(
                    f"Task Compiler rejected invalid dependency sequence "
                    f"{dep_seq} on task {seq}: must satisfy 1 <= dep_seq < {seq}"
                )
            runtime_dependencies.append(task_id_map[dep_seq])

        # Privilege enforcement: the proposed allowed_files must not exceed
        # the approved intake scope. The LLM cannot widen scope. The proposal
        # carries no allowed_tools (only the runtime ChildTask does), so the
        # compiler grants each task the approved intake tool set verbatim.
        if not _subset(task_proposal.allowed_files, constraints.allowed_files):
            raise PlanValidationError(
                f"Task Compiler rejected privilege extension: task {task_id} "
                f"allowed_files {task_proposal.allowed_files!r} exceed approved "
                f"intake {constraints.allowed_files!r}"
            )
        granted_tools = list(constraints.allowed_tools)

        # Attempt cap: the per-task max attempts must not exceed the intake
        # cap. The proposal does not carry attempts; the compiler assigns the
        # runtime default, capped by intake.
        max_attempts = DEFAULT_MAX_ATTEMPTS
        if constraints.max_attempts_per_task is not None:
            max_attempts = min(max_attempts, constraints.max_attempts_per_task)

        verification = _coerce_verification(task_proposal, task_id)

        task = ChildTask(
            task_id=task_id,
            parent_id=parent_id_for(run_id),
            sequence=seq,
            title=task_proposal.title,
            description=task_proposal.description,
            status=TaskStatus.PENDING,
            dependencies=runtime_dependencies,
            constraints=task_proposal.constraints,
            allowed_files=list(task_proposal.allowed_files),
            allowed_tools=granted_tools,
            verification=verification,
            expected_evidence=task_proposal.expected_evidence,
            attempt=0,
            max_attempts=max_attempts,
            budget=TaskBudget(max_attempts=max_attempts),
        )
        tasks.append(task)

    plan = Plan(
        plan_id=f"plan-{run_id}",
        run_id=run_id,
        goal=goal_input.goal,
        tasks=tasks,
    )
    # Plan validators (unique IDs, dependencies exist, no cycles) run on
    # construction; a structural problem here is a compiler bug, surfaced as a
    # ValueError. The compiler guarantees a valid DAG before the run exists.
    return plan


def _coerce_verification(task_proposal: TaskProposal, task_id: str) -> VerificationSpec:
    """Coerce the untrusted proposal's verification into a runtime-owned spec.

    The ``verification_type`` string is validated against the runtime enum; an
    unknown type is rejected so the LLM cannot invent an unverifiable kind.
    """
    try:
        vtype = VerificationType(task_proposal.verification_type)
    except ValueError as exc:
        raise PlanValidationError(
            f"Task Compiler rejected unknown verification_type "
            f"{task_proposal.verification_type!r} on task {task_id}"
        ) from exc
    return VerificationSpec(type=vtype, expected=task_proposal.verification_expected)
