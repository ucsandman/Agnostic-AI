# Where things go

One implementation per capability, one writer per generated file, one place for each kind of change. If a question below has no answer here, that is a bug in this document.

## The three places

| Place | Role | Repository | Visibility |
|---|---|---|---|
| `agnostic-ai` (this repository) | the operating system: engine, hooks, tools, Mods, agents, workflows, rules, docs, tests | `ucsandman/Agnostic-AI` | public |
| `~/.claude/overlay/` and the rest of the Claude home you track | the user profile: identity, private rules, machine config, memory, private jobs | your private repository (the author's is `claude-config`) | private |
| `~/.claude` as Claude Code sees it | the installed runtime: links into this repository plus your overlay, assembled by `npm run sync` | not a codebase | machine |

Dependency direction is one way: `core` → `engine` → installed surfaces (`hooks`, `mods`, `agents`, `workflows`, `tools`) → the client homes. The overlay may depend on public interfaces (config files the engine reads); nothing public reads the overlay except through those interfaces. `labs/` may depend on `engine/`; `engine/` never depends on `labs/` or `examples/`.

## Where do I add...

| I want to | Put it in | Then |
|---|---|---|
| a new guard hook | `engine/hooks/<name>.cjs`, a probe in `engine/hooks/tests/<name>-probe.cjs` that fails once on purpose, a line in `docs/guards.md` | register it in `~/.claude/settings.json` (`examples/installed-harness/settings.json` shows the full set; `npm run setup` wires the core guards); relock: `node tools/gates/gates.cjs --lock` |
| a context capability (a module that loads on demand) | a markdown file with a `context:` block under `core/rules/modules/` (public) or your memory store (private); engine changes in `engine/context/` | `node engine/context/cli.cjs graph` lints; `explain <name>` shows why it loads |
| support for a new client | an entry in `core/templates/targets.json`; an adapter in `engine/harness/targets/<id>.cjs` only if the generic one cannot render it; a `sources/<id>.cjs` only if it can be a capture source | `npm run docs:targets`; `npm test` (the registry test counts adapters) |
| a new skill | the skills library (`~/.claude/skills`, its own repository, installed by setup) | the port links it into every client; `engine/skills/` only if the consolidation or recommendation logic changes |
| a subagent, a saved Workflow | `agents/<name>.md`, `workflows/<name>.js` | they are linked into the Claude home; the port carries agents to other clients |
| an operator CLI or page | `tools/<name>/` with a README; runtime output goes under the Claude home, never beside the code | `.gitignore` any cache it writes into its own directory |
| a Mod (function-hook plugin) | `engine/mods/<plugin>/` | policy in `hooks/lib/*.mjs` with tests under `node --test` |
| a scheduled job | `jobs/<name>/` plus a row in `jobs/install.cjs` | `node jobs/install.cjs --apply` re-points the registered task |
| a change to global portable behaviour (the working agreement) | `core/rules/global-rules.md`; situational text as a module in `core/rules/modules/` | `npm run sync` (this client), `npm run port` (the others) |
| a change to MY behaviour only | `~/.claude/overlay/profile.md` (rules, ALWAYS/NEVER), `overlay/context-graph.json`, `overlay/gates.json`, private hooks in a directory of your own inside the Claude home (say `hooks-private`), registered in settings.json | `npm run sync`; never edit `CLAUDE.md` |
| an experiment | `labs/<name>/` with a README saying what it tests and what would promote it | promotion is a move into `engine/` or `tools/` with tests |
| a generated file | nowhere by hand. `agnostic-rules.md`, `CLAUDE.md`, `SOUL.md`, every other client's rules file, `docs/targets.md`, `storage/*` are outputs | `npm run doctor` names the writer of anything stale |
| a test | next to the code: `engine/tests/` (engine), `engine/hooks/tests/` (hook probes), `engine/mods/*/tests/` (Mods), `tools/<name>/tests/` | `npm test` runs the engine suites; probes run by name |
| documentation | `docs/` (public, word-budgeted by `tools/gates/budgets.json`); private notes in `~/.claude/docs/` | the pre-commit doc gates check links and budgets |

## The three commands

- `npm run sync` compiles the rules, binds the links, assembles `CLAUDE.md`. Idempotent.
- `npm run status` shows every client against the source harness; `npm run port` writes the others.
- `npm run doctor` reports drift, a second writer, a broken link, a stale install, an old path, a private path in public code.

## Runtime state

State lives under the Claude home (`~/.claude/logs`, `~/.claude/state`, `~/.claude/mods/state`, the hooks' dotfiles). Because `~/.claude/hooks` and `~/.claude/tools` are links into this repository, a few tools still write beside their code; those paths are listed in `.gitignore` under "Runtime state", and `npm run doctor` flags anything else that appears untracked there.
