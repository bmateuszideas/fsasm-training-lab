"""T15 — Task-scoped Context Builder.

Proves the v1 Context Builder assembles a bounded, provenance-tracked
TaskContext for one attempt of a Child Task: objective, acceptance criteria,
constraints, allowed files/tools, relevant sources/tests/decisions, prior
observations/verification and a context budget. The first version uses
explicit paths, search, symbols/imports and simple dependencies — no LLMC,
no vector DB. Every fragment records provenance; no file outside the approved
scope and no whole-repo dump is included. The Context Builder grants no PASS
and does not widen scope (architecture §23, §25; canonical TODO T15).
"""

import pathlib

import pytest

from fsasm.context import ContextBuilder
from fsasm.models import (
    ChildTask,
    Plan,
    RunState,
    RunStatus,
    TaskStatus,
    VerificationSpec,
    VerificationType,
)
from fsasm.tool_broker import ToolBroker

RUN = "r"
TASK = "TASK-r-1"


def _task(
    tid: str = TASK,
    allowed_files: list[str] | None = None,
    deps: list[str] | None = None,
    title: str = "Patch add to subtract",
    description: str = "Modify the add function to return a - b",
    constraints: list[str] | None = None,
) -> ChildTask:
    return ChildTask(
        task_id=tid,
        sequence=1,
        title=title,
        description=description,
        dependencies=deps or [],
        allowed_files=allowed_files or ["calc.py"],
        allowed_tools=["read_file", "apply_patch", "run_checks"],
        verification=VerificationSpec(
            type=VerificationType.SCHEMA, expected="return a - b"
        ),
        expected_evidence=["artifact", "check_result"],
        constraints=constraints or [],
    )


def _state(
    task: ChildTask, run_id: str = RUN, extra: list[ChildTask] | None = None
) -> RunState:
    tasks = [task]
    if extra:
        tasks.extend(extra)
    plan = Plan(plan_id="p", run_id=run_id, goal="g", tasks=tasks)
    return RunState(run_id=run_id, goal="g", status=RunStatus.RUNNING, plan=plan)


def _broker(root: pathlib.Path) -> ToolBroker:
    return ToolBroker(workspace_root=root, workspace_scope=[])


@pytest.fixture()
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "helper.py").write_text(
        "from calc import add\n\n\ndef double(x):\n    return add(x, x)\n",
        encoding="utf-8",
    )
    # An unrelated in-scope file that should NOT leak into the context unless
    # its symbols are referenced by the objective.
    (tmp_path / "unrelated.py").write_text(
        "def unrelated_thing():\n    pass\n", encoding="utf-8"
    )
    return tmp_path


