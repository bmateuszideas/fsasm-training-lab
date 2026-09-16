# fsasm-first — FS-ASM runtime training lab

This is the active Mistral Workflows implementation sandbox, **not** the entire historical FS-ASM. The project contains M1–M4 code and tests; M4 is in stabilization, the Executor is still a deterministic stub, and M5 has not started. Never infer actual implementation status from an old milestone instruction or an example workflow.

## Start here (especially a new coding agent)

1. Read [PROJECT_STATUS.md](PROJECT_STATUS.md) for the dated current state, source branch, known fixes/open tasks and one next action. **Verify actual Git branch/HEAD/PR/CI before editing.**
2. Read [documentation map](docs/DOCUMENTATION_MAP.md) for source roles and conflict resolution and [branch policy](docs/BRANCH_POLICY.md) for the PR workflow.
3. Read [current FS-ASM model](docs/CURRENT_FSASM_MODEL.md) for long-term intent and [AGENTS.md](AGENTS.md) for stable implementation rules; M1 bootstrap phrases in AGENTS are historical relative to the status snapshot.
4. Inspect only the chosen atomic task's source and tests. Use [.agents/skills/workflows/SKILL.md](.agents/skills/workflows/SKILL.md) before writing SDK code.
5. [CURRENT_DEVELOPMENT_ANCHOR.md](CURRENT_DEVELOPMENT_ANCHOR.md) is a *historical chronological record* containing superseded pause/LLMC instructions; do not follow those as current work orders. [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) is an implementation reference, not a live progress tracker.

The previous README pointed to `ORIGIN_AND_CURRENT_UNDERSTANDING.md`, `docs/FSASM_SOURCE_AUDIT.md`, and `docs/FSASM_SOURCE_INVENTORY.md`, which are not in this checkout. Their historical context belongs to the Git history and the top-level [historical archive](../stare%20dokumenty%20rozwojowe%20fsasm/), not to a mandatory broken startup checklist.

## Setup and checks

```bash
uv sync --frozen
uv run pytest -q
make check
```

Run tests in an isolated checkout or environment: some legacy tests can access the default `./runtime` folder. Do not run them in a directory containing valuable runtime data. Live Mistral API tests are opt-in, and a green stub suite is not proof of real coding work.

## Run workers and examples

```bash
make start-worker
# In a separate terminal:
make execute workflow=hello-world input='{"name":"World"}'
```

`src/workflows/` contains the FS-ASM milestone workflows plus the preserved `hello-world` scaffold. `src/fsasm/` holds the domain models, transitions, adapters, verifier and persistence. `tests/` holds unit and workflow worker regression tests. `src/entrypoints/` holds startup and execution entrypoints; `worker.py` is an entrypoint wrapper.

`src/examples/` contains standalone SDK cookbook samples (insurance claims, cargo release, code modernization and Linear summarization) and is **not** the FS-ASM Executor. These examples are not loaded by the default worker; use `make start-examples` if deliberately testing them.

## Development rules

- New implementation work: short-lived task branch from current `Fsasm-experimental`, focused PR against that integration branch; no unapproved direct edits to `main` or frozen LLMC branch.
- State transitions, retry admission, permissions and PASS verification belong to deterministic domain/runtime code, not model text.
- `EvidenceRecord` wrapping a stub claim is not an independent proof of an actual file edit or passing test.
- Preserve historical documents; record current decisions once in `PROJECT_STATUS.md`, with PR and SHA. Never append a new conflicting 'current stop point' to the old anchor.
