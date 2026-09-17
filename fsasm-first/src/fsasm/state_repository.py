"""FS-ASM State Repository (T06) — revision + one atomic commit.

The State Repository is the single commit boundary over the authoritative
``state.json`` snapshot. It composes the existing ``RuntimePersistence`` (which
keeps the F3 authoritative-snapshot, F4 run-creation and F5 path-safety
boundaries unchanged for the milestone demonstrator) and adds the v1 contract:

- ``load(run_id)`` reads and reconstructs the authoritative snapshot.
- ``commit_snapshot(run_id, expected_revision, next_state)`` rejects a stale
  ``expected_revision`` (optimistic concurrency), rejects a mismatched
  ``run_id``, increments ``revision`` exactly once on a successful commit, and
  writes the derived ``plan.json`` projection *after* the authoritative snapshot.
- A projection failure cannot roll back the authoritative snapshot and cannot
  yield a false PASS: the authority is committed first and is the only source
  of truth; the projection is rebuildable from it.

This module does NOT replace ``RuntimePersistence``; M1–M4 activities keep
using ``commit_run_state`` until T07 migrates them to ``commit_snapshot``. The
new revision-aware path is the v1 single mutation path (load → apply_event →
commit_snapshot); the demonstrator's imperative path remains intact and green.
"""

from __future__ import annotations

from fsasm.errors import PersistenceError
from fsasm.models import RunState
from fsasm.persistence import RuntimePersistence


class StaleRevisionError(PersistenceError):
    """Raised when ``commit_snapshot`` is called with a stale ``expected_revision``.

    The optimistic-concurrency boundary: the on-disk authoritative snapshot has
    a newer ``revision`` than the caller expected, so the caller's view is stale
    and must reload rather than overwrite newer state (G1). This is the
    revision guard that prevents a stale snapshot from rolling back newer work.
    """

    def __init__(self, message: str, run_id: str, expected: int, actual: int) -> None:
        self.run_id = run_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            message,
            path=None,
            operation="commit_snapshot",
        )


