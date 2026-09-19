# MOD_CAPABILITY_MAP — Claude Code Function Hooks ("Mods"), build 2.1.273

Authority for everything below: the declaration file the running binary embeds
(`snapshot/2.1.273/claude-code.d.ts`, 9,944 lines, extracted from the zstd asset inside
`claude.exe`), the bundled `plugin-authoring` skill, the decompiled loader strings, and
**live runs** of five probe plugins (`lab/probe*`, `lab/bench`) whose raw payloads sit in
`snapshot/2.1.273/payloads/`. Nothing here comes from training memory. Where a claim is
declared in the types but not exercised, it says so.

Vocabulary: Anthropic's name for this is a **hooks module** ("function hooks"); the plugin
that carries one is an ordinary plugin. "Mod" below = a hooks module.

Evidence tags: **[RUN]** observed in a live session this sprint · **[DECL]** declared in
`claude-code.d.ts` / loader strings, not exercised · **[DBG]** seen in the engine debug log.

---

## 0. One-paragraph model of the system

A hooks module is one TS/JS file exporting `register(on, options)`. It runs in its own
sandboxed environment inside a **hooks worker** (one worker per process, one environment per
plugin) with no Node and no DOM; everything it can do is a method on `$`. Every method on `$`
is itself an event (`fs.write`, `model.complete`, `ui.toast`...) that other plugins' hooks
see, so the whole engine is one **middleware chain per event**: `prepend` (managed) →
`user` → `append` (managed) → `builtin` → `core`. A hook is `($, e, next)`: it can observe,
rewrite a copy (`next({...e, x})`), answer for itself (return without `next`), refuse
(`{deny}` / `{drop}` / `{refuse}` / `{skip}`), delay, or read the settled chain beneath it
(`next.trace`). `turn.step` is the one streaming event (async generator over the model's
response chunks). Failures never block the engine: a failing hook is skipped and the chain
runs beneath it. **[RUN]** for all of the above.

---

## 1. Function Hook types and Mod types

| Thing | What it is | Status |
|---|---|---|
| Hooks module | `hooks/hooks.json` → `{"modules": ["./index.ts"]}` (exactly one per plugin) | CONFIRMED WORKING [RUN] |
| Classic hooks | `hooks/hooks.json` → `{"hooks": {...}}` command/http/mcp_tool/prompt/agent hooks (the documented system) — may coexist with `modules` | CONFIRMED WORKING (production harness uses 49 of them) |
| Hook shapes | `($, e, next) => result`; streaming: `async function* ($, e, next)`; `on(pattern, hook)` / `on(pattern, matcher, hook)`; `.catch(handler)` | CONFIRMED WORKING [RUN] |
| Patterns | event name, `*`, `namespace.*` (`tool.*`, `classic.*`), negation `!tool.describe` | `*`, `tool.*`, `classic.*` [RUN]; negation [DECL] |
| Matchers | partial object of `e`, leaf `===` / RegExp / one-of array, depth ≤ 8 | RegExp on `command`, literal on `tool` [RUN] |
| Plugin nouns | a plugin adds `$.myNoun` via `engine.create` and ships `types/index.d.ts` as its contract; other plugins hook `myNoun.method` as events | PRESENT BUT EXPERIMENTAL [DECL] (`engine.create` fold observed [RUN], no custom noun built yet) |
| Tiers | `prepend`, `user`, `append`, `builtin`, `core`; `next.to(e, tier)` skips downward | CONFIRMED [RUN] (sec-default uses `next.to(e,"append")`) |
| Options | `plugin.json` `userConfig` → `register(on, options)`; rows in `/config`; change reloads module | [DECL] (+ WARN when options requested without userConfig [DBG]) |
| Tests | `claude plugin test <dir>` runs `*.test.ts(x)` with `claude-code/testing` kit (`test($, on)`, `mock.clock/store/env`, `$.ui.press`) | PRESENT BUT EXPERIMENTAL [DECL]; hidden from `claude plugin --help`, `--help` of subcommand works |
| Types | `/plugin-types [dir]` (session command) writes `claude-code.d.ts`, `claude-code-plugins.d.ts`, `claude-code-mcp.d.ts` | CONFIRMED present (source extracted from binary; not runnable from `-p`) |

