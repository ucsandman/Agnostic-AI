# Shared brief for the three Phase-17 prototype builders

You are building ONE prototype plugin for Claude Code's early-access **function hooks** API, in an isolated
directory under `C:\Projects\claude-mods-rnd\prototypes\<name>\`. Read this whole file, then
`C:\Projects\claude-mods-rnd\MOD_CAPABILITY_MAP.md` §0–§9, §20, and `C:\Projects\claude-mods-rnd\lab\README.md`.
Working examples that validate and run: `C:\Projects\claude-mods-rnd\lab\xray\hooks\index.tsx`,
`C:\Projects\claude-mods-rnd\lab\demos\*\hooks\index.ts`, `C:\Projects\claude-mods-rnd\adapter\claude-runtime\hooks\index.ts`.
The exact API types: `C:\Projects\claude-mods-rnd\snapshot\2.1.273\claude-code.d.ts` (grep it; do not read all 9,944 lines).

## VERIFIED GROUND TRUTH (measured 2026-09-16 on this machine; do NOT re-verify, do NOT contradict)
- Function hooks are ON. A plugin = folder with `.claude-plugin/plugin.json` (`name`, `version`, `description`, `author`) and
  `hooks/hooks.json` = `{ "modules": ["./index.ts"] }` (ONE module; use `./index.tsx` if the file has JSX).
- Module exports `register(on, options)`; hooks are `($, e, next)`; `next(e)` runs the rest of the chain; return without `next` to answer yourself; `{deny: "..."}` refuses a `tool.call`; `await next(e)` then `return {result: ...}` replaces what the model receives.
- The loader STATICALLY SCANS the module. Rules that break the load if violated: `$` may appear only as `$.noun.method(...)` at a call site, or be passed as an argument to a **top-level** `function` declaration (whose parameter may be named `$` and used the same way); `on("<string literal>", ...)` only; `next.to(e, "<literal tier>")` only; `$.env.get/set` need literal names; the same event registered twice without a matcher is refused; no `require`, no `fetch`, no Node globals (only `$`, `URL`, `TextEncoder`, `crypto.subtle`, `performance`, `AbortController`, `structuredClone`, `atob/btoa`).
- `ui.render` for `Pane`/`AbovePrompt`: `const { Box, Text, Button } = $.ui.resolve(e)` then JSX. Allowed Box props: flexDirection, gap, padding*, margin*, borderStyle, borderColor, width, height, key, hover; Text props: color, dimColor, bold, italic, underline, inverse, wrap. `Button` needs `key`, `label`, `onPress`. A pane opened by a plugin on its own (`$.ui.open({id,title,rows})`) only draws at ≥144 terminal columns; opened from a registered `/command` (`command.run` hook) it draws at ≥110. The `AbovePrompt` band always draws. `$.ui.toast/status/log` always work. The permission dialog itself cannot be drawn by plugins.
- `$.tool.register({name, description, inputSchema})` inside `session.start` + `on("tool.call", {tool: "mcp__<plugin>__<name>"}, ...)` serves a tool; its `result` MUST be a string, an array of content blocks, or undefined.
- `$.command.register({name, description, immediate: true})` + `on("command.run", {command: "<name>"}, ...)` returning `{text}`.
- `agent.spawn`: `next({...e, model: "haiku"})` rewrites the subagent model; `{deny}` refuses; result `{model, agentId}`. Every subagent `turn.step`/`tool.call`/`turn.complete` carries `agentId`; `turn.complete.usage = {input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens, model}`.
- `turn.step` is an async generator hook: `for await (const c of stream) yield c; const r = await stream.result;` — `r.usage` per request, `e.messageCount`, `e.model`.
- `$.session.usage()` → `{context:{tokens,window,percent}, rateLimits:[{kind:'five_hour'|'seven_day',percentUsed,resetsAt}], cost:{usd}}`. `$.session.messages()`, `$.session.repo()`, `$.session.id()`, `$.session.model()`.
- `$.model.complete({model:"haiku", prompt, system, maxTokens})` → text, in-process, ~1 s (measured). `$.model.classify(text, labels)`.
- `$.store.get/set` (JSON, survives sessions). `$.clock.every(ms, fn)` timers. `$.fs.read/write/exists`. `$.process.run(argv)`.
- `tool.check` hook: `const v = await next(e); return {decision: "deny"|"allow"|"ask", reason}` — last word wins.
- NOT available to user plugins on this machine: `classic.*` events (PreToolUse etc.), `prompt.section`, `prompt.context`, `skill.prompt`. Do not use them.
- A hook that throws is skipped and the chain continues (logged in `~/.claude/debug/<session>.txt` under `--debug`); a wrong return shape is the same. Read the debug log when something "does nothing".
- Optional: the shared adapter `C:\Projects\claude-mods-rnd\adapter\claude-runtime` publishes normalised events; if you load it alongside your plugin (`--plugin-dir` for both, adapter FIRST) you can hook `on("runtime.emit", ...)` and call `$.runtime.supports()/judge()/snapshot()`. Using it is encouraged where it simplifies; hooking engine events directly is fine too.

## How to validate and run (mandatory before you report)
1. `claude plugin validate C:\Projects\claude-mods-rnd\prototypes\<name> --json` → must print `"success": true`; fix every error.
2. Headless dogfood: `claude --plugin-dir C:/Projects/claude-mods-rnd/prototypes/<name> -p "<prompt>" --model haiku --allowedTools "Bash,Read,Write,Edit" --debug`. Put `# SEQ: probe` at the end of every Bash command you ask for (the production harness's batch-guard otherwise denies single commands); put `# EST: 1 calls, 0 files # SPAWN_OK: prototype dogfood` inside any Agent prompt you ask the model to spawn (the harness's spawn guards otherwise deny it); spawn only `haiku-scout` / `sonnet-implementer` with `model haiku` unless the prototype is about routing. Run the model as `--model sonnet` only when you need it to spawn subagents (haiku cannot spawn).
3. Interactive dogfood (for panes/HUD): `python C:\Projects\claude-mods-rnd\tools\pty_drive.py <out.txt> 25 "C:/Projects/claude-mods-rnd/prototypes/<name>" "<prompt 1>|||<prompt 2>|||KEYS:/yourcommand\r|||WAIT:6" 35 "" --debug` — it prints the final screen; read `<out.txt>` for all snapshots. NEVER run `taskkill /IM claude.exe` or kill claude by name (it kills the session that dispatched you).
4. Read `~/.claude/debug/<newest>.txt` for lines mentioning your plugin name; a hook that failed is named there.
5. Save evidence (screen snapshots, headless outputs, JSONL) under `prototypes/<name>/evidence/`.

## Deliverables (all inside your directory)
- The plugin (validates, runs).
- `README.md` with sections: What it is · Architecture diagram (ASCII, showing which events it hooks and the middleware order) · Run instructions (copy-paste) · What it proves · What it does NOT prove · API assumptions (list every event and `$` method used, with its status from the capability map) · Failure behaviour (what happens when a hook throws, when the API is missing, when panes cannot draw) · Migration path if the API changes (which functions are the adapter boundary) · Evidence (paths + the key numbers/lines observed).
- Do not modify anything outside your directory. Do not touch `~/.claude`, `C:\Projects\<other repos>`, or production settings. Do not commit.

Model calls in anything you build run through `$.model.complete` / `$.model.classify` (session credentials, in-process) or the Claude Code CLI; NEVER the Anthropic API, never `@anthropic-ai/sdk`, never an `ANTHROPIC_API_KEY`.

At least one verification step MUST execute the real `claude` binary end to end and assert on its actual output. Mocked runs do not count. If the real binary cannot run, report BLOCKED.

Do NOT trust compressed or piped summaries; read the real exit code and quote failing lines.

Reply with ≤250 words: what works (with the observed evidence), what does not, and the three things you learned about the API that were not in the brief.
