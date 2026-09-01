# Configuration

## Files you edit

| File | Purpose |
|---|---|
| `core/rules/global-rules.md` | Your working agreement. The only rules file you maintain; every client's file is compiled from it. |
| `core/traits/traits.md` | Tier-3 dispositions appended after the rules. |
| `core/safety/guards.json` | Secret paths, blocked commands, hard-stop patterns, DashClaw thresholds. Read by the Python guard, the Node hooks and the dashboard simulator. |
| `core/templates/targets.json` | The 18 clients: rules file path, hook config path, skills dir, dialect, preamble. |
| `core/examples/` | Few-shot fixtures produced by `prune.cjs`. |

`npm run sync` after editing any of the first three. `npm run docs:targets`
after editing the fourth.

## Environment variables

Nothing loads `.env` for you; export variables in your shell or CI.
`.env.example` lists every variable with a comment. Summary:

| Variable | Used by | Default |
|---|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `DEEPSEEK_API_KEY` | hosted presets in `/model` | unset (preset refuses to start) |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | generic OpenAI-compatible preset | `http://localhost:1234/v1`, `local-model`, `lm-studio` |
| `DASHCLAW_BASE_URL`, `DASHCLAW_API_KEY`, `DASHCLAW_AGENT_ID`, `DASHCLAW_AGENT_NAME` | `engine/hooks/dashclaw-setup.cjs` | unset; governance stays local |
| `PORT` | dashboard | 7842 (next free port if taken) |
| `RECALL_PORT` | recall | 7844 |
| `PARITY_PORT` | parity | 7845 |
| `AGNOSTIC_STORAGE` | harvest / distill / prune | `<repo>/storage` |
| `AGNOSTIC_EXAMPLES_DIR` | prune | `<repo>/core/examples` |
| `AGNOSTIC_PROJECTS_DIR` | skill recommender, dashboard Projects tab | `C:\Projects` on Windows, `~/Projects` elsewhere |

The agent's web companion (`agnostic --web`, `/web`) starts on 7843. Every
server here walks up to the next free port when its default is already taken by
another local app, and prints the URL it actually bound.

## Agent command-line flags

```
agnostic [--url URL] [--model NAME] [--api-key KEY] [--full-prompt]
         [--prompt TEXT | -p TEXT | --print TEXT] [--output-format text|json]
         [--yes] [--ask-permissions] [--web] [--version]
agnostic-legacy   (same flags, prompt_toolkit shell)
```

| Flag | Effect |
|---|---|
| `--url` | OpenAI-compatible base URL (LM Studio `http://localhost:1234/v1`, Ollama `http://localhost:11434/v1`, ...). |
| `--model` | Model id. `/doctor` can detect it from the endpoint. |

With `--url` and `--model` untouched, startup does **not** assume a local
endpoint: it picks the last `/model` choice (persisted in
`~/.agnostic/settings.json`), else the best installed subscription CLI
(`claude`, then `codex`, then `agy`), else the first API-key preset whose env
var is set, and only then falls back to the local endpoint.

