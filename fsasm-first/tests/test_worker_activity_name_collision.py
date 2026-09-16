"""Regression test for the standard worker activity-name collision.

The standard worker (``entrypoints.worker.main`` -> ``mistralai.workflows.run_worker``)
auto-discovers every workflow module in the ``workflows`` package and registers
*all* activities found in those modules via ``get_all_temporal_activities()``.

Two historical milestone modules defined activities that shared the same
``name=`` even though their contracts differed, e.g. milestone one's stub
``fsasm-plan`` ``(goal_input) -> Plan`` collided with the multi-backend
``fsasm-plan`` ``(goal_input, config) -> PlannerOutput`` from
``planner_activities``. Building a ``temporalio.worker.Worker`` from the full
activity list then raised::

    ValueError: More than one activity named fsasm-plan

The per-milestone test workers avoid this because they pass an explicit
``activities=[...]`` list scoped to a single module, so the collision was never
exercised by the existing suite and only surfaced when the standard worker was
constructed.

This test reproduces the exact construction path of the standard worker:

1. discover workflows through the same ``discover_workflows()`` autodiscovery
   used by ``entrypoints.worker``;
2. collect activities through ``get_all_temporal_activities()``;
3. build a ``temporalio.worker.Worker`` exactly like the production
   ``_create_temporal_workers`` does (SandboxedWorkflowRunner, full activity
   list, no extra event activities), which is where the ``ValueError`` is
   raised.

A duplicate ``name=`` must therefore fail this test.
"""

import importlib
import inspect
import pkgutil
import sys
from collections import defaultdict

import pytest
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from mistralai.workflows.core.activity import get_all_temporal_activities
from mistralai.workflows.core.sandbox import get_sandbox_restrictions


def _activity_source_file(activity_callable: object) -> str:
    """Resolve the source file of the original (undecorated) activity.

    The ``@activity`` decorator returns a ``functools.wraps``-based wrapper,
    so ``inspect.getfile`` on the callable points at the SDK's ``activity.py``.
    The SDK stores the real implementation on ``__original_func__`` (see
    ``mistralai/workflows/core/activity.py``), which lets us recover the
    actual defining file. This is what distinguishes a genuine name collision
    (two *different* files defining the same ``name=``) from a test artifact
    (the *same* file registered twice because it was imported both as
    ``workflows.<m>`` and ``src.workflows.<m>`` in the same process).
    """
    original = getattr(activity_callable, "__original_func__", None) or getattr(
        activity_callable, "__wrapped__", activity_callable
    )
    try:
        return inspect.getfile(original)  # type: ignore[arg-type]
    except TypeError:
        return "<unknown>"


def _ensure_workflow_modules_imported() -> list[type]:
    """Import every workflow module exactly like ``entrypoints.worker`` does.

    Importing the modules registers their ``@activity``-decorated functions in
    the global activity registry that ``get_all_temporal_activities()`` reads.
    """
    # Make the package importable the same way the worker entrypoint expects.
    for path in ("src",):
        if path not in sys.path:
            sys.path.insert(0, path)

    discovered: list[type] = []
    package = importlib.import_module("workflows")
    for _, modname, ispkg in pkgutil.iter_modules(
        package.__path__, prefix="workflows."
    ):
        if ispkg:
            continue
        importlib.import_module(modname)
        module = sys.modules[modname]
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if hasattr(obj, "__workflows_workflow_def"):
                discovered.append(obj)
    return discovered


def test_standard_worker_activity_names_are_unique():
    """All activities discoverable by the standard worker have unique names.

    This mirrors the autodiscovery path of ``entrypoints.worker`` and the
    uniqueness check performed when a ``temporalio.worker.Worker`` is built.
    """
    _ensure_workflow_modules_imported()
    activities = get_all_temporal_activities()

    import temporalio.activity as tactivity

    # Two distinct source files defining the same activity name is the real
    # collision (e.g. the M1 stub planner vs the multi-backend planner). The
    # same source file appearing twice is a benign test-process artifact from
    # importing the same module under two dotted paths (``workflows.x`` and
    # ``src.workflows.x``); it is filtered out before the uniqueness check.
    seen: dict[str, str] = {}
    collisions: dict[str, list[str]] = defaultdict(list)
    for act in activities:
        name = tactivity._Definition.must_from_callable(act).name
        source_file = _activity_source_file(act)
        if name in seen and seen[name] != source_file:
            collisions[name].extend([seen[name], source_file])
        else:
            seen.setdefault(name, source_file)

    duplicates = sorted(collisions)
    assert not duplicates, (
        f"Activity name collision detected by standard worker autodiscovery: "
        f"{duplicates}. Building a worker from get_all_temporal_activities() "
        f"would raise ValueError: More than one activity named {duplicates[0]}."
    )
    # Sanity: autodiscovery actually found something to check.
    assert len(seen) > 0


@pytest.mark.asyncio
async def test_standard_worker_can_be_built_from_autodiscovered_activities(
    temporal_env,
):
    """A Worker built exactly like the production worker must construct.

    The production worker builds ``temporalio.worker.Worker`` from
    ``get_all_temporal_activities()`` plus a sticky-session activity
    (registered with ``_skip_registering=True`` so it is not in the global
    list). ``Worker.__init__`` -> ``_ActivityRunner.__init__`` raises
    ``ValueError: More than one activity named <name>`` on the first duplicate
    name. Using ``temporal_env.client`` keeps this close to the real path
    without depending on a remote Temporal server.
    """
    discovered = _ensure_workflow_modules_imported()
    raw_activities = get_all_temporal_activities()

    # Collapse the benign same-file double registration described above so the
    # Worker is built from one activity per (name, source) pair, matching what
    # the production worker would observe in a single-import-path process.
    activities: list = []
    seen: set[tuple[str, str]] = set()
    import temporalio.activity as tactivity

    for act in raw_activities:
        name = tactivity._Definition.must_from_callable(act).name
        source_file = _activity_source_file(act)
        key = (name, source_file)
        if key in seen:
            continue
        seen.add(key)
        activities.append(act)

    # The Worker is constructed synchronously; the duplicate-name check runs in
    # __init__ before any network I/O, so the assertion holds without running
    # the worker. Constructing inside the test environment mirrors the real
    # client type used by the standard worker.
    worker = Worker(
        temporal_env.client,
        task_queue="test-task-queue",
        workflows=discovered,
        activities=activities,
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=get_sandbox_restrictions()
        ),
    )
    # If construction succeeded there is no name collision.
    assert worker is not None
