---
name: harness-integrity
description: What "done" means for a hook or settings.json change: a probe that failed once, green gates, a relocked frozen set, a docs line, and the doctor green; loads on a hook or settings edit.
context:
  triggers:
    keywords: [hook change, new hook, settings.json, gate-freeze, relock, guard probe, hook-wiring]
    paths: ["~/.claude/settings.json", "~/.claude/settings.local.json", "**/hooks/*.cjs", "**/engine/hooks/**"]
  clients: [claude]
  priority: 60
  stale_after: 180d
---
# Harness integrity (loaded on demand)

A hook or settings change is done only when: its probe in `engine/hooks/tests/` passes (write one if the hook is new; make it fail once on purpose), `node tools/gates/gates.cjs hook-wiring gate-freeze` is green from `C:\Projects\agnostic-ai`, the frozen set is relocked (`gates.cjs --lock`) with the reason in the commit, `docs/guards.md` names the guard and its override marker, and `npm run doctor` is green. The hook is committed in agnostic-ai (the `~/.claude/hooks` path is a link into it); a hook edited in the working tree and never committed runs everywhere and is versioned nowhere.