## 2. Event catalogue (every event the engine defines)

### 2a. Engine events (`EngineEventOf`) — 34

| Event | Fires when | Can a hook… | Status |
|---|---|---|---|
| `tool.call` | engine about to run any tool (model's or a plugin's `$.tool.call`) | observe, rewrite args, `{deny}`, answer own `{result}`, replace result after `next`, delay, attach hidden `context[]` | **CONFIRMED** all six [RUN] |
| `tool.check` | permission decision after tool.call/PreToolUse, before mode settles an ask | return any `{decision: allow/ask/deny, reason}` — **last word up the chain wins** | **CONFIRMED** `ask → allow` by a user plugin, headless [RUN][DBG] |
| `tool.describe` | first render of a tool's schema per session | rewrite `description` (cached; `$.ui.invalidate`) | CONFIRMED fires [RUN]; rewrite [DECL] |
| `tool.register` (op) | `$.tool.register` | deny / observe | CONFIRMED [RUN] |
| `agent.offer` | agent type listed / dispatched | `{isOffered:false}` hides & refuses | fires [RUN]; hide registered [RUN] not exercised by model |
| `agent.spawn` | Agent tool about to start subagent | rewrite prompt/description/subagentType/model/background/cwd; `{deny}` | **CONFIRMED** model forced to haiku, `agentId` returned [RUN] |
| `prompt.submit` | prompt submitted (user, sdk, plugin, peer, scheduled…) | rewrite `text`, attach hidden `context[]`, `{drop}` | **CONFIRMED** hidden context (model saw it, Sonnet flagged it as injected) [RUN] |
| `prompt.fill` / `prompt.suggest` | plugin writes draft / proposes dim suggestion | rewrite / refuse | [DECL] |
| `prompt.section` | each named system-prompt section assembled | rewrite/omit text (cached) | **WITHHELD from user tier on this machine** (sec-default) — see §11 |
| `prompt.context` | first user message's context blocks | append/drop/reorder blocks | WITHHELD from user tier here (sec-default) |
| `skill.prompt` | skill expanded | replace text | WITHHELD here |
| `attribution.text` | commit/PR/exemption text composed | replace | WITHHELD here |
| `command.run` / `command.describe` | slash command runs / listed | answer `{text}`, rewrite args / relabel, hide | `command.describe` 303× [RUN]; `command.run` on registered `/probeui` [RUN, registered] |
| `config.set` / `config.describe` | `/config` row changes / listed | clamp, deny / relabel, hide | [DECL] |
| `session.start` | once per process per plugin, awaited before first prompt | observe; register tools/commands; start timers | CONFIRMED [RUN] |
| `session.receive` | inbound delivery (peer, relay, Remote Control) | rewrite / `{consumed}` | [DECL] |
| `session.compact` | `/compact`, auto, plugin, precompute | rewrite `instructions`/`messages`, own `{messages}`, `{skip}` | [DECL] (needs long session) |
| `session.attach` / `detach` | remote surface joins/leaves | observe | [DECL] |
| `plugin.register` | a hooks module about to join | `{refuse}` (judges = plugins admitted before it) | fires [DBG] "judged by core alone: admitted" |
| `turn.start` | model turn begins | observe (`turnId`) | CONFIRMED [RUN] |
| `turn.step` (streaming) | every model request of a turn, main and subagent | rewrite `model` / `effort` going down; read/rewrite/drop text, thinking, tool, input chunks; own response without `next` | **CONFIRMED** stream read, chunk counts, usage per step, `agentId` on subagent steps; `effort` rewrite accepted (effect unverified) [RUN] |
| `turn.complete` | turn ended (`answer/aborted/refusal/error`) | show alternate `{text}` beneath answer; read `usage`, `agentId` | CONFIRMED incl. subagent turns [RUN] |
| `ui.render` | component about to draw (14 components) | return tree / wrap `next(e)` / rewrite props | **CONFIRMED** 10 components observed, AbovePrompt tree drawn [RUN] |
| `ui.resolve` | plugins load, per surface×component | restyle/remove elements for every other plugin | [DECL] |
| `ui.press` / `ui.input` / `ui.select` / `ui.message` / `ui.scroll` / `ui.focus` | interaction with elements a hook drew | intercept, rewrite value, take | registered [RUN]; not pressed (pane unplaced at 140 cols) |
| `engine.create` | `$` built, once per load | add/withhold nouns | CONFIRMED fires; `$` table observed [RUN] |

