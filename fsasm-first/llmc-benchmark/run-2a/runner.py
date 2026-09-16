#!/usr/bin/env python3
"""Run 2A recording harness: faithful trajectory logger for LLMC mechanical navigation.

Every LLMC operation and every source read goes through this so the trajectory
log reflects real command I/O, real timing, and real line ranges - not
reconstruction from memory. This enforces the Run 2A protocol mechanically:
the agent's tool calls are recorded exactly as executed.

Usage (from fsasm-first):
  python3 <this> search "human gate"          # LLMC search
  python3 <this> where-used HumanDecision    # analytics where-used
  python3 <this> lineage HumanDecision       # analytics lineage
  python3 <this> inspect HumanDecision       # debug inspect
  python3 <this> read src/fsasm/models.py 37 410  # targeted source read (path, start, end)
  python3 <this> span <symbol-substr>        # look up spans by symbol substring in index
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/workspace/github__bmateuszideas__fsasm-training-lab/fsasm-first")
LLMC = Path("/workspace/github__bmateuszideas__llmc")
PY = "/tmp/llmc-venv/bin/python"
TRAJ_DIR = REPO / "llmc-benchmark/run-2a/trajectories"
DB = REPO / ".rag/index_v2.db"

CURRENT_Q = os.environ.get("RUN2A_Q", "scratch")


def _log_path() -> Path:
    TRAJ_DIR.mkdir(parents=True, exist_ok=True)
    return TRAJ_DIR / f"{CURRENT_Q}.jsonl"


def _append(record: dict) -> None:
    record["t_ms"] = round(time.time() * 1000)
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def llmc_cli(args: list[str]) -> tuple[str, float]:
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["PYTHONPATH"] = str(LLMC)
    cmd = [PY, str(LLMC / "llmc-cli"), *args]
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(REPO), timeout=60)
    dt = time.perf_counter() - t0
    out = p.stdout
    if p.returncode != 0 and p.stderr:
        out += "\n[STDERR] " + p.stderr
    return out, dt


def op_search(query: str, limit: int = 20) -> None:
    out, dt = llmc_cli(["search", query, "--plain", "--limit", str(limit)])
    n = sum(1 for ln in out.splitlines() if ln and ln[0].isdigit() and ". " in ln[:5])
    _append({"op": "search", "query": query, "limit": limit, "elapsed_sec": round(dt, 3),
             "n_hits": n, "stdout": out})
    print(f"[search '{query}'] {n} hits, {dt*1000:.0f}ms")
    print(out)


def op_where_used(symbol: str) -> None:
    out, dt = llmc_cli(["analytics", "where-used", symbol])
    n = sum(1 for ln in out.splitlines() if ln and ln[0].isdigit() and ". " in ln[:5])
    _append({"op": "where-used", "symbol": symbol, "elapsed_sec": round(dt, 3),
             "n_hits": n, "stdout": out})
    print(f"[where-used '{symbol}'] {n} hits, {dt*1000:.0f}ms")
    print(out)


def op_lineage(symbol: str, direction: str = "") -> None:
    args = ["analytics", "lineage", symbol]
    if direction:
        args = ["analytics", "lineage", "--direction", direction, symbol]
    out, dt = llmc_cli(args)
    _append({"op": "lineage", "symbol": symbol, "direction": direction,
             "elapsed_sec": round(dt, 3), "stdout": out})
    print(f"[lineage '{symbol}']")
    print(out)


def op_inspect(symbol: str) -> None:
    out, dt = llmc_cli(["debug", "inspect", symbol])
    _append({"op": "inspect", "symbol": symbol, "elapsed_sec": round(dt, 3), "stdout": out})
    print(f"[inspect '{symbol}']")
    print(out)


def op_span(symbol_substr: str) -> None:
    """Look up spans whose symbol contains the substring, via the index DB directly."""
    t0 = time.perf_counter()
    c = sqlite3.connect(str(DB))
    rows = list(c.execute(
        "SELECT s.symbol, s.kind, s.start_line, s.end_line, f.path "
        "FROM spans s JOIN files f ON s.file_id=f.id "
        "WHERE s.symbol LIKE ? ORDER BY f.path, s.start_line",
        (f"%{symbol_substr}%",),
    ))
    c.close()
    dt = time.perf_counter() - t0
    _append({"op": "span", "symbol_substr": symbol_substr, "elapsed_sec": round(dt, 3),
             "n_hits": len(rows), "rows": [list(r) for r in rows]})
    print(f"[span '{symbol_substr}'] {len(rows)} hits, {dt*1000:.0f}ms")
    for r in rows:
        print(f"  {r[4]}:{r[2]}-{r[3]}  {r[0]} ({r[1]})")


def op_read(rel_path: str, start: int, end: int) -> None:
    """Targeted source read of a specific line range. Records exact content."""
    abs_path = REPO / rel_path
    t0 = time.perf_counter()
    try:
        lines = abs_path.read_text(encoding="utf-8").splitlines()
        slc = lines[start - 1:end]
        content = "\n".join(slc)
        nchars = len(content)
        nlines = len(slc)
        dt = time.perf_counter() - t0
        _append({"op": "read", "path": rel_path, "start_line": start, "end_line": end,
                 "n_lines": nlines, "n_chars": nchars, "elapsed_sec": round(dt, 3),
                 "content": content})
        print(f"[read {rel_path}:{start}-{end}] {nlines} lines, {nchars} chars, {dt*1000:.0f}ms")
        print(content)
    except Exception as e:
        dt = time.perf_counter() - t0
        _append({"op": "read_error", "path": rel_path, "start_line": start, "end_line": end,
                 "error": str(e), "elapsed_sec": round(dt, 3)})
        print(f"[read ERROR {rel_path}:{start}-{end}] {e}")


def op_list_symbols(rel_path: str) -> None:
    """List all spans/symbols in a given file via the index (no file read)."""
    t0 = time.perf_counter()
    c = sqlite3.connect(str(DB))
    rows = list(c.execute(
        "SELECT s.symbol, s.kind, s.start_line, s.end_line "
        "FROM spans s JOIN files f ON s.file_id=f.id WHERE f.path=? "
        "ORDER BY s.start_line",
        (rel_path,),
    ))
    c.close()
    dt = time.perf_counter() - t0
    _append({"op": "list_symbols", "path": rel_path, "elapsed_sec": round(dt, 3),
             "n_hits": len(rows), "rows": [list(r) for r in rows]})
    print(f"[list_symbols '{rel_path}'] {len(rows)} symbols, {dt*1000:.0f}ms")
    for r in rows:
        print(f"  {r[2]}-{r[3]}  {r[0]} ({r[1]})")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "search":
        op_search(sys.argv[2])
    elif cmd == "where-used":
        op_where_used(sys.argv[2])
    elif cmd == "lineage":
        op_lineage(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    elif cmd == "inspect":
        op_inspect(sys.argv[2])
    elif cmd == "span":
        op_span(sys.argv[2])
    elif cmd == "read":
        op_read(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    elif cmd == "list_symbols":
        op_list_symbols(sys.argv[2])
    else:
        print(f"unknown op: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
