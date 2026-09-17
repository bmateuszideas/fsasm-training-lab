"""FS-ASM Tool Broker for file operations (T11).

The Tool Broker is the only path through which the Executor may have a real
effect on an isolated workspace. It enforces the approved scope
``allowed_files`` / ``workspace_scope`` **in code, before any effect**: path
normalization, workspace-root containment, traversal (``..``), symlink escape
and size limits are all checked before a read or write touches the filesystem.
The model never receives a general terminal.

Every call carries an ``operation_id`` (binding the observation to one attempt
+ step) and returns a structured :class:`ToolObservation`. The broker never
grants PASS; it records the real effect (or the policy block). The Verifier
reads the actual artifact afterwards; the Domain Core alone grants the
transition (architecture §22, §27, §28; canonical TODO T11).

Scope of T11: ``list_files``, ``read_file``, ``search_code``, ``apply_patch``,
``inspect_changes``. ``run_checks`` / process isolation is T12 and lives in the
same broker then; it is not part of T11.

The broker is a plain Python object (not a workflow): real file I/O belongs in
an activity/tool layer, and the determinism rules forbid I/O only inside
``@workflow.define`` classes. Tests use ``tmp_path`` fixtures with real files so
the safety checks are proven against the real filesystem.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from fsasm.models import ToolObservation, ToolOperationKind, operation_id_for

# Default caps; the broker accepts overrides at construction (T11 keeps them
# conservative; T29 will configure the laptop profile).
DEFAULT_MAX_READ_BYTES = 256 * 1024
DEFAULT_MAX_WRITE_BYTES = 256 * 1024
DEFAULT_MAX_LIST_ENTRIES = 1000


class PolicyBlockError(Exception):
    """Raised when an operation is rejected by policy before any effect.

    Tests assert on the returned :class:`ToolObservation` (``blocked=True``)
    rather than this exception; it exists for callers that want a hard stop.
    """


@dataclass
class ToolBroker:
    """Enforces scope and executes file operations in an isolated workspace.

    The workspace root and the per-call ``allowed_files`` are the only source
    of privilege. A task's ``allowed_files`` must fall under the broker's
    ``workspace_scope`` (empty scope = whole root approved, as at intake). The
    broker never trusts a path from the model: it normalizes, resolves and
    re-validates containment after symlink resolution so a link pointing
    outside the root is rejected before any read or write.
    """

    workspace_root: Path
    workspace_scope: list[str] = field(default_factory=list)
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES
    max_write_bytes: int = DEFAULT_MAX_WRITE_BYTES
    max_list_entries: int = DEFAULT_MAX_LIST_ENTRIES

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root).resolve()
        # Resolve scope globs to approved root-relative directory prefixes up
        # front so per-call membership is a containment check, not glob
        # reasoning over arbitrary model-supplied paths.
        self._scope_dirs: list[Path] = [
            (self.workspace_root / s).resolve() for s in self.workspace_scope
        ]

    # -- public operations ------------------------------------------------

    def list_files(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        step: int,
        pattern: str = "*",
        allowed_files: list[str] | None = None,
    ) -> ToolObservation:
        op = self._op_id(run_id, task_id, attempt, step)
        root = self.workspace_root
        if not root.is_dir():
            return self._blocked(
                op, ToolOperationKind.LIST_FILES, "workspace root missing"
            )
        matches: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in sorted(filenames):
                rel = Path(dirpath, name).relative_to(root).as_posix()
                if fnmatch.fnmatch(rel, pattern):
                    matches.append(rel)
                if len(matches) >= self.max_list_entries:
                    break
            if len(matches) >= self.max_list_entries:
                break
        matches.sort()
        return ToolObservation(
            operation_id=op,
            kind=ToolOperationKind.LIST_FILES,
            ok=True,
            matches=matches,
            content=f"{len(matches)} file(s)",
        )

    def read_file(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        step: int,
        path: str,
        allowed_files: list[str] | None = None,
    ) -> ToolObservation:
        op = self._op_id(run_id, task_id, attempt, step)
        target, rel, err = self._resolve_within_scope(path, allowed_files, write=False)
        if err is not None:
            return self._blocked(
                op, ToolOperationKind.READ_FILE, err, artifact_path=rel
            )
        assert target is not None  # err is None => target resolved within scope
        if not target.is_file():
            return self._blocked(
                op, ToolOperationKind.READ_FILE, "file not found", artifact_path=rel
            )
        size = target.stat().st_size
        if size > self.max_read_bytes:
            return self._blocked(
                op,
                ToolOperationKind.READ_FILE,
                f"file exceeds read limit ({size} > {self.max_read_bytes} bytes)",
                artifact_path=rel,
            )
        content = target.read_text(encoding="utf-8")
        return ToolObservation(
            operation_id=op,
            kind=ToolOperationKind.READ_FILE,
            ok=True,
            artifact_path=rel,
            content=content,
        )

    def search_code(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        step: int,
        needle: str,
        allowed_files: list[str] | None = None,
        pattern: str = "*",
    ) -> ToolObservation:
        op = self._op_id(run_id, task_id, attempt, step)
        root = self.workspace_root
        if not root.is_dir():
            return self._blocked(
                op, ToolOperationKind.SEARCH_CODE, "workspace root missing"
            )
        try:
            regex = re.compile(needle)
        except re.error as exc:
            return self._blocked(
                op, ToolOperationKind.SEARCH_CODE, f"invalid regex: {exc}"
            )
        matches: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in sorted(filenames):
                rel = Path(dirpath, name).relative_to(root).as_posix()
                if not fnmatch.fnmatch(rel, pattern):
                    continue
                # search_code reads files but is not a write; scope membership
                # for reads is enforced against allowed_files only when the
                # caller bound it to a task (None = read-only sweep allowed).
                if allowed_files is not None and not self._is_allowed(
                    rel, allowed_files
                ):
                    continue
                full = Path(dirpath, name)
                if full.is_symlink():
                    continue
                try:
                    text = full.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line):
                        matches.append(f"{rel}:{lineno}: {line.strip()}")
        matches.sort()
        return ToolObservation(
            operation_id=op,
            kind=ToolOperationKind.SEARCH_CODE,
            ok=True,
            matches=matches,
            content=f"{len(matches)} match(es)",
        )

    def apply_patch(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        step: int,
        path: str,
        new_content: str,
        allowed_files: list[str] | None = None,
    ) -> ToolObservation:
        op = self._op_id(run_id, task_id, attempt, step)
        encoded = new_content.encode("utf-8")
        if len(encoded) > self.max_write_bytes:
            return self._blocked(
                op,
                ToolOperationKind.APPLY_PATCH,
                f"patch exceeds write limit ({len(encoded)} > "
                f"{self.max_write_bytes} bytes)",
                artifact_path=path,
            )
        target, rel, err = self._resolve_within_scope(path, allowed_files, write=True)
        if err is not None:
            return self._blocked(
                op, ToolOperationKind.APPLY_PATCH, err, artifact_path=rel
            )
        assert target is not None  # err is None => target resolved within scope
        before = target.read_text(encoding="utf-8") if target.is_file() else ""
        # Atomic-ish write: write to a sibling temp then replace, so a failure
        # does not leave a half-written file. No partial effect on rejection.
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp-fsasm")
        tmp.write_text(new_content, encoding="utf-8")
        os.replace(tmp, target)
        diff = _unified_diff(rel, before, new_content)
        return ToolObservation(
            operation_id=op,
            kind=ToolOperationKind.APPLY_PATCH,
            ok=True,
            artifact_path=rel,
            diff=diff,
            content=f"patched {rel}",
        )

    def inspect_changes(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        step: int,
        path: str,
        allowed_files: list[str] | None = None,
    ) -> ToolObservation:
        op = self._op_id(run_id, task_id, attempt, step)
        target, rel, err = self._resolve_within_scope(path, allowed_files, write=False)
        if err is not None:
            return self._blocked(
                op, ToolOperationKind.INSPECT_CHANGES, err, artifact_path=rel
            )
        assert target is not None  # err is None => target resolved within scope
        if not target.is_file():
            return self._blocked(
                op,
                ToolOperationKind.INSPECT_CHANGES,
                "file not found",
                artifact_path=rel,
            )
        content = target.read_text(encoding="utf-8")
        return ToolObservation(
            operation_id=op,
            kind=ToolOperationKind.INSPECT_CHANGES,
            ok=True,
            artifact_path=rel,
            content=content,
        )

    # -- scope enforcement ------------------------------------------------

    def _resolve_within_scope(
        self,
        path: str,
        allowed_files: list[str] | None,
        write: bool,
    ) -> tuple[Path | None, str, str | None]:
        """Resolve ``path`` to a real path within the root and approved scope.

        Returns ``(resolved_or_None, rel_posix, error_or_None)``. On any policy
        failure ``error`` is set and ``resolved`` is None; the caller must not
        touch the filesystem. Symlink escape is detected by resolving the real
        path and re-checking containment after resolution.
        """
        if not path or path.strip() != path:
            return None, path, "empty or padded path"
        # Reject absolute paths and any component that escapes before resolve.
        candidate = Path(path)
        if candidate.is_absolute():
            return None, path, "absolute paths are not allowed"
        # Normalize only the model-supplied relative components against the
        # root: reject a ``..`` that would climb above the root before any
        # filesystem resolution (so a non-existent ``../escape`` is blocked).
        rel_parts = _normalize_relative_parts(candidate)
        if rel_parts is None:
            return None, path, "path traversal outside workspace"
        norm = self.workspace_root.joinpath(*rel_parts)
        rel = norm.relative_to(self.workspace_root).as_posix()
        # Containment after lexical normalization (handles ``..``).
        if not _is_within(norm, self.workspace_root):
            return None, rel, "path escapes workspace root"
        # If the file exists, resolve real path to follow symlinks and re-check.
        if norm.exists() or norm.is_symlink():
            real = norm.resolve(strict=False)
            if not _is_within(real, self.workspace_root):
                return None, rel, "symlink escapes workspace root"
            norm = real
        # Scope membership (workspace_scope dirs) for both reads and writes.
        if not self._in_scope_dirs(norm):
            return None, rel, "path outside approved workspace scope"
        # allowed_files membership: writes require exact membership; reads
        # require membership only when the task bound allowed_files (None =
        # unconstrained read sweep, used by search/list). This is the only
        # source of file privilege; the model cannot widen it.
        if write:
            if allowed_files is None or not self._is_allowed(rel, allowed_files):
                return None, rel, "path not in allowed_files for write"
        elif allowed_files is not None and not self._is_allowed(rel, allowed_files):
            return None, rel, "path not in allowed_files"
        return norm, rel, None

    def _is_allowed(self, rel: str, allowed_files: list[str]) -> bool:
        """Exact membership (fnmatch glob) against the task's allowed_files."""
        return any(fnmatch.fnmatch(rel, pat) for pat in allowed_files)

    def _in_scope_dirs(self, resolved: Path) -> bool:
        if not self._scope_dirs:
            return True
        return any(_is_within(resolved, d) for d in self._scope_dirs)

    # -- helpers ----------------------------------------------------------

    def _op_id(self, run_id: str, task_id: str, attempt: int, step: int) -> str:
        return operation_id_for(run_id, task_id, attempt, step)

    def _blocked(
        self,
        op: str,
        kind: ToolOperationKind,
        reason: str,
        artifact_path: str | None = None,
    ) -> ToolObservation:
        return ToolObservation(
            operation_id=op,
            kind=kind,
            ok=False,
            blocked=True,
            reason=reason,
            artifact_path=artifact_path,
        )


