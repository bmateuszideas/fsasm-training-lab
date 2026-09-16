# FS-ASM Training Lab

**FS-ASM — File System as State Machine** is a research/education project for an external, persistent state machine controlling AI-agent work. Historical meaning and long-term architecture are documented separately from the current implementation. Core principle: **deterministic code owns state, transitions, permissions and verification; replaceable LLM components propose or perform bounded semantic work.** A model's claim of completion is not independent evidence.

> **START HERE — CURRENT STATUS:** [fsasm-first/PROJECT_STATUS.md](fsasm-first/PROJECT_STATUS.md). Read this dated snapshot, then check actual Git HEAD, merged PRs, source and CI. Do not rely on the README, an old chat, or a historical anchor as a live status feed.

## Where things live

| Path | Contents |
| --- | --- |
| [`fsasm-first/`](fsasm-first/) | Current Mistral Workflows training lab: runtime code, tests, operations and project governance |
| [`fsasm-first/PROJECT_STATUS.md`](fsasm-first/PROJECT_STATUS.md) | **One current status/next-action snapshot** and open M4 stabilization queue |
| [`fsasm-first/docs/DOCUMENTATION_MAP.md`](fsasm-first/docs/DOCUMENTATION_MAP.md) | Document roles, precedence, conflict resolution and context handoff |
| [`fsasm-first/docs/BRANCH_POLICY.md`](fsasm-first/docs/BRANCH_POLICY.md) | Branch roles, atomic PRs, integration/release gates and non-destructive cleanup |
| [`fsasm-first/docs/CURRENT_FSASM_MODEL.md`](fsasm-first/docs/CURRENT_FSASM_MODEL.md) | Approved long-term model and rationale, not a claim that future milestones exist |
| [`fsasm-first/AGENTS.md`](fsasm-first/AGENTS.md) | Engineering contract and historical milestones; see current status for completed stages |
| [`fsasm-first/IMPLEMENTATION_SUMMARY.md`](fsasm-first/IMPLEMENTATION_SUMMARY.md) | Milestone implementation reference, not live status after later PRs |
| [`fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md`](fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md) | Dated historical running record, including superseded pause/LLMC instructions; **not an active command list** |
| [`stare dokumenty rozwojowe fsasm/`](stare%20dokumenty%20rozwojowe%20fsasm/) | Deduplicated historical FS-ASM specifications and audits; preserve as research evidence |

## Branches — do not confuse names with freshness

- **`Fsasm-experimental`**: active implementation/integration for the runtime, M4 stabilization in progress. New changes go via focused task branches and PRs, not direct changes to `main`.
- **`main`**: GitHub default, but currently older/diverged for the runtime and contains historical LLMC benchmark work. It is **not** the latest release of the experimental runtime. Integration is a separate decision.
- **`Fsasm-llmc-testingbranch`**: frozen research baseline. LLMC is deferred and not integrated into FS-ASM.
- Other old `vibe/*` and check branches are cleanup candidates only after verifying ancestry/reference and explicit authorization. No automatic deletion, merge, force push or default-branch change.

See [branch policy](fsasm-first/docs/BRANCH_POLICY.md) for a dated inventory and process. GitHub may move after this document is written: always check the refs.

## Implementation boundary — 16 September 2026 snapshot

M1, M2 and M3 are CLOSED. M4 has implemented bounded retries and a Workflows Human Gate; **M4 remains in stabilization, not CLOSED**. M5 Context Builder is NOT STARTED. The M4 executor is a deterministic STUB and performs exactly one selected ChildTask, possibly with retries; no real coding executor, independent test-artifact proof, complete plan execution or operational run recovery is implemented. Current detailed scope, accepted fixes and open F3–F8 tasks are in [PROJECT_STATUS](fsasm-first/PROJECT_STATUS.md). This is dated, not a substitute for checking current code.

## Development entry

For a fresh coding model: read `PROJECT_STATUS.md`, confirm branch/HEAD, then read `docs/CURRENT_FSASM_MODEL.md`, stable rules in `AGENTS.md`, the documentation map and only the relevant files/tests for the approved atomic task. Read `fsasm-first/.agents/skills/workflows/SKILL.md` before touching the Mistral SDK. Do not start M5 or LLMC work from superseded instructions.

For installation, worker and test commands see [`fsasm-first/README.md`](fsasm-first/README.md). Do not use production runtime data as a pytest fixture; several legacy tests need further isolation.

## History and research

FS-ASM evolved from a human-mediated Planner (ChatGPT) → filesystem handoff → Coding Executor (Codex) workflow. The historical archive preserves those iterations; they are not instructions to reimplement old FS-ASM literally. LLMC results are on `main` under `fsasm-first/llmc-benchmark/`; the benchmark has known scoring/corpus methodology limitations, is not a proven runtime dependency, and future adoption requires a separate decision. Earlier versions of this README and the anchor remain available in Git history.
