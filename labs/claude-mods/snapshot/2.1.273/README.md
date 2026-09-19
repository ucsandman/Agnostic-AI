# Function Hooks API snapshot — Claude Code 2.1.273 (Windows x64)

Captured 2026-09-16 on Wes's machine. Purpose: a frozen record of the experimental
"function hooks" plugin API so later releases can be diffed against it.

## Exact build

| Item | Value |
|---|---|
| `claude --version` | `2.1.273 (Claude Code)` |
| Binary | `C:\Users\sandm\.local\bin\claude.exe` (231,776,416 bytes, Bun-compiled PE32+, `// @bun @bytecode`) |
| Versions dir | `C:\Users\sandm\.local\share\claude\versions\{2.1.271,2.1.272,2.1.273}` |
| Declarations source | Embedded zstd asset `B:/~BUN/root/claude-code.d.ts-4e461dcc.txt.zst` at binary offset 229326584 (decompressed 369,279 bytes, 9,944 lines). Extracted here as `claude-code.d.ts`. |
| In-binary skill | `plugin-authoring` (SKILL-739cc29d.md.zst, offset 229421074) — extracted as `plugin-authoring-SKILL.md` |
| Generator source path (from minified strings) | `src/plugins/functionHooks/mcp-tool-types/mcp-tool-declarations.ts` |
| Public docs | **None.** `code.claude.com/docs/en/{hooks,plugins,plugins-reference}.md` contain zero mentions of `modules`, `register(on`, `plugin-types`, or "function hook" (checked 2026-09-16). The API is documented only by `/plugin-types` output and the bundled skill. |

## Gate / feature flags

| Flag | Where | Behaviour observed |
|---|---|---|
| `tengu_plugin_hooks_modules` | GrowthBook gate, default `false` | **Already ON for this account** — the probe loaded with no env var (run A). Sources logged: local override / this session's payload / disk cache / default. |
| `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS` | env var | Overrides the gate (`nNe = env ?? gate`). Not needed here. |
| `canLoadUserHooksModules()` | code | `rolloutOn && !_b() && !Br("hooks") && !Im()` — also off when hooks are disabled (`--bare`, `Br("hooks")`) and two other process conditions. |
| `CLAUDE_CODE_HOOKS_SAME_THREAD` | env var | Runs plugin environments on the main thread instead of the hooks worker (`"same-thread"` vs `"worker"` host). Used by `claude plugin test`. |
| `CLAUDE_CODE_PLUGIN_DIR_WATCH` | env var | Folder watch / hot reload of `--plugin-dir` plugins. |
| Managed settings `prependPlugins` / `appendPlugins` | policy settings | Seat managed plugins outermost / after user tier. `sec-default@builtin` seats itself outermost whenever policy settings exist or org is Team/Enterprise. |

## Loading

- Plugin = folder with `.claude-plugin/plugin.json` + `hooks/hooks.json` containing `"modules": ["./index.ts"]` (exactly ONE module per plugin; a second entry is refused; `.tsx` needed for JSX).
- `claude --plugin-dir <folder>` (repeatable) loads for that session only; provenance `<name>@inline`, tier `user`.
- `claude plugin validate <folder> --json` statically scans the module and reports `hooks:` patterns and `calls:` (`$.noun.method`). The scan is strict:
  - `$` may only appear as `$.noun.method(...)` at a call site, or be passed to a **top-level** function declaration / const-bound function.
  - `on` must be `on("<literal event>", ...)`; `next.to` must be `next.to(e, "<literal tier>")`.
  - `$.env.get/set` names must be string literals.
  - The same event registered twice **without a matcher** is refused (`on("turn.complete") is registered twice without a matcher`).
- Runtime architecture: **one hooks worker per process** ("hooks worker spawned (one for every plugin)"); each plugin gets an isolated *environment* (env 1 = `sec-default` native link; env 2+ = user plugins in the worker). No DOM, no Node; only the globals in `claude-code.d.ts` (`URL`, `TextEncoder`, `crypto.subtle`, `performance`, `AbortController`, `structuredClone`...).
- Debug log (`~/.claude/debug/<session>.txt`, `--debug`) prints per-dispatch lines: `hooks module <name> <event> settled in N ms (worker hop, next() included)`, and load lines `hooks module <name> loaded (worker, environment N, tier user); events: ...`.

