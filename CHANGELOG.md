# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Turn-done notification: a terminal bell plus a toast (`3 files changed · 2m14s`) when a turn
  that ran 5 seconds or longer finishes while the terminal is unfocused, for agent turns and for
  /test, /fix and the other background workers. Safe-off on terminals that never report focus,
  toggled and persisted with `/notify on|off` (new workspace settings file
  `.agnostic/settings.json` via StateManager.get_setting/set_setting).
- /diff: a turn browser over the automatic per-turn checkpoints — bare `/diff` in the TUI
  opens a picker (newest turn first, each row saying how many files it changed) and prints a
  unified diff per file from the write snapshots, `/diff <turn>` skips the picker, and the
  legacy CLI lists the checkpoint names. Read-only, and usable while a turn is running
  (agent/tui_diff.py, UndoManager.changed_since).
- Multi-line composer: the TUI prompt is a TextArea (agent/tui_composer.py) instead of a
  single-line Input — Enter sends, Shift+Enter / Alt+Enter / Ctrl+J insert a newline, the box
  grows to 8 lines then scrolls, and a pasted block keeps every line (Input kept only the
  first one and silently threw away the rest of a stack trace).
- /memory: a picker over the saved memories (bare `/memory` in the TUI, ↑/↓, Space/Enter to
  print one in full), plus `/memory show|save|forget <name>` in both shells — the store was
  writable only by the model until now (agent/tui_memory.py, docs/memory.md).
- Headless mode: `agnostic -p "..."` (aliases `--prompt`, `--print`, `-` reads stdin) now runs
  one turn with no TUI through agent/headless.py — the answer alone on stdout (or one object
  with `--output-format json`), tool/system/error chatter on stderr, exit 1 when the turn
  errored, and hard stops denied unless `--yes` is passed (docs/configuration.md).
- Persistent auto-memory: workspace store in .agnostic/memory/ (MEMORY.md index +
  one markdown file per memory), injected into the system prompt as
  "## Memory (auto-recalled)", with save_memory / recall_memory tools (agent/governance/memory.py).
- MCP client (zero-dependency, stdio JSON-RPC): servers from .agnostic/mcp.json,
  .mcp.json (Claude Code format) or ~/.agnostic/mcp.json register as
  mcp__<server>__<tool> and run through the governed execute() path;
  registry.mcp_status() reports state (agent/tools/mcp.py).
- /mcp: a Server / State / Tools / Error table of the configured MCP servers, /mcp reload
  to restart them and re-read the config files without leaving the session, and a red
  `!mcp` badge in the TUI status bar while any server is in the error state — a
  misconfigured server used to fail silently into the log.
- Subscription bridges rewritten: every fenced tool call parsed (not just one),
  claude -p session continuity via --session-id/--resume with delta sends,
  --output-format json preferred, codex resume when supported, usage surfaced
  for cost tracking (docs/subscriptions.md).
- Usage / cost / latency log: .agnostic/usage.jsonl with p50/p95 and cost
  summaries; agent/llm/pricing.json ships with explicit nulls for the user to
  fill in — costs are never invented (agent/llm/usage.py, docs/usage.md).
- Every LLM call is now journalled: `LLMClient.chat_completion` writes one
  `.agnostic/usage.jsonl` entry per call on every path (API, streaming,
  subscription bridge; success and failure), streamed turns keep the usage chunk
  that arrives with an empty `choices` list, and the numbers surface as a dim
  `$ 0.42 - p50 12.3s` segment in the TUI status bar and a `p50 12.3s | $0.42
  today` column in the `/model` picker.
- A bare `/session` in the TUI opens an arrow-key resume picker of this
  workspace's saved sessions (newest first, with turn count, timestamp and
  notes) and loads the chosen one; `/session save|load|list <name>` is
  unchanged, so the flat list stays greppable.
- Double-Esc rewind in the TUI: every turn is checkpointed silently, and pressing
  Esc twice while idle opens a two-step picker — which turn, then whether to
  restore the files, the conversation, or both. The generic half of the `/model`
  picker moved to `agent/tui_picker.py::PickerScreen`, which the rewind screen
  subclasses.
- TUI tool cards now carry the tool name, how long it ran and how many lines the
  fold hid (`⚙️ run_command · 3.4s · +812 lines hidden — ctrl+o`), clipped on a
  line boundary instead of mid-line, and `Ctrl+O` prints the last tool's output
  in full — the escape hatch ships with the fold.
- A `!` prefix in the TUI runs a shell command locally without spending a turn:
  `!git status`, `!ls tests`. It goes through the same `run_command` tool the
  model uses, so `core/safety/guards.json` stays the single policy source and a
  hard-stop command still asks, and it appends nothing to the conversation —
  zero context, zero LLM calls.
