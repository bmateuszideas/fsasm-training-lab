"""FS-ASM Runtime v1  diagnostic tool (doctor).

Run as: ``python -m entrypoints.doctor`` or ``uv run python -m entrypoints.doctor``.

Checks:
- Python version and platform
- uv availability and version
- Installed package versions (fsasm-first, mistralai-workflows, pydantic, httpx)
- Workflows connectivity (optional: only if MISTRAL_WORKFLOWS_HOST is set)
- Local model endpoint (optional: only if FSASM_LOCAL_MODEL_ENDPOINT is set)
- Mistral API roles (optional: only if FSASM_MISTRAL_API_KEY is set)
- Filesystem permissions (read/write on workspace/runs)
- Workspace structure (src/fsasm, src/workflows, etc.)

The doctor never requires Vibe or GitHub; it only inspects the local environment.
No secrets are logged or exposed.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


def _python_check() -> dict[str, Any]:
    """Check Python version and implementation."""
    return {
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "python_compiler": platform.python_compiler(),
        "platform": platform.platform(),
        "ok": sys.version_info >= (3, 12),
        "hint": "FS-ASM requires Python >= 3.12",
    }


def _uv_check() -> dict[str, Any]:
    """Check uv availability and version."""
    try:
        result = subprocess.run(
            ["uv", "--version"], capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip() if result.returncode == 0 else None
        return {
            "uv_found": result.returncode == 0,
            "uv_version": version,
            "ok": result.returncode == 0,
            "hint": "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh",
        }
    except Exception:
        return {"uv_found": False, "uv_version": None, "ok": False, "hint": None}


def _package_check() -> dict[str, Any]:
    """Check installed package versions via uv or import."""
    packages = ["fsasm-first", "mistralai-workflows", "pydantic", "httpx"]
    versions: dict[str, str | None] = {}
    ok = True
    try:
        import importlib.metadata as metadata
        for pkg in packages:
            try:
                versions[pkg] = metadata.version(pkg)
            except metadata.PackageNotFoundError:
                versions[pkg] = None
                ok = False
    except ImportError:
        # Fallback: try uv list
        try:
            result = subprocess.run(
                ["uv", "list", "--format", "json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for pkg in packages:
                    versions[pkg] = data.get(pkg, {}).get("version")
        except Exception:
            pass
    return {"packages": versions, "ok": ok, "hint": "Run: uv sync"}


def _workflows_connectivity_check() -> dict[str, Any]:
    """Check Mistral Workflows (Temporal) connectivity (optional)."""
    host = os.getenv("MISTRAL_WORKFLOWS_HOST")
    if not host:
        return {
            "skipped": True,
            "reason": "MISTRAL_WORKFLOWS_HOST not set",
            "ok": True,
            "hint": "Set MISTRAL_WORKFLOWS_HOST to check connectivity",
        }
    try:
        import httpx
        timeout = httpx.Timeout(5.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{host}/api/v1/workflows")
            ok = response.status_code in (200, 401, 403)
            return {
                "host": host,
                "reachable": ok,
                "status_code": response.status_code,
                "ok": ok,
                "hint": None,
            }
    except Exception as e:
        return {
            "host": host,
            "reachable": False,
            "error": str(e),
            "ok": False,
            "hint": "Check Temporal server and network",
        }


def _local_model_endpoint_check() -> dict[str, Any]:
    """Check local model inference endpoint (optional)."""
    endpoint = os.getenv("FSASM_LOCAL_MODEL_ENDPOINT")
    if not endpoint:
        return {
            "skipped": True,
            "reason": "FSASM_LOCAL_MODEL_ENDPOINT not set",
            "ok": True,
            "hint": "Set FSASM_LOCAL_MODEL_ENDPOINT to check local inference",
        }
    try:
        import httpx
        timeout = httpx.Timeout(5.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{endpoint}/health")
            ok = response.status_code == 200
            return {
                "endpoint": endpoint,
                "reachable": ok,
                "status_code": response.status_code,
                "ok": ok,
                "hint": None,
            }
    except Exception as e:
        return {
            "endpoint": endpoint,
            "reachable": False,
            "error": str(e),
            "ok": False,
            "hint": "Check local model server",
        }


def _mistral_api_roles_check() -> dict[str, Any]:
    """Check Mistral API roles configuration (optional)."""
    api_key = os.getenv("FSASM_MISTRAL_API_KEY") or os.getenv("MISTRAL_API_KEY")
    if not api_key:
        return {
            "skipped": True,
            "reason": "FSASM_MISTRAL_API_KEY or MISTRAL_API_KEY not set",
            "ok": True,
            "hint": "Set API key to check Mistral roles",
        }
    try:
        import httpx
        timeout = httpx.Timeout(5.0)
        headers = {"Authorization": f"Bearer {api_key}"}
        with httpx.Client(timeout=timeout) as client:
            response = client.get("https://api.mistral.ai/api/v1/models", headers=headers)
            ok = response.status_code in (200, 401, 403)
            return {
                "reachable": ok,
                "status_code": response.status_code,
                "ok": ok,
                "hint": None,
            }
    except Exception as e:
        return {
            "reachable": False,
            "error": str(e),
            "ok": False,
            "hint": "Check Mistral API key and network",
        }


def _filesystem_check() -> dict[str, Any]:
    """Check filesystem permissions for workspace and runs."""
    cwd = Path.cwd()
    src = cwd / "src"
    fsasm = cwd / "src" / "fsasm"
    runs = cwd / "runtime" / "runs"

    def _check_path(p: Path) -> tuple[bool, bool, bool]:
        exists = p.exists()
        readable = os.access(p, os.R_OK) if exists else False
        writable = os.access(p, os.W_OK) if exists else False
        return exists, readable, writable

    checks = {
        "cwd": _check_path(cwd),
        "src": _check_path(src),
        "src/fsasm": _check_path(fsasm),
        "runtime/runs": _check_path(runs),
    }
    ok = all(exists for exists, _, _ in checks.values())
    hints: list[str] = []
    for name, (exists, readable, writable) in checks.items():
        if not exists:
            hints.append(f"{name} does not exist (will be created on first use)")
        elif not readable:
            hints.append(f"{name} is not readable")
        elif not writable:
            hints.append(f"{name} is not writable")
    return {"checks": checks, "ok": ok, "hint": "; ".join(hints) if hints else None}


def _workspace_structure_check() -> dict[str, Any]:
    """Check that key workspace directories and files exist."""
    cwd = Path.cwd()
    expected = [
        "src/fsasm",
        "src/workflows",
        "src/entrypoints",
        "pyproject.toml",
    ]
    missing = []
    for path in expected:
        if not (cwd / path).exists():
            missing.append(path)
    ok = not missing
    return {
        "missing": missing,
        "ok": ok,
        "hint": f"Missing: {missing}" if missing else None,
    }


def _overall_status(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute overall status from individual reports."""
    all_ok = all(r.get("ok", True) for r in reports)
    skipped = [r for r in reports if r.get("skipped")]
    failed = [r for r in reports if not r.get("ok") and not r.get("skipped")]
    return {
        "all_ok": all_ok,
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "skipped": [r.get("reason", "unknown") for r in skipped],
        "failed": [r.get("reason", r.get("error", "unknown")) for r in failed],
    }


