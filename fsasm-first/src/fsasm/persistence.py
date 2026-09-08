"""FS-ASM Runtime Persistence - filesystem JSON with atomic writes."""

import json
import os
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
from fsasm.errors import PersistenceError


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

    def _get_run_dir(self, run_id: str) -> Path:
        """Get the directory for a specific run."""
        return self.runs_dir / run_id

    def _get_state_path(self, run_id: str) -> Path:
        """Get the path to the state.json file for a run."""
        return self._get_run_dir(run_id) / DEFAULT_STATE_FILE

    def _get_plan_path(self, run_id: str) -> Path:
        """Get the path to the plan.json file for a run."""
        return self._get_run_dir(run_id) / DEFAULT_PLAN_FILE

    def _get_evidence_dir(self, run_id: str) -> Path:
        """Get the evidence directory for a run."""
        return self._get_run_dir(run_id) / DEFAULT_EVIDENCE_DIR

    def _get_run_log_path(self, run_id: str) -> Path:
        """Get the path to the run.log.jsonl file for a run."""
        return self._get_run_dir(run_id) / DEFAULT_RUN_LOG_FILE

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
        evidence_dir = self._get_evidence_dir(evidence.run_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        path = evidence_dir / f"{evidence.evidence_id}.json"
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
        evidence_dir = self._get_evidence_dir(run_id)
        path = evidence_dir / f"{evidence_id}.json"
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
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                records.append(EvidenceRecord(**data))
            except Exception:
                # Skip invalid files
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
