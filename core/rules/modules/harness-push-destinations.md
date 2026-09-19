---
name: harness-push-destinations
description: Where a commit in the harness, the rules repo or the public mirror has to go, and in what order. Loads when a prompt is about pushing, mirroring or syncing the harness.
context:
  triggers:
    keywords: [push, mirror, claude-harness, claude-config, mirror-sync, push everything, publish the harness, sync the rules]
    paths: ["~/.claude/**", "C:/Projects/agnostic-ai/**", "C:/Projects/claude-harness/**"]
  priority: 60
  stale_after: 180d
---
# Harness push destinations (loaded on demand)

GitHub: respect the active user/org context; verify `git remote -v` before pushing. A harness commit (`~/.claude`) has two destinations: push to `claude-config`, then mirror to the public `claude-harness` in the same turn (`node ~/.claude/scripts/mirror-sync.cjs`, CHANGELOG entry, commit, push); a rule change also lands in `agnostic-ai` and is synced (`npm run sync` compiles `core/rules/global-rules.md` into `~/.claude/agnostic-rules.md`; `npm run port` carries it to every other client). "Push everything" means all of them.