- The TUI status bar carries a `CTX ███░░░░░░░  31% (620k/2.0M)` gauge — bar,
  exact percentage and colour (green/yellow/red), fixed width so it never
  shifts — and warns once, before the cliff, naming the auto-compaction
  threshold and the remediation. `/compact` now prints what the distillation
  kept, and `/compact undo` restores the pre-compaction messages.
- Typing ahead during a governance hard-stop no longer revokes it: text that is
  not a y/n answer is queued as a prompt and the confirm stays pending (Esc is
  the explicit deny, so a worker can never block forever). A verdict can carry a
  reason — `n: too risky, patch the test instead` denies and prepends the reason
  to the next turn.
- Shift+Tab in the TUI cycles the trust tier (`strict` → `trust-reads` →
  `trust-tests` → `trust-all` → `strict`), and the status bar carries a `🛡`
  badge read live from `SafetyGuard` on every repaint — red on `trust-all` — so
  the displayed tier can never drift from the one being enforced.
- Ctrl+C in the TUI escalates instead of scolding: while a turn runs it cancels
  it, and a second press within 1.5s force-exits (idle, two presses quit). Ctrl+L
  asks twice before clearing the log. Both share one `_double_tap` timer.
- Live busy indicator in the TUI status bar: `∴ Percolating… 47s · esc to cancel`,
  ticking once a second while a turn or background worker runs, with the verb
  chosen once per turn (override the pool with `AGNOSTIC_SPINNER_VERBS`). The
  status bar is now built as a `rich.text.Text`, so a cwd or model name
  containing `[` can no longer be parsed as markup.
- `/model` in the TUI is an interactive picker (`agent/tui_model_picker.py`):
  arrow keys move, Space/Enter select, Esc steps back. Preset → (subscription
  presets only) concrete model → effort, the last step skipped when the model
  ignores it.
- Subscription presets can pin the model their CLI runs: pick Claude Code
  Monthly Subscription, then `claude-fable-5`, and the bridge passes
  `--model claude-fable-5` to `claude` (`-m` for `codex`, `--model` for `agy`).
  `LLMConfig.sub_model`, `LLMConfig.sub_models(key)`,
  `switch_model(sub_model=...)`; text form `/model 2 claude-fable-5 high` (any
  order after the key, legacy CLI included). Status bar shows `preset › model`.

### Changed
- `agent/tui.py` (1352 lines) split: the slash-command dispatcher and `/commit`
  workflow moved verbatim into `agent/tui_commands.py` as `SlashCommandMixin`
  (~450 lines). No behaviour change; `AgnosticTUI` inherits the mixin. The
  background-dispatch test now parses the method's own source file.

## [1.3.0] - 2026-08-20

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
- `grep_search` / `find_files` prune ignored directories during the walk
  (`os.walk` + `dirs[:]`), skip binary extensions, prefilter each file in one
  pass and run the path guard only on real matches — ~6× faster on this repo.
- AST indexer keeps a per-file symbol map, so re-indexing a changed file no
  longer scans every symbol in the workspace (was 41 % of a full index).
- TUI start-up no longer blocks on the workspace index or the endpoint probe;
  both run as background workers and the banner updates when they answer.
- `@file` / `#symbol` expansion runs on the turn worker, not the UI thread.
- The interceptor no longer spawns a `node` process after every tool call
  (the correction tracker could never fire from that payload).
- `SessionManager.list_sessions()` caches per file by mtime; the web companion
  polls it at 1 Hz.
- One `httpx.Client` per timeout value is shared by every `OpenAI` client and
  the `ModelDoctor` probe instead of building a new SSL context (~200 ms) on
  every construction and `/model` switch; the old pool no longer leaks.
- Command center reads `dashboard.html` once at start-up instead of 142 KB per
  request; the error search is debounced and says when it hits the 500-record
  cap.

### Added
- `agnostic --version`.
- **Esc cancels a running turn.** `AgentLoop.cancel_event` is checked between
  steps and before every tool dispatch; `run_command` kills its child; pending
  tool calls are answered `[cancelled by user]` so the history stays valid.
- `run_command` output streams live into the TUI's growing block (and the
  legacy CLI) while the command runs; the final result card is unchanged.
- `/schedule list` and `/schedule stop <id>|all` for background routines.
- `find_symbol` tool: the AST symbol index the `#symbol` prompt syntax already
  used is now available to the model (read-only, runs in the parallel batch).
- `engine/sync/sync.cjs` `run({check, force, target})` takes options; the
  dashboard and parity UI no longer depend on `process.argv`.
- The Node harvester also reads the cross-client `storage/corrections.jsonl`
  the correction-tracker hook writes.
- Lint feedback: after a successful `write_file` / `edit_file` / `apply_patch`
  of a `.py` file, `ruff check` output is appended as an advisory `[lint]` note.
- The agent system prompt now appends the workspace's own `AGENTS.md` /
  `CLAUDE.md` / `GEMINI.md` / `CONVENTIONS.md` (and `.agnostic/state.md`),
  clipped to ~6 KB.
