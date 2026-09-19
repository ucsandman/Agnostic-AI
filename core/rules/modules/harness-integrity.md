---
name: harness-integrity
description: What a change to a hook, a settings file or a guard has to carry before it is done: test, relock, mirror. Loads when settings.json, hooks.json or a guard file is being touched.
context:
  triggers:
    commands: [settings.json, hooks.json, gates.cjs --lock]
    paths: ["~/.claude/settings.json", "~/.claude/settings.local.json", "**/hooks.json", "~/.claude/hooks/*.cjs", "~/.claude/hooks/*.py", "~/.claude/hooks/*.ps1", "C:/Projects/agnostic-ai/engine/hooks/**"]
  suggests: [harness-push-destinations]
  clients: [claude]
  priority: 80
  stale_after: 180d
---
# Harness integrity (loaded on demand)

A hook or settings change is done only when: its probe in `~/.claude/hooks/tests/` passes (write one if the hook is new; make it fail once on purpose), `node ~/.claude/tools/gates/gates.cjs hook-wiring gate-freeze` is green, the frozen set is relocked (`gates.cjs --lock`) with the reason in the commit, `docs/harness-guards.md` names the guard and its override marker, and the public mirror is refreshed in the same turn (`node ~/.claude/scripts/mirror-sync.cjs`). A hook edited in the working tree and never committed runs everywhere and is versioned nowhere.