class TestTaskContextStructure:
    """TaskContext carries objective, acceptance criteria, constraints, scope."""

    def test_context_carries_task_metadata(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        builder = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1)
        ctx = builder.build(state)
        assert ctx.run_id == RUN
        assert ctx.task_id == TASK
        assert ctx.attempt == 1
        assert "Patch add to subtract" in ctx.objective
        assert "return a - b" in ctx.objective
        # Acceptance criteria include the verification spec + expected evidence.
        assert any("verification" in c for c in ctx.acceptance_criteria)
        assert any("expected_evidence" in c for c in ctx.acceptance_criteria)
        # Constraints include task constraints + the run goal.
        assert any("goal" in c for c in ctx.constraints)
        # Scope boundary is copied from the task.
        assert ctx.allowed_files == ["calc.py"]
        assert ctx.allowed_tools == ["read_file", "apply_patch", "run_checks"]

    def test_context_budget_recorded(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        builder = ContextBuilder(
            broker=broker,
            run_id=RUN,
            task_id=TASK,
            attempt=1,
            context_budget_chars=4096,
        )
        ctx = builder.build(state)
        assert ctx.context_budget_chars == 4096
        assert ctx.used_chars >= 0
        assert ctx.used_chars <= 4096


class TestExplicitPathRead:
    """Explicit allowed_files are read via the Broker (scope-enforced)."""

    def test_allowed_file_becomes_fragment(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(allowed_files=["calc.py"])
        state = _state(task)
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        # calc.py content is present as an objective_source fragment.
        frag = next((f for f in ctx.fragments if f.source_path == "calc.py"), None)
        assert frag is not None
        assert "def add" in frag.content
        assert frag.kind == "objective_source"
        assert frag.reason  # provenance is non-empty

    def test_missing_allowed_file_yields_no_fragment(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        task = _task(allowed_files=["does_not_exist.py"])
        state = _state(task)
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        assert all(f.source_path != "does_not_exist.py" for f in ctx.fragments)


class TestScopeEnforced:
    """A file outside the approved scope is never included."""

    def test_out_of_scope_file_not_read(self, workspace: pathlib.Path) -> None:
        broker = _broker(
            workspace,
        )  # default scope = whole root is approved,
        # but the task's allowed_files is the per-task boundary. The builder
        # reads ONLY the task's allowed_files by default, so a file not listed
        # is not included even if it exists.
        task = _task(allowed_files=["calc.py"])
        state = _state(task)
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        paths = {f.source_path for f in ctx.fragments}
        assert "unrelated.py" not in paths  # not in allowed_files

    def test_broker_blocks_out_of_scope_read(self, workspace: pathlib.Path) -> None:
        """Even an explicit path outside scope is blocked by the Broker."""
        broker = ToolBroker(workspace_root=workspace, workspace_scope=["src"])
        task = _task(allowed_files=["calc.py"])
        state = _state(task)
        # workspace_scope is ['src'], so calc.py at root is out of scope.
        builder = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1)
        ctx = builder.build(state, explicit_paths=["calc.py"])
        # The read was blocked: no fragment for calc.py.
        assert all(f.source_path != "calc.py" for f in ctx.fragments)


class TestSymbolSearch:
    """Files whose symbols are referenced by the objective are selected.

    When a referenced symbol lives in a file that is NOT in the task's
    ``allowed_files`` (so it would not be read in full), the symbol search
    sweep over the approved workspace scope surfaces just the matching lines
    as a targeted ``symbol`` fragment — without a whole-file dump.
    """

    def test_symbol_reference_includes_file(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        # helper.py is NOT in allowed_files, but the objective references
        # 'double' which is defined there. The symbol sweep should surface it.
        task = _task(
            allowed_files=["calc.py"],
            description="Use the double function from helper",
        )
        state = _state(task)
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        frag = next((f for f in ctx.fragments if f.source_path == "helper.py"), None)
        assert frag is not None
        # The symbol fragment contains the matching def line.
        assert "double" in frag.content
        assert frag.kind == "symbol"
        assert "double" in frag.reason  # provenance names the referenced symbol

    def test_unreferenced_file_not_included(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        # unrelated.py defines 'unrelated_thing' which the objective never
        # references -> it must not appear as a symbol fragment.
        task = _task(
            allowed_files=["calc.py"],
            description="Modify the add function in calc",
        )
        state = _state(task)
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        # unrelated.py's symbol is not referenced -> excluded from symbol search.
        assert all(f.source_path != "unrelated.py" for f in ctx.fragments)

    def test_symbol_search_skips_already_read_files(
        self, workspace: pathlib.Path
    ) -> None:
        """A file already read in full (in allowed_files) is not re-added as symbol."""
        broker = _broker(workspace)
        task = _task(
            allowed_files=["calc.py", "helper.py"],
            description="Use the double function from helper",
        )
        state = _state(task)
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        # helper.py was read in full as an objective_source, so it must NOT
        # also appear as a symbol fragment (no duplicate).
        helper_frags = [f for f in ctx.fragments if f.source_path == "helper.py"]
        assert len(helper_frags) == 1
        assert helper_frags[0].kind == "objective_source"


class TestDependencyOutputs:
    """Completed dependencies' accepted evidence become a fragment."""

    def test_dependency_evidence_fragment(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        dep = ChildTask(
            task_id="TASK-r-0",
            sequence=0,
            title="setup",
            description="setup task",
            allowed_files=["calc.py"],
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="setup"
            ),
        )
        # Mark the dependency complete with accepted evidence.
        dep.status = TaskStatus.PASSED
        dep.accepted_evidence_refs = ["evidence-r-TASK-r-0-1-artifact"]
        task = _task(deps=["TASK-r-0"])
        state = _state(task, extra=[dep])
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        dep_frag = next(
            (f for f in ctx.fragments if f.kind == "dependency_output"), None
        )
        assert dep_frag is not None
        assert "TASK-r-0" in dep_frag.content
        assert "evidence-r-TASK-r-0-1-artifact" in dep_frag.content
        assert dep_frag.source_path == "<dependency:TASK-r-0>"

    def test_incomplete_dependency_no_fragment(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        dep = ChildTask(
            task_id="TASK-r-0",
            sequence=0,
            title="setup",
            description="setup",
            allowed_files=["calc.py"],
            verification=VerificationSpec(
                type=VerificationType.SCHEMA, expected="setup"
            ),
        )
        # dependency NOT complete (no accepted evidence).
        task = _task(deps=["TASK-r-0"])
        state = _state(task, extra=[dep])
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        assert all(f.kind != "dependency_output" for f in ctx.fragments)


class TestBudgetEnforcement:
    """The context budget caps total fragment size (no whole-repo dump)."""

    def test_budget_caps_fragments(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        # A tiny budget so only the first fragment (or part of it) fits.
        task = _task(allowed_files=["calc.py", "helper.py"], description="use double")
        state = _state(task)
        builder = ContextBuilder(
            broker=broker, run_id=RUN, task_id=TASK, attempt=1, context_budget_chars=50
        )
        ctx = builder.build(state)
        # Each fragment is capped at a quarter of the budget plus the
        # truncation marker ("\n...[truncated]" = 15 chars).
        marker = len("\n...[truncated]")
        for f in ctx.fragments:
            assert len(f.content) <= (50 // 4) + marker
        # Total used stays within budget (the loop stops once used >= budget).
        assert ctx.used_chars <= 50 + len(ctx.fragments) * marker

    def test_large_file_truncated_in_fragment(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        big = "x = 1\n" * 5000
        (workspace / "calc.py").write_text(big, encoding="utf-8")
        task = _task(allowed_files=["calc.py"])
        state = _state(task)
        builder = ContextBuilder(
            broker=broker, run_id=RUN, task_id=TASK, attempt=1, context_budget_chars=200
        )
        ctx = builder.build(state)
        frag = next((f for f in ctx.fragments if f.source_path == "calc.py"), None)
        assert frag is not None
        # A single fragment is capped at a quarter of the budget plus marker.
        marker = len("\n...[truncated]")
        assert len(frag.content) <= (200 // 4) + marker


class TestProvenance:
    """Every fragment carries non-empty provenance."""

    def test_all_fragments_have_provenance(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task(allowed_files=["calc.py", "helper.py"], description="use double")
        state = _state(task)
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        assert ctx.fragments  # at least one fragment
        for f in ctx.fragments:
            assert f.source_path
            assert f.kind
            assert f.reason  # mandatory provenance


class TestPriorAttemptFeedback:
    """Retry feedback (prior observations + verification) is carried."""

    def test_prior_feedback_recorded(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        builder = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=2)
        ctx = builder.build(
            state,
            prior_observations=["apply_patch returned ok but check exit_code=1"],
            prior_verification="artifact did not contain 'return a - b'",
        )
        assert ctx.attempt == 2
        assert "exit_code=1" in ctx.prior_observations[0]
        assert "return a - b" in ctx.prior_verification


class TestContextGrantsNoPass:
    """The Context Builder / TaskContext hold no transition authority."""

    def test_taskcontext_has_no_pass_method(self) -> None:
        from fsasm.models import TaskContext

        for forbidden in ("grant_pass", "pass_task", "transition", "apply", "commit"):
            assert not hasattr(TaskContext, forbidden)

    def test_builder_has_no_pass_method(self) -> None:
        from fsasm.context import ContextBuilder as CB

        for forbidden in ("grant_pass", "pass_task", "transition", "apply", "commit"):
            assert not hasattr(CB, forbidden)


class TestScriptedBackendSufficiency:
    """A small in-scope context suffices for a scripted backend to find fixture.

    This is the T15 acceptance anchor: the context gives the scripted backend
    exactly the relevant source (calc.py) and the acceptance criteria, within
    budget, without revealing out-of-scope files. The scripted backend (T16)
    will use this; here we assert the context is sufficient and bounded.
    """

    def test_context_sufficient_and_bounded(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        task = _task()
        state = _state(task)
        ctx = ContextBuilder(broker=broker, run_id=RUN, task_id=TASK, attempt=1).build(
            state
        )
        # Sufficient: the relevant source is present.
        assert any("def add" in f.content for f in ctx.fragments)
        # Bounded: used within budget.
        assert ctx.used_chars <= ctx.context_budget_chars
        # In-scope only: no out-of-scope paths.
        for f in ctx.fragments:
            assert f.source_path in {"calc.py"} or f.source_path.startswith("<")
