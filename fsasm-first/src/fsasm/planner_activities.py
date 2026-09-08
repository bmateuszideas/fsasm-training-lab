"""FS-ASM Planner Activities - activity-based planning with Mistral and Stub backends."""

import hashlib

import mistralai.workflows as workflows
from mistralai.workflows import activity
from mistralai.workflows.plugins.mistralai import (
    ChatCompletionRequest,
    ResponseFormat,
    UserMessage,
    mistralai_chat_complete,
)

# Import fsasm modules - these are used in activities, not workflow code
with workflows.workflow.unsafe.imports_passed_through():
    from fsasm.errors import ConfigurationError
    from fsasm.models import (
        GoalInput,
        PlannerBackend,
        PlannerConfig,
        PlannerMetadata,
        PlannerOutput,
        PlannerProposal,
    )
    from fsasm.planner import assemble_plan, PlannerStub


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

# Prompt template for Mistral planner - uses proposal-local sequence numbers for dependencies
MISTRAL_PLANNER_TEMPLATE_V1 = """Jesteś FS-ASM Plannerem. Twoim zadaniem jest stworzenie planu realizacji celu.

## ZASADY:
1. Plan MUST zawierć dokładnie 3 zadania (TaskProposal).
2. Każde zadanie musi mieć: title, description, dependencies, verification_type, verification_expected.
3. Zadania muszą być atomowe, jednoznaczne i konkretne.
4. Dependencies używają numerów sekwencji (1, 2, 3) - NIE używaj TASK-001 itp.
5. Format odpowiedzi: JSON z kluczem "tasks" (lista 3 TaskProposal).

## CELE:
{goal}

## FORMAT ODPOWIEDZI (STRICT JSON):
{{
  "tasks": [
    {{
      "title": "string",
      "description": "string",
      "dependencies": [1],
      "verification_type": "schema" | "exists" | "count" | "custom",
      "verification_expected": "string",
      "constraints": ["string"],
      "allowed_files": ["string"],
      "expected_evidence": ["string"]
    }}
  ]
}}

## PRZYKŁAD:
{{
  "tasks": [
    {{
      "title": "Inspect and prepare input",
      "description": "Inspect the goal and prepare execution context.",
      "dependencies": [],
      "verification_type": "schema",
      "verification_expected": "Input inspection complete",
      "constraints": ["Must not modify any files"],
      "allowed_files": [],
      "expected_evidence": ["input_report"]
    }},
    {{
      "title": "Perform core action",
      "description": "Perform the main action to achieve the goal.",
      "dependencies": [1],
      "verification_type": "exists",
      "verification_expected": "Action completed successfully",
      "constraints": ["Only modify allowed files"],
      "allowed_files": ["*.py"],
      "expected_evidence": ["output_files"]
    }},
    {{
      "title": "Verify and finalize",
      "description": "Verify goal achievement and finalize.",
      "dependencies": [2],
      "verification_type": "custom",
      "verification_expected": "Goal verified and evidence collected",
      "constraints": ["Must not modify any files"],
      "allowed_files": [],
      "expected_evidence": ["verification_report"]
    }}
  ]
}}"""


# Pre-computed template hash for v1.0
MISTRAL_PLANNER_TEMPLATE_V1_HASH = hashlib.sha256(
    MISTRAL_PLANNER_TEMPLATE_V1.encode("utf-8")
).hexdigest()


# =============================================================================
# PROMPT TEMPLATE REGISTRY
# =============================================================================

PROMPT_TEMPLATES: dict[str, tuple[str, str]] = {
    "v1.0": (MISTRAL_PLANNER_TEMPLATE_V1, MISTRAL_PLANNER_TEMPLATE_V1_HASH),
}


def get_planner_prompt_template(version: str) -> tuple[str, str]:
    """
    Get prompt template and its pre-computed hash by version.

    Args:
        version: The prompt version (e.g., "v1.0")

    Returns:
        Tuple of (template, template_hash)

    Raises:
        ValueError: If version is not found.
    """
    if version not in PROMPT_TEMPLATES:
        raise ValueError(f"Unknown prompt version: {version}")
    return PROMPT_TEMPLATES[version]


# =============================================================================
# ACTIVITIES
# =============================================================================


