"""T12 — Controlled run_checks and process isolation.

Proves the Tool Broker runs allowlisted checks in the workspace with process
isolation enforced in code before and during the effect: a trusted check runs
in the fixture and records exit code, stdout/stderr, duration and identity; a
non-allowlisted kind, an absolute/relative executable, shell interpolation,
argument injection, a NUL byte, a write outside the workspace, a timeout and a
missing executable are all controlled — blocked or recorded as a process
error / negative result. Every observation carries an ``operation_id`` and a
``check_kind`` and never grants PASS (architecture §27, §28, §29; canonical
TODO T12).
"""

import os
import pathlib
import sys

import pytest

from fsasm.models import CheckKind, ToolOperationKind
from fsasm.tool_broker import ToolBroker

RUN = "r"
TASK = "TASK-r-1"


@pytest.fixture()
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    # A tiny python helper at the workspace root so a CUSTOM `python helper.py`
    # check has a deterministic effect without path separators in argv.
    (tmp_path / "helper.py").write_text(
        "import sys\nprint('helper-ok')\nsys.exit(0)\n",
        encoding="utf-8",
    )
    # A helper that exits non-zero (a negative check result, not a crash).
    (tmp_path / "failing.py").write_text(
        "import sys\nprint('nope', file=sys.stderr)\nsys.exit(3)\n",
        encoding="utf-8",
    )
    # A helper that sleeps past the timeout.
    (tmp_path / "slow.py").write_text(
        "import time, sys\n"
        "print('starting', flush=True)\n"
        "time.sleep(30)\n"
        "print('done')\n",
        encoding="utf-8",
    )
    # A helper that prints more than the output cap.
    (tmp_path / "noisy.py").write_text(
        "print('A' * 4096)\n",
        encoding="utf-8",
    )
    return tmp_path


def _broker(
    root: pathlib.Path,
    *,
    timeout: float | None = None,
    max_output: int | None = None,
    env_allowlist: tuple[str, ...] | None = None,
) -> ToolBroker:
    kwargs: dict[str, object] = {"workspace_root": root, "workspace_scope": []}
    if timeout is not None:
        kwargs["check_timeout_seconds"] = timeout
    if max_output is not None:
        kwargs["check_max_output_bytes"] = max_output
    if env_allowlist is not None:
        kwargs["check_env_allowlist"] = env_allowlist
    return ToolBroker(**kwargs)  # type: ignore[arg-type]


class TestTrustedRunAndCapture:
    """A trusted check runs in the fixture and captures exit code, stdout, time."""

    def test_custom_python_runs_and_captures_output(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py"]
        )
        assert out.ok and not out.blocked
        assert out.kind is ToolOperationKind.RUN_CHECKS
        assert out.check_kind is CheckKind.CUSTOM
        assert out.exit_code == 0
        assert "helper-ok" in out.stdout
        assert out.duration_ms is not None and out.duration_ms >= 0
        assert out.operation_id == "op-r-TASK-r-1-attempt-1-step-1"
        assert not out.timed_out

    def test_negative_result_recorded_not_pass(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "failing.py"]
        )
        # A non-zero exit is a real, completed run — ok=True (it ran), not a block.
        assert out.ok and not out.blocked
        assert out.exit_code == 3
        assert "nope" in out.stderr
        # The broker never grants PASS; it has no status/passed field.
        assert not hasattr(out, "status")
        assert not hasattr(out, "passed")

    def test_operation_id_bound_to_attempt(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        a = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py"]
        )
        b = broker.run_checks(
            RUN, TASK, 2, 4, CheckKind.CUSTOM, ["python", "helper.py"]
        )
        assert a.operation_id == "op-r-TASK-r-1-attempt-1-step-1"
        assert b.operation_id == "op-r-TASK-r-1-attempt-2-step-4"
        assert a.operation_id != b.operation_id


class TestNoShellInterpolation:
    """The broker composes an argv list; no shell interprets model-supplied text."""

    def test_redirect_character_not_interpreted(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py", ">evil.txt"]
        )
        assert out.blocked and not out.ok
        assert "forbidden character" in out.reason
        # No file was created by a shell redirect.
        assert not (workspace / "evil.txt").exists()

    def test_command_separator_not_interpreted(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py; rm -rf ."]
        )
        assert out.blocked
        assert "forbidden character" in out.reason

    def test_dollar_substitution_not_interpreted(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py", "$HOME"]
        )
        assert out.blocked
        assert "forbidden character" in out.reason

    def test_backtick_not_interpreted(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py", "`whoami`"]
        )
        assert out.blocked
        assert "forbidden character" in out.reason


class TestAllowlistEnforcement:
    """Only allowlisted kinds and executables run; everything else is blocked."""

    def test_non_allowlisted_kind_string_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(RUN, TASK, 1, 1, "rm", ["-rf", "."])  # type: ignore[arg-type]
        assert out.blocked and not out.ok
        assert "unknown check kind" in out.reason

    def test_non_allowlisted_custom_executable_blocked(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, [sys.executable, "helper.py"]
        )
        assert out.blocked
        assert "not allowlisted" in out.reason

    def test_absolute_executable_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["/usr/bin/python", "helper.py"]
        )
        assert out.blocked
        assert "not allowlisted" in out.reason

    def test_relative_executable_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["./python", "helper.py"]
        )
        assert out.blocked
        assert "not allowlisted" in out.reason

    def test_custom_without_executable_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(RUN, TASK, 1, 1, CheckKind.CUSTOM, [])
        assert out.blocked
        assert "requires an executable" in out.reason


