"""T11 — Tool Broker for file operations.

Proves the Tool Broker is the only path to a real filesystem effect and that it
enforces scope in code before any effect: a permitted patch changes a fixture
and produces a structured observation/diff; attempts to read or write outside
``allowed_files``, escape the workspace root via ``..``, escape via a symlink,
exceed size limits, or use an absolute path are blocked before any effect. Every
call carries an ``operation_id`` and never grants PASS (architecture §22, §27,
§28; canonical TODO T11).
"""

import os
import pathlib

import pytest

from fsasm.models import ToolOperationKind
from fsasm.tool_broker import ToolBroker

RUN = "r"
TASK = "TASK-r-1"


@pytest.fixture()
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "src" / "calc").mkdir(parents=True)
    (tmp_path / "src" / "calc" / "calculations.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "src" / "calc" / "other.py").write_text(
        "SECRET = 'x'\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    return tmp_path


def _broker(root: pathlib.Path, scope: list[str] | None = None) -> ToolBroker:
    return ToolBroker(workspace_root=root, workspace_scope=scope or [])


class TestAllowedPatch:
    """A permitted patch changes the fixture and yields an observation/diff."""

    def test_patch_changes_fixture_and_observes_diff(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "src/calc/calculations.py",
            "def add(a, b):\n    return a - b\n",
            allowed_files=["src/calc/calculations.py"],
        )
        assert out.ok and not out.blocked
        assert out.kind is ToolOperationKind.APPLY_PATCH
        assert out.artifact_path == "src/calc/calculations.py"
        assert out.diff is not None and "+    return a - b" in out.diff
        assert out.diff is not None and "-    return a + b" in out.diff
        assert (workspace / "src" / "calc" / "calculations.py").read_text(
            encoding="utf-8"
        ) == "def add(a, b):\n    return a - b\n"

    def test_patch_creates_new_file_under_scope(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "src/calc/new.py",
            "x = 1\n",
            allowed_files=["src/calc/new.py"],
        )
        assert out.ok
        assert (workspace / "src" / "calc" / "new.py").read_text(
            encoding="utf-8"
        ) == "x = 1\n"

    def test_operation_id_is_deterministic_and_bound_to_attempt(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.read_file(
            RUN, TASK, 1, 1, "src/calc/calculations.py", allowed_files=None
        )
        assert out.operation_id == "op-r-TASK-r-1-attempt-1-step-1"
        out2 = broker.read_file(
            RUN, TASK, 2, 3, "src/calc/calculations.py", allowed_files=None
        )
        assert out2.operation_id == "op-r-TASK-r-1-attempt-2-step-3"


class TestReadAndList:
    def test_read_returns_content(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.read_file(RUN, TASK, 1, 1, "README.md", allowed_files=None)
        assert out.ok and out.content == "hello\n"

    def test_list_files_returns_relative_paths(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.list_files(RUN, TASK, 1, 1, pattern="*.py")
        assert out.ok
        assert "src/calc/calculations.py" in out.matches
        assert "src/calc/other.py" in out.matches

    def test_search_code_finds_matches(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.search_code(RUN, TASK, 1, 1, "return a \\+ b")
        assert out.ok
        assert any("calculations.py" in m for m in out.matches)

    def test_inspect_changes_reads_real_artifact(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "src/calc/calculations.py",
            "def add(a, b):\n    return a * b\n",
            allowed_files=["src/calc/calculations.py"],
        )
        out = broker.inspect_changes(
            RUN, TASK, 1, 2, "src/calc/calculations.py", allowed_files=None
        )
        assert out.ok and "return a * b" in out.content


class TestNoPass:
    """The broker never grants PASS; it only records effects/blocks."""

    def test_observation_has_no_status_field(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.read_file(RUN, TASK, 1, 1, "README.md", allowed_files=None)
        assert not hasattr(out, "status")
        assert not hasattr(out, "passed")


class TestScopeOutOfAllowedFiles:
    """Writing outside allowed_files is blocked before any effect."""

    def test_write_outside_allowed_files_is_blocked(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        before = (workspace / "src" / "calc" / "other.py").read_text(encoding="utf-8")
        out = broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "src/calc/other.py",
            "y = 2\n",
            allowed_files=["src/calc/calculations.py"],
        )
        assert out.blocked and not out.ok
        assert "allowed_files" in out.reason
        assert (workspace / "src" / "calc" / "other.py").read_text(
            encoding="utf-8"
        ) == before

    def test_write_with_no_allowed_files_is_blocked(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.apply_patch(RUN, TASK, 1, 1, "README.md", "z", allowed_files=None)
        assert out.blocked
        assert "allowed_files" in out.reason

    def test_read_bound_to_disallowed_file_is_blocked(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.read_file(
            RUN,
            TASK,
            1,
            1,
            "src/calc/other.py",
            allowed_files=["src/calc/calculations.py"],
        )
        assert out.blocked

    def test_allowed_files_glob_membership(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "src/calc/calculations.py",
            "v = 0\n",
            allowed_files=["src/calc/*.py"],
        )
        assert out.ok


class TestTraversalAndAbsolute:
    """Path traversal and absolute paths are blocked before any effect."""

    def test_traversal_outside_root_is_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.read_file(
            RUN, TASK, 1, 1, "../../../etc/passwd", allowed_files=None
        )
        assert out.blocked
        assert "traversal" in out.reason or "escape" in out.reason

    def test_absolute_path_is_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.read_file(RUN, TASK, 1, 1, "/etc/passwd", allowed_files=None)
        assert out.blocked
        assert "absolute" in out.reason

    def test_traversal_write_blocked_before_effect(
        self, workspace: pathlib.Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        outside = tmp_path_factory.mktemp("outside")
        outside_file = outside / "secret.txt"
        outside_file.write_text("KEEP", encoding="utf-8")
        broker = _broker(workspace)
        rel = os.path.relpath(outside_file, workspace)
        out = broker.apply_patch(RUN, TASK, 1, 1, rel, "PWNED", allowed_files=[rel])
        assert out.blocked
        assert outside_file.read_text(encoding="utf-8") == "KEEP"


class TestSymlinkEscape:
    """A symlink inside the workspace pointing outside is blocked."""

    def test_symlink_escape_is_blocked(
        self, workspace: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        target = tmp_path.parent / "escape_target.txt"
        target.write_text("OUTSIDE", encoding="utf-8")
        link = workspace / "src" / "calc" / "link.py"
        try:
            os.symlink(target, link)
        except OSError:
            pytest.skip("symlinks not supported")
        broker = _broker(workspace)
        out = broker.read_file(
            RUN, TASK, 1, 1, "src/calc/link.py", allowed_files=["src/calc/link.py"]
        )
        assert out.blocked
        assert "symlink" in out.reason or "escape" in out.reason


class TestWorkspaceScope:
    """workspace_scope restricts the maximum directory scope."""

    def test_write_under_scope_dir_allowed(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace, scope=["src/calc"])
        out = broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "src/calc/calculations.py",
            "n = 1\n",
            allowed_files=["src/calc/calculations.py"],
        )
        assert out.ok

    def test_write_outside_scope_dir_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace, scope=["src/calc"])
        out = broker.apply_patch(
            RUN, TASK, 1, 1, "README.md", "m", allowed_files=["README.md"]
        )
        assert out.blocked
        assert "scope" in out.reason


class TestSizeLimits:
    def test_read_over_limit_is_blocked(self, workspace: pathlib.Path) -> None:
        big = workspace / "big.txt"
        big.write_text("a" * 64, encoding="utf-8")
        broker = ToolBroker(workspace_root=workspace, max_read_bytes=8)
        out = broker.read_file(RUN, TASK, 1, 1, "big.txt", allowed_files=None)
        assert out.blocked
        assert "read limit" in out.reason

    def test_write_over_limit_is_blocked_before_effect(
        self, workspace: pathlib.Path
    ) -> None:
        broker = ToolBroker(workspace_root=workspace, max_write_bytes=8)
        out = broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "src/calc/calculations.py",
            "x" * 64,
            allowed_files=["src/calc/calculations.py"],
        )
        assert out.blocked
        assert "write limit" in out.reason
        # the original file is unchanged (no partial effect)
        assert (workspace / "src" / "calc" / "calculations.py").read_text(
            encoding="utf-8"
        ) == "def add(a, b):\n    return a + b\n"


class TestNoPartialEffect:
    """A disallowed write leaves the fixture untouched."""

    def test_rejected_patch_leaves_file_unchanged(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        original = (workspace / "src" / "calc" / "calculations.py").read_text(
            encoding="utf-8"
        )
        broker.apply_patch(
            RUN,
            TASK,
            1,
            1,
            "src/calc/calculations.py",
            "WRONG",
            allowed_files=["src/calc/other.py"],
        )
        assert (workspace / "src" / "calc" / "calculations.py").read_text(
            encoding="utf-8"
        ) == original


class TestNoGeneralTerminal:
    """The broker exposes only file operations, not an arbitrary command path."""

    def test_broker_has_no_shell_or_exec_method(self) -> None:
        broker = ToolBroker(workspace_root=pathlib.Path("."))
        for forbidden in ("run_shell", "exec", "subprocess", "terminal", "shell"):
            assert not hasattr(broker, forbidden)
