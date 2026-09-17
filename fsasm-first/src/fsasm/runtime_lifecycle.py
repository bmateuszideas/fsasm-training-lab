"""FS-ASM runtime lifecycle foundation (T07) — ``start_new`` and ``resume``.

Disjoint contracts (architecture §14):
- ``start_new`` reserves a NEW run (F4: does not overwrite an existing run or
  goal) and writes the initial authoritative snapshot at revision 0 via the
  State Repository. It refuses to target an existing run.
- ``resume`` loads and validates the approved authoritative snapshot; it does
  NOT promise to reconcile real tool effects yet (that is T23). It returns the
  validated state and its revision so a caller can advance it through
  ``apply_event`` → ``commit_snapshot``.

Both paths go through the State Repository's single commit boundary; the
milestone demonstrator's imperative path remains intact (T07 does not remove
it). Technical retry activity does NOT increment ``task_attempt``: only a
``TaskActivated`` domain event (a real execution attempt) does, via
``apply_event``.
"""

from __future__ import annotations

from fsasm.errors import PersistenceError
from fsasm.models import Plan, RunState
from fsasm.state_repository import StateRepository


class RuntimeLifecycle:
    """Foundation for ``start_new`` / ``resume`` over a ``StateRepository``."""

    def __init__(self, repository: StateRepository) -> None:
        self._repository = repository

    @property
    def repository(self) -> StateRepository:
        return self._repository

    def start_new(self, run_id: str, goal: str, plan: Plan) -> RunState:
        """Reserve a new run and write its initial authoritative snapshot.

        F4 / §14: creates a NEW run only. Refuses to overwrite an existing run
        (raises ``RunAlreadyExistsError``) and refuses a plan whose ``run_id``
        does not match ``run_id``. The initial snapshot is written at revision 0
        through the repository, so the v1 single-commit path is the only way the
        first state is established.

        Args:
            run_id: The run identifier to create.
            goal: The run goal.
            plan: The compiled plan (its ``run_id`` must equal ``run_id``).

        Returns:
            The initial committed ``RunState`` (revision 0).

        Raises:
            RunAlreadyExistsError: if the run directory already exists.
            PersistenceError: if the plan run_id mismatches or the init fails.
        """
        if plan.run_id != run_id:
            raise PersistenceError(
                message=(
                    f"start_new: plan run_id '{plan.run_id}' does not match "
                    f"target run_id '{run_id}'"
                ),
                path=None,
                operation="start_new",
            )
        self._repository.create_run(run_id)
        initial = RunState(run_id=run_id, goal=goal, plan=plan)
        return self._repository.init_snapshot(initial)

    def resume(self, run_id: str) -> tuple[RunState, int]:
        """Load and validate the approved authoritative snapshot.

        §14: ``resume`` reads the approved snapshot and validates its coherence;
        it does NOT promise to reconcile real tool effects (that is T23). It
        returns the validated state and its on-disk ``revision`` so the caller
        can advance it via ``apply_event`` → ``commit_snapshot(expected_revision
        = revision)``. A run that was never initialized, or has no authoritative
        snapshot, is rejected (fail closed).

        Returns:
            ``(state, revision)`` — the validated snapshot and its revision.

        Raises:
            PersistenceError: if the run is uninitialized or has no snapshot.
        """
        state = self._repository.load(run_id)
        return state, state.revision