class StateRepository:
    """Revision-aware single-commit repository over ``state.json``.

    Composes ``RuntimePersistence`` so F3/F4/F5 protections (atomic single-file
    write, run-creation reservation, path-safety, symlink containment) are
    reused unchanged. The repository adds the v1 revision contract on top: a
    commit succeeds only when ``expected_revision`` matches the on-disk
    authoritative snapshot's ``revision`` (optimistic concurrency), and on
    success ``revision`` is incremented exactly once.
    """

    def __init__(self, persistence: RuntimePersistence) -> None:
        self._persistence = persistence

    @property
    def persistence(self) -> RuntimePersistence:
        return self._persistence

    def create_run(self, run_id: str):
        """Reserve a new run directory (F4 boundary). Delegates to persistence."""
        return self._persistence.create_run(run_id)

    def is_run_initialized(self, run_id: str) -> bool:
        return self._persistence.is_run_initialized(run_id)

    def has_snapshot(self, run_id: str) -> bool:
        """True if the run has an authoritative ``state.json`` on disk."""
        return self._persistence._get_state_path(run_id).exists()

    def init_snapshot(self, state: RunState) -> RunState:
        """Write the FIRST authoritative snapshot for a newly created run.

        This is the v1 start path (``start_new``): a brand-new run has no prior
        authoritative snapshot, so ``commit_snapshot``'s optimistic-concurrency
        check has nothing to compare against. ``init_snapshot`` writes the
        initial snapshot at ``revision = 0`` and the derived ``plan.json``
        projection. It is the only way to establish the first snapshot; it is
        rejected if a snapshot already exists (no overwrite of an existing run).

        Raises:
            PersistenceError: if the run is uninitialized or a snapshot exists.
        """
        if not self._persistence.is_run_initialized(state.run_id):
            raise PersistenceError(
                message=(
                    f"run '{state.run_id}' is not initialized; create_run() "
                    f"must be called before init_snapshot()"
                ),
                path=str(self._persistence._get_run_dir(state.run_id)),
                operation="init_snapshot",
            )
        if self.has_snapshot(state.run_id):
            raise PersistenceError(
                message=(
                    f"run '{state.run_id}' already has an authoritative "
                    f"snapshot; use commit_snapshot() to advance it"
                ),
                path=str(self._persistence._get_state_path(state.run_id)),
                operation="init_snapshot",
            )
        initial = state.model_copy(update={"revision": 0})
        initial.touch()
        self._persistence.commit_run_state(initial)
        return initial

    def load(self, run_id: str) -> RunState:
        """Read and reconstruct the authoritative snapshot for ``run_id``.

        ``state.json`` is the single source of truth. A run that was created via
        ``create_run`` but has no authoritative snapshot yet raises
        ``PersistenceError`` (fail closed), so a partially initialized run is
        never fabricated from a derived view.

        Raises:
            PersistenceError: if the run is uninitialized or the authoritative
                snapshot is missing/corrupt.
        """
        if not self._persistence.is_run_initialized(run_id):
            raise PersistenceError(
                message=(
                    f"run '{run_id}' is not initialized; create_run() must be "
                    f"called before load()"
                ),
                path=str(self._persistence._get_run_dir(run_id)),
                operation="load",
            )
        state = self._persistence.load_run_state(run_id)
        if state is None:
            raise PersistenceError(
                message=(f"authoritative state.json for run '{run_id}' is missing"),
                path=str(self._persistence._get_state_path(run_id)),
                operation="load",
            )
        return state

    def commit_snapshot(
        self,
        run_id: str,
        expected_revision: int,
        next_state: RunState,
    ) -> RunState:
        """Atomically commit ``next_state`` as the authoritative snapshot.

        v1 optimistic-concurrency contract (G1 / architecture §11):
        1. Reject a mismatched ``run_id`` (the snapshot belongs to another run).
        2. Reject a stale ``expected_revision``: the on-disk authoritative
           snapshot's ``revision`` must equal ``expected_revision``; a newer
           on-disk revision means the caller's view is stale and must reload.
        3. Increment ``revision`` exactly once on the committed state.
        4. Write the authoritative ``state.json`` atomically first.
        5. Write the derived ``plan.json`` projection afterwards from the
           authoritative state's plan; a failure here does NOT roll back the
           authoritative snapshot and cannot yield a false PASS.

        Returns:
            The committed ``RunState`` (with the incremented ``revision``).

        Raises:
            StaleRevisionError: if ``expected_revision`` does not match the
                on-disk authoritative revision.
            PersistenceError: if the run is uninitialized or a write fails.
        """
        if run_id != next_state.run_id:
            raise PersistenceError(
                message=(
                    f"run_id mismatch: commit target '{run_id}' does not match "
                    f"state run_id '{next_state.run_id}'"
                ),
                path=None,
                operation="commit_snapshot",
            )
        if not self._persistence.is_run_initialized(run_id):
            raise PersistenceError(
                message=(
                    f"run '{run_id}' is not initialized; create_run() must be "
                    f"called before commit_snapshot()"
                ),
                path=str(self._persistence._get_run_dir(run_id)),
                operation="commit_snapshot",
            )

        current = self._persistence.load_run_state(run_id)
        actual_revision = current.revision if current is not None else None
        if actual_revision is None:
            raise PersistenceError(
                message=(
                    f"authoritative state.json for run '{run_id}' is missing; "
                    f"cannot commit over a run with no initial snapshot"
                ),
                path=str(self._persistence._get_state_path(run_id)),
                operation="commit_snapshot",
            )
        if actual_revision != expected_revision:
            raise StaleRevisionError(
                message=(
                    f"stale revision for run '{run_id}': expected "
                    f"{expected_revision} but on-disk authoritative revision is "
                    f"{actual_revision}"
                ),
                run_id=run_id,
                expected=expected_revision,
                actual=actual_revision,
            )

        committed = next_state.model_copy(update={"revision": actual_revision + 1})
        committed.touch()
        self._persistence.commit_run_state(committed)
        return committed