### 2b. Classic events as function events (`classic.<Name>`) — 33
`PreToolUse` (e = tool envelope; result allow/ask/deny + updatedInput + additionalContext), `PostToolUse` (updatedToolOutput), `PostToolUseFailure`, `PostToolBatch`, `PermissionDenied`, `PermissionRequest`, `Notification`, `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `SessionEnd`, `Stop` (with `background_tasks`, `session_crons`), `StopFailure`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch` (with `estimated_cache_write_usd`, `prompt_cache_warm`), `Setup`, `TeammateIdle`, `TaskCreated`, `TaskCompleted`, `Elicitation`, `ElicitationResult`, `ConfigChange`, `InstructionsLoaded`, `WorktreeCreate`, `WorktreeRemove`, `CwdChanged`, `FileChanged`, `DirectoryAdded`, `MessageDisplay`.
Chain: `[managed settings hooks, ...hooks modules, other settings hooks as core]`.
**Status on this machine: NOT VISIBLE to user-tier plugins** (0 events in 3 runs) because `sec-default@builtin` does `next.to(e,"append")` on `classic.*` whenever managed settings exist. [RUN][decompiled]. On a machine without managed settings they should reach user plugins [DECL] — UNKNOWN until tested.

### 2c. Op events — every `$` call is hookable — ~60
`model.complete|classify|fork`, `audio.play|speak`, `mcp.call`, `session.cwd|model|turns|id|messages|repo|surfaces|authorize|usage`, `turn.abort`, `tool.list|register`, `command.list|register`, `config.list`, `agent.list`, `ui.toast|status|log|notice|invalidate|open|close|blit`, `fs.read|write|list|exists|stat|ancestors`, `store.get|set|delete|keys`, `clock.now|sleep|after|every`, `http.fetch`, `process.run`, `settings.read`, `env.get|set`. Result to hooks: `{value}` or `{deny}`. A hook above the caller can deny or rewrite any of them. **[RUN]** for tool.list, session.*, fs.write, clock.sleep, model.classify, tool.register, settings.read, ui.* (all seen as events with `origin: {plugin:'probe', tier:'user'}`).

## 3. Wildcard `on("*")`
CONFIRMED WORKING [RUN]. `e` is `unknown`; `next.event` names the event; `next.is(pattern, e)` narrows. It sees engine events, classic events (when not withheld), the plugin's own op calls (re-entry-guarded: a hook's own frame is skipped for its own `$` calls, [DBG] "fs.write skipped: re-entry"), and other plugins' op calls. At `engine.create` `$` is empty. 306 events captured in a trivial `-p` run.

## 4. `on()` behaviour
Registrations nest in order, first outermost. A repeat of the same event without matcher throws at validate/load ("registered twice without a matcher") [RUN]. `on()` returns a `Registration` with one `.catch`. `register` may return a promise (awaited). Options are frozen per activation; a change reloads the module (timers dropped).

## 5. `$` (engine interface)
Frozen table, built by the `engine.create` fold. Core nouns observed [RUN]: `plugin{name,root}`, `ui{notice,invalidate,blit,resolve,log,ask,toast,status,open,close,scroll,focus}`, `model{complete,fork,classify}`, `audio{play,speak}`, `mcp{call}`, `session{messages,cwd,model,turns,id,repo,surface,surfaces,authorize,usage,compact}`, `prompt{submit,fill,suggest}`, `turn{abort}`, `tool{register,list,call,check}`, `command{list,register,run}`, `config{list,set}`, `agent{spawn,list}`, `fs{read,write,list,exists,stat,ancestors}`, `store{get,set,delete,keys}`, `clock{now,sleep,after,every}`, `http{fetch}`, `process{run}`, `settings{read}`, `env{get,set}`.
Notable: `$.model.complete/classify/fork` use the **session's own credentials** (classify → "greeting" [RUN], default small model); `$.model.fork` shares the main thread's prompt cache; `$.mcp.call` calls connected MCP servers **without a permission prompt**; `$.process.run(argv)` runs host commands (no shell, 30 s default, 10 min max) [RUN]; `$.session.authorize()` gives an opaque credential handle usable only against first-party hosts via `$.http.fetch`.