@activity(
    name="fsasm-stub-plan",
    retry_policy_max_attempts=1,
)
async def plan_with_stub(
    goal_input: GoalInput,
    config: PlannerConfig,
) -> PlannerOutput:
    """
    Plan using the deterministic stub planner.

    This is an activity because it could later call an LLM.
    For now, it uses the deterministic PlannerStub.

    Args:
        goal_input: The GoalInput with goal and optional run_id.
        config: The PlannerConfig with backend and other settings.

    Returns:
        PlannerOutput with proposal, assembled plan, and stub metadata.

    Raises:
        ConfigurationError: If backend is not STUB.
    """
    if config.backend != PlannerBackend.STUB:
        raise ConfigurationError(
            message=f"plan_with_stub wymaga backend='stub', otrzymano '{config.backend}'",
            backend=config.backend.value,
        )

    planner = PlannerStub()
    proposal = planner.create_proposal(goal_input)
    plan = assemble_plan(goal_input, proposal)

    run_id = plan.run_id

    # Compute hashes for stub (deterministic)
    template = "stub planner template v1"
    template_hash = PlannerMetadata.compute_template_hash(template)
    rendered_prompt = f"stub planner for goal: {goal_input.goal}"
    rendered_hash = PlannerMetadata.compute_rendered_hash(rendered_prompt)

    metadata = PlannerMetadata(
        run_id=run_id,
        provider="stub",
        requested_model="stub-planner",
        resolved_model="stub-planner",
        model_version=None,
        prompt_version=config.prompt_version,
        template_hash=template_hash,
        rendered_hash=rendered_hash,
        model_call_count=0,  # Stub makes 0 model API calls
        planner_invocation_count=1,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        provider_request_id=None,
    )

    return PlannerOutput(
        proposal=proposal,
        plan=plan,
        metadata=metadata,
    )


@activity(
    name="fsasm-mistral-plan",
    retry_policy_max_attempts=1,
)
async def plan_with_mistral(
    goal_input: GoalInput,
    config: PlannerConfig,
) -> PlannerOutput:
    """
    Plan using Mistral API with structured output.

    Makes EXACTLY ONE model call per planning operation.
    Both structured proposal and token usage come from the same response.

    Args:
        goal_input: The GoalInput with goal and optional run_id.
        config: The PlannerConfig with backend='mistral' and model_name.

    Returns:
        PlannerOutput with proposal, assembled plan, and Mistral metadata.

    Raises:
        ConfigurationError: If backend is not MISTRAL or model_name is missing.
    """
    if config.backend != PlannerBackend.MISTRAL:
        raise ConfigurationError(
            message=f"plan_with_mistral wymaga backend='mistral', otrzymano '{config.backend}'",
            backend=config.backend.value,
        )

    if not config.model_name:
        raise ConfigurationError(
            message="plan_with_mistral wymaga podania model_name",
            backend="mistral",
            missing_field="model_name",
        )

    # Get prompt template and pre-computed hash
    template, template_hash = get_planner_prompt_template(config.prompt_version)

    # Render prompt with goal
    rendered_prompt = template.format(goal=goal_input.goal)
    rendered_hash = PlannerMetadata.compute_rendered_hash(rendered_prompt)

    # Build request for structured output
    request = ChatCompletionRequest(
        model=config.model_name,
        messages=[UserMessage(content=rendered_prompt)],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        response_format=ResponseFormat(type="json_object"),  # Ensures JSON object mode
        # Note: response_format ensures JSON output, but schema validation happens below
        # via json.loads(...) -> PlannerProposal(...) - single model call only.
    )

    # Single model call - get both structured output AND usage from same response
    # We use mistralai_chat_complete to get the full response with usage
    from mistralai.client.models.chatcompletionresponse import ChatCompletionResponse

    response: ChatCompletionResponse = await mistralai_chat_complete(request)

    # Parse the structured output from the response
    # The response content is JSON, parse it to PlannerProposal
    import json

    # Get the message content safely
    message = response.choices[0].message
    response_content = message.content if message else ""

    # response_content can be str or list of chunks, handle both
    if isinstance(response_content, str):
        content_str = response_content
    else:
        # Join chunks if it's a list
        content_str = (
            "".join(str(chunk) for chunk in response_content)
            if response_content
            else ""
        )

    response_data = json.loads(content_str)
    proposal = PlannerProposal(**response_data)

    # Assemble plan using shared assembler
    plan = assemble_plan(goal_input, proposal)
    run_id = plan.run_id

    # Extract token usage from the same response
    usage = response.usage

    metadata = PlannerMetadata(
        run_id=run_id,
        provider="mistral",
        requested_model=config.model_name,
        resolved_model=response.model,
        model_version=config.model_version,
        prompt_version=config.prompt_version,
        template_hash=template_hash,
        rendered_hash=rendered_hash,
        model_call_count=1,  # Exactly one model call
        planner_invocation_count=1,
        input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        total_tokens=usage.total_tokens if usage else None,
        provider_request_id=response.id,
    )

    return PlannerOutput(
        proposal=proposal,
        plan=plan,
        metadata=metadata,
    )


@activity(
    name="fsasm-plan",
    retry_policy_max_attempts=1,
)
async def plan_activity(
    goal_input: GoalInput,
    config: PlannerConfig,
) -> PlannerOutput:
    """
    Main planning activity - delegates to appropriate backend.

    Args:
        goal_input: The GoalInput with goal and optional run_id.
        config: The PlannerConfig specifying which backend to use.

    Returns:
        PlannerOutput from the selected backend.

    Raises:
        ConfigurationError: If backend is invalid or required config is missing.
    """
    if config.backend == PlannerBackend.STUB:
        return await plan_with_stub(goal_input, config)
    elif config.backend == PlannerBackend.MISTRAL:
        return await plan_with_mistral(goal_input, config)
    else:
        raise ConfigurationError(
            message=f"Nieznany backend: {config.backend}",
            backend=config.backend.value,
        )
