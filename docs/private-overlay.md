# The private overlay

Agnostic-AI is the operating system; your overlay is your user profile. The overlay is a directory in the Claude home, `~/.claude/overlay/`, that you version in a private repository of your own. Nothing in it is required: a public install with no overlay is a complete harness.

## What the engine reads from it

| File | Read by | Purpose |
|---|---|---|
| `overlay/profile.md` | `npm run sync` (engine/sync/claude-md.cjs) | your private section of `CLAUDE.md`: who you are, your ALWAYS/NEVER lines, machine notes. Appended after the public rules, inside `<!-- agnostic:profile -->` markers |
| `overlay/context-graph.json` | `engine/hooks/context-graph.cjs` | your context roots (memory store, private docs) and budgets; replaces the portable default entirely |
| `overlay/gates.json` | `tools/gates/freeze.cjs` | extra harness roots and frozen files (a product repository whose hooks this machine also freezes). Merged into the repository manifest; never removes anything |

The `CLAUDE_CONFIG_DIR` environment variable moves the Claude home, and the overlay with it.

## What else is private, and where it lives

- **Memory**: `~/.claude/projects/<slug>/memory/` (Claude Code's own auto-memory location). The engine's memory policy and linter are public (`packages/markdown-agent-memory`, `tools/memory-lint`); the content is yours.
- **Meditations, reflections, digests**: `~/.claude/meditations/`. The nightly runner is public (`jobs/meditation`), the corpus is private.
- **Private hooks and jobs**: a hook that names your products or accounts goes in a directory of your own inside the Claude home (say `hooks-private`) and is registered in `settings.json` like any other; a private scheduled job lives beside it and is registered by you, not by `jobs/install.cjs`.
- **settings.json**: owned by Claude Code. The harness manages its `hooks` key (and freezes it); everything else (model, theme, permissions you add, plugins) is yours.
- **Secrets**: never in any repository. The secret guards deny reads of `.env`-shaped files and scan staged commits.

## Relationship to the public repository

```
public rules (core/rules)  ─┐
                            ├─ npm run sync ─▶ ~/.claude/agnostic-rules.md  ─▶ @import in CLAUDE.md
overlay/profile.md         ─┘                                                  + <!-- agnostic:profile --> block
engine/hooks, tools, mods, agents, workflows  ─ npm run sync (links) ─▶ ~/.claude/{hooks,tools,mods,agents,workflows}
```

Public code never reads your overlay except through the three files above. `npm run doctor` fails when a tracked file in this repository carries a machine-absolute home path, which is how a private detail is kept from leaking upward.

## Migrating an existing hand-built `~/.claude`

`npm run sync` moves a real `~/.claude/hooks` (or tools, mods, agents, workflows) directory aside to `~/.claude/.agnostic-migrated/<name>-<stamp>/`, copies anything it held that the repository does not into the repository directory, and puts a link in its place. Nothing is deleted. `npm run doctor` then lists what came along under `linked-leftovers`, so you can commit it, ignore it or remove it deliberately.