## 6. `next()`
`next(e)` runs the rest of the chain and resolves the event result; each call re-runs beneath (two calls = two runs; on `turn.step` two model requests). Returning without calling it answers alone; returning `undefined` is a failure. `next.signal` aborts when the dispatch is abandoned. `next.origin` = `{plugin, tier}` of who raised it (engine = `{engine, core}`) [RUN]. `next.trace` = settled links beneath with `outcome` (`returned|passed|skipped|kept|expired|caught|rejected`), `ms`, `received`, `returned` [RUN]. `next.to(e, tier)` skips tiers (managed use). `next.error`/`next.called` exist only in `.catch` [RUN: `{kind:'throw', budget:1000}`].

## 7. Middleware composition and ordering
Order = tier, then registration order within a plugin, then plugin list order within a tier (managed `prependPlugins`/`appendPlugins`; user plugins in load order). A hook that returns while its `next` is pending aborts what runs beneath. Managed-settings hooks run first on `tool.call`; their deny is final. **Cross-plugin ordering test (two user plugins): NOT YET RUN** — UNKNOWN which user plugin is outer (declared: "in list order, first is outermost").

## 8. Tool interception / result interception / mutation
- Input rewrite: `next({...e, command})` → tool ran the rewritten command; model saw `REWRITTEN-BY-HOOK` [RUN].
- Deny: `{deny}` → model receives the text as an error result; engine logs "resolved by a hooks module (deny: …)" [RUN].
- Result replacement: hook awaited `next(e)` then returned its own `{result}` → model saw the replacement (it even replaced an error result) [RUN]. Core validates a hook's `result` against the tool's output schema; the model-facing text is produced by the tool's own mapper. For a **plugin-registered tool** the result must be `string | content-block[] | undefined` (learned from the refusal) [RUN].
- Hidden context on results (`context[]`, capped 32k chars) and on prompts [DECL/RUN].
- Classic `PostToolUse.updatedToolOutput` also exists but is withheld here.
- Reserved/pinned: `tool`, `tool_use_id`, `agentId` — rewrites refused.

## 9. Blocking
`tool.call {deny}` [RUN]; `tool.check {decision:'deny'}` [DECL]; `prompt.submit {drop}` [DECL]; `agent.spawn {deny}` [DECL]; `agent.offer {isOffered:false}` [registered RUN]; `session.receive {consumed}`; `session.compact {skip}`; `config.set {deny}`; `plugin.register {refuse}`; any op event `{deny}`. Also **delay**: `await $.clock.sleep(ms, {signal: next.signal})` before `next` — 2,367 ms measured for a 1,500 ms sleep incl. hops [RUN].

