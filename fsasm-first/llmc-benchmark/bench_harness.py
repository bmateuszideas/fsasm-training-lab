#!/usr/bin/env python3
"""LLMC context-efficiency benchmark harness for fsasm-first (M4).

Implements the benchmark described in fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md
section 7 ("First LLMC benchmark target").

For each benchmark question it:
  - runs an LLMC retrieval (FTS/grep fallback path, no embeddings available),
  - measures wall-clock time,
  - counts returned spans / distinct files,
  - estimates context tokens sent to a coding model (LLMC default 350 tok/span),
  - checks recall against a manually verified gold answer set.

Mechanical path only: no embeddings, no enrichment, no LLM round-trip.
This measures the retrieval layer in isolation, as the anchor requires
("initially avoid unnecessary LLM-based enrichment").
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Resolve repo root from the location of this file (llmc-benchmark/ is inside fsasm-first).
_REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(os.environ.get("BENCH_REPO_ROOT", _REPO_ROOT))
LLMC_ROOT = Path(os.environ.get("LLMC_ROOT", "/workspace/github__bmateuszideas__llmc"))
EST_TOKENS_PER_SPAN = 350  # LLMC DEFAULT_EST_TOKENS_PER_SPAN

sys.path.insert(0, str(LLMC_ROOT))
os.chdir(REPO_ROOT)


@dataclass
class GoldAnswer:
    """A manually verified relevant location for a benchmark question."""
    file_substring: str          # substring that must appear in a returned path
    symbol_substring: str = ""   # substring that must appear in a returned symbol (optional)


@dataclass
class BenchQuestion:
    id: str
    query: str
    gold: list[GoldAnswer] = field(default_factory=list)
    rationale: str = ""


@dataclass
class QuestionResult:
    id: str
    query: str
    elapsed_sec: float
    n_spans: int
    n_files: int
    est_context_tokens: int
    returned_paths: list[str]
    hit_gold: list[str]      # gold answer ids that were found
    missed_gold: list[str]   # gold answer ids NOT found
    error: str | None = None


# Gold answers verified against HEAD c47f356 / branch Fsasm-experimental by direct grep.
# Each anchor question (section 7) is run in TWO forms:
#   - "natural": the phrasing a fresh coding agent would actually ask (anchor section 7).
#   - "symbolic": the exact symbol name a navigator-style query would use.
# This exposes the mechanical-path limitation (grep fallback is case-sensitive
# substring match; natural-language phrasing fails without embeddings/enrichment).
QUESTIONS: list[BenchQuestion] = [
    BenchQuestion(
        id="Q1",
        query="durable Human Gate implementation",
        gold=[
            GoldAnswer("fsasm_milestone_four.py", "transition_to_needs_human"),
            GoldAnswer("fsasm_milestone_four.py", "receive_human_decision"),
            GoldAnswer("fsasm_milestone_four.py", "validate_and_apply_human_decision"),
        ],
        rationale="Where is the durable Human Gate implemented? (natural phrasing)",
    ),
    BenchQuestion(
        id="Q1s",
        query="transition_to_needs_human",
        gold=[
            GoldAnswer("fsasm_milestone_four.py", "transition_to_needs_human"),
        ],
        rationale="Where is the durable Human Gate implemented? (symbolic phrasing)",
    ),
    BenchQuestion(
        id="Q2",
        query="execution retry budget control",
        gold=[
            GoldAnswer("models.py", "can_retry"),
            GoldAnswer("models.py", "retry_count_remaining"),
            GoldAnswer("fsasm_milestone_four.py", "check_retry_budget"),
        ],
        rationale="What controls the execution retry budget? (natural phrasing)",
    ),
    BenchQuestion(
        id="Q2s",
        query="can_retry",
        gold=[
            GoldAnswer("models.py", "can_retry"),
        ],
        rationale="What controls the execution retry budget? (symbolic phrasing)",
    ),
    BenchQuestion(
        id="Q3",
        query="mutate task max_attempts",
        gold=[
            GoldAnswer("models.py", "max_attempts"),
            GoldAnswer("transitions.py", "max_attempts"),
        ],
        rationale="Find every relevant path that can mutate task.max_attempts. (natural phrasing)",
    ),
    BenchQuestion(
        id="Q3s",
        query="max_attempts",
        gold=[
            GoldAnswer("models.py", "max_attempts"),
            GoldAnswer("transitions.py", "max_attempts"),
        ],
        rationale="Find every relevant path that can mutate task.max_attempts. (symbolic phrasing)",
    ),
    BenchQuestion(
        id="Q4",
        query="RETRY_ONCE behavior proof tests",
        gold=[
            GoldAnswer("test_fsasm_milestone_four.py", "retry_once"),
        ],
        rationale="Which tests prove RETRY_ONCE behavior? (natural phrasing)",
    ),
    BenchQuestion(
        id="Q4s",
        query="retry_once",
        gold=[
            GoldAnswer("test_fsasm_milestone_four.py", "retry_once"),
        ],
        rationale="Which tests prove RETRY_ONCE behavior? (symbolic phrasing)",
    ),
    BenchQuestion(
        id="Q5",
        query="run transition PLANNED to RUNNING",
        gold=[
            GoldAnswer("transitions.py", "PLANNED"),
            GoldAnswer("fsasm_milestone_four.py", "persist_initial_state"),
        ],
        rationale="Which code transitions a run from PLANNED to RUNNING? (natural phrasing)",
    ),
    BenchQuestion(
        id="Q5s",
        query="persist_initial_state",
        gold=[
            GoldAnswer("fsasm_milestone_four.py", "persist_initial_state"),
        ],
        rationale="Which code transitions a run from PLANNED to RUNNING? (symbolic phrasing)",
    ),
    BenchQuestion(
        id="Q6",
        query="repeated Human Gate decisions evidence",
        gold=[
            GoldAnswer("fsasm_milestone_four.py", "evidence_id"),
            GoldAnswer("persistence.py", "save_evidence"),
        ],
        rationale="What code and tests are relevant to repeated Human Gate decisions? (natural phrasing)",
    ),
    BenchQuestion(
        id="Q6s",
        query="evidence_id",
        gold=[
            GoldAnswer("fsasm_milestone_four.py", "evidence_id"),
        ],
        rationale="What code and tests are relevant to repeated Human Gate decisions? (symbolic phrasing)",
    ),
]


def run_search(query: str, limit: int = 20) -> tuple[list[dict], float, str | None]:
    """Run the unified LLMC search command and parse JSON results."""
    import subprocess

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["PYTHONPATH"] = str(LLMC_ROOT)
    cmd = [
        os.environ.get("BENCH_PYTHON", "/tmp/llmc-venv/bin/python"),
        str(LLMC_ROOT / "llmc-cli"),
        "search",
        query,
        "--json",
        "--limit",
        str(limit),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), timeout=60)
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        return [], elapsed, proc.stderr.strip() or f"exit {proc.returncode}"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return [], elapsed, f"JSON parse error: {e}"
    items = data.get("items", [])
    source = data.get("source", "UNKNOWN")
    return items, elapsed, (None if source != "ERROR" else f"source={source}")


def evaluate(q: BenchQuestion, items: list[dict], elapsed: float, error: str | None) -> QuestionResult:
    paths: list[str] = []
    for it in items:
        loc = it.get("snippet", {}).get("location", {})
        p = loc.get("path", it.get("file", ""))
        if p:
            paths.append(p)

    # Deduplicate files while preserving order.
    seen = set()
    distinct_files = []
    for p in paths:
        key = p.split(":")[0] if ":" in p else p
        if key not in seen:
            seen.add(key)
            distinct_files.append(key)

    n_spans = len(items)
    est_tokens = n_spans * EST_TOKENS_PER_SPAN

    hit, missed = [], []
    for i, g in enumerate(q.gold):
        found = False
        for p in paths:
            if g.file_substring in p:
                if not g.symbol_substring:
                    found = True
                    break
                # symbol check: search across item symbol + snippet text
                for it in items:
                    loc = it.get("snippet", {}).get("location", {})
                    ip = loc.get("path", it.get("file", ""))
                    sym = it.get("symbol", "") or ""
                    txt = it.get("snippet", {}).get("text", "") or ""
                    if g.file_substring in ip and (
                        g.symbol_substring.lower() in sym.lower()
                        or g.symbol_substring.lower() in txt.lower()
                    ):
                        found = True
                        break
            if found:
                break
        (hit if found else missed).append(f"{q.id}.G{i+1}({g.file_substring}:{g.symbol_substring})")

    return QuestionResult(
        id=q.id,
        query=q.query,
        elapsed_sec=elapsed,
        n_spans=n_spans,
        n_files=len(distinct_files),
        est_context_tokens=est_tokens,
        returned_paths=distinct_files[:15],
        hit_gold=hit,
        missed_gold=missed,
        error=error,
    )


def main() -> int:
    print(f"# LLMC context-efficiency benchmark: fsasm-first (M4, branch Fsasm-experimental)")
    print(f"# repo: {REPO_ROOT}")
    print(f"# est tokens/span (LLMC default): {EST_TOKENS_PER_SPAN}")
    print(f"# mechanical path only (no embeddings, no enrichment, no LLM round-trip)\n")

    results: list[QuestionResult] = []
    for q in QUESTIONS:
        items, elapsed, error = run_search(q.query)
        r = evaluate(q, items, elapsed, error)
        results.append(r)
        status = "OK" if r.error is None else f"ERR: {r.error}"
        print(f"[{r.id}] {r.query!r}")
        print(f"    {status} | {r.elapsed_sec*1000:.0f} ms | spans={r.n_spans} | files={r.n_files} | est_tok={r.est_context_tokens}")
        print(f"    hit {len(r.hit_gold)}/{len(q.gold)} gold; missed={r.missed_gold}")
        if r.returned_paths:
            print(f"    top files: {', '.join(r.returned_paths[:5])}")
        print()

    # Aggregate.
    total_spans = sum(r.n_spans for r in results)
    total_tokens = sum(r.est_context_tokens for r in results)
    total_time = sum(r.elapsed_sec for r in results)
    total_gold = sum(len(q.gold) for q in QUESTIONS)
    total_hit = sum(len(r.hit_gold) for r in results)
    recall = total_hit / total_gold if total_gold else 0.0

    print("# === Aggregate ===")
    print(f"# questions: {len(QUESTIONS)}")
    print(f"# total retrieval time: {total_time*1000:.0f} ms")
    print(f"# total spans returned: {total_spans}")
    print(f"# total est context tokens: {total_tokens}")
    print(f"# gold recall: {total_hit}/{total_gold} = {recall:.0%}")

    # Baseline: whole-repo exploration would send ~231 000 tokens (660 spans x 350).
    repo_tokens = 660 * EST_TOKENS_PER_SPAN
    print(f"# whole-repo baseline: ~{repo_tokens:,} tokens (660 spans)")
    if total_tokens:
        print(f"# context reduction vs whole-repo: {(1 - total_tokens/repo_tokens):.0%}")

    # Split natural vs symbolic.
    nat = [r for r in results if not r.id.endswith("s")]
    sym = [r for r in results if r.id.endswith("s")]
    nat_gold = sum(len(q.gold) for q in QUESTIONS if not q.id.endswith("s"))
    sym_gold = sum(len(q.gold) for q in QUESTIONS if q.id.endswith("s"))
    nat_hit = sum(len(r.hit_gold) for r in nat)
    sym_hit = sum(len(r.hit_gold) for r in sym)
    nat_tok = sum(r.est_context_tokens for r in nat)
    sym_tok = sum(r.est_context_tokens for r in sym)
    print(f"# natural recall:  {nat_hit}/{nat_gold} = {nat_hit/nat_gold:.0%} | tokens={nat_tok}")
    print(f"# symbolic recall: {sym_hit}/{sym_gold} = {sym_hit/sym_gold:.0%} | tokens={sym_tok}")

    out = {
        "config": {
            "repo": str(REPO_ROOT),
            "est_tokens_per_span": EST_TOKENS_PER_SPAN,
            "path": "mechanical (FTS/grep fallback, no embeddings)",
        },
        "questions": [
            {
                "id": r.id, "query": r.query, "rationale": next(q.rationale for q in QUESTIONS if q.id == r.id),
                "elapsed_sec": r.elapsed_sec, "n_spans": r.n_spans, "n_files": r.n_files,
                "est_context_tokens": r.est_context_tokens, "returned_paths": r.returned_paths,
                "hit_gold": r.hit_gold, "missed_gold": r.missed_gold, "error": r.error,
            }
            for r in results
        ],
        "aggregate": {
            "total_retrieval_sec": total_time,
            "total_spans": total_spans,
            "total_est_context_tokens": total_tokens,
            "gold_recall": recall,
            "whole_repo_baseline_tokens": repo_tokens,
            "context_reduction_pct": (1 - total_tokens / repo_tokens) if total_tokens else None,
            "natural_recall": nat_hit / nat_gold if nat_gold else 0,
            "symbolic_recall": sym_hit / sym_gold if sym_gold else 0,
            "natural_tokens": nat_tok,
            "symbolic_tokens": sym_tok,
        },
    }
    Path("/tmp/llmc_bench/results.json").write_text(json.dumps(out, indent=2))
    print("\n# results written to /tmp/llmc_bench/results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
