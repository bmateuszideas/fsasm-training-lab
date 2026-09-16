# FS-ASM documentation map and authority

Last reviewed: 2026-09-16. Do not reconstruct current status by reading the longest document or the oldest README.

| Location | Purpose | Authority / how to read |
| --- | --- | --- |
| Repository `README.md` | Landing page, pointers, repo identity | Navigation; never proof of implementation |
| `fsasm-first/PROJECT_STATUS.md` | **One current, dated status snapshot:** active branch, baseline SHA, approved decisions, milestone states, outstanding atomic tasks and next action | Read first for *current intent*, then verify branch/commits/CI; update upon status-changing PRs |
| `fsasm-first/docs/CURRENT_FSASM_MODEL.md` | Long-term goal and conceptual architecture | Authoritative intent; future components are not implemented merely because described here |
| `fsasm-first/AGENTS.md` | Engineering architecture invariants and original milestone acceptance contracts | Use stable rules; its original M1 bootstrap/current-work phrasing is historical where superseded by PROJECT_STATUS and verified code |
| Repository `.vibe/skills/fsasm-vibe-coding/` | **Optional Vibe coding-agent process skill**: multi-file implementation, debugging, review and task-specific handoff | How the external agent develops FS-ASM; not a runtime feature, a source of live status, approval to start work or a replacement for SDK rules. Web auto-discovery requires a separate live test. |
| `fsasm-first/IMPLEMENTATION_SUMMARY.md` | Description of milestones and original acceptance evidence | Reference/handoff, not live status; some data can be stale after stabilization PRs |
| `fsasm-first/CURRENT_DEVELOPMENT_ANCHOR.md` | Chronological decisions, 9–16 Sep context experiment and stabilization backlog | **Historical running record containing superseded stop points**; do not execute old 'pause development' or 'start LLMC' instructions |
| `fsasm-first/README.md` | Build/run commands and examples | Operational entry; historical context links in the previous version may not exist in the present checkout |
| `fsasm-first/.agents/skills/workflows/` | Mistral SDK skill and reference guides | SDK-specific instructions only; not current project status or permission to start milestone; do not duplicate under `.vibe` |
| `stare dokumenty rozwojowe fsasm/` | Deduplicated historical records | Historical evidence, **not executable instructions** |
| `fsasm-first/llmc-benchmark/` on `main` | LLMC research harness, report and result | Research evidence with documented methodology defects; not adopted runtime component |
| Git commits, merged PRs, CI, source and tests | Implemented and verified behavior | Check pinned SHA for any implementation or test claim; a review recommendation is not DONE |
| `fsasm-first/docs/BRANCH_POLICY.md` | Integration and task-branch rules, dated branch inventory | Branch governance; never delete/force update without explicit authorization |

## Conflict-resolution procedure

1. Confirm actual current branch, SHA, clean/dirty tree, merged PRs and test/check evidence.
2. Distinguish **goal/architecture** (CURRENT_FSASM_MODEL + stable AGENTS rules), **approved scope/status** (PROJECT_STATUS + latest explicit user decision), **actual behavior** (source/tests at SHA), **external coding method** (`.vibe/skills/fsasm-vibe-coding`), **SDK rules** (`fsasm-first/.agents/skills/workflows`) and **history** (anchor, archive, review reports).
3. If any disagree, **report the conflict** rather than quietly selecting whichever text is newest or longest. Prefer code/CI for 'implemented' claims, explicit approved decision for work authorization and the architectural contract for intended behavior. No skill or document alone overrides the user.
4. A milestone is CLOSED only after explicit external review/approval and persisted status update. A green pytest or an agent's summary alone does not close it.
5. Update the short status snapshot and linked PR when a decision/status changes. Do not append contradictory 'current stop points' to the historical anchor.

## Handoff contract for coding sessions

Use a compact task-scoped record in its PR/issue or task-branch handoff if context ends: base branch + starting SHA, target atomic task and acceptance criterion, exact changed files, verified commands/results, failing reproducer, open blocker, next command. A model-generated progress summary is a claim until the receiving agent checks Git. No half-edited/syntactically invalid files should be committed. Finish a single atomic item before starting another. Do not turn a temporary session handoff into a competing current-status file on the integration branch.

## Documentation maintenance

Do not copy-paste the entire review into AGENTS, README, anchor, skill and summary. One canonical current snapshot; other pages link to it. Preserve historical reports and dated decisions; label methodological limitations rather than silently editing measured results. Use a documentation-only PR for navigation/skill changes, with no changes under `src/` or `tests/` and no branch merge.
