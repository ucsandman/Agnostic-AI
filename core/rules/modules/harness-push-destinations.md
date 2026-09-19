---
name: harness-push-destinations
description: Where a harness change is committed and pushed now that agnostic-ai is the one public repository and claude-config the private overlay; loads on a harness commit or push.
context:
  triggers:
    keywords: [push, commit the harness, mirror, claude-config, agnostic-ai, push everything, where do I commit]
    paths: ["~/.claude/**", "C:/Projects/agnostic-ai/**"]
  clients: [claude]
  priority: 60
  stale_after: 180d
---
# Harness push destinations (loaded on demand)

GitHub: respect the active user/org context; verify `git remote -v` before pushing. Two destinations, decided by what changed:

- **Engine, hooks, tools, Mods, agents, workflows, rules, public docs** live in `C:\Projects\agnostic-ai` (public `ucsandman/Agnostic-AI`). `~/.claude/{hooks,tools,mods,agents,workflows}` are links into it, so an edit made through either path is committed there. A rule change is `core/rules/global-rules.md` (or a module under `core/rules/modules/`), then `npm run sync` (this client) and `npm run port` (the others) in the same turn.
- **The private overlay** (`~/.claude/overlay/`, memory under `projects/`, meditations, private jobs and docs, `settings.json`, `CLAUDE.md`) is `claude-config` (private). Push after every verified commit.

There is no public mirror to refresh: agnostic-ai is the public repository. "Push everything" means both repositories. `npm run doctor` in agnostic-ai must be green before either push.
