# Agnostic AI

[![CI](https://github.com/ucsandman/Agnostic-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/ucsandman/Agnostic-AI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Node 18+](https://img.shields.io/badge/node-18%2B-green.svg)](package.json)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](package.json)
[![Clients](https://img.shields.io/badge/clients-20-blue.svg)](docs/targets.md)

**Your AI coding harness, ported to every client you use.**

You spent months tuning Claude Code: a working agreement in `CLAUDE.md`, guard
hooks that block secrets and destructive commands, skills, custom subagents,
slash commands, MCP servers. Then you open Codex, or Cursor, or Gemini CLI, and
none of it is there. Agnostic AI captures that harness once and applies it,
identically, to every other client on the machine. Switch models and tools
without switching how the agent behaves.

```sh
git clone https://github.com/ucsandman/Agnostic-AI.git && cd Agnostic-AI
npm run port
```

That is the whole install. No npm dependencies, no Python, nothing phones
home. Node 18 or newer.

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

1. **Capture** reads the client you use into a client-neutral bundle:
   markdown rules with every `@import` inlined, hooks in one canonical dialect,
   the list of skills, agents, commands, MCP servers and permissions. A
   credential never enters the bundle: an env value that looks like a token is
   replaced with `${NAME}` and you are told which variable to export.
2. **Apply** renders the bundle into every other installed client, in that
   client's dialect. Hooks are not copied; each client is pointed at the same
   scripts, wrapped in a [shim](docs/porting.md#hooks-one-dialect-one-shim)
   where the client speaks another payload format. Codex gets its hook trust
   hashes pre-computed so nothing asks for a `/hooks` review. Skills are
   linked, not copied, so an edit is live everywhere at once.
3. **Nothing is destroyed.** Generated files carry a header that marks them
   as the port's; user-owned files (`config.toml`, `settings.json`, `mcp.json`)
   get a marked region or per-key ownership and are otherwise preserved byte
   for byte. Every overwrite is backed up first. `--check` exits 1 on drift.
4. **Every drop is explained.** A hook that only makes sense in one client, a
   skill that needs a tool only one client has, an MCP server bound to one
   OAuth grant: each is listed by `npm run explain` with its reason, and the
   list lives in `core/port.json` where you can change it.

Details, dialect tables and the not-ported list: [docs/porting.md](docs/porting.md).

## Commands

| Command | What |
|---|---|
| `npm run port` | Capture the source client and apply to every other installed client. The everyday command. |
| `npm run port:check` | Same, writes nothing; exit 1 if anything drifted. Put it in a nightly job. |
| `npm run status` / `npm run status:open` | Per-client, per-component matrix, in the terminal or as a page. |
| `npm run explain` | Everything that was not ported, with reasons. |
| `npm run parity` | The status page as a local server with a "Port now" button (`127.0.0.1` only). |
| `npm run capture` / `npm run apply` | The two halves separately. |
| `npm run setup:default` | First-run onboarding: harvest past lessons, consolidate skills, port, install the shipped guards into your primary client. |
| `npm run launch` | Setup check, port check, engine tests, then the command center. |

Flags: `--from claude|codex`, `--to codex,gemini`, `--check`, `--dry-run`,
`--force`, `--home <dir>`, `--json`. Full list:
[docs/configuration.md](docs/configuration.md).

## Also in the box

- **Safety policy.** `core/safety/guards.json` is one file read by the
  shipped guards (`secret-guard`, `dashclaw-guard`) and the dashboard
  simulator. Secret paths are always blocked; hard-stop commands need a human;
  a missing or unreachable policy fails closed. `npm run setup:default`
  installs the guards into your primary client, and the port carries them
  everywhere else.
- **A learning loop.** `npm run harvest` collects errors and corrections from
  local agent logs into candidate rules; `npm run distill` runs a promotion
  ladder (observation, fact, rule) and writes a proposal; you approve from the
  dashboard and the rule lands in your working agreement.
- **Authoring mode.** Prefer to keep the working agreement in this repo?
  Write `core/rules/global-rules.md`, run `npm run sync` to compile it into
  your primary client, then `npm run port`.
- **Human surfaces.** `npm run dashboard` (command center: candidates, rules,
  skills matrix, project recommendations, DashClaw settings, guard simulator),
  `npm run recall` (search rules and memory), `npm run parity` (port status).
  All bind `127.0.0.1`; mutating routes need a per-process token and a loopback
  origin.
- **Governed autonomy (optional).** Point `DASHCLAW_BASE_URL` at a
  [DashClaw](https://github.com/ucsandman/DashClaw) instance and risky calls
  are held for remote approval.

## Documentation

| | |
|---|---|
| [docs/porting.md](docs/porting.md) | What each component is, how it maps per client, the hook shim, what is deliberately not ported, ownership and secrets. |
| [docs/targets.md](docs/targets.md) | The generated per-client table: home, rules file, hook config, skills, agents, commands, MCP. |
| [docs/architecture.md](docs/architecture.md) | How capture, apply, the shim, harvest and distill fit together; storage layout. |
| [docs/configuration.md](docs/configuration.md) | `core/port.json`, every command and flag, env vars, scheduled jobs, uninstall. |
| [engine/harness/README.md](engine/harness/README.md) | The adapter contract: add a client in one file. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, tests, where things live, rules for a change. |
| [SECURITY.md](SECURITY.md) | Scope, reporting, what the guard is not. |
| [CHANGELOG.md](CHANGELOG.md) | Release notes. |

## Repository layout

```
engine/harness/   capture.cjs, apply.cjs, status.cjs, cli.cjs, bundle.cjs, toml.cjs, common.cjs
                  sources/ (claude, codex)   targets/ (codex, claude, gemini, agy, cursor, generic)
engine/hooks/     shim.cjs (dialect translation), universal-adapter.cjs, secret-guard, dashclaw-guard,
                  fable-delegate-guard, capability-graph-guard, correction-tracker
engine/           sync/ (authoring mode), harvest/, distill/, ingest/, skills/, audit/, setup/, docs/, tests/
core/             port.json (policy), templates/targets.json (registry), safety/guards.json,
                  rules/ + traits/ (authoring mode), examples/
tools/            Local web UIs: sync/ (port status), dashboard/, recall/
harness/          Your captured bundle (gitignored; holds machine paths, never secrets)
storage/          Runtime state (gitignored): ownership, reports, backups of every overwritten file
jobs/             PowerShell wrappers for a scheduled port and the nightly distill
```

## Development

```sh
npm test               # engine suite + sync, hook, wire-protocol and port regressions
npm run docs:check     # generated docs are current
```

Every test builds a throwaway home directory; nothing in the suite touches
yours. CI runs on Ubuntu (Node 18 and 22) and Windows (Node 22). See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Using this repository as a template

Click **Use this template** on GitHub, clone your copy, run `npm run port`.
Edit `core/port.json` to change the source client, restrict the targets, or
exclude a hook, skill or MCP server with a reason. To version your harness,
remove the `harness/` line from `.gitignore`; the bundle is plain markdown and
JSON and the save refuses anything that looks like a secret.

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
