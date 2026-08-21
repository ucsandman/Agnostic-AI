# Agnostic AI

[![CI](https://github.com/ucsandman/agnostic-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/ucsandman/agnostic-harness/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![Node 18+](https://img.shields.io/badge/node-18%2B-green.svg)](package.json)

One rules file for every AI coding tool you use, plus a terminal coding agent
that runs against local or hosted models under the same safety policy.

- **Harness.** Write your working agreement once in
  `core/rules/global-rules.md`. `npm run sync` compiles it into the rules file
  of 18 clients (Claude Code, Codex, Cursor, Windsurf, Copilot, Cline, Aider,
  OpenHands, Goose, Continue, Zed, Trae, Amazon Q, Cody, Antigravity,
  OpenClaw, Hermes, generic system prompt), links your skills directory into
  the 14 that have one, and registers the same guard hook in the 10 that
  support hooks. Corrections and errors from those sessions are harvested back into
  candidate rules, which you approve from a local dashboard.
- **Agent.** `agnostic` is a Textual TUI coding agent with file / shell /
  search tools, subagents, an AST symbol index, checkpoints, a test-and-fix
  loop and an arrow-key `/model` picker covering LM Studio and Ollama, hosted
  Gemini / Claude / GPT / DeepSeek presets, and logged-in `claude` / `codex` /
  `agy` CLIs with no API key (with per-subscription model pinning and session
  continuity). It has persistent auto-memory, MCP tool servers (`.mcp.json`),
  per-model cost/latency tracking, a multi-line composer, double-Esc rewind,
  a `/diff` turn browser, `!cmd` shell escape and a headless `agnostic -p`
  mode for scripting it as a subagent.
- **Policy.** `core/safety/guards.json` is read by the Python guard, the Node
  hooks and the dashboard. Secret paths are always blocked; hard-stop commands
  need a human unless you opt in; a missing or unreachable policy fails closed.

Developed on Windows 11; CI runs on Ubuntu with Python 3.9 and 3.12 and
Node 20.

## Quick start

Requirements: Python 3.9+, Node 18+. There are no npm dependencies.

```bash
git clone https://github.com/ucsandman/agnostic-harness.git
cd agnostic-harness
pip install -e .

# Edit your rules, then compile them to every client
#   core/rules/global-rules.md
npm run sync:check     # what would change (exit 1 if stale)
npm run sync           # write, with a backup of every file it overwrites

# Start the coding agent (LM Studio default endpoint)
agnostic
agnostic --url http://localhost:11434/v1 --model qwen2.5-coder   # Ollama
agnostic -p "explain #CodebaseIndexer in @agent/tools/indexer.py"  # one shot

# Open the command center
npm run dashboard      # http://127.0.0.1:7842
```

`python launch.py` runs first-run setup (harvest, skill consolidation, sync),
checks parity, checks DashClaw, runs the engine self-tests and then opens the
dashboard. It is not interactive.

## The agent in two minutes

```
agnostic > /model                      # pick endpoint, preset and effort
agnostic > @agent/loop.py how does tool dispatch work?
agnostic > /plan add a --dry-run flag to sync
agnostic > /test                       # detect runner, loop fixes until green
agnostic > /review                     # reviewer subagent over the diff
agnostic > /commit
```

- `@path` injects a file, `#symbol` injects one function or class from the
  AST index. Tab completes both against the workspace index, in either shell.
- Read-only tools (`read_file`, `grep_search`, `find_files`, `get_outline`,
  `find_symbol`) run in parallel when the model asks for several at once.
  `read_file` and `get_outline` truncate past 120 lines to head and tail (an
  explicit line range is never truncated); `grep_search` and `find_files` stop
  at 40 and 50 results and say so.
- `/trust reads|tests|all` sets the session tier. Only `all` lets hard-stop
  commands run without a prompt; start with `--ask-permissions` to be asked
  instead of denied. Secret paths are blocked in every tier.
- `/undo`, `/checkpoint`, `/session`, `/compact`, `/swarm`, `/diagram`,
  `/pr`, `/learn` and the rest are in
  [docs/slash-commands.md](docs/slash-commands.md).
- `agnostic --web` (or `/web`) starts a browser companion on 7843 (next free
  port if taken) with live telemetry, diffs and a context meter.
- Prefer a classic readline shell? `agnostic-legacy` runs the same loop with
  prompt_toolkit.

## The harness in two minutes

| Command | What |
|---|---|
| `npm run sync` / `sync:check` | Compile rules + traits + policy into every client listed in `core/templates/targets.json`. Drifted (hand-edited) targets are backed up and skipped unless `--force`. |
| `npm run merge` / `merge:global` | Pull lessons from project `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` files back into the rules. |
| `npm run harvest` | Collect errors and corrections from local agent logs into `storage/candidates.jsonl`. |
| `npm run distill` | Run the promotion ladder (observation → fact → rule) and the pruner; write a digest and proposal. Rules are only written into the SSOT when you approve them. |
| `npm run dashboard` | Command center on 7842: candidates, rules, skills matrix, per-project recommendations, routines, governance settings, guard simulator. |
| `npm run skills:consolidate` / `skills:recommend` | Gather skills from every client into one catalog; score them per project. |
| `npm run parity` / `recall` | Per-target sync status (7845), rule and memory search (7844). |
| `npm run setup:default` | First-run onboarding (what `launch.py` calls). |
| `npm run dashclaw:setup` / `dashclaw:status` | Optional governed autonomy via [DashClaw](https://github.com/ucsandman/DashClaw). |

All local UIs bind `127.0.0.1`. Mutating routes need a per-process token and a
loopback origin, so a page in another tab cannot trigger a sync or approve a
rule.

Full client table (rules file, hook config, skills dir per client), generated
from `targets.json`: [docs/targets.md](docs/targets.md).

## Documentation

| | |
|---|---|
| [docs/architecture.md](docs/architecture.md) | How sync, hooks, harvest, distill and the agent loop fit together; storage layout. |
| [docs/configuration.md](docs/configuration.md) | Files you edit, every env var, CLI flags, trust tiers, DashClaw, scheduled jobs, uninstall. |
| [docs/slash-commands.md](docs/slash-commands.md) | Every slash command, and whether the TUI or legacy shell handles it. |
| [docs/targets.md](docs/targets.md) | The 18 supported clients. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, test commands, where things live, rules for a change. |
| [SECURITY.md](SECURITY.md) | Scope, reporting, what the guard is not. |
| [CHANGELOG.md](CHANGELOG.md) | Release notes. |

## Repository layout

```
agent/          Python coding agent: tui.py (default), cli.py (legacy), loop.py,
                llm/ (client, presets, endpoint detector), tools/ (registry, indexer,
                subagents), governance/ (guard, audit, undo, context, sessions),
                workflows/ (swarm, tester, pr_pilot, diagram, scheduler), web/
core/           Single source of truth: rules/, traits/, safety/guards.json,
                templates/targets.json, examples/
engine/         Zero-dependency Node: sync/, hooks/, harvest/, distill/, ingest/,
                skills/, audit/, setup/, docs/, tests/
tools/          Local web UIs: dashboard/, recall/, sync/ (parity)
jobs/           PowerShell wrappers for scheduled sync and nightly distill
tests/          pytest suite for the agent
storage/        Runtime state (gitignored except .gitkeep); backups of every synced file
launch.py       First-run + dashboard launcher
```

## Development

```bash
pip install -e ".[dev]"
ruff check .
python -m pytest tests/ -q
npm test                 # engine + sync + hook regression suites
npm run docs:check
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Using this repository as a template

Click **Use this template** on GitHub, clone your copy, replace
`core/rules/global-rules.md` and `core/traits/traits.md` with your own
working agreement, and run `npm run sync`. Set `AGNOSTIC_PROJECTS_DIR` if
your projects do not live in `C:\Projects` / `~/Projects`.

## License

MIT. See [LICENSE](LICENSE).