## 10. UI capabilities (terminal)
| Capability | Status |
|---|---|
| `$.ui.log` → dim transcript line, not sent to model | CONFIRMED (visible on screen) [RUN] |
| `$.ui.status` → pinned line under prompt | CONFIRMED (drawn with ⚠ prefix) [RUN] |
| `$.ui.toast` → notification bar | CONFIRMED dispatched [DBG]; visible window missed by snapshot |
| `ui.render` for `AbovePrompt` (own bordered Box) | CONFIRMED drawn [RUN] |
| `ui.render` observed for `InfoNotice, AbovePrompt, SessionMode, PromptHint, UserMessage, Spinner, ToolGroup, AssistantMessage, TurnDuration` (+ `Pane` opened) | CONFIRMED [RUN]; `ToolUse`, `ToolResult`, `AskUserQuestion`, `CommandOutput` not yet seen (tool rows were folded into ToolGroup) |
| `$.ui.open` pane | PRESENT BUT CONSTRAINED: an *unasked* open "waits unplaced" below 144 columns (110 once the person asked, e.g. via a command) [DBG]; opened=true resolved [RUN] |
| Elements | terminal: `Box, Text, Button, Input, Select, Link, Code, Client, Raster`; remote surfaces add `Svg`; `Raster` + `$.ui.blit` = cell-grid animation [DECL] |
| `$.ui.ask` → engine's AskUserQuestion dialog, resolves label | [DECL] (rejects in `-p`) |
| Permission dialog | **NOT renderable by plugins** (engine-only; `$.ui.notice` adds a line under it) [DECL] |
| Hover/scope styles, hotkeys, `action` chords, `autoFocus`, scroll/focus rings | [DECL] |
| Surfaces | `terminal`, `desktop`, `mobile` (no Input/Select yet), `vscode` (no Client) [DECL] |
| `Client` surface module (a `.tsx` running on the drawing thread with local state, pointer, keys, `post()` → `ui.message`) | PRESENT BUT EXPERIMENTAL [DECL] |

## 11. Session capabilities
`$.session.messages()` (last 4096, `{role,text,toolUses[{tool,input,result,text,isError}],toolResults}`), `cwd`, `model`, `turns`, `id`, `repo` (`{root, remote, internal, name}` [RUN]), `surfaces`, `usage` (§13), `compact({instructions})`, `authorize()`. `$.prompt.submit` wakes an idle session with a prompt under the plugin's name; `$.turn.abort({turnId})` cancels the running turn [DECL]. `$.store` = per-plugin JSON store under the config dir, kept across sessions and reloads (≤ 4 MiB) [DECL]. `$.clock.every/after` timers outlive a dispatch [DECL].

## 12. Subagent visibility
**CONFIRMED [RUN]**: `agent.spawn` (`subagentType, prompt, model, parentModel, permissionMode, background, fork, provider`) → `{model: 'claude-haiku-4-5-20251001', agentId}`; the subagent's `turn.step` (×4 with usage each), `tool.call` (Bash, `SubagentHandback`), `turn.complete` (reason, durationMs, usage) all carry `agentId`; the parent's Agent `tool.call` result text arrives after. A spawn a plugin makes runs in the background and steps past the spawning hook. `$.agent.list()` returned `[]` after the subagent completed — appears to list live agents only (UNKNOWN whether completed ones ever appear). No `turn.start` for subagents (declared).

## 13. Usage / cost information
`$.session.usage()` → `{context:{tokens, window, percent}, rateLimits:[{kind:'five_hour'|'seven_day', percentUsed, resetsAt}], cost:{usd}}` [RUN: window 1,000,000, 7 %, five_hour 11 %, $0.31]. With `{breakdown:'summary'|'full'}` → the full `/context` breakdown (categories, memory files, MCP tool schemas with tokens, agents, skills) [DECL]. Per request: `turn.step` result `usage {input, output, cache_read, cache_creation, model}` and `messageCount`; per turn: `turn.complete.usage`. Classic `PreModelSwitch/PostModelSwitch` carry `estimated_cache_write_usd`, `prompt_cache_warm`, `context_tokens` [DECL, withheld here].

## 14. Context information
`turn.step.messageCount` (35 messages in a trivial `-p` run — system reminders count) [RUN]; `$.session.messages()` [RUN]; `prompt.context` blocks (`claudeMd`, `userEmail`, `attachedProject`, `currentDate`) and `prompt.section` names (`env_info_simple`, `memory`, …) [DECL, withheld here]; `$.fs.ancestors({names:['CLAUDE.md']})` reads instruction files the way the engine does [DECL]; `session.compact` hands the whole transcript with `handle`s [DECL].

