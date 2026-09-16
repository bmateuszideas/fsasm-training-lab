# fsasm-vibe-coding

Repository-scoped **single skill** for the Mistral Vibe coding agent. It guides the *agent developing FS-ASM*, not the FS-ASM runtime itself.

## Contents

- `SKILL.md`: entry point and routing via progressive disclosure.
- `references/large-code-planning.md`: bounded multi-file work.
- `references/systematic-debugging.md`: reproduce and fix root causes.
- `references/session-handoff.md`: durable task-specific progress across sessions.
- `references/code-review.md`: repository-grounded review, not a substitute for an independent reviewer.
- `references/fsasm-implementation.md`: FS-ASM domain/workflow invariants.

## Installation in Vibe Code Web

This skill is installed by **committing its directory into the repository** at `.vibe/skills/fsasm-vibe-coding/` and opening a new Vibe Web session on a branch that contains it. There is no need to import a ZIP through the Web UI; the ZIP was only the source package for this repository integration. Project-level discovery depends on the trusted project directory and the active Vibe environment.

Test discovery in a new read-only session. Ask Vibe whether it discovered `fsasm-vibe-coding` natively, its name/description and reference modules; ask it to distinguish discovery from a manual read of `SKILL.md`. The `user-invocable` metadata exposes `/fsasm-vibe-coding` in CLI/VS Code; Web slash support is not assumed.

## What is authoritative

Read root `AGENTS.md`, `fsasm-first/PROJECT_STATUS.md` and project branch/documentation rules before acting. This skill has no current task list and never makes a decision to start M5, close a milestone, delete a branch, or merge a PR. Mistral Workflows SDK reference remains at `fsasm-first/.agents/skills/workflows/SKILL.md`.

No custom `.vibe/config.toml`, agents, hooks, MCP or tool permissions are required for this package. The skill itself does not prove automatic discovery or successful execution until a live Web session demonstrates it.