## Failure semantics observed / declared

| Case | Behaviour |
|---|---|
| Hook throws, no `.catch` | Hook skipped, chain continues beneath; transcript gets one dim line, debug log every occurrence. Trace outcome `skipped` (before next) / `kept` (after next). Verified: `echo CRASH` hook. |
| Hook throws with `.catch` | Handler runs with `next.error = { kind:'throw', message, budget: 1000 }` and `next.called`. Verified: budget was **1000 ms** grace. |
| Hook overruns budget | `kind:'timeout'`; outcome `expired`. Budget value not printed for normal hooks (only the catch grace). |
| Hook returns wrong shape | "a result that does not match its output shape" → treated as failure, skipped. Verified with a registered tool returning `{content:[...]}` — a **registered tool's `result` must be a string, an array (content blocks), or undefined**. |
| Hook mutates pinned field | refused (e.g. `tool`, `tool_use_id`, `agentId`, `origin`, `provider`). |
| Hook calls its own `$` op inside its own frame | `fs.write skipped: re-entry (its own frame is being dispatched; origin probe#0)` — the call still executes at core, but the plugin's own `*` hook is not re-entered. |
| Worker crash | plugin unloaded ("it crashed the hooks worker"); after N unattributed crashes: "function hooks are off for this session". Heartbeat: "no answer to a heartbeat within N ms: the hooks worker is wedged (a hook spinning without yielding)". A hook that "ignored its signal 5 times in a row" is called a runaway. |
| Unawaited rejection | "hooks worker: a promise a plugin did not await rejected" |
| `engine.create` step fails | plugin unloads, `$` rebuilt. |
| `plugin.register` refused by another plugin | never joins; transcript names the refuser. |
| `-p` / headless | `session.start.surface = null`, `isInteractive=false`; `$.ui.log` goes to host as `ui_log`; `$.ui.ask` rejects. |

## Tiers and the built-in `sec-default` plugin (important restriction on this machine)

Chain order: `prepend` → `user` → `append` → `builtin` → `core`. `next.to(e, tier)` skips tiers with less authority.

`C:\Program Files\ClaudeCode\managed-settings.json` exists here (it only sets `statusLine`), so **`sec-default@builtin` is seated outermost**. Its decompiled register body:

```
classic.*, prompt.section, prompt.context, skill.prompt, attribution.text, settings.read  → next.to(e,"append")   // user tier SKIPPED
tool.describe, command.describe, agent.offer, agent.spawn → user tier sees it only if the provider tier is user/builtin/core
tool.register from user tier → denied when policy sets allowedMcpServers
tool.list → managed tools restored after user hooks
```

Consequences verified: a user plugin hooking `classic.*` **received zero events** in three runs (bench, probe2). `prompt.section`, `prompt.context`, `skill.prompt`, `attribution.text` hooks in the user tier are likewise dead on any machine with managed settings. Removing that managed file (or listing `prependPlugins` without sec-default) would restore them; not done in this sprint (production config untouched).

## Representative raw payloads

See `payloads/*.jsonl` (each line: `{t, event, origin, ms, e, r, trace}` as captured by `lab/probe*`):

- `probe-star-headless.jsonl` — every event of a `-p` run (`engine.create`, 303× `command.describe`, 17× `agent.offer`, 13× `tool.describe`, `session.start`, `prompt.submit`, `turn.start`, `turn.step` w/ usage, `turn.complete`, plus the plugin's own op events `tool.list`, `session.cwd/model/usage`).
- `probe2-interception.jsonl` — `tool.call` with `next.trace`, deny, input rewrite, result replacement, delay, caught throw, registered-tool serve, `$.model.classify`, `tool.check` verdicts.
- `probe3-subagent-permission.jsonl` — `agent.spawn` (model forced), subagent `turn.step`/`tool.call`/`turn.complete` carrying `agentId`, `tool.check` `ask → allow` override, `prompt.submit` hidden context, `$.settings.read({source:'policy'})`, `$.session.usage()` with rate limits and cost.
- `bench.jsonl` — timings.
- `debug-log-probe3-run.txt` — one full engine debug log.

## Benchmark (see MOD_CAPABILITY_MAP.md §Benchmark for the table)
