# Agnostic AI

[![CI](https://github.com/ucsandman/Agnostic-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/ucsandman/Agnostic-AI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Node 18+](https://img.shields.io/badge/node-18%2B-green.svg)](package.json)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](package.json)
[![Clients](https://img.shields.io/badge/clients-20-blue.svg)](docs/targets.md)

**One harness. Every client. One repository.**

Agnostic AI is the operating system for an AI coding harness: the guard hooks
that block secrets and destructive commands, the working agreement (rules),
the on-demand context modules, subagents, saved workflows, Mods (function-hook
plugins), operator tools and scheduled jobs. It is installed into the client
you use (Claude Code) as links, and ported from there into every other client
on the machine (Codex, Gemini CLI, Cursor and sixteen more) in each one's
dialect. Your identity, private rules, memory and machine config stay in a
small private overlay of your own.

## Install

```sh
git clone https://github.com/ucsandman/Agnostic-AI.git && cd Agnostic-AI
npm run setup      # wire the core guards, link the surfaces, assemble CLAUDE.md, port, doctor
```

Node 18+ and git, nothing else. `setup` compiles `core/rules` into
`~/.claude/agnostic-rules.md`, generates a `CLAUDE.md` that imports it, wires
the core guards into `settings.json`, links `~/.claude/{hooks,tools,mods,agents,workflows}`
into this checkout (a real directory there is moved aside, never deleted),
ports the harness to every other installed client and runs the doctor
(`CLAUDE_CONFIG_DIR` moves the home). The three commands you keep using:

```sh
npm run sync       # rules changed, or a link is missing: recompile, relink, reassemble CLAUDE.md
npm run port       # push the harness to every other installed client
npm run doctor     # drift, a second writer, a broken link, an old path, a private path in public code
```

## What is shared, what stays private

This repository holds everything portable: rules and modules, guards, Mods,
agents, workflows, tools, jobs, docs. Your overlay (`~/.claude/overlay/`, in a
repository of your own) holds `profile.md` (the private section of
`CLAUDE.md`), `context-graph.json` (your context roots) and `gates.json`
(extra frozen files); memory, meditations and `settings.json` stay in the
Claude home. `CLAUDE.md` has one writer, `npm run sync`. The doctor fails when
a tracked file here carries your account's home path.
[docs/private-overlay.md](docs/private-overlay.md).

## Context on demand

Situational text is a module, not standing prompt: a markdown file with a
`context:` block (keyword, path and command triggers; `requires` and
`suggests` edges) loads when the prompt, the edited file or the command says
it applies, in dependency order, under a budget, with the reason attached.
[docs/context-graph.md](docs/context-graph.md).

## Customize

A rule for every client: `core/rules/global-rules.md`, `npm run sync`,
`npm run port`. A rule for you only: `overlay/profile.md`, `npm run sync`. A
guard: `engine/hooks/<name>.cjs` plus a probe that fails once, a line in
[docs/guards.md](docs/guards.md), a `settings.json` registration, a relock. A
client: one entry in `core/templates/targets.json`
([engine/harness/README.md](engine/harness/README.md)). Every other "where
do I put..." is answered in [docs/where-things-go.md](docs/where-things-go.md).

## What gets ported

| Component | From (Claude Code) | To Codex CLI | To Gemini CLI | To Cursor | To 16 others |
|---|---|---|---|---|---|
| Rules (`CLAUDE.md`, imports inlined) | ✓ | `AGENTS.md` | `GEMINI.md` | `rules/*.mdc` | each client's rules file |
| Identity (`SOUL.md`) | ✓ | inlined | inlined | inlined | inlined or traits file |
| Hooks (`settings.json`) | ✓ | `config.toml`, pre-trusted | `settings.json` via shim | `hooks.json` via shim | where the client has hooks |
| Skills (`skills/*/SKILL.md`) | ✓ | linked | linked | linked | linked |
| Subagents (`agents/*.md`) | ✓ | `agents/*.toml`, model ladder mapped | – | `agents/*.md` | where supported |
| Slash commands (`commands/*.md`) | ✓ | `prompts/*.md` | `commands/*.toml` | `commands/*.md` | where supported |
| MCP servers (`.claude.json`) | ✓ | `[mcp_servers]` | `mcpServers` | `mcp.json` | where supported |
| Permissions | ✓ | `rules/*.rules` | – | – | – |

Codex CLI works as the source too: the same eight components are read back
from `~/.codex` and written into Claude Code and the rest. The live matrix for
your machine is `npm run status`; the generated per-client table is
[docs/targets.md](docs/targets.md).

Supported clients: Claude Code, Codex CLI, Gemini CLI, Antigravity CLI,
Cursor, Windsurf, GitHub Copilot, Cline, Aider, OpenHands, Goose, Continue,
Zed, OpenCode, Trae, Amazon Q, Sourcegraph Cody, OpenClaw, Hermes, and a
generic system prompt for any local or API model.

## How it works

```
capture  ~/.claude  ──▶  harness/  ──▶  apply  ~/.codex  ~/.gemini  ~/.cursor  ...
         (the client        (client-neutral        (each client's own dialect,
          you use)           bundle)                same guard scripts, same skills)
```

1. **Capture** reads the client you use into a client-neutral bundle: rules
   with every `@import` inlined, hooks in one dialect, skills, agents,
   commands, MCP servers, permissions. A value that looks like a token becomes
   `${NAME}` and you are told what to export.
2. **Apply** renders the bundle into each other client's dialect. Hooks are
   not copied: every client is pointed at the same scripts through a
   [shim](docs/porting.md#hooks-one-dialect-one-shim); skills are linked.
3. **Nothing is destroyed.** Generated files carry the port's header;
   user-owned files get a marked region and are otherwise preserved. Every
   overwrite is backed up. `--check` exits 1 on drift.
4. **Every drop is explained** by `npm run explain`, from `core/port.json`.

Details, dialect tables and the not-ported list: [docs/porting.md](docs/porting.md).

## Commands

| Command | What |
|---|---|
| `npm run setup` | First install: wire the core guards, link the surfaces, assemble `CLAUDE.md`, port, doctor. |
| `npm run sync` / `npm run sync:check` | Compile the rules for the primary client, bind the links, assemble `CLAUDE.md`. Idempotent. |
| `npm run port` / `npm run port:check` | Capture the primary client and apply to every other installed client; `check` writes nothing, exit 1 on drift. |
| `npm run doctor` | Thirteen checks with counts: links, hook wiring, generated drift, second writers, retired references, private paths, data files, orphans, context graph, deps, scheduled jobs. |
| `npm run status` / `npm run status:open` | Per-client, per-component matrix, in the terminal or as a page. |
| `npm run explain` | Everything that was not ported, with reasons. |
| `node jobs/install.cjs --apply` | Re-point the scheduled jobs (Windows Task Scheduler) at this checkout. |
| `npm test` | Engine suite plus sync, hook, wire-protocol, port, capability and context regressions. |

Flags: `--from claude|codex`, `--to codex,gemini`, `--check`, `--dry-run`,
`--force`, `--home <dir>`, `--json`. Full list:
[docs/configuration.md](docs/configuration.md).

## Also in the box

- **Safety policy.** `core/safety/guards.json` is one file read by the shipped
  guards (`secret-path-guard`, `secret-guard`, `dashclaw-guard`). Secret paths
  are always blocked; hard-stop commands need a human; a missing policy fails
  closed. The full guard roster, each with its override marker:
  [docs/guards.md](docs/guards.md).
- **Mods.** `engine/mods/` holds the function-hook plugins (`claude-runtime`,
  `harness-mods`): routing, context nudges, secret redaction, subagent
  accounting, a read cache, with a heartbeat a classic hook can verify.
- **Governed autonomy (optional).** Point `DASHCLAW_BASE_URL` at a
  [DashClaw](https://github.com/ucsandman/DashClaw) instance and risky calls
  are held for remote approval.
- **Experimental**: `labs/` and the harvest, distill and ingest ladder. Nothing in `engine/` depends on `labs/`.

## Documentation

| | |
|---|---|
| [docs/where-things-go.md](docs/where-things-go.md) | One implementation per capability, one writer per generated file: where every kind of change goes. |
| [docs/architecture.md](docs/architecture.md) | The three places, the dependency direction, capture and apply, storage. |
| [docs/ownership.md](docs/ownership.md) | The ownership matrix: every capability, its one implementation, its writer, what generates from it. |
| [docs/private-overlay.md](docs/private-overlay.md) | What the engine reads from your overlay and what stays private. |
| [docs/guards.md](docs/guards.md) | Every guard hook and its override marker. |
| [docs/context-graph.md](docs/context-graph.md) | Context modules: triggers, edges, budgets, the ledger. |
| [docs/porting.md](docs/porting.md), [docs/parity.md](docs/parity.md), [docs/targets.md](docs/targets.md) | How each component maps per client, verification, the generated per-client table. |
| [docs/configuration.md](docs/configuration.md) | `core/port.json`, every command and flag, env vars, scheduled jobs, uninstall. |
| [docs/migration-2026-09.md](docs/migration-2026-09.md), [docs/PROVENANCE.md](docs/PROVENANCE.md) | The 2026-09 consolidation and where every moved file came from. |
| [engine/harness/README.md](engine/harness/README.md) | The adapter contract: add a client in one file. |
| [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [CHANGELOG.md](CHANGELOG.md) | Setup and rules for a change; scope and reporting; release notes. |

## Repository layout

```
core/       rules/ (global-rules.md + modules/), templates/targets.json (the client registry), safety/guards.json, port.json
engine/     harness/ (capture, apply, status, cli; sources/, targets/)   context/ (the module graph)
            sync/ (rules compiler, link binder, CLAUDE.md assembly: npm run sync)   setup/ (first-run, link)
            doctor/   hooks/ (the guards, lib/, tests/, adapters/)   mods/ (function-hook plugins)   tests/
agents/     subagent definitions        workflows/   saved Workflow scripts
tools/      operator CLIs and pages      jobs/        scheduled jobs + install.cjs
packages/   markdown-agent-memory        labs/        experiments (may depend on engine; never the reverse)
docs/       this documentation           examples/    an installed harness, for reference
harness/    your captured bundle (gitignored)    storage/  runtime state, backups, reports (gitignored)
```

Installed surfaces: `~/.claude/{hooks,tools,mods,agents,workflows}` are links
into `engine/hooks`, `tools`, `engine/mods`, `agents`, `workflows`.

## Development

```sh
npm test               # engine suite + sync, hook, wire-protocol and port regressions
npm run docs:check     # generated docs are current
```

Every test builds a throwaway home directory; nothing in the suite touches
yours. CI runs on Ubuntu (Node 18 and 22) and Windows (Node 22). See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Using this repository as a template

Click **Use this template**, clone, `npm run setup`. `core/port.json` chooses
the source client, restricts targets, or excludes a hook, skill or MCP server
with a reason.

## Related

- [agnostic-agent](https://github.com/ucsandman/agnostic-agent): the terminal
  coding agent that used to live in this repo. Local or hosted models,
  subagents, the same safety policy.
- [DashClaw](https://github.com/ucsandman/DashClaw): remote approvals and
  execution evidence for unattended agents.
- [agent-capsule](https://github.com/ucsandman/agent-capsule): move a whole
  Claude Code harness onto a fresh Linux box.

## License

MIT. See [LICENSE](LICENSE).

## Runtime capabilities (`supports` in core/templates/targets.json)

Claude Code now has capabilities other targets do not (the Function Hooks layer in `~/.claude/mods`, 2026-09-16). Every target declares them explicitly; `universal-adapter.cjs` exposes `capabilitiesOf(client)` and `requires(client, feature)` so a porter DROPS a Mods-only artefact with a recorded reason (`dropped: target lacks <feature>`) instead of forcing every runtime to the lowest common denominator or pretending a target exposes a feature it does not. The Claude row describes the harness with `~/.claude/mods` installed. `engine/tests/reg-capabilities.cjs` fails when this table and targets.json disagree.

<!-- capabilities:start -->
| target | tool intercept | result mutation | runtime events | subagent events | UI injection | dynamic permissions | context signals | usage signals | middleware | runtime memory | checkpointing | semantic judgment |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | file-level | stub,model,jev |
| codex | yes | no | yes | yes | no | yes | no | no | no | no | none | stub |
| gemini | yes | no | yes | no | no | no | no | no | no | no | none | stub |
| agy | yes | no | yes | no | no | no | no | no | no | no | none | stub |
| cursor | no | no | no | no | no | no | no | no | no | no | none | stub |
| windsurf | no | no | no | no | no | no | no | no | no | no | none | stub |
| copilot | no | no | no | no | no | no | no | no | no | no | none | stub |
| cline | no | no | no | no | no | no | no | no | no | no | none | stub |
| aider | no | no | no | no | no | no | no | no | no | no | none | stub |
| openhands | no | no | no | no | no | no | no | no | no | no | none | stub |
| goose | no | no | no | no | no | no | no | no | no | no | none | stub |
| continue | no | no | no | no | no | no | no | no | no | no | none | stub |
| zed | no | no | no | no | no | no | no | no | no | no | none | stub |
| opencode | no | no | no | no | no | no | no | no | no | no | none | stub |
| trae | no | no | no | no | no | no | no | no | no | no | none | stub |
| amazonq | no | no | no | no | no | no | no | no | no | no | none | stub |
| cody | no | no | no | no | no | no | no | no | no | no | none | stub |
| openclaw | no | no | no | no | no | no | no | no | no | no | none | stub |
| hermes | no | no | no | no | no | no | no | no | no | no | none | stub |
| generic | no | no | no | no | no | no | no | no | no | no | none | stub |
<!-- capabilities:end -->
