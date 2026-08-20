# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security
- Command center (`tools/dashboard`) and parity UI (`tools/sync`): every
  mutating `POST` route now requires a per-process token plus a loopback
  `Origin`/`Referer`; request bodies are capped at 1 MB. Previously any page
  open in the browser could trigger a sync, approve a rule into the SSOT, or
  rewrite governance config.
- Dashboard guard simulator now evaluates `core/safety/guards.json` through the
  real local guard instead of a separate hardcoded pattern list.
- Removed three fabricated "audit events" (including a "zero secret leaks"
  scan result that never ran) from the governance view; it now shows only real
  events and an explicit count.
- `tools/errorlog --selftest` now asserts and exits non-zero on failure.

### Performance
- `agnostic --help` and test start-up: the `openai` SDK is imported lazily.
- `grep_search` / `find_files` skip `node_modules`, `venv`, `dist`, `build` and
  similar directories (same list the indexer uses) and run the cheap path
  filter before the safety-guard check.
- `@file` / `#symbol` lookups reuse one `SafetyGuard` per workspace instead of
  re-reading and re-compiling `guards.json` on every reference.
- Web companion shuts down promptly (`poll_interval=0.05`), which also cuts
  ~6 s from the Python test suite.
- `/api/projects` loads the skills manifest, config and candidates once per
  request instead of once per project.

### Added
- `agnostic --version`.
- `pyproject.toml` (PEP 621) with a `dev` extra (`pytest`, `ruff`) and ruff /
  pytest configuration; `setup.py` removed.
- `docs/` (architecture, configuration, slash-command reference, generated
  client table), `SECURITY.md`, `CONTRIBUTING.md`, issue and PR templates.
- `npm run docs:targets` / `docs:check`: `docs/targets.md` is generated from
  `core/templates/targets.json` and checked in CI.
- CI: ruff, Python 3.9 + 3.12 matrix, generated-docs check.

### Fixed
- Port collisions no longer hand you another app's UI. The command center used
  to treat any `EADDRINUSE` on 7842 as "already running" and open a browser at
  whatever was listening; it now probes for its own `x-agnostic-dashboard`
  header and, if a foreign app owns the port, binds the next free one (10 tries)
  and prints the URL it actually bound. `--port N` works as documented.
- The web companion (`--web`, `/web`) walks up from 7843 to the next free port
  instead of refusing to start when the port is taken.

### Changed
- README rewritten to describe what the code actually does (swarm roles,
  worktrees off by default, all four local ports, every slash command and
  npm script, Windows-first note).
- `/multiline` in the Textual TUI now answers (pointing at `agnostic-legacy`)
  instead of being sent to the model. A test now asserts every entry in
  `SLASH_COMMANDS` has a dispatch branch.
- URL-fetch tool identifies itself as `AgnosticAI/<version>` instead of a
  browser user agent.
- `except Exception: pass` sites narrowed or surfaced; sandbox rollback now
  reports whether `git restore` / `git clean` actually succeeded.
- Generated runtime state (`storage/skills-manifest.json`,
  `storage/prune-report.json`, `storage/deleted-candidates.json`) is no longer
  tracked.

## [1.2.0] - 2026-08-20

### Added
- Textual-based TUI (`agnostic`) with an always-available input box; the
  prompt_toolkit shell remains as `agnostic-legacy`.
- Promotion loop closed: approving a candidate from the dashboard writes the
  rule into `core/rules/global-rules.md`.
- Native subscription bridges (`agy`, `claude`, `codex` CLIs) and hosted API
  presets behind `/model`.
- Parallel read-only tool calls, mtime-based AST cache, output truncation,
  multi-file checkpoints, session bookmarks, `/swarm`, `/diagram`, `/test`,
  `/fix`, `/pr`, `/learn`, `/grill-me`.
- CI workflow running pytest and the three Node suites.

### Fixed
- Claude Code `PreToolUse` hook schema written by first-run setup.
- Duplicate system messages on auto-compaction; web companion live telemetry.

## [1.0.0] - 2026-08-18

### Added
- Initial harness: rules SSOT, 18-target sync engine, cross-agent merge,
  harvester, 4-tier distillation ladder, DashClaw governance hooks, skill
  consolidation and recommendation, local command center.
