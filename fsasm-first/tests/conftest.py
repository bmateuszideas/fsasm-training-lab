"""Pytest configuration and fixtures for FS-ASM workflow tests."""

# Import Mistral Workflows testing fixtures
from mistralai.workflows.testing.fixtures import (
    clear_dependency_cache,  # noqa: F401
    event_loop,  # noqa: F401
    mock_upsert_search_attributes,  # noqa: F401
    setup_test_config,  # noqa: F401
    temporal_env,  # noqa: F401
)


import pytest


def _build_decision_signal(
    run_id: str,
    task_id: str,
    attempt: int,
    action,
    reason: str = "",
    gate_id: str | None = None,
    decision_id: str | None = None,
):
    """Build a complete-ID HumanDecisionSignal for the open gate of ``attempt``.

    T03 / policy 1 requires run_id, gate_id and decision_id at the runtime
    boundary. Tests that exercise the ACCEPT path must send full IDs; the gate
    id is deterministic from run_id/task_id/attempt. ``gate_id``/``decision_id``
    override the derived values when a test wants a stale/future/wrong gate.
    """
    from src.workflows.fsasm_milestone_four import (
        HumanDecisionSignal,
        _decision_id,
        _gate_id,
    )

    g = gate_id if gate_id is not None else _gate_id(run_id, task_id, attempt)
    d = (
        decision_id
        if decision_id is not None
        else _decision_id(run_id, task_id, g, action)
    )
    return HumanDecisionSignal(
        run_id=run_id,
        task_id=task_id,
        action=action,
        reason=reason,
        gate_id=g,
        decision_id=d,
    )


@pytest.fixture
def full_decision_signal():
    """Return a builder for complete-ID HumanDecisionSignal payloads (T03).

    The runtime boundary now requires run_id, gate_id and decision_id; legacy
    minimal payloads are rejected as ``incomplete_payload``. Tests that drive
    the ACCEPT path (or a complete-but-wrong rejection path) call this builder
    with the run_id, task_id, attempt and action of the targeted gate.
    """
    return _build_decision_signal