def _print_report(report: dict[str, Any], title: str, indent: int = 0) -> None:
    """Pretty-print a report section."""
    prefix = "  " * indent
    status = "[32mOK[0m" if report.get("ok") else "[31mFAIL[0m"
    if report.get("skipped"):
        status = "[33mSKIP[0m"
    print(f"{prefix}{title}: {status}")
    if "hint" in report and report["hint"]:
        print(f"{prefix}  Hint: {report['hint']}")
    for key, value in report.items():
        if key in ("ok", "skipped", "hint", "reason", "error"):
            continue
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, (str, int, bool)) and v is not None:
                    print(f"{prefix}  {k}: {v}")
        elif isinstance(value, (str, int, bool)) and value is not None:
            print(f"{prefix}  {key}: {value}")


def main() -> int:
    """Run all diagnostic checks and print a report."""
    print("=" * 60)
    print("FS-ASM Runtime v1  Doctor Diagnostic")
    print("=" * 60)
    print()

    reports = []

    # Core checks (always run)
    print("--- Core ---")
    py = _python_check()
    _print_report(py, "Python")
    reports.append(py)

    uv = _uv_check()
    _print_report(uv, "uv")
    reports.append(uv)

    pkg = _package_check()
    _print_report(pkg, "Packages")
    for name, ver in pkg["packages"].items():
        print(f"    {name}: {ver}")
    reports.append(pkg)

    fs = _filesystem_check()
    _print_report(fs, "Filesystem")
    reports.append(fs)

    ws = _workspace_structure_check()
    _print_report(ws, "Workspace structure")
    reports.append(ws)

    # Optional checks
    print()
    print("--- Optional (set env vars to enable) ---")
    wf = _workflows_connectivity_check()
    _print_report(wf, "Workflows connectivity")
    reports.append(wf)

    local = _local_model_endpoint_check()
    _print_report(local, "Local model endpoint")
    reports.append(local)

    mistral = _mistral_api_roles_check()
    _print_report(mistral, "Mistral API roles")
    reports.append(mistral)

    # Overall
    print()
    print("--- Overall ---")
    overall = _overall_status(reports)
    if overall["all_ok"]:
        print("[32mAll checks passed![0m")
    else:
        print(f"\n[31m{overall['failed_count']} failed, {overall['skipped_count']} skipped[0m")
        if overall["failed"]:
            for f in overall["failed"]:
                print(f"  - {f}")
    print()
    print("Note: FS-ASM Runtime v1 does NOT require Vibe or GitHub during operation.")
    print("      This doctor only inspects the local environment.")

    return 0 if overall["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
