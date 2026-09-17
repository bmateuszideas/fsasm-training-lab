"""FS-ASM Runtime Persistence - filesystem JSON with atomic writes."""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fsasm.models import (
    EvidenceRecord,
    GoalInput,
    Plan,
    RunState,
    VerificationResult,
)
from fsasm.errors import (
    InvalidIdentifierError,
    PersistenceError,
    RunAlreadyExistsError,
)


# =============================================================================
# F5 FILESYSTEM IDENTIFIER SAFETY POLICY
# =============================================================================
#
# Centralized policy for untrusted ``run_id`` / ``evidence_id`` identifiers that
# derive filesystem paths. Validation is enforced by the persistence boundary
# before any identifier-derived directory or file is touched, so direct
# callers cannot bypass it even when the domain models happen to accept the
# same string.
#
# Policy goals:
#   * accept existing generated UUIDs and conventional FS-ASM IDs
#     (letters, digits, ``-`` and ``_``);
#   * reject empty/whitespace, ``/`` and ``\`` separators, absolute/drive/UNC
#     input, ``.`` / ``..``, null bytes and other control characters;
#   * reject identifiers exceeding the length limit (leaving room for the
#     ``.json`` suffix and a component length budget);
#   * reject Windows-reserved filenames for cross-platform safety;
#   * behave consistently on Linux and Windows.

MAX_IDENTIFIER_LENGTH = 200

# Conservative ASCII allowlist: letters, digits, hyphen, underscore.
# Conventional FS-ASM IDs (``run-123``, ``evidence-m3-execution-...``,
# UUIDs) use only these characters. No separators or traversal chars.
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\Z")

# Windows-reserved device/file names (case-insensitive), with or without an
# extension. Rejecting them keeps the allowlist cross-platform safe.
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def _validate_identifier(identifier: str, kind: str) -> None:
    """Raise ``InvalidIdentifierError`` if ``identifier`` is path-unsafe.

    ``kind`` is used only for the error message (e.g. "run_id").
    """
    if not isinstance(identifier, str):
        raise InvalidIdentifierError(
            f"{kind} must be a non-empty string", identifier=str(identifier)
        )
    stripped = identifier.strip()
    if not stripped:
        raise InvalidIdentifierError(
            f"{kind} cannot be empty or whitespace-only", identifier=identifier
        )
    # Reject the raw identifier if it has leading/trailing whitespace; the
    # allowlist below already excludes most whitespace, but be explicit.
    if identifier != stripped:
        raise InvalidIdentifierError(
            f"{kind} cannot have leading or trailing whitespace",
            identifier=identifier,
        )
    if len(identifier) > MAX_IDENTIFIER_LENGTH:
        raise InvalidIdentifierError(
            f"{kind} exceeds the length limit ({MAX_IDENTIFIER_LENGTH})",
            identifier=identifier,
        )
    # Null bytes and control characters are path-unsafe; reject explicitly.
    if any(ord(c) < 32 for c in identifier):
        raise InvalidIdentifierError(
            f"{kind} contains control characters", identifier=identifier
        )
    # Reject path separators and traversal regardless of platform.
    if "/" in identifier or "\\" in identifier:
        raise InvalidIdentifierError(
            f"{kind} contains a path separator", identifier=identifier
        )
    if identifier in (".", ".."):
        raise InvalidIdentifierError(
            f"{kind} cannot be a path traversal component", identifier=identifier
        )
    if os.path.isabs(identifier):
        raise InvalidIdentifierError(
            f"{kind} cannot be an absolute path", identifier=identifier
        )
    if not _IDENTIFIER_PATTERN.match(identifier):
        raise InvalidIdentifierError(
            f"{kind} contains disallowed characters", identifier=identifier
        )
    stem = identifier.split(".", 1)[0]
    if stem.upper() in _WINDOWS_RESERVED:
        raise InvalidIdentifierError(
            f"{kind} uses a Windows-reserved name", identifier=identifier
        )


