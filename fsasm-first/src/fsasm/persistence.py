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
from fsasm.errors import InvalidIdentifierError, PersistenceError


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
        Load a Plan from JSON file.

        Args:
            run_id: The run ID to load.

        Returns:
            The loaded Plan, or None if not found.

        Raises:
            PersistenceError: If load fails.
        """
        path = self._get_plan_path(run_id)
        if not path.exists():
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
