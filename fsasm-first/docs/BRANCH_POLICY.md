# FS-ASM branch policy

Snapshot: 2026-09-16. This inventory reflects the branches currently present in the GitHub repository at the time of this update. Verify actual refs and GitHub settings before changing branch configuration.

## Branches currently present

| Branch | Current SHA | Intended treatment |
| --- | --- | --- |
| `Fsasm-experimental` | `e6a3bd3e9cd6174246218dc92e6787f68e3fd12f` | Active runtime integration, source for new task branches, and target for atomic reviewed PRs |
| `main` | `a9f8ab6640acfda21c31675a03ba53d094f2909f` | GitHub default branch; older and divergent runtime plus LLMC benchmark. Do not synchronize or force-update automatically |
| `__noop_check__` | `30a6e56935b7238b471f7f21365c21679693de20` | Existing legacy check branch; candidate for later manual cleanup only after checking references |

Branch refs and snapshots are not immutable. This table is a point-in-time inventory, not a substitute for checking the current GitHub branch list. The previously listed `Fsasm-llmc-testingbranch`, `vibe/f2-retry-state-consistency-b6d6c2`, and `vibe/worker-activity-name-collision-b6d6c2` branches are no longer present and are intentionally omitted from the active inventory.

No branch is deleted, renamed, merged, moved, or made the default by this documentation update.

## Work procedure

1. Verify the current `Fsasm-experimental` HEAD, existing open PRs, Git status, and CI. Create `task/<issue-id>-<topic>` or `docs/<topic>` from its current HEAD. Never base new work on a stale task branch or on `main` unless the integration decision explicitly requires it.
2. Keep one narrowly defined issue, reproducer, and set of acceptance criteria per PR. State explicit exclusions; do not implement M5 while M4 is open. For documentation-only PRs, change no runtime code or tests.
3. PRs for runtime work must target `Fsasm-experimental` and include base/head SHAs, a complete base-relative diff description, tests that ran, the actual CI URL, and outstanding issues. A commit-only summary is insufficient when review context is needed.
4. Review the actual changes and tests at the candidate head. For state-related defects, test serialized activity boundaries and durable filesystem outcomes. Human Gate tests require controlled signal/wait conditions.
5. Merge only after explicit review, positive CI at the correct SHA, and acceptance. Update `PROJECT_STATUS.md` in that PR or in a following status-only PR, without reporting draft work as merged.
6. The code baseline for the next task is the post-merge `Fsasm-experimental` HEAD, not an AI summary from an old session.

## `main` integration decision — separate and explicit

`main` and `Fsasm-experimental` have diverged. `main` contains older runtime and LLMC research work and is not automatically synchronized with the experimental runtime. Do not fast-forward, force-reset, or merge either branch solely to make branch names or status appear consistent. Any integration must be proposed as a separate, reviewed decision with a documented purpose, tested result, and explicit approval.

## Historical branch cleanup

Never delete old refs as part of a documentation edit. Before removing `__noop_check__` or any future legacy branch, check branch ancestry, unique commits, open PRs, tags, external references, and benchmark provenance. Propose a named deletion list and obtain explicit approval. Git history and research provenance must remain recoverable.

## Preventing context drift

Use `../PROJECT_STATUS.md` as the active status snapshot. Use `CURRENT_FSASM_MODEL.md` for architecture, `../AGENTS.md` for engineering constraints, and `../CURRENT_DEVELOPMENT_ANCHOR.md` plus the archived source documents for history. Recheck this branch inventory whenever branch maintenance is performed.
