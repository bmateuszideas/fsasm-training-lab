"""FS-ASM Runtime v1 (T17) — real Executor Loop.

Realizes the agent loop ``model → Tool Broker → ToolObservation → model``
until an explicit terminal outcome for ONE ``task_attempt``. Within a single
attempt the loop handles multiple ``agent_step`` iterations, each carrying
tool calls and model calls. The Model Gateway (T16) is the single provider-neutral
entry point; the Tool Broker (T11/T12) is the only path to real effects; the
Context Builder (T15) assembles the bounded task-scoped context. The loop never
grants PASS: a ``FinalResponse`` is a request for the Verification Plane, not a
PASS claim — only the Domain Core grants the task transition after the Verifier
inspects the real artifact.

Budgets (:class:`ModelCallBudget` / :class:`BudgetUsage`) are enforced BEFORE the
next effect: a model call or tool call that would exceed any set cap stops the
loop with ``STEP_LIMIT_REACHED`` rather than silently extending the attempt. A
blocked tool (policy rejection before any effect) stops with
``POLICY_BLOCKED``. A transport error (:class:`ModelError`) stops with
``TOOL_ERROR`` and does NOT consume a new merytoryczna attempt (the retry
activity, T18, decides separately). An unparseable model output
(:class:`InvalidResponse`) is treated as a recoverable step error: the loop
re-asks within the step budget, and terminalizes with ``TOOL_ERROR`` if the
model cannot recover before the budget is exhausted (architecture §23, §24;
canonical TODO T17).

The existing M3/M4 :class:`fsasm.executor.ExecutorStub` (the milestone
demonstrator path) is unchanged: this is the parallel v1 agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fsasm.context import ContextBuilder
from fsasm.gateway import ModelGateway
from fsasm.model_types import (
    BudgetUsage,
    EscalationRequest,
    ExecutorOutcomeReason,
    FinalResponse,
    InvalidResponse,
    ModelCallBudget,
    ModelMessage,
    ModelMessageRole,
    ModelRequest,
    ModelUsage,
    ToolCall,
    ToolDeclaration,
)
from fsasm.models import (
    CheckKind,
    ChildTask,
    RunState,
    TaskContext,
    ToolObservation,
    ToolOperationKind,
)
from fsasm.tool_broker import ToolBroker


# -- declarations of the tools the model may call ----------------------------

_READ_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Workspace-relative file path."},
    },
    "required": ["path"],
}
_APPLY_PATCH_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Workspace-relative file path."},
        "new_content": {"type": "string", "description": "Full new file content."},
    },
    "required": ["path", "new_content"],
}
_SEARCH_CODE_PARAMS = {
    "type": "object",
    "properties": {
        "needle": {"type": "string", "description": "Regex to search for."},
        "pattern": {"type": "string", "description": "Glob file pattern."},
    },
    "required": ["needle"],
}
_LIST_FILES_PARAMS = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Glob file pattern."},
    },
    "required": [],
}
_RUN_CHECKS_PARAMS = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "description": "Check kind: pytest|pytest_file|ruff_check|custom.",
        },
        "args": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind"],
}

_DEFAULT_TOOLS = [
    ToolDeclaration(
        name="read_file",
        description="Read a file within the task's allowed scope.",
        parameters=_READ_FILE_PARAMS,
    ),
    ToolDeclaration(
        name="apply_patch",
        description="Overwrite a file within the task's allowed scope.",
        parameters=_APPLY_PATCH_PARAMS,
    ),
    ToolDeclaration(
        name="search_code",
        description="Search files in scope for a regex.",
        parameters=_SEARCH_CODE_PARAMS,
    ),
    ToolDeclaration(
        name="list_files",
        description="List files in the workspace.",
        parameters=_LIST_FILES_PARAMS,
    ),
    ToolDeclaration(
        name="run_checks",
        description="Run an allowlisted check in the workspace.",
        parameters=_RUN_CHECKS_PARAMS,
    ),
]

# Map a task's allowed_tools to the declarations offered to the model. A tool
# not listed in the task's allowed_tools is never declared, so the model cannot
# call it. run_checks is offered only when the task allows it.
_TOOL_DECL_BY_NAME = {t.name: t for t in _DEFAULT_TOOLS}


@dataclass
class ExecutorStepRecord:
    """One recorded agent step within an attempt (provenance/audit only)."""

    step: int
    model_call: bool
    tool_call: bool
    response_kind: str
    observation: ToolObservation | None = None
    note: str = ""


@dataclass
class ExecutorAttemptOutcome:
    """The terminal outcome of one Executor attempt.

    Carries the normalized terminal :class:`ExecutorOutcomeReason`, the final
    model response (for ``COMPLETED`` / ``ESCALATION_REQUESTED``), the live
    budget usage counters, the ordered observations the loop produced, and the
    recorded agent steps. This is a transient transport result, NOT
    authoritative state: it holds no transition/PASS power and is not
    serialized into the snapshot. The driver (T18+ / workflow) feeds the
    ``COMPLETED`` outcome to the Verification Plane; only the Domain Core
    grants the task transition.
    """

    run_id: str
    task_id: str
    attempt: int
    reason: ExecutorOutcomeReason
    usage: BudgetUsage
    observations: list[ToolObservation] = field(default_factory=list)
    steps: list[ExecutorStepRecord] = field(default_factory=list)
    final_content: str = ""
    escalation: EscalationRequest | None = None
    backend: str = ""


@dataclass
class ExecutorLoop:
    """The v1 agent loop: model → Tool Broker → observation → model → … → terminal.

    One :meth:`run` call drives ONE ``task_attempt`` to an explicit terminal
    outcome. The loop builds a :class:`TaskContext` via the Context Builder,
    constructs a normalized :class:`ModelRequest`, calls the Model Gateway,
    pattern-matches the normalized response, executes tool calls through the
    Tool Broker (the only path to real effects), feeds observations back as
    TOOL-role messages, and enforces budgets before the next effect. It never
    grants PASS: a ``FinalResponse`` is a verification request, not a PASS
    claim. The loop is deterministic given a deterministic backend and broker.
    """

    gateway: ModelGateway
    broker: ToolBroker
    context_builder: ContextBuilder
    budget: ModelCallBudget
    # Max recoverable InvalidResponse re-asks before terminalizing with
    # TOOL_ERROR (independent of the step budget; defaults small so a stuck
    # model does not spin). Each re-ask still consumes a model_call/agent_step.
    max_invalid_reasks: int = 2

    def run(
        self,
        state: RunState,
        *,
        run_id: str,
        task_id: str,
        attempt: int,
        prior_observations: list[str] | None = None,
        prior_verification: str = "",
    ) -> ExecutorAttemptOutcome:
        """Drive one ``task_attempt`` to an explicit terminal outcome.

        Args:
            state: The authoritative RunState (read-only; the loop never
                mutates it — only the Domain Core commits transitions).
            run_id: The run this attempt belongs to.
            task_id: The task this attempt belongs to.
            attempt: The 1-indexed attempt number.
            prior_observations: Prior tool observations on previous attempts
                (retry feedback, T18).
            prior_verification: Summary of the prior attempt's verification
                failure (retry feedback, T18).

        Returns:
            The terminal :class:`ExecutorAttemptOutcome` for this attempt.
        """
        task = _find_task(state, task_id)
        ctx = self.context_builder.build(
            state,
            prior_observations=prior_observations,
            prior_verification=prior_verification,
        )
        # Tools the model may call: only those the task allows. The broker
        # re-validates scope per call regardless, but the declaration is the
        # first boundary (the model never sees an undeclared tool).
        tools = [
            _TOOL_DECL_BY_NAME[name]
            for name in task.allowed_tools
            if name in _TOOL_DECL_BY_NAME
        ]
        # The set of tool names the model is permitted to call for this task.
        # A name not in allowed_tools is never declared AND never dispatched: a
        # model that emits an undeclared tool anyway is policy-blocked (no effect).
        allowed_tool_names = {
            name for name in task.allowed_tools if name in _TOOL_DECL_BY_NAME
        }
        usage = BudgetUsage()
        observations: list[ToolObservation] = []
        steps: list[ExecutorStepRecord] = []
        invalid_streak = 0
        messages = _initial_messages(ctx)
        step = 0
        backend_name = ""

        while True:
            step += 1
            # Enforce budgets BEFORE the next model call (architecture §24:
            # limits enforced before the next effect).
            if usage.would_exceed(self.budget):
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=False,
                        tool_call=False,
                        response_kind="budget_exhausted",
                        note="model_call budget exceeded before next call",
                    )
                )
                return self._terminal(
                    run_id,
                    task_id,
                    attempt,
                    ExecutorOutcomeReason.STEP_LIMIT_REACHED,
                    usage,
                    observations,
                    steps,
                    backend=backend_name,
                )
            if self._agent_step_exhausted(usage):
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=False,
                        tool_call=False,
                        response_kind="step_limit",
                        note="agent_step budget exceeded",
                    )
                )
                return self._terminal(
                    run_id,
                    task_id,
                    attempt,
                    ExecutorOutcomeReason.STEP_LIMIT_REACHED,
                    usage,
                    observations,
                    steps,
                    backend=backend_name,
                )

            usage.model_calls += 1
            usage.agent_steps += 1
            request = ModelRequest(
                run_id=run_id,
                task_id=task_id,
                attempt=attempt,
                step=step,
                messages=list(messages),
                tools=tools,
            )
            result = self.gateway.generate(request)
            backend_name = result.backend or backend_name
            self._accumulate_usage(usage, result.usage)

            # A transport error: terminal TOOL_ERROR. It does NOT consume a
            # new merytoryczna attempt (T18 retry activity decides separately).
            if result.error is not None:
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=True,
                        tool_call=False,
                        response_kind=f"model_error:{result.error.kind.value}",
                        note=str(result.error),
                    )
                )
                return self._terminal(
                    run_id,
                    task_id,
                    attempt,
                    ExecutorOutcomeReason.TOOL_ERROR,
                    usage,
                    observations,
                    steps,
                    backend=backend_name,
                )

            response = result.response

            # FinalResponse: terminal COMPLETED (verification request, NOT PASS).
            if isinstance(response, FinalResponse):
                messages.append(
                    ModelMessage(
                        role=ModelMessageRole.ASSISTANT,
                        content=f"[VERIFY] {response.content}",
                    )
                )
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=True,
                        tool_call=False,
                        response_kind="final",
                    )
                )
                return self._terminal(
                    run_id,
                    task_id,
                    attempt,
                    ExecutorOutcomeReason.COMPLETED,
                    usage,
                    observations,
                    steps,
                    final_content=response.content,
                    backend=backend_name,
                )

            # EscalationRequest: terminal ESCALATION_REQUESTED.
            if isinstance(response, EscalationRequest):
                messages.append(
                    ModelMessage(
                        role=ModelMessageRole.ASSISTANT,
                        content=f"[ESCALATE {response.kind}] {response.reason}",
                    )
                )
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=True,
                        tool_call=False,
                        response_kind=f"escalation:{response.kind}",
                    )
                )
                return self._terminal(
                    run_id,
                    task_id,
                    attempt,
                    ExecutorOutcomeReason.ESCALATION_REQUESTED,
                    usage,
                    observations,
                    steps,
                    escalation=response,
                    backend=backend_name,
                )

            # InvalidResponse: recoverable step error. Re-ask within the
            # invalid-reask budget; terminalize with TOOL_ERROR if unrecoverable.
            if isinstance(response, InvalidResponse):
                invalid_streak += 1
                messages.append(
                    ModelMessage(
                        role=ModelMessageRole.ASSISTANT,
                        content=response.raw or "",
                    )
                )
                messages.append(
                    ModelMessage(
                        role=ModelMessageRole.USER,
                        content=(
                            "Your previous output was unparseable "
                            f"({response.reason}). Emit a valid tool call JSON, "
                            "[VERIFY] <rationale>, or [ESCALATE ...]."
                        ),
                    )
                )
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=True,
                        tool_call=False,
                        response_kind="invalid",
                        note=response.reason,
                    )
                )
                if invalid_streak > self.max_invalid_reasks:
                    return self._terminal(
                        run_id,
                        task_id,
                        attempt,
                        ExecutorOutcomeReason.TOOL_ERROR,
                        usage,
                        observations,
                        steps,
                        backend=backend_name,
                    )
                continue

            # ToolCall: enforce the tool-call budget BEFORE the effect. Only the
            # tool-call cap is checked here; the agent_step cap is enforced at
            # the top of the loop (it counts model-call iterations, and this
            # step's model call already incremented agent_steps).
            assert isinstance(response, ToolCall)
            if self._tool_calls_exhausted(usage):
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=True,
                        tool_call=False,
                        response_kind="tool_budget_exhausted",
                        note="tool_call budget exceeded before effect",
                    )
                )
                return self._terminal(
                    run_id,
                    task_id,
                    attempt,
                    ExecutorOutcomeReason.STEP_LIMIT_REACHED,
                    usage,
                    observations,
                    steps,
                    backend=backend_name,
                )
            # Defense in depth: a tool name not in the task's allowed_tools is
            # policy-blocked before any effect, even if the model emits it.
            if response.name not in allowed_tool_names:
                obs = ToolObservation(
                    operation_id=self.broker._op_id(run_id, task_id, attempt, step),
                    kind=ToolOperationKind.LIST_FILES,
                    ok=False,
                    blocked=True,
                    reason=f"tool not allowed for task: {response.name!r}",
                )
                observations.append(obs)
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=True,
                        tool_call=True,
                        response_kind="tool_blocked",
                        observation=obs,
                        note=obs.reason,
                    )
                )
                return self._terminal(
                    run_id,
                    task_id,
                    attempt,
                    ExecutorOutcomeReason.POLICY_BLOCKED,
                    usage,
                    observations,
                    steps,
                    backend=backend_name,
                )
            usage.tool_calls += 1
            messages.append(
                ModelMessage(
                    role=ModelMessageRole.ASSISTANT,
                    content=response.model_dump_json(),
                    tool_call_id=response.tool_call_id,
                )
            )
            obs = self._dispatch_tool(
                response, run_id, task_id, attempt, step, task.allowed_files
            )
            observations.append(obs)
            # A policy block (broker rejected before any effect) is terminal:
            # the loop does not silently continue past a rejected effect.
            if obs.blocked:
                steps.append(
                    ExecutorStepRecord(
                        step=step,
                        model_call=True,
                        tool_call=True,
                        response_kind="tool_blocked",
                        observation=obs,
                        note=obs.reason,
                    )
                )
                return self._terminal(
                    run_id,
                    task_id,
                    attempt,
                    ExecutorOutcomeReason.POLICY_BLOCKED,
                    usage,
                    observations,
                    steps,
                    backend=backend_name,
                )
            # Feed the observation back as a TOOL-role message and continue.
            messages.append(
                ModelMessage(
                    role=ModelMessageRole.TOOL,
                    content=_observation_summary(obs),
                    tool_result_for=response.tool_call_id,
                )
            )
            steps.append(
                ExecutorStepRecord(
                    step=step,
                    model_call=True,
                    tool_call=True,
                    response_kind=f"tool:{obs.kind.value}",
                    observation=obs,
                )
            )

    # -- internals --------------------------------------------------------

    def _dispatch_tool(
        self,
        call: ToolCall,
        run_id: str,
        task_id: str,
        attempt: int,
        step: int,
        allowed_files: list[str],
    ) -> ToolObservation:
        """Execute one tool call through the Broker (the only path to effects)."""
        name = call.name
        args = call.arguments
        if name == "read_file":
            path = _str_arg(args, "path")
            return self.broker.read_file(
                run_id, task_id, attempt, step, path, allowed_files=allowed_files
            )
        if name == "apply_patch":
            path = _str_arg(args, "path")
            new_content = _str_arg(args, "new_content")
            return self.broker.apply_patch(
                run_id,
                task_id,
                attempt,
                step,
                path,
                new_content,
                allowed_files=allowed_files,
            )
        if name == "search_code":
            needle = _str_arg(args, "needle")
            pattern = _str_arg(args, "pattern", default="*")
            return self.broker.search_code(
                run_id,
                task_id,
                attempt,
                step,
                needle,
                allowed_files=allowed_files,
                pattern=pattern,
            )
        if name == "list_files":
            pattern = _str_arg(args, "pattern", default="*")
            return self.broker.list_files(
                run_id,
                task_id,
                attempt,
                step,
                pattern=pattern,
                allowed_files=allowed_files,
            )
        if name == "run_checks":
            kind_raw = _str_arg(args, "kind")
            try:
                kind = CheckKind(kind_raw)
            except ValueError:
                return ToolObservation(
                    operation_id=self.broker._op_id(run_id, task_id, attempt, step),
                    kind=ToolOperationKind.RUN_CHECKS,
                    ok=False,
                    blocked=True,
                    reason=f"unknown check kind: {kind_raw!r}",
                )
            raw_args = args.get("args")
            check_args = (
                [str(a) for a in raw_args] if isinstance(raw_args, list) else []
            )
            return self.broker.run_checks(
                run_id, task_id, attempt, step, kind, check_args
            )
        # Undeclared/unknown tool name: a policy block (no effect).
        return ToolObservation(
            operation_id=self.broker._op_id(run_id, task_id, attempt, step),
            kind=ToolOperationKind.LIST_FILES,
            ok=False,
            blocked=True,
            reason=f"unknown tool: {name!r}",
        )

    def _agent_step_exhausted(self, usage: BudgetUsage) -> bool:
        cap = self.budget.max_agent_steps
        return cap is not None and usage.agent_steps >= cap

    def _tool_calls_exhausted(self, usage: BudgetUsage) -> bool:
        """True if the next tool call would exceed the tool-call cap.

        Only ``max_tool_calls`` is checked here: ``max_agent_steps`` counts
        model-call iterations and is enforced at the top of the loop (this
        step's model call already incremented ``agent_steps``).
        """
        cap = self.budget.max_tool_calls
        return cap is not None and usage.tool_calls >= cap

    def _accumulate_usage(self, usage: BudgetUsage, reported: ModelUsage) -> None:
        if reported.total_tokens is not None:
            usage.tokens += reported.total_tokens
        elif (
            reported.prompt_tokens is not None or reported.completion_tokens is not None
        ):
            usage.tokens += (reported.prompt_tokens or 0) + (
                reported.completion_tokens or 0
            )
        if reported.cost is not None:
            usage.cost += reported.cost
        if reported.duration_ms is not None:
            usage.elapsed_ms += reported.duration_ms

    def _terminal(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        reason: ExecutorOutcomeReason,
        usage: BudgetUsage,
        observations: list[ToolObservation],
        steps: list[ExecutorStepRecord],
        *,
        final_content: str = "",
        escalation: EscalationRequest | None = None,
        backend: str = "",
    ) -> ExecutorAttemptOutcome:
        return ExecutorAttemptOutcome(
            run_id=run_id,
            task_id=task_id,
            attempt=attempt,
            reason=reason,
            usage=usage,
            observations=observations,
            steps=steps,
            final_content=final_content,
            escalation=escalation,
            backend=backend,
        )


def _initial_messages(ctx: TaskContext) -> list[ModelMessage]:
    """Build the opening conversation from a bounded TaskContext."""
    messages: list[ModelMessage] = []
    system = _system_prompt(ctx)
    messages.append(ModelMessage(role=ModelMessageRole.SYSTEM, content=system))
    user_parts = [f"Objective: {ctx.objective}"]
    if ctx.acceptance_criteria:
        user_parts.append(
            "Acceptance criteria:\n- " + "\n- ".join(ctx.acceptance_criteria)
        )
    if ctx.constraints:
        user_parts.append("Constraints:\n- " + "\n- ".join(ctx.constraints))
    if ctx.allowed_files:
        user_parts.append("Allowed files: " + ", ".join(ctx.allowed_files))
    if ctx.allowed_tools:
        user_parts.append("Allowed tools: " + ", ".join(ctx.allowed_tools))
    if ctx.fragments:
        frag_lines = []
        for f in ctx.fragments:
            frag_lines.append(
                f"--- {f.source_path} ({f.kind}) [{f.reason}] ---\n{f.content}"
            )
        user_parts.append("Relevant context:\n" + "\n".join(frag_lines))
    if ctx.prior_observations:
        user_parts.append(
            "Prior observations:\n- " + "\n- ".join(ctx.prior_observations)
        )
    if ctx.prior_verification:
        user_parts.append(f"Prior verification failure: {ctx.prior_verification}")
    user_parts.append(
        "Use the declared tools to make real changes, then end with "
        "[VERIFY] <rationale> to request verification, or [ESCALATE ...] "
        "to request expert help. Do not claim PASS yourself."
    )
    messages.append(
        ModelMessage(role=ModelMessageRole.USER, content="\n\n".join(user_parts))
    )
    return messages


def _system_prompt(ctx: TaskContext) -> str:
    return (
        "You are the FS-ASM Executor for one task attempt. You operate only "
        "through the declared tools within the approved scope. Make real "
        "changes via the tools; do not declare success without a real effect. "
        "When you believe the task is done, emit [VERIFY] <rationale> to "
        "request independent verification. You never grant PASS. To request "
        "expert help, emit [ESCALATE consultation|handover] <reason>."
    )


def _observation_summary(obs: ToolObservation) -> str:
    """Compact, honest summary of a tool observation for the model turn."""
    if obs.blocked:
        return f"BLOCKED ({obs.kind.value}): {obs.reason}"
    if not obs.ok:
        return f"ERROR ({obs.kind.value}): {obs.reason}"
    parts = [f"OK ({obs.kind.value})"]
    if obs.artifact_path:
        parts.append(f"path={obs.artifact_path}")
    if obs.content:
        parts.append(obs.content)
    if obs.diff:
        parts.append("diff:\n" + obs.diff)
    if obs.matches:
        parts.append("matches:\n" + "\n".join(obs.matches))
    if obs.exit_code is not None:
        parts.append(f"exit_code={obs.exit_code}")
        if obs.stdout:
            parts.append("stdout:\n" + obs.stdout)
        if obs.stderr:
            parts.append("stderr:\n" + obs.stderr)
        if obs.timed_out:
            parts.append("TIMED_OUT")
    return "\n".join(parts)


def _str_arg(args: dict, key: str, default: str = "") -> str:
    val = args.get(key, default)
    if val is None:
        return default
    return str(val)


def _find_task(state: RunState, task_id: str) -> ChildTask:
    """Resolve the active ChildTask from the authoritative plan."""
    assert state.plan is not None, "ExecutorLoop requires a plan"
    return next(t for t in state.plan.tasks if t.task_id == task_id)


__all__ = [
    "ExecutorAttemptOutcome",
    "ExecutorLoop",
    "ExecutorStepRecord",
]