def _is_within(child: Path, parent: Path) -> bool:
    """True when ``child`` is ``parent`` or inside it (both resolved)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _normalize_relative_parts(path: Path) -> list[str] | None:
    """Lexically normalize a relative ``path`` rejecting ``..`` escape.

    Walks the components; on encountering ``..`` that would climb above the
    root (i.e. ``parts`` is empty) returns None. Only the model-supplied
    relative components are walked, so the root prefix is not mistaken for a
    climbable component. This catches ``..`` before any filesystem resolution
    so a non-existent ``../escape`` is still rejected.
    """
    parts: list[str] = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return parts


def _unified_diff(rel: str, before: str, after: str) -> str:
    """A minimal unified-style diff of two text contents (no external dep)."""
    if before == after:
        return ""
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    out: list[str] = [f"--- a/{rel}", f"+++ b/{rel}"]
    out.append(f"@@ -1,{len(before_lines)} +1,{len(after_lines)} @@")
    for line in before_lines:
        out.append("-" + _strip_eol(line))
    for line in after_lines:
        out.append("+" + _strip_eol(line))
    return "\n".join(out)


def _strip_eol(line: str) -> str:
    return line[:-1] if line.endswith("\n") else line


__all__ = [
    "DEFAULT_MAX_LIST_ENTRIES",
    "DEFAULT_MAX_READ_BYTES",
    "DEFAULT_MAX_WRITE_BYTES",
    "PolicyBlockError",
    "ToolBroker",
]
