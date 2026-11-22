# Skills

## backtrader-repo-toolkit

Repository maintenance helpers extracted from `scripts/`.

**Single source of truth:** `skills/backtrader-repo-toolkit/` in this repository. Edit only this copy. It contains `SKILL.md`, `scripts/` (10 standalone Python tools), and `references/script_inventory.md` (full `scripts/` classification and deletion rationale).

All task catalog entries and script invocations in `SKILL.md` use absolute paths under `D:/source_code/backtrader/skills/backtrader-repo-toolkit/`, so the skill works when loaded from any agent's discovery path.

### Agent discovery (pointer stubs only)

Each agent discovers the skill through its own path. Those directories contain **only a short pointer SKILL.md** that redirects to the canonical document — no scripts, no references, nothing to keep in sync.

| Agent | Discovery path | Contents |
| --- | --- | --- |
| WorkBuddy (user scope) | `~/.workbuddy/skills/backtrader-repo-toolkit/` | pointer stub |
| Claude Code (user scope) | `~/.claude/skills/backtrader-repo-toolkit/` | pointer stub |
| Claude Code (project scope) | `.claude/skills/backtrader-repo-toolkit/` | pointer stub (`.claude/` is gitignored) |

The stub tells the agent to read `D:/source_code/backtrader/skills/backtrader-repo-toolkit/SKILL.md` and the `scripts/` directory there before using any tool. If the canonical path is unavailable, the agent must report it rather than improvise.

### Why not more locations

`.joyincode/skills/` was removed on 2026-11-22 — no longer used. Duplicating the full skill into every agent directory created three copies that drifted after any edit; pointer stubs avoid that while keeping each agent's auto-discovery working. To update the skill, edit only the canonical `skills/backtrader-repo-toolkit/` directory.
