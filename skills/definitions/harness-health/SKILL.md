---
name: harness-health
description: Read-only health check of the local Claude Code harness — verifies every hook target file exists, finds orphaned hook scripts, flags enabled plugins with missing cache dirs, and counts backup/state-file cruft. Use when hooks misbehave, after editing settings.json, after installing/removing plugins, or for periodic maintenance.
---

# Harness Health

Run: `pwsh -NoProfile -File "$env:USERPROFILE\.claude\scripts\harness-health.ps1"`

Read-only — it never modifies anything. Interpret the output:

- **MISSING hook target** — a settings.json hook points at a deleted/moved script. Fix the path or remove the entry (use the update-config skill for settings.json changes).
- **ORPHANED hook script** — a file in `hooks\` that no settings entry references. Wire it up or archive it. (`run_hook.cjs`-style launchers referenced by other repos' settings are exempt — check before removing.)
- **ENABLED plugin with no cache dir** — plugin enabled in settings but not installed/cached; re-install or disable it.
- **Cruft counts** — prune when flagged; CLAUDE.md backups and security-warning state files older than 7 days are safe to delete.

If issues were found and the fix is obvious and reversible, apply it; otherwise report to the user.

Context: dormant skills were archived to `~\.claude\skills-archive\` on 2026-06-11 (restore = move the folder back to `skills\`). The DashClaw hooks live in `C:\Projects\DashClaw\hooks\` by absolute path — if DashClaw moves, this check is what catches it.
