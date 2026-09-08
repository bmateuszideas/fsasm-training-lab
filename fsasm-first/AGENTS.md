# FS-ASM implementation contract for coding agents

## Purpose of this file

This file is the implementation bootstrap for a coding agent entering `fsasm-first/` with no prior conversation context.

Treat it as the operational contract for the current experimental branch. Its purpose is not to explain the whole history of FS-ASM. Its purpose is to let you inspect the existing scaffold and begin implementing the first real FS-ASM runtime without inventing a new architecture.

Before changing code, read this file completely. Then inspect the current repository state. Also read `docs/CURRENT_FSASM_MODEL.md` for the full project rationale and long-term direction.

Historical documents outside `fsasm-first/` are research material only. Do not implement them literally.

---

# 1. Project identity

FS-ASM means **File System as State Machine**.

The current project is an experimental implementation of a deterministic runtime around LLM roles.

The central rule is:

> **State, control flow, validation and verification belong to deterministic code. LLMs are replaceable cognitive components used only where semantic reasoning or generation is required.**

Do not turn the LLM into the runtime. Do not encode deterministic state-machine rules only in prompts.

The runtime must be able to operate without relying on model memory or chat history.

---

# 2. Current repository and branch assumptions

Active development branch:

```text
Fsasm-experimental
```

Working project directory:

```text
fsasm-first/
```

Technology already present:

- Python `>=3.12`
- `uv`
- `mistralai-workflows>=3,<4`
- Pydantic
- pytest
- Ruff
- mypy
- Semgrep workflow checks

Existing workflow scaffold:

```text
src/workflows/hello.py
```

Existing worker/entrypoint infrastructure:

```text
src/entrypoints/
src/worker.py
worker.py
```

Existing Mistral Workflows documentation/skill:

```text
.agents/skills/workflows/
```

Existing project source of truth:

```text
docs/CURRENT_FSASM_MODEL.md
```

Do not rewrite or remove the existing `hello-world` example unless required by a later explicit task. Add the FS-ASM implementation beside it.

---

# 3. What is being built now

Build the **smallest observable deterministic FS-ASM runtime**.

The first implementation must prove this path:

```text
GoalInput
    ↓
Planner Stub
    ↓
Plan with exactly 3 ChildTasks
    ↓
Schema validation
    ↓
Persistent RunState written to JSON
    ↓
Deterministic verification
    ↓
EvidenceRecord written separately
    ↓
PASS or FAIL
    ↓
Run log
```

The first milestone MUST work with:

```text
no Mistral API call
no local LLM
no vector database
no web UI
```

The initial Planner is a deterministic stub. The initial Verifier is deterministic code.

The point of this milestone is to prove the machine before inserting intelligence into it.

---

# 4. Architecture boundaries

Keep these concerns separate.

## 4.1 Domain core

Pure Python + Pydantic.

Responsible for:

- domain schemas
- state transitions
- task dependency rules
- retry counters
- verification rules
- evidence contracts
- run status

The domain core must not depend on Mistral API calls.

## 4.2 Persistence

Responsible for:

- JSON serialization
- atomic writes
- loading state
- run directories
- evidence records
- append-only run log where practical

Initial persistence is filesystem JSON.

Do not introduce SQLite yet.

## 4.3 Mistral Workflows orchestration

Responsible for:

- durable orchestration
- calling activities
- coordinating deterministic stages
- later calling model adapters

Workflow code must stay deterministic.

I/O, filesystem writes, model calls, external APIs and heavy work belong in **activities**, not directly in workflow control flow.

Use the repository's Workflows skill at `.agents/skills/workflows/SKILL.md` for SDK rules.

## 4.4 Model adapters

Do not tightly couple domain objects to Mistral.

The future design must allow roles to use different backends, e.g.:

```text
Planner -> Mistral API
Executor -> local coding model
Verifier -> deterministic checks or another model
Expert escalation -> stronger Mistral model
```

Therefore model-specific code must sit behind explicit adapters/interfaces.

The first milestone does not need a real model adapter, but the structure must not make future adapters difficult.

---

# 5. Canonical domain models for milestone 1

Implement Pydantic models with clear typing and validation.

The exact filenames may be adjusted if repository conventions strongly justify it, but do not change the concepts without a concrete reason.

## 5.1 `GoalInput`

Minimum fields:

