---
name: plugin-hygiene
description: "What is enabled, what was pruned, and how to reverse it: plugins, MCP servers, skill overrides"
context:
  triggers:
    keywords: ["plugin", "skilloverrides", "enable the plugin", "disable the plugin", "mcp server", "skill listing", "skill-doctor"]
  priority: 40
---
# Plugin hygiene

Why a disabled plugin is not a stopped plugin, and what a real uninstall takes.
Standing rules live in `CLAUDE.md` (Environment Facts); this file holds the
mechanism and the incidents behind them.

## `enabledPlugins: false` does not stop hooks

A plugin's hooks live in its own `hooks.json` under
`~/.claude/plugins/cache/`, and registrations load at session start. Setting the
plugin `false` stops its skills and commands. It does not stop its hooks.

Two plugins billed against the API key while marked disabled: claude-mem
($227) and security-guidance ($95).

## Renaming `hooks.json` is an emergency stop, not a fix

The rename disables one version folder. When the marketplace updates, the
plugin re-materialises into a **new** version folder with a fresh manifest, and
the rename is left behind on a folder nothing reads.

Measured 2026-08-11: hookify was renamed at 02:27 and had re-armed itself by
03:16 on `PreToolUse`, `PostToolUse`, `Stop`, and `UserPromptSubmit`, every one
matcher `*`.

Pair the rename with stubbing the plugin's entry scripts to `sys.exit(0)` to
stop a session already running, then uninstall properly.

## A real uninstall takes five places

There is no `claude plugin uninstall` CLI. Do it by hand:

1. The entry in `plugins/installed_plugins.json`, **every scope** — plugins can
   be installed per-project as well as per-user.
2. `plugins/cache/<marketplace>/<plugin>/`.
3. `plugins/marketplaces/<marketplace>/` if that marketplace served only that
   plugin, plus its key in `known_marketplaces.json`. This clone is the source
   the cache re-materialises from, so leaving it is what lets a plugin come back.
4. `enabledPlugins` in `~/.claude/settings.json`.
5. `enabledPlugins` in every `C:\Projects\*\.claude\settings.json` and
   `settings.local.json`. **Project settings override global** — DashClaw had
   `security-guidance` and `claude-mem` set `true` the entire time they were
   globally `false`.

Uninstalled 2026-08-11: security-guidance, claude-mem, hookify, vercel,
everything-claude-code, last30days (~892 MB).

Run the `harness-health` skill and `node ~/.claude/tools/gates/gates.cjs` after
any plugin update.
