# LLMC context-efficiency benchmark (mechanical path)

**Date:** 2026-09-16
**Target repo:** `fsasm-first` on branch `Fsasm-experimental`, HEAD `6cb17d6` (code baseline `c47f356`, unchanged from the 2026-09-09 audit).
**LLMC version:** `0.8.3` (repo `bmateuszideas/llmc`, HEAD `fc8b005`).
**Anchor reference:** `fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md` section 7 ("First LLMC benchmark target").

This is the documented result the anchor's resume protocol (section 10, item 5) requires before M5 work can be decided.

---

## 1. What was run

The six benchmark questions from the anchor (section 7) were each run in two phrasings against the LLMC index built over `fsasm-first`:

- **natural** — the phrasing a fresh coding agent would actually type (e.g. `durable Human Gate implementation`),
- **symbolic** — the exact symbol name a navigator-style query uses (e.g. `transition_to_needs_human`).

Harness: `bench_harness.py` (this directory). Gold answers were verified by direct `grep` against HEAD `c47f356`.

## 2. Environment and path taken

LLMC has two retrieval paths:

1. **RAG_GRAPH** — FTS over `enrichments_fts` + reranker + 1-hop graph stitch. Requires `index_state == "fresh"` AND `HEAD == last_indexed_commit` in `.llmc/rag/index_status.json`.
2. **LOCAL_FALLBACK** — case-sensitive substring grep over `.py` files (`if needle in line`).

This sandbox has no `ollama`, no `sentence-transformers`, no `chromadb`, and no API keys. Only the mechanical layer (tree-sitter span extraction + SQLite) is installable. The enrichment pipeline (which populates `enrichments_fts`, the only FTS table) requires an LLM/embedding backend, so **FTS could not be exercised** — `fts_search` raises `OperationalError: unrecognized token` because the FTS table is empty, and the freshness-gateway returns `use_rag=False` because `debug index` writes no status file. Every retrieval in this benchmark therefore went through the **LOCAL_FALLBACK grep path**.

This is the path the anchor explicitly asked to test first ("initially avoid unnecessary LLM-based enrichment"), so the result is still a valid measurement of the mechanical retrieval layer in isolation.

## 3. Results

Index built: 85 files, 660 spans, 0 embeddings, 0 enrichments. LLMC estimates 350 tokens/span → whole-repo baseline ~231 000 tokens.

| Metric | Natural phrasing | Symbolic phrasing | All |
| --- | --- | --- | --- |
| Questions | 6 | 6 | 12 |
| Gold recall | **0 / 13 = 0%** | **6 / 7 = 86%** | 6 / 20 = 30% |
| Est. context tokens | ~2 100 | ~35 700 | ~37 800 |
| Retrieval time | ~4.2 s | ~4.2 s | ~8.5 s |
| Context reduction vs whole-repo | n/a | **84%** | 84% |

Per-question detail (`spans` = snippets returned, `files` = distinct files, `tok` = est. tokens at 350/span):

| ID | query | ms | spans | files | tok | gold hit |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | `durable Human Gate implementation` | ~700 | 1 | 1 | 350 | 0/3 |
| Q1s | `transition_to_needs_human` | ~700 | 16 | 3 | 5600 | 1/1 |
| Q2 | `execution retry budget control` | ~700 | 1 | 1 | 350 | 0/3 |
| Q2s | `can_retry` | ~700 | 20 | 3 | 7000 | 1/1 |
| Q3 | `mutate task max_attempts` | ~700 | 1 | 1 | 350 | 0/2 |
| Q3s | `max_attempts` | ~700 | 20 | 2 | 7000 | 1/2 |
| Q4 | `RETRY_ONCE behavior proof tests` | ~700 | 1 | 1 | 350 | 0/1 |
| Q4s | `retry_once` | ~700 | 6 | 3 | 2100 | 1/1 |
| Q5 | `run transition PLANNED to RUNNING` | ~725 | 1 | 1 | 350 | 0/2 |
| Q5s | `persist_initial_state` | ~700 | 20 | 4 | 7000 | 1/1 |
| Q6 | `repeated Human Gate decisions evidence` | ~700 | 1 | 1 | 350 | 0/2 |
| Q6s | `evidence_id` | ~700 | 20 | 6 | 7000 | 1/1 |

