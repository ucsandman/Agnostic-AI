# Architecture

Two products share this repository and one safety policy:

1. **The harness** (Node, zero dependencies, `engine/` + `tools/`): one rules
   file compiled into the rules file of 18 AI coding clients, hook shims that
   put the same guard in front of each client's tool calls, and a loop that
   harvests errors and corrections back into candidate rules.
2. **The coding agent** (Python, `agent/`): a terminal agent that talks to any
   OpenAI-compatible endpoint or to a logged-in `claude` / `codex` / `agy` CLI,
   with the same guard compiled in.

```
core/rules/global-rules.md  core/traits/traits.md  core/safety/guards.json
          │                        │                       │
          └──────────── engine/sync/sync.cjs ──────────────┘
                                   │  (dialect per core/templates/targets.json)
      ┌─────────┬─────────┬────────┼────────┬─────────┬──────────┐
   ~/.claude  ~/.codex  ~/.gemini  ~/.cursor  ...   ~/.hermes  storage/compiled
   CLAUDE.md  AGENTS.md GEMINI.md  rules.mdc        system.md  system_prompt.md
      │         │         │
      └─ hooks ─┴─────────┘  engine/hooks/universal-adapter.cjs normalises each
                             client's hook payload → secret-guard / dashclaw-guard /
                             correction-tracker
                                          │
                 engine/harvest/harvest.cjs ← error logs, corrections, CLAUDE.md lessons
                                          │
                 storage/candidates.jsonl → engine/distill/distill.cjs (promotion ladder)
                                          │
                 tools/dashboard (human approves) → writes back into global-rules.md
```

## Harness

### Sync (`engine/sync/sync.cjs`)

Reads `core/rules/global-rules.md`, `core/traits/traits.md` and
`core/safety/guards.json`, then for every entry in
`core/templates/targets.json` writes the client's rules file with that
client's preamble and dialect, links the skills directory (`mklink /J` on
Windows, symlink elsewhere) and registers hook config where the client has one.

- Every overwrite is preceded by a timestamped backup in `storage/backups/`.
- A target whose content no longer matches the hash sync last wrote is
  "drifted" (hand-edited). It is backed up and skipped unless `--force`.
- `--check` exits 1 if any target is stale. `--target <id>` syncs one client.
- The generated client table is in [`targets.md`](targets.md).

### Hooks (`engine/hooks/`)

| File | Role |
|---|---|
| `universal-adapter.cjs` | Translates Claude Code / Codex / Antigravity / OpenClaw / generic hook payloads into one `{client, event, toolName, command, targetFile}` object and back into each dialect's allow / deny response. |
| `secret-guard.cjs` | Denies tool calls that touch secret paths. Patterns come from `guards.json`; a built-in fallback list applies if that file is unreadable (fail closed). |
| `dashclaw-guard.cjs` | Scores the call (`calculateLocalRisk`) from `guards.json`. Below the query threshold: allow. At or above it: ask DashClaw if configured, else apply the local verdict. At or above the hard-block threshold with no reachable approver: deny. An unreachable or timed-out governance layer never turns a hard stop into an allow. |
| `correction-tracker.cjs` | Appends user corrections / rejections to `storage/corrections.jsonl` for the harvester. |
| `dashclaw-setup.cjs` | Writes `storage/dashclaw-config.json` from `DASHCLAW_*` env vars and registers the guard hook in each client that supports hooks. |

Hooks are wired for 10 of the 18 clients; the rest get the rules-file guards
only (see `targets.md`).

### Harvest and distill

`engine/harvest/harvest.cjs` scans local agent logs (`~/.claude/error-log`,
`~/.claude/corrections.jsonl`, `storage/corrections.jsonl` from the
correction-tracker hook, meditation candidates, the learned-rules
section of `global-rules.md`) and writes deduplicated records to
`storage/candidates.jsonl`. Deleted candidates are tombstoned in
`storage/deleted-candidates.json` so they do not reappear.

`engine/distill/distill.cjs` runs the promotion ladder over the candidates and
writes `storage/distill-digest.json` (what the dashboard shows) and
`storage/distill-PROPOSAL.md`:

| Tier | Meaning | Automated? |
|---|---|---|
| 0 Observation | a raw sighting | yes (harvest) |
| 1 Fact | repo-specific, repeated | yes: promoted by the distiller |
| 2 Rule | seen on 3+ distinct days; capped at 5 core rules | yes: proposed by the distiller, **written only when a human approves** in the dashboard (or `--approve <id>`) |
| 3 Trait | a disposition in `core/traits/traits.md` | no: hand-curated |
| E Example | failure converted to a few-shot fixture in `core/examples/` | yes (`prune.cjs`) |

