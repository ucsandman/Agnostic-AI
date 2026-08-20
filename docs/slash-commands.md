# Slash-command reference

Commands typed at the `agnostic` prompt. Anything that does not start with `/`
is sent to the model. `@path` and `#symbol` can be used anywhere in a prompt;
`@image:path` attaches an image's metadata.

"UI" says where the command is handled: **TUI** is `agnostic` (Textual),
**legacy** is `agnostic-legacy` (prompt_toolkit). Most work in both.

## Model and session

| Command | UI | What it does |
|---|---|---|
| `/model [preset] [effort]` | both | Pick a preset: subscription bridges (`agy`, `claude`, `codex` CLIs, no API key), hosted APIs (Gemini, Claude, GPT, DeepSeek; key from env), or a local / custom OpenAI-compatible endpoint. Optional effort `low` / `medium` / `high`. With no args the legacy shell opens an arrow-key picker; the TUI prints the preset list and takes the argument form. |
| `/doctor` | both | Probe the configured endpoint: model id, context length, latency. |
| `/compact` | both | Condense older turns into a summary that keeps touched files, test results and symbols. Also happens automatically near the context limit. |
| `/session save\|load\|list <name>` | both | Snapshot / restore the conversation and whiteboard. |
| `/state` | both | Show the persistent whiteboard (`.agnostic/state.md`): objectives, milestones, notes. |
| `/theme [name]` | both | Terminal colour theme; picker when no name is given. |
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
| `/checkpoint save\|restore\|list [name]` | both | Named snapshots of several files; restore atomically. |

## Doing the work

| Command | UI | What it does |
|---|---|---|
| `/plan <task>` | both | Ask the model for a step-by-step plan before touching code. |
| `/grill-me <task>` | legacy | The model asks you three architect-style trade-off questions before starting. In the TUI the command prints a pointer to `agnostic --legacy`. |
| `/schedule "every 30s run /test"` | both | Start a background routine: `every <N>s|m|h <command or prompt>`. |
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
| `/harvest` | both | Run the cross-agent harvester over local transcripts and error logs. |
| `/distill` | both | Run the promotion ladder and pruner; write the digest and proposal. |
| `/web` | both | Start the web companion on `http://127.0.0.1:7843`: telemetry, diffs, context meter, run tests / distill from the browser. |