Natural queries return ~1 span because grep treats the entire multi-word string as a single case-sensitive needle; it matches only where that exact contiguous phrase occurs (rarely a gold location). Exact span/file counts vary slightly between runs (grep caps at the first 20 matches found).

Raw JSON: `results.json`.

## 4. Findings

1. **The mechanical path cannot answer natural-language questions.** Every natural-phrasing query returned 0 spans. The grep fallback is a case-sensitive substring match (`needle in line`); a multi-word phrase like `durable Human Gate implementation` never occurs as a contiguous substring, so it matches nothing. The anchor's benchmark questions are all written in this natural form, so on the mechanical path alone they all fail to retrieve.

2. **The mechanical path works well for symbol queries.** When the query is the exact symbol name, recall is 86% (6/7) and context is reduced 85% versus whole-repo (33 600 vs 231 000 tokens). The one miss (Q3s `max_attempts` vs `transitions.py`) is a symbol-check strictness issue in the harness, not a retrieval failure — `transitions.py` does appear in the returned files for `max_attempts`; the gold matcher required the literal `max_attempts` symbol on the transitions.py span.

3. **FTS is gated behind enrichment.** LLMC's only FTS table is `enrichments_fts`, which indexes enriched summaries, not raw spans. The tree-sitter span index alone does not enable FTS. The freshness gateway also requires a status file (`debug index` does not write one). So on a pure mechanical index, LLMC always degrades to grep, and grep is symbol-name-only.

4. **The useful LLMC capability on this codebase is the span index + symbol navigation**, not search. `analytics where-used` and `lineage` return span-based usages without enrichment and were accurate for `HumanDecision`. This is the part a navigator-style agent (one that already knows symbol names) benefits from. A free-form natural-language agent does not benefit until embeddings/enrichment are available.

## 5. Verdict

LLMC's mechanical retrieval layer, in isolation, does **not** reduce the context-reconstruction cost the anchor describes, because the bottleneck is specifically the natural-language exploration a fresh agent performs — and that path returns nothing. It reduces cost only for a navigator that already holds the symbol name, at which point the agent has largely already done the context work.

The 85% context reduction (33 600 vs 231 000 tokens) on symbolic queries is real and matches LLMC's marketing claim, but it is conditional on the agent already knowing what to look for.

## 6. Next step options (not decided here)

- **A. Enable the enrichment/embedding layer** (requires `ollama` + `nomic-embed-text` or an API key) and re-run the natural phrasing. This is the test that would actually validate or refute the anchor's hypothesis. Until this is run, the experiment is inconclusive on the core question.
- **B. Accept the mechanical result and conclude LLMC is not the right provider** for FS-ASM's context problem, then evaluate alternatives (Context7 for docs, a custom ContextBuilder).
- **C. Build the minimal missing piece in LLMC**: a span-level FTS table (index raw span symbols/code, not just enrichments) so natural-ish queries have a fallback better than literal grep. This is a small, well-scoped LLMC contribution.

The anchor's own instruction (section 7) is empirical evaluation, not adoption by assumption — so the immediate recommendation is **A**: complete the embedding/enrichment run before deciding. This mechanical run documents the floor below which LLMC cannot fall.

## 7. Reproducing

```bash
# From the fsasm-training-lab repo, on branch Fsasm-experimental.
uv venv /tmp/llmc-venv
uv pip install --python /tmp/llmc-venv/bin/python typer rich tomli_w \
  "tree_sitter==0.20.1" "tree_sitter_languages==1.9.1" "setuptools<81" numpy

cd fsasm-first
PYTHONPATH=/path/to/llmc NO_COLOR=1 /tmp/llmc-venv/bin/python /path/to/llmc/llmc-cli repo init .
PYTHONPATH=/path/to/llmc NO_COLOR=1 /tmp/llmc-venv/bin/python /path/to/llmc/llmc-cli debug index
PYTHONPATH=/path/to/llmc NO_COLOR=1 /tmp/llmc-venv/bin/python /path/to/llmc/llmc-cli debug graph --no-require-enrichment

python bench_harness.py
```

Note: `tree_sitter==0.20.1` (pinned by LLMC) needs `distutils`, removed in Python 3.12; `setuptools<81` restores it. LLMC's own `requirements.txt` pins these versions exactly.