```text
goal: str
run_id: optional str
```

Rules:

- goal cannot be blank
- if run_id is omitted, generate it outside deterministic workflow code or via a deterministic workflow-safe mechanism

## 5.2 `Plan`

Minimum fields:

```text
plan_id: str
run_id: str
goal: str
tasks: list[ChildTask]
```

Milestone rule:

```text
len(tasks) == 3
```

The stub planner must always create exactly three ordered tasks.

## 5.3 `ChildTask`

Minimum fields:

```text
task_id: str
parent_id: str | None
sequence: int
title: str
description: str
status: TaskStatus
dependencies: list[str]
constraints: list[str]
allowed_files: list[str]
verification: VerificationSpec
expected_evidence: list[str]
attempt: int
max_attempts: int
```

Suggested default:

```text
max_attempts = 3
attempt = 0
status = pending
```

Tasks are atomic units. Do not create vague tasks like `implement project`.

## 5.4 `VerificationSpec`

Minimum fields:

```text
type: str
expected: str
```

The first milestone can use simple deterministic verification types such as:

```text
schema
exists
count
```

Do not build a general verification DSL yet.

## 5.5 `VerificationResult`

Minimum fields:

```text
run_id: str
task_id: str | None
status: PASS | FAIL
checks: list[VerificationCheck]
message: str
```

A model declaration is never sufficient evidence for PASS.

## 5.6 `EvidenceRecord`

Minimum fields:

```text
evidence_id: str
run_id: str
task_id: str | None
kind: str
source: str
payload: dict | str
created_at: str
```

Evidence must be a separate object from the claim/result it supports.

## 5.7 `RunState`

Minimum fields:

```text
run_id: str
goal: str
status: RunStatus
plan: Plan | None
active_task_id: str | None
completed_task_ids: list[str]
failed_task_ids: list[str]
created_at: str
updated_at: str
```

The runtime owns this state. LLM output never directly overrides it.

---

# 6. Status enums and allowed transitions

Use enums, not arbitrary strings.

Suggested task states:

```text
PENDING
READY
RUNNING
PASSED
FAILED
BLOCKED
NEEDS_HUMAN
```

Suggested run states:

```text
CREATED
PLANNED
RUNNING
PASSED
FAILED
NEEDS_HUMAN
```

Implement explicit transition validation.

At minimum, illegal transitions must raise a domain error.

Examples:

```text
PENDING -> READY        allowed
READY -> RUNNING        allowed
RUNNING -> PASSED       allowed only after verification PASS
RUNNING -> FAILED       allowed after verification FAIL
FAILED -> READY         allowed only when retry budget remains
FAILED -> NEEDS_HUMAN   allowed when retry budget is exhausted or policy requires escalation
PASSED -> RUNNING       forbidden
```

Do not let callers assign arbitrary status changes directly.

Prefer functions/methods such as:

```python
transition_task(task, target_status, verification=None)
```

or an equivalent explicit API.

---

# 7. Persistence layout

Use a dedicated runtime directory that is not source code.

Recommended structure:

```text
runtime/
└── runs/
    └── <run_id>/
        ├── state.json
        ├── plan.json
        ├── evidence/
        │   └── <evidence_id>.json
        └── run.log.jsonl
```

If the repository already has a better runtime path when implementation begins, preserve the same semantics.

## Atomic writes

For mutable JSON state:

```text
write temp file
flush
replace destination atomically
```

Never partially overwrite `state.json`.

The persistence layer should be unit-testable using pytest temporary directories.

Runtime output should not be committed to Git. Update `.gitignore` if necessary.

---

# 8. Stub planner contract

The first Planner is deliberately dumb and deterministic.

Input:

```text
GoalInput
```

Output:

```text
Plan
```

It must produce exactly three tasks.

The task text can be generic but must remain deterministic for the same goal.

Example conceptual plan:

```text
TASK-001: inspect/prepare input
TASK-002: perform core action
TASK-003: verify/finalize result
```

Do not call an LLM in milestone 1.

Keep the planner behind an interface/protocol so it can later be replaced by a Mistral planner without changing the domain core.

---

# 9. Deterministic verifier contract

The first Verifier verifies the plan/runtime artifacts, not generated production code.

At minimum verify:

1. a valid `Plan` exists,
2. it contains exactly three ChildTasks,
3. task IDs are unique,
4. dependency references point to valid tasks,
5. state and plan share the same run ID,
6. a separate EvidenceRecord can be persisted,
7. final workflow result is unambiguously PASS or FAIL.

Return a structured `VerificationResult`.

The final RunState can become `PASSED` only if deterministic verification passes.

---

# 10. Workflow/activity split

Create a real FS-ASM workflow in `src/workflows/` beside `hello.py`.

Suggested workflow name:

```text
fsasm-milestone-one
```

Suggested control flow:

```text
Workflow entrypoint
    ↓
create/normalize input
    ↓
planner activity
    ↓
validate plan
    ↓
persist plan/state activity
    ↓
verification activity
    ↓
persist evidence activity
    ↓
persist final state/log activity
    ↓
return structured result
```

Important Mistral Workflows rule:

> Keep workflow code deterministic. Filesystem I/O belongs in activities.

Do not use direct `open()`, network calls, environment lookups, random UUID generation or wall-clock time inside deterministic workflow logic unless using workflow-safe APIs documented by Mistral Workflows.

Use activity retry policies conservatively and only where retry is safe/idempotent.

---

# 11. Suggested source layout

A clean first implementation may look like:

```text
src/
├── fsasm/
│   ├── __init__.py
│   ├── models.py
│   ├── transitions.py
│   ├── errors.py
│   ├── planner.py
│   ├── verifier.py
│   └── persistence.py
│
├── workflows/
│   ├── __init__.py
│   ├── hello.py
│   └── fsasm_milestone_one.py
│
└── entrypoints/
    └── ... existing files ...

tests/
├── test_models.py
├── test_transitions.py
├── test_persistence.py
├── test_planner_stub.py
├── test_verifier.py
└── test_fsasm_workflow.py
```

If adding `src/fsasm/`, update `pyproject.toml` package configuration so it is packaged correctly.

Do not place domain logic inside `hello.py` or entrypoint scripts.

---

# 12. Testing contract

The project is not complete because code exists. It is complete when behavior is verified.

Implement unit tests for:

- Pydantic validation
- blank goals rejected
- exactly-three-task plan invariant
- duplicate task IDs rejected or verifier FAIL
- invalid dependency rejected or verifier FAIL
- legal state transitions
- illegal state transitions
- retry bound
- atomic persistence save/load
- evidence saved separately
- deterministic stub planner
- verifier PASS case
- verifier FAIL case

Add at least one workflow-level test using the repository's Mistral Workflows testing utilities or quick-test tooling.

Run:

```bash
uv sync --frozen
uv run pytest
make check
```

If the Workflows skill documents a more appropriate local workflow test command, use it as well.

Do not make a paid Mistral API call merely to prove milestone 1.

---

# 13. Definition of done for milestone 1

Milestone 1 is DONE only when all of the following are true:

1. A goal can be submitted to the FS-ASM workflow.
2. A deterministic planner creates exactly three ChildTasks.
3. All input/output models are Pydantic validated.
4. A `RunState` is persisted to JSON.
5. `plan.json` is persisted separately.
6. At least one `EvidenceRecord` is persisted separately from state/result.
7. Verification returns explicit PASS or FAIL.
8. RunState cannot become PASSED without verification PASS.
9. Runtime writes are atomic where state is mutable.
10. Unit tests pass.
11. Workflow-level test passes.
12. `make check` passes, or any advisory-only workflow-lint findings are documented with a concrete justification.
13. No Mistral API key is required for the tests above.
14. `hello-world` still works or remains untouched.

Do not declare completion without running the verification commands.

---

# 14. What comes after milestone 1

Do not implement these until milestone 1 is green unless a blocking design issue requires a small preparatory abstraction.

## Milestone 2 — real Mistral Planner

Replace `PlannerStub` through an adapter.

Requirements:

- Mistral structured output
- model name/version recorded
- prompt version recorded
- cost/call count observable
- plan still validated by FS-ASM domain rules

The LLM proposes a plan. The runtime decides whether the plan is valid.

## Milestone 3 — Executor + execution verification

Add one-task execution semantics:

```text
READY -> RUNNING -> PASSED/FAILED
```

Executor result and Evidence remain separate.

## Milestone 4 — bounded retry + Human Gate

Add deterministic retry counters and escalation:

```text
FAIL
├── retry budget remains -> READY
└── exhausted -> NEEDS_HUMAN
```

Use Mistral Workflows HITL/durable mechanisms where they fit, but retain FS-ASM's own domain state.

## Milestone 5 — Context Builder / retrieval

Start with exact code retrieval:

- file search
- symbol search
- AST/Tree-sitter where useful
- dependencies/import relationships

Only later add vector retrieval/RAG.

## Milestone 6 — local coding worker

Add a model adapter for a local specialized coding model (~6B–9B class) for atomic ChildTasks.

The architecture must allow model replacement without rewriting the state machine.

## Later — model routing and fine-tuning

Possible routing:

```text
simple coding -> local coder
planning -> Mistral
hard reasoning -> stronger API model
missing information -> retrieval/web/expert
critical decision -> Human Gate
```

Fine-tune a local FS-ASM worker only after the runtime has produced enough real, verified trajectories.

---

# 15. Explicit non-goals for current implementation

Do NOT add now:

- LangGraph
- another orchestration framework
- Kubernetes
- distributed infrastructure
- web UI
- vector database
- custom neural MoE
- many-agent free-form conversation
- automatic agent handoff as the source of control truth
- own model training
- literal implementation of historical FS-ASM v7
- global handwritten symbol table
- Trap Tasks
- huge prompt-based state-machine instructions

Mistral Workflows is the execution/orchestration substrate for the current experiment.

FS-ASM domain rules remain our code.

---

# 16. Rules for using Mistral Workflows

Use the installed repository skill:

```text
.agents/skills/workflows/SKILL.md
```

Key constraints:

- import through `mistralai.workflows`
- never import `temporalio` directly
- workflow code must be deterministic
- I/O and model calls belong in activities
- call activities through the supported decorator/API style
- use workflow-safe time/UUID/random helpers where needed
- test workflows with the provided test utilities
- use retries only for safe/idempotent operations

Do not copy cookbook examples wholesale. Extract patterns and adapt them to FS-ASM domain contracts.

---

# 17. Coding quality rules

Prefer:

- explicit types
- small modules
- pure domain functions where possible
- Pydantic validation at boundaries
- deterministic transitions
- dependency injection/interfaces for model backends
- descriptive domain errors
- tests before adding complexity

Avoid:

- magic global state
- hidden mutation
- duplicated status strings
- catch-all exceptions without context
- mixing filesystem persistence with Pydantic domain definitions
- embedding provider-specific code into domain models
- prompts that are responsible for enforcing hard safety/state rules

Security:

- never commit `.env`
- never print API keys
- never put secrets into evidence or logs

---

# 18. How to work when entering this directory with zero context

Follow this exact startup sequence:

1. Read `AGENTS.md` completely.
2. Read `docs/CURRENT_FSASM_MODEL.md` for project rationale and later roadmap.
3. Inspect the actual repository tree and current Git diff.
4. Confirm the current branch is `Fsasm-experimental` before modifying project code.
5. Read `.agents/skills/workflows/SKILL.md` before writing Mistral Workflow code.
6. Inspect `src/workflows/hello.py`, `pyproject.toml`, and `Makefile` to preserve local conventions.
7. Run the existing baseline checks before editing if the environment permits.
8. Implement only the next incomplete milestone, beginning with milestone 1.
9. Keep changes small and testable.
10. Run tests and checks before claiming completion.
11. Report what changed, what was verified, and what remains incomplete.

Do not stop merely because the project contains historical documents or incomplete older notes. The operational source of truth for implementation is this file plus `docs/CURRENT_FSASM_MODEL.md` and the actual current code.

---

# 19. Decision hierarchy

When instructions appear to conflict, use this order:

```text
1. explicit current user instruction
2. AGENTS.md implementation contract
3. docs/CURRENT_FSASM_MODEL.md
4. current code and tests
5. Mistral Workflows SDK/skill requirements
6. historical FS-ASM documents
```

Historical documents are evidence about the evolution of the idea, not executable specifications.

---

# 20. Core invariant to preserve

At every stage of development, preserve this invariant:

> **The LLM may propose, interpret, generate and request actions. It must not be the sole authority for deterministic state, permissions, verification, retry limits or completion.**

If an implementation choice moves deterministic control from code back into model instructions without a compelling reason, it is probably moving FS-ASM in the wrong direction.