def _ensure_contained(
    resolved: Path, root: Path, *, allow_symlink: bool = False
) -> None:
    """Validate that ``resolved`` stays within ``root`` after resolution.

    ``resolved`` is the path as it would be used (parent directories may not yet
    exist). ``root`` is the authorized boundary (e.g. ``runs_dir`` or an evidence
    dir). When ``allow_symlink`` is False (the safe default), an existing
    symlink at the run directory, evidence directory, or destination-file
    level is rejected so that an operation cannot follow a pre-existing link
    to another run or an external location.

    This is a containment + symlink-isolation check, not a TOCTOU-hardened
    sandbox. See the F5 limitation note in PROJECT_STATUS.md.
    """
    try:
        root_real = root.resolve(strict=False)
        resolved_real = resolved.resolve(strict=False)
    except OSError as exc:
        raise InvalidIdentifierError(
            f"path resolution failed for {resolved}", identifier=str(resolved)
        ) from exc

    try:
        resolved_real.relative_to(root_real)
    except ValueError as exc:
        raise InvalidIdentifierError(
            f"path {resolved} escapes the authorized root {root}",
            identifier=str(resolved),
        ) from exc

    if allow_symlink:
        return

    if os.path.islink(resolved):
        raise InvalidIdentifierError(
            f"path {resolved} is a symlink and may redirect outside {root}",
            identifier=str(resolved),
        )
    if os.path.islink(root):
        raise InvalidIdentifierError(
            f"authorized root {root} is a symlink and may redirect operations",
            identifier=str(root),
        )
    for parent in [resolved, *list(resolved.parents)]:
        if parent == root or root in parent.parents:
            if os.path.islink(parent):
                raise InvalidIdentifierError(
                    f"path component {parent} is a symlink and may redirect "
                    f"operations outside {root}",
                    identifier=str(parent),
                )


# =============================================================================
# DEFAULT PATHS
# =============================================================================

DEFAULT_RUNTIME_DIR = Path("runtime")
DEFAULT_RUNS_DIR = DEFAULT_RUNTIME_DIR / "runs"
DEFAULT_STATE_FILE = "state.json"
DEFAULT_PLAN_FILE = "plan.json"
DEFAULT_EVIDENCE_DIR = "evidence"
DEFAULT_RUN_LOG_FILE = "run.log.jsonl"


# =============================================================================
# RUNTIME PERSISTENCE
# =============================================================================


