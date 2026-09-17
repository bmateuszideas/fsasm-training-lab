# FS-ASM implementation reference — subordinate to architecture v1

This is a short process reference for the **external developer Vibe Code Web**; it must not replace the complete, approved `fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`. Read the original, `fsasm-first/docs/DEPLOYMENT_DECISIONS.md`, current `PROJECT_STATUS.md` and a user-approved atomic task before implementation. Check the actual source and tests on the current SHA; use the Mistral Workflows SDK skill for provider-specific constraints.

## Domain and state

- FS-ASM Domain Core owns semantics, task status transitions, dependency admission, attempt counters, resource budgets, authorization and PASS. Workflows provides technical orchestration, durable wait/signals/history; do not build a second framework or let a model control state by writing arbitrary JSON.
- One authoritative `state.json`-equivalent snapshot per run contains the plan, Task Register, counters, gate/application records and accepted evidence references. `plan.json` is a derived view only. Adopt a revision/expected-revision mechanism and one state commit boundary; do not pass independent mutable copies of plan/state/task through serializing activities and then reconcile them ad hoc.
- One writer and one active Child Task per run in v1. `start_new` cannot overwrite an existing run; `resume` must validate state and reconcile uncertain tool outcomes. A single-file atomic replace does not give multi-file transactions; exactly-once external tool execution is not promised.

## Planning, execution and proof

- Planner proposes semantic tasks; deterministic Compiler assigns IDs, validates dependencies/scope and emits a verified program. Exactly three tasks was a historical stub fixture, not a v1 limit. Scheduler handles every eligible Child Task and completes Parent/run only after all required results.
- Context Builder selects a bounded task-specific package, initially via paths/search/symbols. LLMC, vector DB and fine-tuning are deferred.
- Executor performs a bounded loop `Model → Tool Broker → ToolObservation → Model`, distinguishing task retry, tool/model step and Workflows activity retry. Tools enforce allowed files and operations in code; prompt-only `allowed_files` is insufficient.
- Verifier checks actual diff/files/test result and provenance from the SAME run/task/attempt. A stub's claimed `DONE` converted to EvidenceRecord is not independent evidence. Evidence must exist before an authoritative snapshot commits PASS.
- Adapter/Gateway normalizes model/tool outputs; local 7B Q4 is the default eventual runtime Executor and two yet-unselected Mistral API models provide bounded escalation. Vibe is the external coder, never a runtime adapter. Use fixtures in cloud development; real 7B after laptop transfer.

## Known baseline and narrow follow-up

PR #20 was merged into `Fsasm-experimental` on 17.09.2026; it did NOT close M4. Astra's dated audit (`142db38`) showed G3: legacy decisions without gate ID can bind to a later gate; G4: `gate_id=None` rejection misattributed to a gate; G5: flush cursor can skip rejection arriving during await. These are component-level reproductions, not proof of a production exploit. Verify them on current code; obtain user decision on legacy no-ID contract; repair in a bounded task without refactoring all persistence.

The broader migration includes stale snapshot revision (G1), synthetic/older-attempt proof (G2), actual scheduler, Tool Broker, genuine Verifier, model loop, escalation and operational resume. Preserve existing F3/F4/F5/F8 protections. See the approved architecture and `fsasm-first/docs/MIGRATION_BACKLOG_V1.md`; neither this skill nor the backlog authorizes the next task.

## Test and delivery

Use isolated temporary runtime data. Tests should prove domain invariants, real tool scope and meaningful integrated behavior, not accumulate arbitrary microtest counts. `uv run pytest`, `make check` and focused defect reproductions are appropriate when scoped to runtime changes. Record actual SHA/CI, failures, what was NOT tested, and await independent review before claiming milestone closure or merging.