## 15. Permission capabilities
`tool.check` is the engine's permission verdict as an event: core returned `{decision:'ask', reason:'This command requires approval'}` and a user plugin answered `allow` → the tool ran in headless mode where an ask would have been a deny [RUN][DBG]. `$.tool.check({tool,input})` queries without running. Classic `PermissionRequest.decision` (allow with `updatedInput`/`updatedPermissions`, deny with `interrupt`) [DECL, withheld here]. **Security note:** a user-tier plugin can silently widen permissions; the only defences are `plugin.register` refusal by an earlier plugin and managed `prependPlugins`.

## 16. Plugin interaction
Plugins see each other's op calls (`next.origin` names the caller) and can deny them; `plugin.register` lets earlier plugins refuse later ones by `tier`/`uses`/`provenance` [DECL, fires DBG]; `engine.create` lets a plugin add a noun others call (`$.voice.say()` becomes event `voice.say`) or withhold a noun from plugins loaded after it [DECL]; `ui.resolve` lets one plugin restyle/remove elements for all others [DECL]; a plugin's `$.tool.call`/`$.prompt.submit`/`$.agent.spawn` run through *every other* plugin's hooks [RUN for tool.register/list].

## 17. Error behaviour and failure semantics
See `snapshot/2.1.273/README.md` table. Verified: throw-without-catch → skipped, chain continued; throw-with-catch → handler ran (`budget: 1000`); wrong result shape → hook failed, error text reached the model; re-entry guard; `-p` mode has no UI. Declared: per-hook time budget (value not surfaced), worker heartbeat / wedge detection, crash → plugin unloaded, ≥N crashes → function hooks off for the session, "a broken plugin never blocks a prompt".

## 18. Capability restriction
- Static scan at load: only `$.noun.method(...)` call sites (or `$` passed to a top-level function) load; `uses` is what `plugin.register` judges.
- Tiers: user tier cannot skip to `prepend`; `next.to` only downward.
- `sec-default@builtin` (present here because `C:\Program Files\ClaudeCode\managed-settings.json` exists): withholds `classic.*`, `prompt.section`, `prompt.context`, `skill.prompt`, `attribution.text`, `settings.read` **hooks** from user tier; managed-provider `tool.describe/command.describe/agent.offer/agent.spawn` too; denies user `tool.register` when policy has `allowedMcpServers`. (User plugins can still *call* `$.settings.read` [RUN].)
- Pinned fields refused on rewrite; `ui.render` trees validated (invalid → engine draws its own, debug log says why); Link `href` https-only; Text/Code bounded (10k chars for Code).
- No network from the module itself: only `$.http.fetch` through the host (subject to admin policy).

## 19. Undocumented but clearly present
- The whole API (zero public docs). `sec-default` builtin. `claude plugin test`. `CLAUDE_CODE_HOOKS_SAME_THREAD`. Managed `prependPlugins`/`appendPlugins`. `hooks.json.surface` is "gone" (replaced by `Client({module})`), i.e. this API has already had at least one breaking revision.
- Telemetry names: `plugin_function_hooks_load`, `_worker`, `_register_tool`, `_register_command`, `_pane_resize`.
- Render components include `TurnDuration`, `Spinner`, `SessionMode`, `PromptHint`, `InfoNotice` — the whole footer is hookable.
- `turn.step` lets a hook drop a tool chunk so the engine "records none and runs none", and lets it rewrite `model` per request — model routing *inside* a turn.
- `session.receive` exposes GitHub-relay wakes with `untrustedKeys`.
- `PromptOrigin` has 16 kinds (`composer, bridge, sdk, task-notification, scheduled-trigger, peer, peer-send-message, projects-relay, channel, coordinator, observer, observer-activity, auto-continuation, unclassified, slack-ping, plugin`).

---

## 20. Status summary (do not blur)

