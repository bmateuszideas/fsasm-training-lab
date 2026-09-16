# Vibe project configuration — FS-ASM

This directory contains a **repository-scoped coding-agent skill**, not the FS-ASM runtime, its task register, or a second project-status source.

## Installed skill

- [`skills/fsasm-vibe-coding/SKILL.md`](skills/fsasm-vibe-coding/SKILL.md) — optional on-demand process guidance for substantial implementation, debugging, handoff and code review.
- Its `references/` files provide focused guidance and are read only when needed.
- The existing Mistral Workflows SDK skill is **not duplicated or replaced**: [`../fsasm-first/.agents/skills/workflows/SKILL.md`](../fsasm-first/.agents/skills/workflows/SKILL.md).

## Source of truth and authorization

Start with [`../AGENTS.md`](../AGENTS.md) and [`../fsasm-first/PROJECT_STATUS.md`](../fsasm-first/PROJECT_STATUS.md). Verify actual Git branch, HEAD, merged PRs, source and CI. Branch procedure lives in [`../fsasm-first/docs/BRANCH_POLICY.md`](../fsasm-first/docs/BRANCH_POLICY.md). A skill is general methodology, **not authorization to select a backlog task, close M4, start M5, merge a PR or modify Git settings**. Explicit user tasks and project-specific contracts take precedence.

## Vibe Code Web setup and discovery

Vibe's documented project-level discovery location is `.vibe/skills/<skill-name>/SKILL.md` (or `.agents/skills/`), for a trusted working directory. Start a **new session on a branch containing these files**. Ask Vibe to report whether it natively discovered `fsasm-vibe-coding`; distinguish native discovery from simply opening the file on request. Web slash-picker parity with CLI/VS Code is not assumed. If the project is not trusted or discovery is unavailable, do not claim automatic activation.

This package needs **no** `.vibe/config.toml`, custom agent, subagent, MCP server, hook, or expanded tool permissions. These are deliberately not added. The skill does not grant permissions or enforce runtime policy. Treat repository-supplied agent instructions as code to review before accepting them.

## Persistence

Vibe Code Web sandboxes are ephemeral. Only committed/pushed branch changes and PR content survive session teardown. Keep task-specific handoffs on the task branch or in its PR; do not overwrite the canonical `PROJECT_STATUS.md` with temporary session scratch notes.
