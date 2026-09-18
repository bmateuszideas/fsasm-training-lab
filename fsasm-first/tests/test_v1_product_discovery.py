"""T27 — the standard product worker registers only the target FS-ASM Runtime.

The historical milestone demonstrators (M1--M4) and the ``hello`` example remain
in ``src/workflows/`` as documented Git history, but they MUST NOT be registered
by the product worker's default discovery (``entrypoints.worker.discover_workflows``).
Their F3/F4/F5/F8 safety invariants have been transferred to the v1 boundary
(T04--T14); the activity-name uniqueness safety test
(``tests/test_worker_activity_name_collision.py``) is the successor at the new
boundary and remains in force because the historical modules stay importable.

This test does not require a live Temporal server: it exercises the pure
discovery function and asserts which module names are / are not registered.
"""

from __future__ import annotations

import importlib


def _workflow_module_names(workflow_classes: list[type]) -> set[str]:
    return {cls.__module__ for cls in workflow_classes}


def test_default_discovery_excludes_historical_demonstrators(monkeypatch):
    """Product discovery must not register M1--M4 or hello by default."""
    from entrypoints import worker

    monkeypatch.delenv("FSASM_INCLUDE_HISTORICAL", raising=False)
    discovered = worker.discover_workflows()
    modules = _workflow_module_names(discovered)
    historical = {
        "workflows.fsasm_milestone_one",
        "workflows.fsasm_milestone_two",
        "workflows.fsasm_milestone_three",
        "workflows.fsasm_milestone_four",
        "workflows.hello",
    }
    assert modules.isdisjoint(historical), (
        f"historical demonstrators leaked into product discovery: {modules & historical}"
    )


def test_historical_opt_in_restores_demonstrators(monkeypatch):
    """FSASM_INCLUDE_HISTORICAL=1 opts the legacy modules back in (research)."""
    from entrypoints import worker

    monkeypatch.setenv("FSASM_INCLUDE_HISTORICAL", "1")
    discovered = worker.discover_workflows()
    modules = _workflow_module_names(discovered)
    assert "workflows.fsasm_milestone_four" in modules
    assert "workflows.fsasm_milestone_one" in modules
    assert "workflows.hello" in modules


def test_opt_in_is_not_default(monkeypatch):
    """The opt-in must be a non-default, explicit choice."""
    from entrypoints import worker

    monkeypatch.delenv("FSASM_INCLUDE_HISTORICAL", raising=False)
    default_discovered = worker.discover_workflows()
    monkeypatch.setenv("FSASM_INCLUDE_HISTORICAL", "1")
    opt_in_discovered = worker.discover_workflows()
    assert len(opt_in_discovered) >= len(default_discovered)
    assert len(default_discovered) < len(opt_in_discovered), (
        "opt-in did not add any historical workflows; default and opt-in are identical"
    )


def test_historical_modules_remain_importable():
    """The successor safety test (activity-name uniqueness) needs importable modules.

    T27 keeps the historical demonstrators in Git/documented history; they stay
    importable so ``tests/test_worker_activity_name_collision.py`` (the safety
    successor at the v1 boundary) continues to guard activity-name uniqueness.
    """
    for modname in (
        "workflows.fsasm_milestone_one",
        "workflows.fsasm_milestone_two",
        "workflows.fsasm_milestone_three",
        "workflows.fsasm_milestone_four",
        "workflows.hello",
    ):
        module = importlib.import_module(modname)
        assert module is not None