| `--api-key` | Key for `--url`; defaults to `lm-studio`. |
| `--full-prompt` | Send the whole compiled rules file as system prompt. Without it the agent runs on the same rules clipped to ~4 KB for small local context windows — never on a summary. |
| `-p`, `--prompt`, `--print` | Run one prompt headlessly and exit — see [Headless / scripting](#headless--scripting). `-` reads the prompt from stdin. |
| `--output-format` | `text` (default) or `json`, for `-p` runs. |
| `-y`, `--yes` | `-p` only: approve hard stops instead of denying them. |
| `--ask-permissions` | Prompt y/n on hard-stop commands. **Without it hard stops are denied**, never auto-approved. |
| `--web` | Start the companion UI on 7843 (next free port if taken). |
| `--legacy` | (`agnostic` only) Run the prompt_toolkit shell instead of the TUI; same as `agnostic-legacy`. |
| `--version` | Print the version and exit. |

Presets, effort levels and subscription bridges are chosen at runtime with
`/model`; see [`slash-commands.md`](slash-commands.md).

## Headless / scripting

`-p` (aliases `--prompt`, `--print`) runs exactly one turn with no TUI:

- **stdout** — the final assistant text and nothing else (or one JSON object with
  `--output-format json`), so it pipes.
- **stderr** — every tool, system and error line, prefixed `[tool_start]`, `[error]`, ...
- **exit code** — `0` on a clean turn, `1` if the turn emitted an error (including the
  max-steps cap), `2` for an empty prompt.
- Hard-stop confirmations are **denied** unless you pass `--yes`; `--ask-permissions`
  does nothing here because there is no terminal to answer on.
- `--model <preset key>` switches preset (e.g. `--model sub-claude-code`); any other
  value is a model id. `--web` still starts the companion, but never opens a browser.

```bash
agnostic -p 'summarise README.md' 2>/dev/null          # answer only
git diff | agnostic -p - --output-format json          # prompt from stdin
agnostic -p 'how many python files?' --output-format json | jq -r .result
```

The JSON object:

```json
{
  "result": "37",
  "tool_calls": [{"name": "run_command", "preview": "run_command({\"command\": \"...\"})"}],
  "usage": {"prompt_tokens": 5123, "completion_tokens": 88, "cost_usd": 0.02, "calls": 2},
  "model": "claude-opus-5",
  "ok": true
}
```

`usage` is `null` when the run recorded nothing in `.agnostic/usage.jsonl`, and
`cost_usd` is `null` when any call in the run had no price (see [`usage.md`](usage.md)).

## System prompt

The agent's system prompt is `storage/compiled/system_prompt.md`, compiled from
`core/rules/global-rules.md` by `npm run sync` — it is gitignored, so run the
sync once after cloning or the agent starts on a two-sentence stub and says so.

Appended to it, if present in the workspace: the first of `AGENTS.md`,
`CLAUDE.md`, `GEMINI.md`, `CONVENTIONS.md`, plus `.agnostic/state.md`, clipped to
~6 KB under a `### [Project Agreement: <file>]` heading. Without `--full-prompt`
the project agreement is dropped when it would push the prompt past ~8 KB.

## Trust tiers

`/trust reads|tests|all` sets the session tier (`strict`, `trust-reads`
(default), `trust-tests`, `trust-all`); `/untrust` returns to `strict`. What the
tier changes today (`agent/governance/guard.py → check_command_safety`):

| Tier | Hard-stop commands (force push, deploys, destructive git/db ops, ...) |
|---|---|
| `strict`, `trust-reads`, `trust-tests` | Require a human. Prompted if the agent was started with `--ask-permissions`, otherwise **denied**. |
| `trust-all` | Run without confirmation. |

Commands and file paths matching the secret patterns in `guards.json` are
blocked in every tier, with no override. Every hard-stop decision is written to
the session audit (`/audit`).

## DashClaw (optional)

Set `DASHCLAW_BASE_URL` (and `DASHCLAW_API_KEY` for a remote instance) and run
`npm run dashclaw:setup`. The guard then asks DashClaw for a decision on any
call scoring at or above `guards.json → dashclaw.defaultRiskThreshold` (50)
and holds hard stops (>= `hardBlockRiskThreshold`, 90) for remote approval.
Opt out at any time: dashboard → Governed Decisions → Settings → Opt Out, or
set `"active": false` in `storage/dashclaw-config.json`. When opted out the
harness makes no network requests for governance; the agent itself still
talks to whichever model endpoint you configured.

## Scheduled jobs (Windows)

`jobs/sync-targets.ps1` runs `npm run sync`; `jobs/daily-distill.ps1` runs
harvest + distill and logs to `storage/daily-distill.log`. Register them with
Task Scheduler (for example nightly) or run them by hand. On other platforms
call the same `node` commands from cron.

## Uninstall

The harness writes only inside this repo's `storage/` and `skills/definitions/`,
plus one rules/hooks/skills entry per client under your home directory (the
paths in [`targets.md`](targets.md)), each backed up to
`storage/backups/<client>-<file>-<timestamp>.bak` before every overwrite.

1. Restore a client's previous rules file from the newest `.bak` for it, or
   delete the target path.
2. Remove hook wiring: delete the `PreToolUse` entry pointing at
   `engine/hooks/dashclaw-guard.cjs` from `~/.claude/settings.json`, and
   `~/.codex/hooks.json` / `~/.gemini/config/hooks.json` for Codex / Antigravity.
3. Delete the skills junction or directory in the client's skills column.
4. Delete this repo's `storage/` and `skills/definitions/`.
5. `pip uninstall agnostic-agent`.