class TestNulByteAndPadding:
    def test_nul_byte_in_argument_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py\x00rm"]
        )
        assert out.blocked
        assert "NUL byte" in out.reason

    def test_padded_argument_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", " helper.py"]
        )
        assert out.blocked
        assert "padded" in out.reason

    def test_path_separator_in_custom_arg_blocked(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        # A subdirectory path as a trailing custom arg must be rejected (no
        # shell, no path injection through trailing args).
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "sub/dir.py"]
        )
        assert out.blocked
        assert "forbidden character" in out.reason


class TestTimeout:
    def test_timeout_terminates_process(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace, timeout=1.0)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "slow.py"]
        )
        assert not out.ok and not out.blocked
        assert out.timed_out
        assert "timed out" in out.reason
        assert out.exit_code is None
        assert out.check_kind is CheckKind.CUSTOM


class TestCwdPinnedToWorkspace:
    def test_check_runs_with_cwd_at_workspace_root(
        self, workspace: pathlib.Path
    ) -> None:
        # A helper that reports its cwd; the broker must pin cwd to the root.
        (workspace / "cwdreport.py").write_text(
            "import os, sys\nprint(os.getcwd())\nsys.exit(0)\n",
            encoding="utf-8",
        )
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "cwdreport.py"]
        )
        assert out.ok and out.exit_code == 0
        assert str(workspace) in out.stdout


class TestEnvironmentAllowlist:
    """Secrets in the parent env never reach the check child."""

    def test_secret_env_not_inherited(self, workspace: pathlib.Path) -> None:
        (workspace / "envreport.py").write_text(
            "import os, sys\n"
            "print(os.environ.get('FSASM_TEST_SECRET', 'MISSING'))\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        broker = _broker(workspace)
        # Poison the parent environment with a secret.
        os.environ["FSASM_TEST_SECRET"] = "super-secret-value"
        try:
            out = broker.run_checks(
                RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "envreport.py"]
            )
        finally:
            del os.environ["FSASM_TEST_SECRET"]
        assert out.ok and out.exit_code == 0
        assert "super-secret-value" not in out.stdout
        assert "MISSING" in out.stdout

    def test_allowlisted_env_inherited(self, workspace: pathlib.Path) -> None:
        (workspace / "pathreport.py").write_text(
            "import os, sys\n"
            "print('HAS_PATH' if 'PATH' in os.environ else 'NO_PATH')\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "pathreport.py"]
        )
        assert out.ok and out.exit_code == 0
        assert "HAS_PATH" in out.stdout

    def test_custom_env_allowlist_drops_path(self, workspace: pathlib.Path) -> None:
        # An empty allowlist means even PATH is dropped; `python` then cannot
        # be found, which surfaces as a process error (not a policy block).
        (workspace / "any.py").write_text("print('x')\n", encoding="utf-8")
        broker = _broker(workspace, env_allowlist=())
        out = broker.run_checks(RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "any.py"])
        assert not out.ok and not out.blocked
        assert out.exit_code is None
        assert "not found" in out.reason or "process error" in out.reason


class TestOutputTruncation:
    def test_large_output_truncated_with_marker(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace, max_output=64)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "noisy.py"]
        )
        assert out.ok
        assert out.truncated is True
        assert "[truncated]" in out.stdout
        assert len(out.stdout.encode("utf-8")) <= 64


class TestRecordedIdentity:
    def test_observation_records_check_kind_and_operation_id(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py"]
        )
        assert out.check_kind is CheckKind.CUSTOM
        assert out.kind is ToolOperationKind.RUN_CHECKS
        assert out.operation_id == "op-r-TASK-r-1-attempt-1-step-1"


class TestProcessError:
    def test_missing_executable_is_process_error(self, workspace: pathlib.Path) -> None:
        # An allowlisted bare name that cannot be resolved (empty env -> no PATH
        # to find `python` outside the default system dirs) is a process error,
        # not a policy block and not a negative result.
        (workspace / "any.py").write_text("print('x')\n", encoding="utf-8")
        broker = _broker(workspace, env_allowlist=())
        out = broker.run_checks(RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "any.py"])
        assert not out.ok and not out.blocked
        assert out.exit_code is None
        assert out.check_kind is CheckKind.CUSTOM
        assert "not found" in out.reason or "process error" in out.reason


class TestPytestFileCheckPath:
    """PYTEST_FILE takes exactly one workspace-contained test path argument."""

    def test_pytest_file_requires_exactly_one_arg(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(RUN, TASK, 1, 1, CheckKind.PYTEST_FILE, [])
        assert out.blocked
        assert "exactly one" in out.reason

    def test_pytest_file_traversal_path_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.PYTEST_FILE, ["../../../etc/passwd"]
        )
        assert out.blocked
        assert "traversal" in out.reason or "escape" in out.reason

    def test_pytest_file_absolute_path_blocked(self, workspace: pathlib.Path) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(RUN, TASK, 1, 1, CheckKind.PYTEST_FILE, ["/etc/passwd"])
        assert out.blocked
        assert "absolute" in out.reason


class TestNoPassAndNoGeneralTerminal:
    """The broker records effects; it never grants PASS or a general terminal."""

    def test_run_checks_observation_has_no_status_field(
        self, workspace: pathlib.Path
    ) -> None:
        broker = _broker(workspace)
        out = broker.run_checks(
            RUN, TASK, 1, 1, CheckKind.CUSTOM, ["python", "helper.py"]
        )
        assert not hasattr(out, "status")
        assert not hasattr(out, "passed")

    def test_broker_exposes_no_shell_method(self) -> None:
        broker = ToolBroker(workspace_root=pathlib.Path("."))
        for forbidden in ("run_shell", "exec", "subprocess", "terminal", "shell"):
            assert not hasattr(broker, forbidden)
