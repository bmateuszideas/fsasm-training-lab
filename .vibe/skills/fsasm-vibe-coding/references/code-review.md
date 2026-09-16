# Repository-Grounded Code Review

Use for review of a commit, PR, milestone, or bug fix. Prefer a separate reviewer/session; an implementer's self-review is **not independent external acceptance**.

Previous agent summaries are evidence to investigate, not facts to trust.

## Priority order

1. correctness
2. violated invariants
3. persistence/state consistency
4. tests and missing regression proof
5. architecture boundaries
6. retry/reliability behavior
7. safety/security constraints
8. maintainability
9. style

## Establish the target

Identify:

- branch
- HEAD
- baseline/parent commit
- changed files
- intended acceptance criteria

Use Git rather than memory. Confirm whether a PR has already merged before discussing its status.

## Read contracts

Read the relevant:

- repository `AGENTS.md` and canonical `fsasm-first/PROJECT_STATUS.md`
- approved task/milestone brief
- models
- transitions
- persistence code
- tests
- project/framework docs

## Verify claims

Locate real proof for each important claim. Examples:

- "worker tests cover Human Gate" → inspect the test and assertions
- "state and plan stay synchronized" → inspect durable persistence boundaries; ordinary-path consistency does not imply crash-atomic multi-file writes
- "retry increments once per execution" → inspect transition logic and scenarios

Clearly distinguish a passing CI run from independent local execution, and a stub's output from independently verified code artifacts.

## Cross-boundary review

Pay special attention to:

- workflow ↔ activity serialization
- domain ↔ persistence
- task ↔ run state
- executor output ↔ evidence
- evidence ↔ verification and finalization
- human signal ↔ persisted decision
- retry budget ↔ attempt counter

Look for stale-object overwrites, mutation assumptions, duplicated log writes and non-authoritative counts.

## Test strength

Check whether tests:

- exercise the real bug boundary
- assert persisted state, not just returned dictionaries
- observe durable gate state before signals
- preserve evidence across attempts
- test legal and illegal transitions
- would fail if the implementation regressed

Flag tests that accept multiple outcomes when only one is intended.

## Findings and disposition

Use `Critical`, `High`, `Moderate`, or `Low`. For each finding include path, observed behavior, violated contract, impact, reproduction evidence/limitation, and smallest corrective direction. Report the actual PR head, CI state and remaining known issues.

End with one of:

- `READY FOR EXTERNAL REVIEW`
- `NOT READY — blocking fixes required`
- `READY WITH NON-BLOCKING NITS`

These review summaries are not authorization to merge, mark a backlog item DONE or close an FS-ASM milestone; follow branch governance and the explicit user decision.