class RuntimePersistence:
    """
    Filesystem-based persistence for FS-ASM runtime.

    Provides atomic JSON writes for mutable state.
    Uses the directory structure:

    runtime/
    └── runs/
        └── <run_id>/
            ├── state.json
            ├── plan.json
            ├── evidence/
            │   └── <evidence_id>.json
            └── run.log.jsonl
    """

    def __init__(
        self,
        runtime_dir: Path | str | None = None,
        runs_dir: Path | str | None = None,
    ) -> None:
        """
        Initialize the persistence layer.

        Args:
            runtime_dir: Root runtime directory. Defaults to ./runtime
            runs_dir: Runs subdirectory. Defaults to runtime_dir/runs
        """
        if runtime_dir is not None:
            self.runtime_dir = Path(runtime_dir)
        else:
            self.runtime_dir = DEFAULT_RUNTIME_DIR

        if runs_dir is not None:
            self.runs_dir = Path(runs_dir)
        else:
            self.runs_dir = self.runtime_dir / "runs"

        # Ensure directories exist
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------
    # F5 identifier validation + path containment
    # --------------------------------------------------------------------

    def _validate_run_id(self, run_id: str) -> None:
        """Validate ``run_id`` and raise ``InvalidIdentifierError`` if unsafe."""
        _validate_identifier(run_id, "run_id")

    def _validate_evidence_id(self, evidence_id: str) -> None:
        """Validate ``evidence_id`` and raise ``InvalidIdentifierError`` if unsafe."""
        _validate_identifier(evidence_id, "evidence_id")

    def _get_run_dir(self, run_id: str) -> Path:
        """Get the directory for a specific run.

        Validates the identifier and rejects run-directory symlinks that would
        redirect operations into another run or outside ``runs_dir``, even when
        the symlink target stays inside ``runs_dir``.
        """
        self._validate_run_id(run_id)
        run_dir = self.runs_dir / run_id
        _ensure_contained(run_dir, self.runs_dir)
        return run_dir

    def _get_state_path(self, run_id: str) -> Path:
        """Get the path to the state.json file for a run."""
        run_dir = self._get_run_dir(run_id)
        path = run_dir / DEFAULT_STATE_FILE
        _ensure_contained(path, run_dir)
        return path

    def _get_plan_path(self, run_id: str) -> Path:
        """Get the path to the plan.json file for a run."""
        run_dir = self._get_run_dir(run_id)
        path = run_dir / DEFAULT_PLAN_FILE
        _ensure_contained(path, run_dir)
        return path

    def _get_evidence_dir(self, run_id: str) -> Path:
        """Get the evidence directory for a run."""
        run_dir = self._get_run_dir(run_id)
        evidence_dir = run_dir / DEFAULT_EVIDENCE_DIR
        _ensure_contained(evidence_dir, run_dir)
        return evidence_dir

    def _get_evidence_path(self, run_id: str, evidence_id: str) -> Path:
        """Get the path to a specific evidence file."""
        self._validate_evidence_id(evidence_id)
        evidence_dir = self._get_evidence_dir(run_id)
        path = evidence_dir / f"{evidence_id}.json"
        _ensure_contained(path, evidence_dir)
        return path

    def _get_run_log_path(self, run_id: str) -> Path:
        """Get the path to the run.log.jsonl file for a run."""
        run_dir = self._get_run_dir(run_id)
        path = run_dir / DEFAULT_RUN_LOG_FILE
        _ensure_contained(path, run_dir)
        return path

    # =========================================================================
    # F4 RUN-CREATION BOUNDARY
    # =========================================================================
    #
    # ``create_run`` is the explicit new-run creation boundary. It atomically
    # reserves the run directory using exclusive creation (``mkdir`` with
    # ``exist_ok=False``) so that two concurrent local creation attempts for the
    # same ``run_id`` cannot both succeed, and an existing run cannot be silently
    # reinitialized. F5's identifier validation and symlink containment are
    # applied first. A successful ``create_run`` establishes exclusive ownership
    # of the run directory; subsequent normal internal writes to an established
    # run (``save_plan`` / ``save_run_state`` / ...) are NOT creation operations
    # and remain unaffected.
    #
    # The reservation marker file (``.fsasm-run``) records that this directory is
    # a legitimately created FS-ASM run (rather than a partially initialized or
    # foreign directory), so recovery can distinguish a crashed creation from a
    # clean existing run (F3).

    _RESERVATION_MARKER = ".fsasm-run"

    def create_run(self, run_id: str) -> Path:
        """Atomically reserve the run directory for a new run.

        This is the F4 identity boundary: it separates *creating* a new run
        from *accessing* or *resuming* an existing run. It MUST be called before
        the first ``save_plan`` / ``save_run_state`` for a new run.

        Args:
            run_id: The run identifier to create. Validated by the F5 policy.

        Returns:
            The reserved run directory ``Path``.

        Raises:
            InvalidIdentifierError: If ``run_id`` is path-unsafe (F5).
            RunAlreadyExistsError: If the run directory already exists
                (whether fully or partially initialized), so a duplicate
                creation cannot silently overwrite existing state, plan,
                evidence or log history.
        """
        run_dir = self._get_run_dir(run_id)
        # Exclusive creation: race-free on a local filesystem. ``exist_ok=False``
        # raises ``FileExistsError`` if the directory already exists, even if it
        # was created concurrently between the F5 check and this call.
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise RunAlreadyExistsError(
                f"Run '{run_id}' already exists; cannot create a new run with "
                f"this run_id (use resume/load to access an existing run)",
                run_id=run_id,
            ) from exc
        # Write the reservation marker atomically so the directory is a
        # legitimately created FS-ASM run. This marker survives partial
        # initialization and crash recovery (F3).
        marker = run_dir / self._RESERVATION_MARKER
        try:
            self._atomic_write_marker(marker, {"run_id": run_id})
        except Exception:
            # If the marker write fails, remove the empty reservation so the
            # creation can be retried cleanly rather than leaving a half-created
            # run that blocks future creation.
            import shutil

            shutil.rmtree(run_dir, ignore_errors=True)
            raise
        return run_dir

    def _atomic_write_marker(self, path: Path, data: dict[str, Any]) -> None:
        """Write the reservation marker atomically."""
        try:
            temp_fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, path)
            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
        except Exception as exc:
            raise PersistenceError(
                message=f"Failed to write reservation marker {path}: {exc}",
                path=str(path),
                operation="create_run_marker",
            ) from exc

    def is_run_initialized(self, run_id: str) -> bool:
        """Return True if the run directory exists AND was created via ``create_run``.

        A directory that merely exists but lacks the reservation marker is a
        partially initialized or foreign directory, not a legitimately created
        run. This distinction supports F3 crash recovery and F4 duplicate
        detection.
        """
        run_dir = self._get_run_dir(run_id)
        return run_dir.exists() and (run_dir / self._RESERVATION_MARKER).exists()

    def assert_run_initialized(self, run_id: str) -> None:
        """Raise ``PersistenceError`` if the run was not created via ``create_run``.

        Used by internal write paths to guard against writes to a partially
        initialized or foreign directory that should not be treated as a run.
        """
        if not self.is_run_initialized(run_id):
            raise PersistenceError(
                message=(
                    f"Run '{run_id}' is not initialized; create_run() must be "
                    f"called before any save operation for a new run"
                ),
                path=str(self._get_run_dir(run_id)),
                operation="assert_run_initialized",
            )

    # =========================================================================
    # F3 AUTHORITATIVE SNAPSHOT / RECOVERY
    # =========================================================================
    #
    # Crash-consistency contract for this laboratory:
    #
    #   * ``state.json`` (with its embedded ``RunState.plan``) is the
    #     authoritative run-state snapshot.
    #   * ``plan.json`` is a derived/materialized view of that authoritative
    #     snapshot. It exists for direct inspection and legacy readers, but it
    #     is NEVER a second competing authority.
    #   * A task transition is not considered durably committed until the
    #     authoritative snapshot (``state.json``) has been atomically committed.
    #   * Readers and recovery code must not treat a newer or partially written
    #     ``plan.json`` as authoritative over ``state.json``.
    #
    # ``commit_run_state`` writes the authoritative snapshot first and the
    # derived ``plan.json`` second (from the authoritative state's plan), so the
    # derived view can never be newer than the authoritative snapshot. A crash
    # between the two writes leaves a possibly-stale ``plan.json`` that recovery
    # repairs from ``state.json``.
    #
    # This does NOT make evidence/log writes part of the same atomic
    # transaction as state.json; those remain separate supplementary artifacts
    # (see the F3 limitation note). Recovery guarantees logical plan/state
    # consistency, not a fully transactional store.

    def commit_run_state(self, state: RunState) -> None:
        """Commit the authoritative run-state snapshot, then refresh the derived plan view.

        F3 authoritative-snapshot boundary:
        1. Write ``state.json`` (with the embedded plan) atomically first.
        2. Write ``plan.json`` (derived from ``state.plan``) atomically second.

        A crash between (1) and (2) leaves ``plan.json`` stale relative to
        ``state.json``; ``recover_run`` / ``load_plan`` reconcile or repair it.
        A crash before (1) leaves the previous authoritative snapshot intact.

        Args:
            state: The authoritative RunState (with ``state.plan`` embedded).

        Raises:
            PersistenceError: If either write fails. If the authoritative write
                fails, the derived view is NOT written (no newer derived view
                is ever left without a matching authoritative snapshot).
        """
        # Authoritative snapshot first. If this fails, do not write the derived
        # view: a derived view newer than the authoritative snapshot is exactly
        # the contradictory-state F3 forbids.
        state_path = self._get_state_path(state.run_id)
        self._atomic_write_json(state_path, state)

        # Derived view second, from the authoritative state's plan. A crash
        # here leaves a stale plan.json that recovery repairs from state.json.
        if state.plan is not None:
            plan_path = self._get_plan_path(state.run_id)
            self._atomic_write_json(plan_path, state.plan)

    def recover_run(self, run_id: str) -> RunState:
        """Recover the authoritative run state, repairing the derived plan view.

        F3 recovery contract:
        - ``state.json`` is the single source of truth.
        - If ``state.json`` is missing or corrupt, raise ``PersistenceError``
          (do NOT silently substitute ``plan.json`` or fabricate state).
        - If ``state.json`` is valid, repair ``plan.json`` from the embedded
          ``state.plan`` so the derived view matches the authoritative snapshot.
        - Recovery is idempotent: repeated recovery produces the same result.
        - F4's duplicate-creation protection and F5's path validation remain
          effective (recovery never creates a new run; it validates the
          identifier and asserts the run was initialized).

        Args:
            run_id: The run to recover.

        Returns:
            The recovered authoritative RunState.

        Raises:
            PersistenceError: If the run was not created via ``create_run``,
                if ``state.json`` is missing/corrupt, or if repair fails.
        """
        self._validate_run_id(run_id)
        self.assert_run_initialized(run_id)

        state = self.load_run_state(run_id)
        if state is None:
            raise PersistenceError(
                message=(
                    f"Cannot recover run '{run_id}': authoritative state.json is "
                    f"missing; refusing to fabricate state from a derived view"
                ),
                path=str(self._get_state_path(run_id)),
                operation="recover_run",
            )
        # load_run_state already raises PersistenceError on corrupt JSON; if we
        # reach here state is a valid RunState.

        # Repair the derived plan.json from the authoritative snapshot's plan.
        if state.plan is not None:
            plan_path = self._get_plan_path(run_id)
            self._atomic_write_json(plan_path, state.plan)

        return state

    # =========================================================================
    # ATOMIC WRITE HELPERS
    # =========================================================================

    def _atomic_write_json(self, path: Path, data: Any) -> None:
        """
        Write JSON data to a file atomically.

        Uses temp file + rename pattern to ensure atomic writes.

        Args:
            path: The destination file path.
            data: The data to serialize to JSON.

        Raises:
            PersistenceError: If write fails.
        """
        try:
            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file first
            temp_fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(
                        data.model_dump() if hasattr(data, "model_dump") else data,
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename
                os.replace(temp_path, path)
            except Exception as exc:
                # Clean up temp file if it exists
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise PersistenceError(
                    message=f"Failed to write {path}: {exc}",
                    path=str(path),
                    operation="atomic_write_json",
                ) from exc
        except Exception as exc:
            raise PersistenceError(
                message=f"Failed atomic write to {path}: {exc}",
                path=str(path),
                operation="atomic_write_json",
            ) from exc

    def _atomic_append_jsonl(self, path: Path, data: Any) -> None:
        """
        Append a JSON line to a JSONL file atomically.

        Args:
            path: The destination file path.
            data: The data to append as a JSON line.

        Raises:
            PersistenceError: If append fails.
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file
            temp_fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                # If file exists, copy existing content
                if path.exists():
                    with open(path, "r", encoding="utf-8") as f:
                        existing = f.read()
                    with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                        f.write(existing)
                        if not existing.endswith("\n"):
                            f.write("\n")
                else:
                    with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                        pass  # Empty file

                # Append new line
                with open(temp_path, "a", encoding="utf-8") as f:
                    json.dump(
                        data.model_dump() if hasattr(data, "model_dump") else data,
                        f,
                        ensure_ascii=False,
                    )
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename
                os.replace(temp_path, path)
            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
        except Exception as exc:
            raise PersistenceError(
                message=f"Failed to append to {path}: {exc}",
                path=str(path),
                operation="atomic_append_jsonl",
            ) from exc

    # =========================================================================
    # SAVE OPERATIONS
    # =========================================================================

    def save_goal_input(self, input: GoalInput) -> GoalInput:
        """
        Save a GoalInput and return it with generated run_id.

        Args:
            input: The GoalInput to save.

        Returns:
            The GoalInput with run_id populated.
        """
        if input.run_id is None:
            input.run_id = input.generate_run_id()
        return input

    def save_plan(self, plan: Plan) -> None:
        """
        Save a Plan to JSON file atomically.

        Args:
            plan: The Plan to save.

        Raises:
            PersistenceError: If save fails.
        """
        path = self._get_plan_path(plan.run_id)
        self._atomic_write_json(path, plan)

    def save_run_state(self, state: RunState) -> None:
        """
        Save a RunState to JSON file atomically.

        Args:
            state: The RunState to save.

        Raises:
            PersistenceError: If save fails.
        """
        path = self._get_state_path(state.run_id)
        self._atomic_write_json(path, state)

    def save_evidence(self, evidence: EvidenceRecord) -> None:
        """
        Save an EvidenceRecord to JSON file atomically.

        Args:
            evidence: The EvidenceRecord to save.

        Raises:
            PersistenceError: If save fails.
        """
        self._validate_evidence_id(evidence.evidence_id)
        evidence_dir = self._get_evidence_dir(evidence.run_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self._get_evidence_path(evidence.run_id, evidence.evidence_id)
        self._atomic_write_json(path, evidence)

    def save_verification_result(self, result: VerificationResult) -> None:
        """
        Save a VerificationResult to the run log as JSONL.

        Args:
            result: The VerificationResult to save.

        Raises:
            PersistenceError: If save fails.
        """
        path = self._get_run_log_path(result.run_id)
        self._atomic_append_jsonl(path, result)

    def save_run_log_entry(self, run_id: str, entry: dict[str, Any]) -> None:
        """
        Save a generic log entry to the run log.

        Args:
            run_id: The run ID for the log.
            entry: The log entry data.

        Raises:
            PersistenceError: If save fails.
        """
        path = self._get_run_log_path(run_id)
        self._atomic_append_jsonl(path, entry)

    # =========================================================================
    # LOAD OPERATIONS
    # =========================================================================

    def load_plan(self, run_id: str) -> Plan | None:
        """
        Load a Plan for a run.

        F3 authoritative-snapshot contract: ``state.json`` (with its embedded
        plan) is the single source of truth. When ``state.json`` exists and
        contains an embedded plan, that authoritative plan is returned and the
        derived ``plan.json`` is never treated as a competing authority (a
        stale or partially written ``plan.json`` cannot contradict the
        authoritative snapshot).

        Fail-closed rule for F4-initialized runs: a run created via
        ``create_run`` (reservation marker present) treats ``state.json`` as
        the sole authority. If ``state.json`` is absent, or exists but has no
        embedded plan, ``load_plan`` returns ``None`` rather than falling back
        to an orphan/stale ``plan.json``. This prevents an F4-reserved
        partially initialized run (or a run whose authoritative state lost its
        plan) from presenting a derived ``plan.json`` as a legitimate plan.

        Legacy-plan-only path: a directory that was NOT created via
        ``create_run`` (no reservation marker) and has only ``plan.json`` keeps
        the legacy read so existing legacy tests that intentionally persist a
        standalone ``plan.json`` are not silently broken. ``state.json`` is
        still preferred when present.

        Args:
            run_id: The run ID to load.

        Returns:
            The authoritative Plan (from ``state.json`` when present with an
            embedded plan), a legacy standalone ``plan.json`` for an
            unreserved run, or None.

        Raises:
            PersistenceError: If the authoritative ``state.json`` exists but is
                corrupt, or if only a corrupt ``plan.json`` exists.
        """
        # Authoritative snapshot first.
        state = self.load_run_state(run_id)
        if state is not None:
            if state.plan is not None:
                return state.plan
            # state.json exists but has no embedded plan. For an F4-
            # initialized run, the authority says "no plan": fail closed (do
            # NOT fall through to an orphan/stale plan.json). For a legacy run
            # (no reservation marker), fall through to the legacy plan-only
            # read.
            if self.is_run_initialized(run_id):
                return None

        # Legacy-plan-only path: only read a standalone plan.json for a run
        # that was NOT created via create_run (no reservation marker). An
        # F4-initialized run with absent authority never reaches here.
        path = self._get_plan_path(run_id)
        if not path.exists():
            return None
        if self.is_run_initialized(run_id):
            # F4-initialized run with absent/plan-less authority: the orphan
            # plan.json is NOT authoritative.
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Plan(**data)
        except Exception as e:
            raise PersistenceError(
                message=f"Failed to load plan from {path}: {e}",
                path=str(path),
                operation="load_plan",
            ) from e

    def load_run_state(self, run_id: str) -> RunState | None:
        """
        Load a RunState from JSON file.

        Args:
            run_id: The run ID to load.

        Returns:
            The loaded RunState, or None if not found.

        Raises:
            PersistenceError: If load fails.
        """
        path = self._get_state_path(run_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RunState(**data)
        except Exception as e:
            raise PersistenceError(
                message=f"Failed to load state from {path}: {e}",
                path=str(path),
                operation="load_run_state",
            ) from e

    def load_evidence(self, run_id: str, evidence_id: str) -> EvidenceRecord | None:
        """
        Load an EvidenceRecord from JSON file.

        Args:
            run_id: The run ID.
            evidence_id: The evidence ID.

        Returns:
            The loaded EvidenceRecord, or None if not found.

        Raises:
            PersistenceError: If load fails.
        """
        path = self._get_evidence_path(run_id, evidence_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return EvidenceRecord(**data)
        except Exception as e:
            raise PersistenceError(
                message=f"Failed to load evidence from {path}: {e}",
                path=str(path),
                operation="load_evidence",
            ) from e

    def load_all_evidence(self, run_id: str) -> list[EvidenceRecord]:
        """
        Load all EvidenceRecords for a run.

        Args:
            run_id: The run ID.

        Returns:
            List of loaded EvidenceRecords.
        """
        evidence_dir = self._get_evidence_dir(run_id)
        if not evidence_dir.exists():
            return []

        records = []
        for path in evidence_dir.glob("*.json"):
            # Validate each discovered path with the F5 containment/symlink
            # mechanism BEFORE opening it. A symlinked evidence file could
            # otherwise redirect reads into another run or outside the
            # authorized evidence directory. This security check is kept
            # OUTSIDE the broad exception handler below so a security
            # rejection is never silently swallowed as a malformed file.
            _ensure_contained(path, evidence_dir)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                records.append(EvidenceRecord(**data))
            except Exception:
                # Skip invalid (non-symlink) JSON files only.
                continue
        return records

    def load_run_log(self, run_id: str) -> list[dict[str, Any]]:
        """
        Load all entries from the run log.

        Args:
            run_id: The run ID.

        Returns:
            List of log entries as dictionaries.
        """
        path = self._get_run_log_path(run_id)
        if not path.exists():
            return []

        entries = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception:
            pass
        return entries

    # =========================================================================
    # UTILITY OPERATIONS
    # =========================================================================

    def run_exists(self, run_id: str) -> bool:
        """Check if a run directory exists."""
        return self._get_run_dir(run_id).exists()

    def get_all_run_ids(self) -> list[str]:
        """Get all run IDs that have directories."""
        if not self.runs_dir.exists():
            return []
        return [d.name for d in self.runs_dir.iterdir() if d.is_dir()]

    def cleanup_run(self, run_id: str) -> None:
        """
        Remove all files for a run (for testing/cleanup).

        Args:
            run_id: The run ID to clean up.
        """
        import shutil

        run_dir = self._get_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir)

    def cleanup_all(self) -> None:
        """Remove all runtime data (for testing/cleanup)."""
        import shutil

        if self.runtime_dir.exists():
            shutil.rmtree(self.runtime_dir)
        self._ensure_directories()


# Singleton instance for convenience
persistence = RuntimePersistence()
