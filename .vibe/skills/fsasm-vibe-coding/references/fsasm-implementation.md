# FS-ASM Implementation Contract

Use for an explicitly authorized FS-ASM milestone implementation or repair. This reference describes **method**, not live milestone status or permission to start work.

Before editing, read the root `AGENTS.md`, `fsasm-first/PROJECT_STATUS.md`, the branch policy, `fsasm-first/AGENTS.md`, the current task contract, and the existing Mistral Workflows SDK skill at `fsasm-first/.agents/skills/workflows/SKILL.md`. Verify current source and Git/CI when project documents contain dated claims. Run project commands from `fsasm-first/`.

## Architectural rule

**LLM proposes, runtime decides.** Keep deterministic control, validation, transition authorization and state ownership in runtime/domain code. Use LLMs for semantic work only. Do not confuse Vibe (the agent developing this repository) with the not-yet-implemented real FS-ASM Executor.

## Separate claims, evidence and verified authorization

```text
ExecutorOutput = executor's reported output/claim
EvidenceRecord = a separately recorded observation/artifact with traceable provenance
VerificationResult = structured verifier verdict, subject to finalizer validation
```

A separate `EvidenceRecord` is **not automatically independent proof**: evidence wrapping stub output cannot prove a real file was changed or a test passed. A model saying `done`, or an internally inconsistent PASS verdict, is never authorization to mark a task PASSED. Inspect the actual verifier and finalizer for the current task; do not assume unimplemented verification types (`exists`, `count`, `schema`) already provide real artifact checks.

## Persistent state and known limits

State belongs to the runtime/filesystem, not model memory. At successfully completed durable boundaries, `state.json` and `plan.json` must agree about the authoritative task and attempt, and activities must return authoritative updated values to subsequent steps. Do not rely on shared Python object identity across serialized activity inputs. Preserve the existing F2 normal-path fix and F8 finalizer consistency guards.

**Do not claim multi-file atomicity or crash recovery.** Individual-file atomic replace does not make writes across state, plan, evidence and log one transaction; F3 remains a separate stabilization issue until explicitly closed. Likewise F4 run-ID reuse, F5 path safety, and F6/F7 signal identity/deduplication remain separate issues unless Git/source and current status establish otherwise. Never silently solve them inside an unrelated task.

## Layer responsibilities

- Pure transition/domain logic belongs in domain code.
- Workflow code orchestrates deterministically.
- Activities perform side effects (filesystem, APIs, tool calls).
- Verification belongs in the verifier/finalizer boundaries, not hidden inside persistence.
- Never bypass domain transitions with arbitrary status assignment.

## Attempt semantics

Unless the explicitly approved task contract changes them:

- `attempt` counts actual execution attempts started.
- Increment on `READY -> RUNNING`, not on `FAILED -> READY`.
- Autonomous retry only while its budget remains; exhaustion escalates instead of looping forever.
- Domain task retry is different from Mistral Workflows activity retry; avoid replaying side-effecting activities unless explicitly made idempotent.

## Human Gate

When authorization is required: persist `NEEDS_HUMAN` and relevant state, clear inappropriate active execution state, keep state/plan consistent on successful writes, wait durably via supported Workflows mechanisms, and validate/persist the decision through the correct domain/activity layer. Signal handlers must remain deterministic and free of filesystem I/O. Do not treat current Human Gate tests as evidence that duplicate/stale/multiple-signal handling is completely solved.

## Evidence and verification

Evidence should be attempt-specific, preserved, safely named, traceable to run/task/attempt and sufficient for the verification actually claimed. Failed attempts stay in audit history. For a real code task, independently collected tool/test output or a checked artifact is required; a stub's statement alone is not proof. Verify no false PASS and no unauthorized transition at the relevant boundary.

## Workflows and scope

Use the project's supported `mistralai.workflows` API and bundled SDK references; do not import `temporalio` directly unless a separately approved contract changes this. Preserve the current one-ChildTask M4 semantics and deterministic STUB until an authorized task changes them. Do not start M5, LLMC work, another orchestration framework, policy engine, UI or paid-model experiment from this skill.

## Testing and delivery

Prove the defect at the correct level before fixing it when practical: (1) domain tests, (2) activity/persistence tests, (3) real workflow worker tests for durable behavior. Inspect actual persisted state at relevant boundaries, including retries and Human Gate. Use isolated test persistence; do not clear a valuable default runtime directory. Run focused tests, full `uv run pytest`, `make check`, and `git diff --check` for runtime changes, or the checks required by the approved task. Report exact results, final commit SHA, CI status, scenario/acceptance outcomes and outstanding limitations.

When implementation was requested and acceptance criteria exist, inspect, plan, implement, test and correct routine failures without repetitive permission prompts. Update the canonical `PROJECT_STATUS.md` **only for a genuine status change**, and never report a draft PR as merged. Use `IMPLEMENTED — READY FOR EXTERNAL REVIEW` before independent acceptance; do not independently declare an issue DONE or milestone CLOSED.