- TUI: `@file` / `#symbol` Tab completion (prefix before substring, cycles on
  repeated Tab), ↑/↓ prompt history shared with the legacy CLI's history file,
  `/model` with no argument prints the preset table with live availability and
  supports `/model <n>`, `/help` is rendered from one command table shared by
  both UIs (a test keeps it in sync with `docs/slash-commands.md`).
- CI: `windows-latest` leg (Python 3.12) so the junction / CRLF / `.exe` paths
  are exercised.
- Tests: import smoke test over every `agent` submodule (14 modules were never
  imported by any test), end-to-end `/undo` test, distill legacy-record test,
  merge preamble / nested-bullet test, first-run backup test, traits-drift
  test, cancel / lint / line-ending / regex-grep / streaming / scheduler tests;
  the preset test is parametrized over all presets with the client stubbed.
  138 → 245 pytest, 23 → 28 engine tests, 11 → 13 sync regressions.
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
  instead of refusing to start when the port is taken, and reports the port it
  actually bound when started twice.
- **Compact prompt mode (the default) now carries your rules.** It used to
  replace the compiled `global-rules.md` with a hardcoded five-line prompt; it
  now clips the real rules to ~4 KB. A missing compiled prompt is reported
  (`npm run sync`) instead of silently falling back to a stub.
- **Line endings are preserved.** `write_file` / `edit_file` / `apply_patch`
  and `/undo` restores wrote with platform newlines, so on Windows one edit
  rewrote an LF file as CRLF; edits that target `\n` still match CRLF files.
- Read-only tool output is truncated to head/tail beyond 120 lines as the docs
  always claimed (`read_file` with an explicit line range is exempt);
  `grep_search` / `find_files` say when they hit their 40 / 50 result caps.
- `grep_search` does what its description says: regex (case-insensitive), with
  a literal fallback that names the mode it ran in.
- A turn that aborts between an assistant tool call and its result (exception,
  Ctrl+C) no longer bricks the session: trailing tool calls get an `[aborted]`
  result so the next request is well-formed.
- TUI: the banner no longer shows a green check for an offline endpoint; a
  pending y/n approval is visible in the prompt and a non-y/n answer is echoed
  back instead of silently swallowed; background commands (`/test`, `/review`,
  `/swarm`, `/distill`) stream their output live instead of dumping it at the
  end; the reply streams into one growing block instead of relabelled
  fragments; the Tab binding actually fires (Textual's screen binding shadowed
  it).
- Subagent `share` workspace mode handed the worker an empty directory; it is
  removed and `branch` falls back to the real workspace when no worktree can be
  created.
- `candidates.jsonl` and session files are written atomically (tmp +
  `os.replace`).
- `engine/tests/reg-hooks.cjs` crashed the whole suite when port 3000 was taken
  (listen error is an event, not a rejection); it binds an ephemeral port.
- `distill` crashed on legacy candidates without `sightingDays` and on
  corrections without `correction`; records are normalised once at load.
- `merge.cjs` dropped every rule above the first `##` heading and flattened
  nested bullets, then overwrote `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` with
  no backup; preamble and indentation are preserved and targets are backed up.
- First-run setup no longer overwrites its own pristine settings backup on the
  second run.
- `sync --check` and the parity UI report a target stale when only the traits
  file drifted.
- Scheduler task ids no longer collide within the same second; swarm worktree
  paths are unique, git calls time out, synthesis survives a `None` worker;
  the subscription CLI bridge kills a hung child on timeout instead of leaking
  it.
- Web companion shows the actual test / distill output (not just the exit
  code) and disables the button while a run is in flight; every command-center
  routine button shows a pending state and cannot double-fire.

### Removed
- Tools the model could never use successfully: `ask_question` (no input
  channel), `generate_artifact` (a `write_file` with a worse path),
  `manage_subagents` (`kill` was not implemented). Three fewer schemas on every
  request.
- Dead modules: `agent/workflows/planner.py`, `TaskManager` / `BackgroundTask`
  in `diff_viewer.py` (faked a cron schedule), `agent/tools/mcp_client.py`
  (stub), `agent/tools/mcp_discovery.py` (no caller), and the Python
  `agent/governance/harvester.py` — `/harvest` now shells out to the same Node
  harvester `npm run harvest` uses, so there is one harvester and one
  behaviour.
- `requirements.txt` is a one-line `-e .` shim; `pyproject.toml` is the single
  source of dependencies.
- `tools/errorlog` (a two-line alias of the command center; `/api/data` serves
  the same payload), `/grill-me` and `agent/workflows/grill.py`, and every
  `# noqa: vulture` marker in the code (ruff warned on each one). The vulture
  whitelist moved to `.vulture_whitelist.py`, which the pre-commit hook picks
  up; it lists only framework callbacks and cross-UI entry points.

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