`engine/distill/prune.cjs` enforces the rule ceiling, detects contradictions
between a candidate and active rules, and suggests evictions.
`engine/ingest/merge.cjs` pulls lessons from project-level `CLAUDE.md` /
`AGENTS.md` / `GEMINI.md` files back into the SSOT.

### Skills

`engine/skills/consolidate.cjs` copies skills found in each client's skills
directory into `skills/definitions/` (gitignored; rebuilt locally) and writes
`storage/skills-manifest.json`. `engine/skills/recommend.cjs` inspects a
project (package.json, requirements, Cargo, go.mod, etc.) and scores skills
for it; `storage/skills-config.json` holds global and per-project enables.
`engine/audit/bloat-audit.cjs` estimates the context cost of globally enabled
skills and stale observations.

### Human surfaces (`tools/`)

All servers bind `127.0.0.1`. Mutating routes are `POST`, require the
per-process token injected into the page, and reject non-loopback origins.

| Tool | Port | What |
|---|---|---|
| `tools/dashboard` | 7842 | Command center: candidates, rules, skills matrix, project recommendations, routines, DashClaw settings, guard simulator. |
| `tools/recall` | 7844 | Search rules, memory files and decisions. |
| `tools/sync/parity` | 7845 | Per-target sync status with a "sync now" button. |
| `agent/web/server.py` | 7843 | Live companion for the coding agent: telemetry, diffs, context meter, run tests / distill. |

Ports are defaults, not guarantees. If another local app already holds one, the
server walks up to the next free port (10 tries) and logs the URL it bound. It
never reuses an occupied port unless it can confirm the occupant is itself.

## Coding agent (`agent/`)

```
agent/tui.py (Textual)  ──┐
agent/cli.py (prompt_toolkit, legacy) ──┤→ agent/loop.py AgentLoop → agent/llm/client.py
                           │                   │                       ├─ OpenAI-compatible HTTP (LM Studio, Ollama, hosted)
ui_common.py: arg parser,  │                   │                       └─ subscription bridge (agy / claude / codex CLIs)
@file #symbol expansion,   │                   ▼
slash list                 │      agent/tools/registry.py  (read_file, write, edit, bash, grep, find, outline, find_symbol, fetch_url ...)
                           │                   │  read-only tools run in a ThreadPoolExecutor when a batch is all read-only
                           │                   ▼
                           │      agent/governance/guard.py  ← core/safety/guards.json (same policy as the hooks)
                           │      interceptor.py (pre/post tool hooks), audit.py, undo.py, context.py (auto-compaction),
                           │      session_manager.py, state.py (.agnostic/state.md), watchdog.py (git rollback)
                           └──→   agent/tools/indexer.py  (AST symbol index, mtime cache, honours DEFAULT_IGNORED_DIRS)
                                  agent/tools/subagent.py (researcher / tester / reviewer roles, optional git worktrees)
                                  agent/workflows/  swarm, tester (/test /fix), pr_pilot, diagram, scheduler
```

- **Trust tiers** (`/trust`): `strict`, `trust-reads`, `trust-tests`,
  `trust-all`. Secret paths stay blocked in every tier. Hard-stop commands are
  denied unless the agent was started with `--ask-permissions`, in which case
  you are prompted.
- **Context**: `run_command`, `read_file` and `get_outline` truncate output to
  head/tail beyond 120 lines (an explicit `read_file` range is exempt), and the
  search tools stop at their result cap and say so; older turns are compacted
  automatically or with `/compact`.
- **Checkpoints / undo**: `/undo` reverts the last file write; `/checkpoint`
  snapshots and restores groups of files.
- **Swarm**: `/swarm <task>` runs three subagents (researcher, tester,
  reviewer) in threads and asks the model for a combined summary. Worktree
  isolation exists in `SubagentManager` but is off by default.

## Storage layout

| Path | Tracked | Written by |
|---|---|---|
| `storage/candidates.jsonl` | no | harvest, `/learn`, dashboard edits |
| `storage/distill-digest.json`, `distill-PROPOSAL.md` | no | distill |
| `storage/corrections.jsonl` | no | correction-tracker hook |
| `storage/deleted-candidates.json`, `prune-report.json`, `skills-manifest.json`, `skills-config.json` | no | harvest / prune / consolidate / dashboard |
| `storage/backups/`, `sync-state.json` | no | sync |
| `storage/dashclaw-config.json`, `harness-installed.json` | no | dashclaw-setup, first-run |
| `storage/compiled/` | no | sync (generic system prompt) |
| `skills/definitions/` | no | consolidate |
| `core/**` | yes | you (and approved promotions) |