**CONFIRMED WORKING [RUN] — added 2026-09-16 20:15 from the shared-adapter spike (`adapter/`):** `engine.create` adding a custom noun (`$.runtime` with 4 methods; debug log: "engine.create: $.runtime (claude-runtime: emit, supports, judge, snapshot); $ built for sec-default,claude-runtime,runtime-echo"); a **second plugin** hooking the noun's method as an event (`on("runtime.emit")` received all 16 normalised events, `{value:{seq}}` result) and calling `$.runtime.judge/supports/snapshot`; a plugin hooking **its own** noun event (`on("runtime.judge")`) to answer with `$`-needing code; `plugin.json` `types` contract accepted by the validator; `userConfig` fields (`string` with `options`, `sensitive`, `number`) read from `--settings '{"pluginConfigs":{"<name>@inline":{"options":{...}}}}'`; `$.model.complete({model:"haiku"})` answering a JSON judgment in-process in **1,099 ms** (vs ~40 s for the same judgment through `claude -p`); `$.settings.read({source:"policy"})` from a user plugin; `$.store.set`.

**CONFIRMED WORKING [RUN] — added 20:22 from `lab/spike-compact` and `lab/spike-handoff`:** `$.session.compact({instructions})` called by a plugin at `turn.complete` (interactive): the `session.compact` hook saw `trigger:"plugin"`, 12 messages all carrying `handle`s and the instructions; core returned 3 messages (a continuation summary + kept), **52,599 → 9,229 tokens in 10.4 s**; `$.session.turns()`; `$.turn.abort({turnId})` from a `tool.call` hook ended the turn (`turn.complete.reason:"aborted"`, `isAborted:true`, the model's answer empty, the pending Bash reported "The user doesn't want to take this action right now") and a handoff bundle was written inside `turn.complete` from the runtime bus + `git status` via `$.process.run`. Caveat observed: in that headless run `$.session.messages()` returned no user message at abort time (R13).

**CONFIRMED WORKING [RUN] — added 20:26 from `lab/spike-describe`:** `tool.describe` rewrite reaches the model (asked to quote the Bash description's first sentence, Haiku answered `"MARKER-ZQX-77: Executes a shell command on the host."`); `agent.offer {isOffered:false}` removes a built-in type from the model's listing (`Plan` absent from the 16 types the model enumerated; `source:"built-in"`); `$.prompt.suggest` and the `prompt.suggest` event fire (origin `{kind:"plugin"}`, `isShown:false` headless as declared).

**Reconciliation (20:35):** `$.ui.ask` is CONFIRMED (MATRIX demo: the engine's AskUserQuestion dialog opened from a `tool.call` hook and held the call 28.3 s until answered); `$.store.get/set` CONFIRMED within a session (xray filter, adapter probe) — persistence *across* sessions is declared, not yet read back (UNKNOWN); `tool.check {decision:'deny'}` and `agent.spawn {deny}` remain [DECL] until the Phase-17 prototypes' evidence lands (see `prototypes/*/README.md`).

**CONFIRMED WORKING [RUN]:** module load via `--plugin-dir`; `on('*')`; matchers; `tool.call` observe/rewrite/deny/replace-result/delay; `.catch`; `tool.check` allow-override; `tool.register` + serve; `$.model.classify`; `agent.spawn` model rewrite + subagent `agentId` on `turn.step`/`tool.call`/`turn.complete`; `turn.step` streaming read with usage; `prompt.submit` hidden context; `session.start/usage/repo/messages/settings.read`; `ui.render` (10 components) with own tree on `AbovePrompt`; `$.ui.log/status/toast`; `$.command.register`; `$.ui.open` (resolves); `next.trace`/`origin`; `$.process.run`; `$.fs.write`; `$.clock.sleep`; validator; debug-log reporting; headless (`-p`) operation.

**PRESENT BUT EXPERIMENTAL [DECL, not exercised]:** `engine.create` custom nouns + type contracts; `Client` surface modules; `Raster`/`blit`; `ui.press/input/select` round-trip; panes at ≥144 cols; `$.ui.ask`; `$.model.fork`; `$.mcp.call`; `session.compact` rewrite; `session.receive`; `config.*`; `prompt.fill/suggest`; `turn.step` chunk rewriting/dropping and `model` rewrite; `$.turn.abort`; `$.store`; `$.clock.every` timers; `$.prompt.submit`; `plugin.register` refusal; `claude plugin test`; remote surfaces (desktop/mobile/vscode); managed `prependPlugins`.

**APPARENTLY INTENDED BUT INCOMPLETE:** mobile `Input/Select` ("the table grows when those messages exist"); vscode `Client`; `session.send` ("reserved"); pixel-sized viewport ("arrives with the first element that lays out in pixels"); `Raster` on non-terminal surfaces; `PromptFillOrigin.engine` ("none of which raises prompt.fill as shipped").

**NOT CURRENTLY POSSIBLE:** drawing/replacing the permission dialog; a second hooks module per plugin; hooking `classic.*`, `prompt.section/context`, `skill.prompt`, `attribution.text`, `settings.read` from the user tier **on a machine with managed settings** (this one); rewriting pinned fields (`tool`, `tool_use_id`, `agentId`, origins, providers); reading the transcript beyond 4096 messages; module-level `fetch`/`require`/Node APIs; running a hook longer than its budget; seeing another plugin's `ui.message`; a `$.tool.register` from user tier when policy sets `allowedMcpServers`; opening a pane unasked in a terminal narrower than 144 columns.

**UNKNOWN:** the numeric hook budget (only the catch grace of 1,000 ms is surfaced); whether `classic.*` reaches user plugins on a machine *without* managed settings (declared yes); ordering between two user plugins (declared list order); whether `effort`/`model` rewrites on `turn.step` change the request (accepted without error, not proven); whether `$.agent.list()` ever lists finished agents; behaviour of `desktop`/`mobile` surfaces; how the GrowthBook gate flips per account (it is ON for this account with no env var).

---

## 21. Benchmark: classic hooks vs function hooks (measured 2026-09-16, this machine)

| Dimension | Classic (settings/command hook) | Function hook | Evidence |
|---|---|---|---|
| Subprocess overhead per invocation | node `-e 0`: 32–46 ms warm, 117–482 ms cold (first spawn); Python 48–76 ms | **none** (in-process worker) | `bench.jsonl` baseline, shell timing |
| Host round-trip per `$` call | n/a | 0.12–0.37 ms (`$.session.model()` ×5) | `bench.jsonl` |
| Per-dispatch worker hop | n/a | 1–6 ms typical (`tool.describe` 5.3–6.2 ms, `tool.check` 4.8 ms, `engine.create` 2.3 ms); first `ui.render` batch 120–400 ms (cold) | [DBG] "settled in N ms (worker hop, next() included)" |
| Hook frame own cost | one process per hook per event (19 PreToolUse + 6 PostToolUse hooks in the production harness) | `tool.check` own frame ≈ wall − core ≈ 0.1 ms | `bench.jsonl` |
| Whole `tool.call` for `echo bN` under the production harness | core median **1,099 ms** (min 808, max 4,556) — the echo itself is ~50 ms; the rest is the classic hook chain + permission path | same event observed from the function hook at +0.1 ms | `bench.jsonl` (9 calls) |
| Event coverage | 33 lifecycle events, tool-level | 34 engine events + 33 classic + ~60 op events + streaming model steps + UI + plugin nouns | §2 |
| State persistence | none (stateless process each time; must use files) | in-memory across events for the session + `$.store` across sessions | [RUN] `lines[]` accumulated across 306 events |
| Mutation ability | PreToolUse `updatedInput`; PostToolUse `updatedToolOutput`; additionalContext; permission decision | everything in §8 plus model/effort per request, prompt text/context, subagent spawn params, UI trees, descriptions, compaction messages | §8 |
| Enforcement ability | allow/ask/deny on PreToolUse; block on Stop etc. | same plus `tool.check` last-word verdict, deny on any op another plugin makes, refuse another plugin's load, hide agents/commands | §9, §15 |
| Failure semantics | exit code 2 = block; non-zero = error text shown; timeout kills process; a hung hook blocks the tool | skipped + logged; `.catch` grace; worker heartbeat; ≥N crashes disables all function hooks for the session; never blocks a prompt | §17 |
| Observability of the chain | none (each hook blind to the others) | `next.trace` with per-link ms/outcome/received/returned | [RUN] |

Caveat: the 1.1 s figure is the production harness's real per-Bash-call overhead as observed from inside a function hook, not an isolated A/B; isolating it would require running without the user settings hooks (`--bare` also disables plugins).
