# Porting a harness between clients

What "the same harness everywhere" means in practice: what each piece of a
harness is, how it is carried from the client you use to every other client,
and what cannot be carried and why. The live, per-machine version of this table
is `npm run status` (or the page at `npm run parity`).

## The seven components

| Component | Source of truth (Claude Code example) | What the port writes elsewhere |
|---|---|---|
| Rules | `~/.claude/CLAUDE.md` with its `@imports` inlined | the client's global instructions file (`AGENTS.md`, `GEMINI.md`, `.mdc`, `.goosehints`, ...) with a client-specific preamble and a tool-name mapping table |
| Identity | `~/.claude/SOUL.md` | appended to the rules file, or the client's own traits file when it has one |
| Hooks | `~/.claude/settings.json` `hooks` | the client's hook config in its dialect (Codex `config.toml` with trust hashes; Gemini `settings.json`; Cursor `hooks.json`), pointing at the **same** scripts |
| Skills | `~/.claude/skills/<name>/SKILL.md` | a directory link per skill into the client's skills dir; never a copy |
| Agents | `~/.claude/agents/<name>.md` | Codex `agents/<name>.toml` with the model ladder mapped; Cursor `agents/<name>.md` |
| Commands | `~/.claude/commands/<name>.md` | Codex `prompts/<name>.md` (`/prompts:<name>`), Gemini `commands/<name>.toml`, Cursor and OpenCode `commands/<name>.md` |
| MCP servers | `~/.claude.json` `mcpServers` | Codex `[mcp_servers.*]`, Gemini / Cursor / Windsurf / Cline `mcpServers`, OpenCode `mcp` |
| Permissions | `~/.claude/settings.json` `permissions` | Codex `rules/agnostic.rules` prefix rules for `Bash(...)` patterns |

Codex CLI can also be the source: the same components are read back from
`AGENTS.md`, `config.toml`, `agents/*.toml`, `prompts/*.md`, `skills/`,
`rules/*.rules`, and written into Claude Code (`agnostic-rules.md` plus an
`@import` line in `CLAUDE.md`, `settings.json` hooks, `.claude.json` servers,
agents and commands as markdown).

## Hooks: one dialect, one shim

Hooks are written once, in the Claude Code dialect: JSON on stdin, a decision
on stdout (`hookSpecificOutput.permissionDecision`) or exit code 2 with the
reason on stderr. The port never copies a hook script. It registers the same
script path in each client, and where the client speaks another dialect it
wraps the call in `engine/hooks/shim.cjs`, which translates the payload in and
the decision out.

| | Claude Code | Codex CLI | Gemini CLI | Cursor | Antigravity |
|---|---|---|---|---|---|
| config | `settings.json` | `config.toml` `[[hooks.<Event>]]` | `settings.json` `hooks` | `hooks.json` | `config/hooks.json` |
| payload | `tool_name`, `tool_input` | same | same keys, Gemini tool names | `tool_name`, `tool_input` or `command` | camelCase `toolCall.{name,args}` |
| deny | `permissionDecision: deny` or exit 2 | same | `decision: deny` or exit 2 | `permission: deny` | `decision: deny` |
| shim needed | no | no | yes | yes | yes |
| trust | none | `[hooks.state]` hash per hook, written by the port | none | none | none |

Event mapping (Claude name first): `PreToolUse` -> Codex `PreToolUse`, Gemini
`BeforeTool`, Cursor `preToolUse`; `PostToolUse` -> `AfterTool` / `postToolUse`;
`UserPromptSubmit` -> Gemini `BeforeAgent`, Cursor `beforeSubmitPrompt`;
`Stop` -> Gemini `AfterAgent`, Cursor `stop`; `SessionStart` maps by name;
`MessageDisplay` exists only in Claude Code and is dropped with that reason.

Matcher tokens are translated per client (`Bash|PowerShell` -> Codex `Bash`,
Gemini `run_shell_command`, Cursor `Shell`; `Edit|Write|MultiEdit` -> Codex
`Edit`/`Write`, Gemini `replace`/`write_file`; `Read|Glob|Grep` has no Codex
hook surface and is dropped). Where a client merges the results of several
hooks on one event and keeps only the last reason (Gemini, Antigravity), the
port chains every guard for that event into one shim call (`cmd1 ++ cmd2`) so
the first deny wins and its reason survives.

Codex records a trust hash per hook and asks for a review in `/hooks` until it
matches. The port computes the same hash (sha256 over the normalised hook
identity, reproduced from Codex's own `discovery.rs`) and writes the
`[hooks.state]` entries, so a ported hook runs on the next session without a
prompt. A self-test against a hash Codex itself wrote runs on every port; if
Codex ever changes the scheme the port says so instead of writing hashes that
silently never match.

## What is deliberately not ported

`core/port.json` is the authoritative list and every run prints each drop
with its reason (`npm run explain`). The shipped defaults exclude hooks that
police one client's own state: Claude Code's model-ladder guards
(`capability-graph-guard`, `agent-model-guard`, `fable-delegate-guard`), its
statusline and transcript readers, and DashClaw's per-client handlers (DashClaw
installs those itself with `dashclaw install <client>`).

Skills and MCP servers are excluded by name in the same file. Two reasons show
up often enough to name here: a skill that runs a tool only one client has (a
Claude Code `Workflow` or `Artifact` skill is invisible elsewhere), and an MCP
server whose credential is bound to one client (X keeps one OAuth grant per
app, so a second client needs its own app, not a copied config).

A skill that already lives in a directory the client reads natively
(`~/.agents/skills` for Codex, OpenHands and OpenCode) is not linked again; it
would be listed twice.

## Model ladder

Agent files name a tier, not a vendor model: `fable`, `opus`, `sonnet`,
`haiku`, or `inherit`. `core/port.json` maps each tier to a model and effort
per target (`agents.modelLadder.codex`). The port checks each slug against the
client's own model cache when one exists and names any it cannot find. A raw
model id in the source passes through unchanged.

## Secrets

The port never moves a credential. At capture, an MCP env or header value that
matches the secret patterns in `core/safety/guards.json`, or that sits under a
key named like a credential and looks like a token, is replaced with
`${NAME}`. Codex gets `env_vars = ["NAME"]` (read from the environment at
launch); JSON clients get the literal `${NAME}` (Claude Code and Cursor expand
it). The capture warning names every variable you need to export.

## Ownership and safety of the write

- A generated file carries `GENERATED by agnostic-ai` on its first line. That
  header is the ownership claim: the port overwrites such a file whatever
  touched it in between, and refuses (backs up, reports) a file that lost it,
  unless `--force`.
- A file the user also edits (`config.toml`, `settings.json`, `.claude.json`,
  `hooks.json`, `mcp.json`) gets a marked region or per-key ownership recorded
  in `storage/harness-state.json`. Everything else in the file is preserved
  byte for byte, and a rerun only ever removes what the port itself added.
- Links never replace a real directory. Pruning only touches links and files
  the state file says the port created.
- Every overwrite is preceded by a timestamped backup in `storage/backups/`.
- `--check` writes nothing and exits 1 on any drift; `--dry-run` prints what
  would change.

## Verifying a port

```sh
npm run port -- --check      # every generated file matches the bundle?
npm run explain              # what was dropped, and why
npm run status:open          # the rendered matrix
npm test                     # fixture homes: capture, apply twice, drift, prune, shim wire tests
```

The end-to-end proof is the target client itself: start a session and trigger
a guard on purpose (`cat .env`). A guard never seen denying is wired, not
verified.
