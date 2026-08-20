# Slash-command reference

Commands typed at the `agnostic` prompt. Anything that does not start with `/`
is sent to the model. `@path` and `#symbol` can be used anywhere in a prompt;
`@image:path` attaches an image's metadata.

"UI" says where the command is handled: **TUI** is `agnostic` (Textual),
**legacy** is `agnostic-legacy` (prompt_toolkit). Most work in both.

## Keys (TUI)

| Key | What it does |
|---|---|
| `Esc` | Cancel the running turn: it stops after the current step, and a running `run_command` child is killed. While a turn runs the status bar names the key itself — `∴ Percolating… 47s · esc to cancel` — ticking once a second so you can see the turn is alive. Set `AGNOSTIC_SPINNER_VERBS` (comma separated) to pick your own verbs. |
| `Esc` `Esc` | Rewind. While idle with an empty input box, pressing Esc twice within 800ms opens a two-step picker: which turn to go back to, then what to restore — the **files** (every write made since that turn is reverted), the **conversation** (the history as it was when that turn started), or **both**. Every turn is checkpointed automatically, so nothing has to be set up first; the last 20 turns are offered, newest first. Esc inside the picker steps back, and cancels on the first step. |
| `Ctrl+C` | Cancel the running turn; press again within 1.5s to force-exit. Idle: press twice to quit. |
| `Ctrl+L` | Clear the output log — press twice. |
| `Shift+Tab` | Cycle the trust tier: `strict` → `trust-reads` → `trust-tests` → `trust-all` → back to `strict`. The status bar shows the tier the guard is actually enforcing (`🛡 trust-tests`), re-read from it on every repaint, and turns red on `trust-all`. Same setting as `/trust`. |
| `Ctrl+O` | Print the last tool's output in full. Tool cards are folded on a line boundary and say how much they hid (`⚙️ run_command · 3.4s · +812 lines hidden — ctrl+o`), so nothing is truncated without a way back; the last 10 outputs are kept. |
| `Tab` | Complete a partially typed slash command, or an `@file` / `#symbol` token against the workspace index (press again to cycle candidates). |
| `↑` / `↓` | Walk the prompt history. |
| `!command` | Run a shell command locally without spending a turn — `!git status`, `!ls tests`. It goes through the same `run_command` tool the model uses, so the same guard rules and hard-stop confirm apply, and its output is streamed into the log but never added to the conversation (zero context, zero LLM calls). A bare `!` is sent to the model as ordinary text. |

## Model and session

| Command | UI | What it does |
|---|---|---|
| `/model [preset] [model] [effort]` | both | Pick a preset: subscription bridges (`agy`, `claude`, `codex` CLIs, no API key), hosted APIs (Gemini, Claude, GPT, DeepSeek; key from env), or a local / custom OpenAI-compatible endpoint. With no args both shells open an arrow-key picker (↑/↓, Space/Enter to select, Esc back): preset, then — for a subscription — the concrete model the CLI should run (e.g. Claude Code Monthly Subscription → `claude-fable-5`), then effort `low` / `medium` / `high` when the model honours it. Text form: `/model <key or number> [model] [effort]`, e.g. `/model 2 claude-fable-5 high`. |
| `/doctor` | both | Probe the configured endpoint: model id, context length, latency. |
| `/compact [undo]` | both | Condense older turns into a summary that keeps touched files, test results and symbols, and print what the summary kept. `/compact undo` restores the pre-compaction messages (manual compactions only). Also happens automatically near the context limit — the status bar's `CTX` gauge warns once before that. |
| `/session save\|load\|list <name>` | both | Snapshot / restore the conversation and whiteboard. In the TUI, a bare `/session` opens an arrow-key resume picker of this workspace's saved sessions (newest first, ↑/↓, Space/Enter to load, Esc to cancel) and loads the one you choose; `/session list` still prints the flat, greppable list. |
| `/state` | both | Show the persistent whiteboard (`.agnostic/state.md`): objectives, milestones, notes. |
| `/theme [name]` | both | Terminal colour theme. The legacy CLI opens a picker when no name is given; the TUI lists the available names instead. |
| `/clear` | both | Clear the screen / output log, keep memory. |
| `/help` | both | Command list. |
| `/exit` | both | Quit. |
| `/multiline` | legacy | Enter a paste mode for long logs and specs; submit with `Ctrl+Z` + `Enter`. The TUI uses a single-line input, so there the command prints a note pointing at `agnostic-legacy`. |

## Safety and governance

| Command | UI | What it does |
|---|---|---|
| `/trust reads\|tests\|all` | both | Set the trust tier. Only `all` lets hard-stop commands run without a human; secret paths are always blocked. See [configuration](configuration.md#trust-tiers). |
| `/untrust` | both | Back to `strict`. |
| `/audit`, `/retro` | both | Write a Markdown report of the session: tool calls, hard stops, files changed. |
| `/undo` | both | Revert the last file write / edit (or delete a newly created file). |
| `/checkpoint save\|restore\|list [name]` | both | Named snapshots of several files; restore atomically. The TUI also writes one automatically at the start of every turn (`turn-1`, `turn-2`, …) — that is what `Esc` `Esc` rewinds to, and `/checkpoint list` shows them alongside your own. |

## Doing the work

| Command | UI | What it does |
|---|---|---|
| `/plan <task>` | both | Ask the model for a step-by-step plan before touching code. |
| `/schedule "every 30s run /test"` | both | Start a background routine: `every <N>s\|m\|h <command or prompt>`. `/schedule list` shows the running routines (id, interval, prompt); `/schedule stop <id>` or `/schedule stop all` cancels them. |
| `/loop <N> "prompt"` | both | Run a prompt N times in the background. |
| `/fix [cmd]` | both | Run the test command (or read the last stack trace), diagnose, apply a fix in one turn. |
| `/test [cmd]` | both | Detect the test runner (`npm test`, `pytest`, `cargo test`, ...) or use `cmd`; loop fix-and-rerun until green or the retry cap. |
| `/research <topic>` | both | Spawn a researcher subagent over the codebase and return its notes. |
| `/review` | both | Spawn a reviewer subagent over `git status` / recent diffs for bugs, missing tests, security issues. |
| `/swarm <task>` | both | Three subagents in parallel (researcher, tester, reviewer), then a combined summary from the model. Worktree isolation is available in the API but off by default. |
| `/diagram`, `/map` | both | Scan imports and print a Mermaid dependency diagram. |
| `/commit` | both | Read `git status` + `git diff`, propose a conventional commit, run it on confirmation. |
| `/pr` | both | Draft a pull-request title and body from the branch diff. |

## Harness loop

| Command | UI | What it does |
|---|---|---|
| `/learn <lesson>` | both | Append a candidate rule to `storage/candidates.jsonl` (tier 0) for the distiller. |
| `/harvest` | both | Run `engine/harvest/harvest.cjs`: scan local agent error logs, corrections and meditation candidates into `storage/candidates.jsonl`. |
| `/distill` | both | Run the promotion ladder and pruner; write the digest and proposal. |
| `/web` | both | Start the web companion on `http://127.0.0.1:7843` (next free port if taken): telemetry, diffs, context meter, run tests / distill from the browser. |
