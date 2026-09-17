"""FS-ASM Task-scoped Context Builder (T15).

Assembles a bounded, provenance-tracked :class:`TaskContext` for one attempt of
a Child Task. The first version uses explicit paths, simple search over the
approved scope, symbol/import extraction and simple dependency outputs — no
LLMC and no vector DB. Every fragment records provenance; no file outside the
approved scope and no whole-repo dump is included without a justified need.

The Context Builder is a projection: it holds no transition/PASS power and
does not widen the approved scope. It reads real files through the
:class:`ToolBroker` so the same ``allowed_files``/``workspace_scope`` boundary
that governs writes also governs what the model may see at assembly time. The
model may do additional allowed reads through the Broker at run time
(architecture §23, §25; canonical TODO T15).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fsasm.models import (
    ChildTask,
    ContextFragment,
    RunState,
    TaskContext,
)
from fsasm.tool_broker import ToolBroker

# A simple Python symbol/import matcher. Kept intentionally narrow: it captures
# top-level ``def``/``class``/``import``/``from ... import`` lines and their
# names so the builder can select relevant fragments by symbol reference. It
# does not execute any code and does not parse arbitrary languages.
_SYMBOL_RE = re.compile(r"^\s*(async\s+def|def|class)\s+(\w+)")
_IMPORT_RE = re.compile(r"^\s*(from\s+([\w.]+)\s+import\s+(.+)|import\s+([\w.]+))")


@dataclass
class ContextBuilder:
    """Assemble a bounded TaskContext for one attempt of a Child Task.

    The builder uses the :class:`ToolBroker` for every file read so the approved
    ``allowed_files``/``workspace_scope`` boundary (enforced in code before any
    read) governs what enters the context. Explicit path reads are bound to the
    task's own ``allowed_files`` (the per-call boundary) so the model never sees
    a file outside the task's approved scope. Symbol/import search is a broader
    sweep over the approved ``workspace_scope`` (using an unconstrained read,
    still contained to the workspace root) that surfaces *targeted lines* from
    related in-scope files the objective references — without a whole-file dump.
    It then selects fragments by:

    1. Explicit paths listed on the task's ``allowed_files`` (the obvious
       targets): full in-scope file reads.
    2. Symbol/import search across the approved workspace scope: for files NOT
       already read in full, if the objective references a symbol/import
       declared there, the matching lines are added as a targeted fragment.
    3. Simple dependency outputs: the accepted evidence of completed dependency
       tasks (prior results) so the model knows what upstream produced.

    Fragments are trimmed to a soft character budget; once the budget is
    exhausted no further fragments are added (no silent whole-repo dump).
    Provenance is mandatory on every fragment. The builder grants no PASS.
    """

    broker: ToolBroker
    run_id: str
    task_id: str
    attempt: int
    context_budget_chars: int = 8192

    def build(
        self,
        state: RunState,
        *,
        explicit_paths: list[str] | None = None,
        prior_observations: list[str] | None = None,
        prior_verification: str = "",
    ) -> TaskContext:
        """Assemble the TaskContext for the current task from the live state.

        Args:
            state: The authoritative RunState (carries the plan + accepted
                evidence refs of dependency tasks).
            explicit_paths: Optional explicit workspace-relative paths to read
                first (must still be in-scope). Defaults to the task's
                ``allowed_files``.
            prior_observations: Prior tool observations on previous attempts of
                this task (retry feedback).
            prior_verification: Summary of the prior attempt's verification
                failure (retry feedback).

        Returns:
            A bounded TaskContext with provenance-tracked fragments.
        """
        task = _find_task(state, self.task_id)
        plan = state.plan
        assert plan is not None, "ContextBuilder requires a plan"
        objective = f"{task.title}: {task.description}"
        acceptance_criteria = _acceptance_criteria(task)
        constraints = _constraints(task, state)
        # Default explicit paths = the task's approved files.
        paths = (
            list(explicit_paths)
            if explicit_paths is not None
            else list(task.allowed_files)
        )

        fragments: list[ContextFragment] = []
        used = 0
        budget = self.context_budget_chars

        # 1. Explicit path reads (scope-enforced by the Broker).
        seen_paths: set[str] = set()
        allowed = list(task.allowed_files)
        for rel in paths:
            if used >= budget:
                break
            frag = self._read_fragment(
                rel, kind="objective_source", reason="explicit path", allowed=allowed
            )
            if frag is not None:
                fragments.append(frag)
                used += len(frag.content)
                seen_paths.add(rel)

        # 2. Symbol/import search across the approved workspace scope: for
        #    files NOT already read in full, if the objective references a
        #    symbol/import declared there, add the matching lines as a targeted
        #    fragment (no whole-file dump). The read is still contained to the
        #    workspace root by the Broker; ``allowed_files=None`` enables the
        #    unconstrained read sweep used for search.
        if used < budget:
            refs = _symbol_refs(objective + " " + " ".join(acceptance_criteria))
            for rel in self._in_scope_python_files(exclude=seen_paths):
                if used >= budget:
                    break
                frag = self._search_fragment(rel, refs, kind="symbol")
                if frag is not None:
                    fragments.append(frag)
                    used += len(frag.content)
                    seen_paths.add(rel)

        # 3. Dependency outputs: accepted evidence of completed dependencies.
        if used < budget:
            for dep_id in task.dependencies:
                if used >= budget:
                    break
                dep_frag = self._dependency_fragment(state, dep_id)
                if dep_frag is not None:
                    fragments.append(dep_frag)
                    used += len(dep_frag.content)

        return TaskContext(
            run_id=self.run_id,
            task_id=self.task_id,
            attempt=self.attempt,
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            constraints=constraints,
            allowed_files=list(task.allowed_files),
            allowed_tools=list(task.allowed_tools),
            fragments=fragments,
            prior_observations=list(prior_observations or []),
            prior_verification=prior_verification,
            context_budget_chars=budget,
            used_chars=used,
        )

    # -- fragment selectors ------------------------------------------------

    def _read_fragment(
        self, rel: str, *, kind: str, reason: str, allowed: list[str]
    ) -> ContextFragment | None:
        """Read one in-scope file via the Broker and wrap it as a fragment.

        A blocked/missing read yields no fragment (the scope boundary held); it
        never widens scope or fabricates content. ``allowed`` is the task's
        ``allowed_files``, passed as the per-call read boundary so only files
        the task is approved to read can enter the context.
        """
        obs = self.broker.read_file(
            self.run_id, self.task_id, self.attempt, 0, rel, allowed_files=allowed
        )
        if obs.blocked or not obs.ok:
            return None
        content = obs.content
        # Cap a single fragment at a quarter of the budget so one huge file
        # cannot consume the whole context.
        cap = max(1, self.context_budget_chars // 4)
        if len(content) > cap:
            content = content[:cap] + "\n...[truncated]"
        return ContextFragment(
            source_path=rel,
            kind=kind,
            content=content,
            reason=reason,
        )

    def _search_fragment(
        self, rel: str, refs: set[str], *, kind: str
    ) -> ContextFragment | None:
        """Select symbol/import lines from an in-scope file matching ``refs``.

        Only files whose declared symbols/imports intersect the objective's
        referenced names are included, so unrelated files do not leak into the
        context. The read uses ``allowed_files=None`` (the unconstrained read
        sweep the Broker permits for search) but is still contained to the
        workspace root and the approved ``workspace_scope``.
        """
        if not refs:
            return None
        obs = self.broker.read_file(
            self.run_id, self.task_id, self.attempt, 0, rel, allowed_files=None
        )
        if obs.blocked or not obs.ok:
            return None
        lines = obs.content.splitlines()
        matches: list[tuple[int, str, str]] = []
        for i, line in enumerate(lines, start=1):
            name = _symbol_name(line)
            if name and name in refs:
                matches.append((i, line, name))
        if not matches:
            return None
        # Build a compact fragment from the matching lines only.
        cap = max(1, self.context_budget_chars // 4)
        parts: list[str] = []
        for lineno, line, name in matches:
            parts.append(f"L{lineno}: {line}")
            if sum(len(p) for p in parts) >= cap:
                parts.append("...[truncated]")
                break
        content = "\n".join(parts)
        names = sorted({name for _, _, name in matches})
        return ContextFragment(
            source_path=rel,
            kind=kind,
            content=content,
            start_line=matches[0][0],
            end_line=matches[-1][0],
            reason=f"symbols/imports referenced by objective: {', '.join(names)}",
        )

    def _in_scope_python_files(self, exclude: set[str]) -> list[str]:
        """List workspace-relative ``*.py`` files for the symbol search sweep.

        Bounded by the Broker's ``workspace_scope`` (containment to the
        approved directories) and the ``workspace_root``; files already read in
        full (``exclude``) are skipped. Only ``*.py`` files are considered so the
        narrow symbol/import matcher applies; non-Python sources are read only
        via explicit paths.
        """
        root = self.broker.workspace_root
        scope_dirs = self.broker._scope_dirs or [root]
        out: list[str] = []
        for base in scope_dirs:
            if not base.is_dir():
                continue
            for p in sorted(base.rglob("*.py")):
                if not _is_within(p, root):
                    continue
                rel = p.relative_to(root).as_posix()
                if rel in exclude:
                    continue
                out.append(rel)
        return out

    def _dependency_fragment(
        self, state: RunState, dep_id: str
    ) -> ContextFragment | None:
        """Summarize a completed dependency's accepted evidence as a fragment.

        This is a simple dependency output projection: the dependency task's
        accepted evidence refs signal what upstream produced, without reading
        a second authority. If the dependency is not complete, no fragment is
        added (the scheduler would not have selected this task).
        """
        assert state.plan is not None
        dep = next((t for t in state.plan.tasks if t.task_id == dep_id), None)
        if dep is None or not dep.accepted_evidence_refs:
            return None
        refs = ", ".join(dep.accepted_evidence_refs)
        content = (
            f"Dependency '{dep_id}' (title: {dep.title}) completed with accepted "
            f"evidence: {refs}."
        )
        return ContextFragment(
            source_path=f"<dependency:{dep_id}>",
            kind="dependency_output",
            content=content,
            reason=f"completed dependency of {self.task_id}",
        )


# -- helpers ------------------------------------------------------------------


def _find_task(state: RunState, task_id: str) -> ChildTask:
    assert state.plan is not None, "ContextBuilder requires a plan"
    return next(t for t in state.plan.tasks if t.task_id == task_id)


def _acceptance_criteria(task: ChildTask) -> list[str]:
    """Acceptance criteria: verification spec + expected evidence."""
    out: list[str] = []
    if task.verification is not None:
        out.append(
            f"verification: type={task.verification.type.value}"
            + (
                f", expected={task.verification.expected}"
                if task.verification.expected
                else ""
            )
        )
    if task.expected_evidence:
        out.append(f"expected_evidence: {', '.join(task.expected_evidence)}")
    return out


def _constraints(task: ChildTask, state: RunState) -> list[str]:
    """Constraints from the task and the run-level goal/scope."""
    out: list[str] = list(task.constraints)
    out.append(f"goal: {state.goal}")
    return out


def _symbol_refs(text: str) -> set[str]:
    """Extract candidate symbol/import names referenced in ``text``.

    Matches ``word`` tokens that look like identifiers, so an objective like
    "use the add function" surfaces ``add`` for symbol search. Very narrow by
    design: only tokens that could be a Python identifier are kept.
    """
    refs: set[str] = set()
    for tok in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", text):
        if len(tok) >= 2 and tok.lower() not in _STOPWORDS:
            refs.add(tok)
    return refs


def _is_within(child: Path, parent: Path) -> bool:
    """True if ``child`` is ``parent`` or inside it (lexical containment)."""
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _symbol_name(line: str) -> str | None:
    """Return the declared symbol/import name on a source line, or None."""
    m = _SYMBOL_RE.match(line)
    if m:
        return m.group(2)
    m = _IMPORT_RE.match(line)
    if m:
        # from X import Y -> X is group(2); import X -> group(4)
        return m.group(2) or m.group(4)
    return None


# A small stopword set so the objective's prose does not flood symbol search
# with common words. Kept tiny and domain-agnostic on purpose.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "use",
        "using",
        "task",
        "must",
        "should",
        "into",
        "onto",
        "over",
        "under",
        "file",
        "files",
        "function",
        "class",
        "def",
        "import",
        "return",
        "true",
        "false",
        "none",
        "list",
        "dict",
        "set",
        "type",
        "int",
        "str",
        "add",
        "all",
        "any",
        "not",
        "but",
        "are",
        "was",
        "has",
        "have",
        "will",
        "can",
        "may",
        "via",
        "per",
        "out",
        "its",
        "our",
        "you",
        "they",
    }
)


__all__ = ["ContextBuilder"]
