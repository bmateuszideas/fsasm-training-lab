# FS-ASM branch policy

Snapshot: 2026-09-16. Verify actual refs and GitHub settings before changing branch configuration. This document describes the agreed proposed operating procedure for review; it does not claim branch protection is enabled.

## Branches observed at snapshot

| Branch | Snapshot SHA | Intended treatment |
| --- | --- | --- |
| `Fsasm-experimental` | `603fc607439b44e46b26d8c3a2114b34ba7c458c` | Active runtime integration, source for new task branches, target for atomic reviewed PRs |
| `main` | `a9f8ab6640acfda21c31675a03ba53d094f2909f` | Default branch, older divergent runtime + LLMC benchmark; no automatic synchronization or force update |
| `Fsasm-llmc-testingbranch` | `6cb17d62eb91813d147960533ea0ee1e9efc5d0d` | Frozen LLMC research baseline; keep unchanged |
| `__noop_check__` | `30a6e56935b7238b471f7f21365c21679693de20` | Old check branch; **candidate for later manual cleanup** only after checking references |
| `vibe/f2-retry-state-consistency-b6d6c2` | `425d4960286991890948cdc548a894d03d4fd183` | Historical task branch, ancestor of active integration; candidate for later cleanup |
| `vibe/worker-activity-name-collision-b6d6c2` | `3eeffeb1753acf4cb6fc9c1284c39f087065e3b6` | Historical task branch, ancestor of active integration; candidate for later cleanup |

Branch refs and snapshots are not immutable; inspect the current GitHub branch list on each maintenance run. No branch is deleted, renamed, merged, moved or made the default by this documentation PR.

## Work procedure

1. Verify `Fsasm-experimental` HEAD, existing open PRs, Git status and CI. Create `task/<issue-id>-<topic>` or `docs/<topic>` from its CURRENT HEAD. Never base new work on a stale task branch or on `main` by accident.
2. One narrowly defined issue and reproducer/acceptance criteria per PR. State explicit exclusions; do not implement M5 while M4 is open. For docs-only PRs change no runtime or tests.
3. PR must target `Fsasm-experimental`; provide base/head SHAs, complete base-relative diff description, tests that ran, actual CI URL and outstanding issues. A commit-only summary is insufficient when a PR contains earlier commits.
4. Review actual changes and tests at the candidate head. For state-related defects, test serialized activity boundaries and durable filesystem outcomes. Human Gate tests require controlled signal/wait timing and isolated `tmp_path`.
5. Merge only after explicit review, positive CI at the correct SHA and acceptance. Update `PROJECT_STATUS.md` in that PR or in the following status-only PR, without misreporting draft work as merged.
6. The code baseline for the next task is the post-merge `Fsasm-experimental` HEAD, not an AI summary from an old session.

## `main` integration decision — separate and explicit

`main` and `Fsasm-experimental` have diverged: `main` contains LLMC research work not automatically merged into experimental. Do not fast-forward/force-reset `main` or merge either branch solely to 'tidy things up'. Before any release/integration, examine `main...Fsasm-experimental` and `Fsasm-experimental...main`, preserve the benchmark archive, decide whether to retain/rehome it, expand CI triggers to the intended target, resolve all conflicts, then open a separately reviewed PR. Changing the default branch or adding protection rules is a repository-administration decision, not part of this PR.

## Historical branch cleanup

Never delete old refs as part of a docs edit. Once PR ancestry, unique commits, open PRs and benchmark provenance are checked, propose a named deletion list and request explicit approval. Git history and closed PR references should remain discoverable. If preserving a long-lived experiment, use an explicit immutable tag or an archival branch as separately approved. `Fsasm-llmc-testingbranch` is frozen, not a cleanup candidate by default.

## Preventing context drift

One active status snapshot: `../PROJECT_STATUS.md`. Architecture: `CURRENT_FSASM_MODEL.md`. Engineering constraints: `../AGENTS.md`. History: `../CURRENT_DEVELOPMENT_ANCHOR.md` and archived source documents. Each current-state assertion must specify branch/SHA and verification. Historical documents retain their original chronology and are not retroactively interpreted as active instructions.
