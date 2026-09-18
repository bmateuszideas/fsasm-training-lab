"""Discover the target FS-ASM Runtime product workflow and start a worker.

T27: the standard product worker registers ONLY the target FS-ASM Runtime
v1 product path. The historical milestone demonstrators (M1--M4) and the
``hello`` example live in ``src/workflows/`` for Git/documented history, but
they are excluded from default discovery so they no longer influence the
product worker, active contracts, or activity-name registration. Their F3/F4/
F5/F8 safety invariants have been transferred to the v1 boundary (T04--T14).

To inspect or run a historical demonstrator (research only), set
``FSASM_INCLUDE_HISTORICAL=1``: discovery then also returns the legacy
modules. This opt-in is NOT the product path.
"""
# ruff: noqa: E402

import asyncio
import importlib
import inspect
import os
import pkgutil
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

import mistralai.workflows as mistralai_workflows
from mistralai.workflows.core.definition.workflow_definition import (
    get_workflow_definition,
)

# Historical milestone demonstrators + the hello example. Kept in
# ``src/workflows/`` as documented Git history; excluded from the product
# worker's default discovery (T27). Their activity-name uniqueness is still
# guarded by ``tests/test_worker_activity_name_collision.py`` (the successor
# safety test at the v1 boundary).
_HISTORICAL_MODULES = {
    "workflows.fsasm_milestone_one",
    "workflows.fsasm_milestone_two",
    "workflows.fsasm_milestone_three",
    "workflows.fsasm_milestone_four",
    "workflows.hello",
}


def discover_workflows() -> list[type]:
    """Return the product workflows to register on the standard worker.

    Default (product) discovery excludes the historical milestone demonstrators
    and the ``hello`` example so the product worker registers only the target
    FS-ASM Runtime. Setting ``FSASM_INCLUDE_HISTORICAL=1`` opts the legacy
    modules back in for research; that is not the product path.
    """
    include_historical = os.getenv("FSASM_INCLUDE_HISTORICAL", "") == "1"
    discovered = []
    package = importlib.import_module("workflows")

    for _, modname, ispkg in pkgutil.iter_modules(
        package.__path__, prefix="workflows."
    ):
        if ispkg:
            continue
        if modname in _HISTORICAL_MODULES and not include_historical:
            continue
        module = importlib.import_module(modname)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if hasattr(obj, "__workflows_workflow_def"):
                discovered.append(obj)

    return discovered


async def main() -> None:
    discovered = discover_workflows()

    if not discovered:
        print(
            "No product workflows discovered. The target FS-ASM Runtime v1 "
            "workflow is not registered yet (laptop integration). Set "
            "FSASM_INCLUDE_HISTORICAL=1 to inspect legacy demonstrators."
        )
        sys.exit(1)

    names = [get_workflow_definition(wf).name for wf in discovered]
    print(f"Discovered {len(discovered)} workflow(s): {', '.join(names)}")

    await mistralai_workflows.run_worker(discovered)


if __name__ == "__main__":
    asyncio.run(main())
