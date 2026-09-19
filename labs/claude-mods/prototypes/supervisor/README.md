# SUBAGENT SUPERVISOR

A Claude Code **hooks module** (function hooks, build 2.1.273) that does the routing-and-budget job
that four separate classic PreToolUse guards do today in the production harness —
`agent-model-guard`, `subagent-budget-guard`, `capability-graph-guard`, `fable-delegate-guard` —
in one file, with three capabilities none of them has: it **rewrites** instead of denying, it
**measures** instead of parsing a declaration, and it **remembers** across sessions.

None of those four guards is modified by this prototype. This is a parallel implementation in
`C:\Projects\claude-mods-rnd\prototypes\supervisor\`, loaded only with `--plugin-dir`.

---

## What it is

1. **Capability-graph routing on `agent.spawn`.** Fable → Opus/Sonnet/Haiku, Opus → Sonnet/Haiku,
   Sonnet → Haiku, Haiku → nobody. Downward only; peers are not edges. The one upward edge is the
   `advisor` agent type, which is set to **one rung above the parent** (Sonnet → Opus, Opus → Fable,
   Fable → Fable) and is **never capped**. A spawn that violates the graph has its `model` field
   **rewritten** — `next({ ...e, model: "haiku" })` — not refused. The only deny is a spawn from a
   Haiku loop, because Haiku is a leaf and no rewrite of `model` can make a leaf into a parent.
   The parent's model comes from `e.parentModel`, which the event carries; no registry, no
   transcript tail.
2. **A measured budget ledger** in `$.store` under the key `supervisor.ledger`. Every spawn reserves
   tokens from a prior (17,000 for a lean agent type, 60,000 otherwise — the `subagent-budget-guard`
   constants). Every subagent `turn.step` adds its `usage` to that agent's live total; the subagent's
   `turn.complete` **settles** the row with the real number and pushes it into a running median for
   that subagent type, persisted across sessions. An agent that never completes is charged its full
   reservation. Where the Agent prompt carries the harness's `# EST: <n> calls, <n> files` marker,
   the ledger prints **declared vs measured** and the delta.
3. **A per-subagent tool-call cap.** Every `tool.call` that carries an `agentId` is counted against
   that agent's row. Past `maxSubagentCalls` (a `userConfig` number field, default 40) the hook
   answers `{ deny: "supervisor: subagent over budget" }` for that agent's further calls and leaves
   every other loop alone.
4. **A HUD and a command.** An `AbovePrompt` band shows live subagents (type, model, calls, tokens so
   far), the last routing decision with its reason codes, the five-hour rate-limit percentage and the
   session cost. `/supervisor [log|ledger|priors|all]` (an `immediate: true` command) prints the
   routing log, the ledger and the learned priors.
5. **A JSONL routing log** at `prototypes/supervisor/logs/<sessionId>.jsonl`, one object per
   session start, routing decision, settlement and budget denial.

Every decision carries an Agent-Task-Router style `reasons[]` array — e.g.
`["peer-edge-not-in-graph", "downgraded-to-highest-child-rung"]` — which is what appears in the HUD,
the `/supervisor` log and the JSONL.

---

## Architecture

```
                         Claude Code engine (build 2.1.273)
                                      |
   ┌──────────────────────────────────┴───────────────────────────────────┐
   │                        hooks worker, tier "user"                     │
   │                                                                      │
   │  session.start ──► $.session.id, $.store.get("supervisor.ledger"),   │
   │                    $.command.register("supervisor"),                 │
   │                    $.clock.every(2000) ──► flush + status + redraw   │
   │                                                                      │
   │  agent.spawn ──► decide(e, fableUsed)                                │
   │        │           rungOf(e.parentModel)  vs  rungOf(e.model)        │
   │        │           advisor?  → parentRung + 1                        │
   │        │           parent is haiku? → {deny}      ◄── the only deny  │
   │        │           else clamp to parentRung - 1                      │
   │        ├─ deny  ─► return {deny: reason}      (chain below never runs)│
   │        └─ else  ─► next({...e, model: target}) ─► core starts agent  │
   │                      │                                               │
   │                      └─ r.agentId ─► ledger row, reserve = prior(type)│
   │                                                                      │
   │  turn.step  (async generator, yield* next(e))                        │
   │        └─ e.agentId ─► row.tokens += weigh(r.usage)   [live]         │
   │                                                                      │
   │  turn.complete                                                       │
   │        ├─ e.agentId ─► settle: measured, median(type), $.store.set   │
   │        └─ main loop ─► session totals + $.session.usage()            │
   │                                                                      │
   │  tool.call                                                           │
   │        └─ e.agentId in ledger ─► row.calls++                         │
   │              calls > maxSubagentCalls ─► {deny: "...over budget"}    │
   │                                                                      │
   │  command.run{command:"supervisor"} ─► {text: log + ledger + priors}  │
   │  ui.render{AbovePrompt, terminal}  ─► HUD tree                       │
   └──────────────────────────────────────────────────────────────────────┘
                                      |
                       $.fs.write ──► logs/<sessionId>.jsonl
```

**Middleware order.** Every hook here is a *wrapper*: it calls `next(e)` and post-processes, except
the two enforcement paths (`agent.spawn` deny, `tool.call` over-budget deny) which answer without
calling `next`, so nothing beneath them runs. Load this plugin **first** (`--plugin-dir supervisor`
before any other) if you also load a recorder: a plugin that answers without `next` is invisible to
everything loaded after it. That lesson is the lab's own (`lab/README.md`: blackbox loaded after
guardian reported "0 denied").

---

## Run it

Validate:

```
claude plugin validate C:\Projects\claude-mods-rnd\prototypes\supervisor --json
```

Headless routing proof (a Sonnet loop asks for an Opus subagent; the supervisor rewrites it to Haiku):

```
claude --plugin-dir C:/Projects/claude-mods-rnd/prototypes/supervisor ^
  -p "Use the Agent tool exactly once. subagent_type haiku-scout, model opus, prompt: '# EST: 1 calls, 0 files # SPAWN_OK: prototype dogfood. Run the Bash command: echo scout-alive  # SEQ: probe . Then reply ALIVE.' Then reply PARENT-DONE." ^
  --model sonnet --allowedTools "Bash,Read,Agent,Task" --debug
```

(The production harness's own `capability-graph-guard` denies a Sonnet→Opus Agent call before the
engine ever raises `agent.spawn`. Set its documented per-session off switch —
`CAPABILITY_GRAPH_GUARD=off` — for the probe, or the prototype never gets the event to correct.)

Interactive, to see the HUD (the stock lab driver, unmodified):

```
python C:\Projects\claude-mods-rnd\tools\pty_drive.py out.txt 25 ^
  "C:/Projects/claude-mods-rnd/prototypes/supervisor" ^
  "<prompt that spawns one subagent>|||WAIT:25|||KEYS:/supervisor\r|||WAIT:8" 75 "" --model sonnet --debug
```

`pty_drive.py` hard-codes `--model haiku` into the command line, and a Haiku loop cannot spawn, so
the HUD's interesting rows would stay empty. A second `--model` wins: verified directly —
`claude --model haiku --model sonnet -p "Reply with only your model id, nothing else."` printed
`claude-sonnet-5`. So `--model sonnet` is passed as an extra argument rather than editing the shared
driver.

---

## The four guards this supersedes

| Guard | What it did | How the supervisor does it now | What is lost |
|---|---|---|---|
| **`agent-model-guard.cjs`** (16 KB, PreToolUse on `Agent\|Task\|Workflow`) | Denied any spawn whose prompt/`model` did not *declare* a model; capped Fable at 3 spawns/session; **statically parsed Workflow JS source** for `agent(` call sites, requiring an inline `model:` on each and Fable ones at module top level. | `agent.spawn` carries `model` as a rewritable field. An undeclared model is not an error: reason `model-undeclared` is recorded and the model is **set** to the highest legal child rung. The Fable cap survives as a counter (`FABLE_CAP = 3`, reason `fable-cap-3-per-session`) applied to non-advisor spawns. | **The Workflow static parse.** A `Workflow({name})` runs its `agent()` calls through the engine, so each one *does* surface as an `agent.spawn` and gets corrected at runtime — but the guard's *lint* (a bare `agent()` blocks the whole script before it runs, Fable must be top-level and outside every fan-out) has no runtime equivalent. That half stays a source-lint job. |
| **`subagent-budget-guard.cjs`** (15 KB, PreToolUse + PostToolUse) | Required `# EST: <n> calls, <n> files` in every Agent prompt; priced the declaration against inline work with fixed constants (`LEAN_SPAWN=17000`, `FULL_SPAWN=60000`, `RESULT_TOKENS=2000`, `FILE_TOKENS=2000`, `CACHE_DISCOUNT=0.1`); denied a spawn below break-even, showing the arithmetic; logged declared-vs-actual to `.subagent-budget-log.jsonl` for `calibrate.cjs` to refit offline. Its own header: *"a PreToolUse hook sees only tool_input — never the files, never the result. So it does not guess."* | The same constants are the **prior only**. `turn.step.usage` and `turn.complete.usage` per `agentId` are the real cost; each settlement pushes into a running median per subagent type held in `$.store` under `supervisor.ledger`, so the constants refit themselves **in-session** with no separate `calibrate.cjs` pass. `# EST:` is still parsed, but only to print declared-vs-measured and the delta. | **The pre-spawn deny.** The supervisor never refuses a spawn for being too small, because by the time it can measure, the spawn has happened. The economics become a visible ledger rather than a gate — which is the `fable-delegate-guard` lesson applied (see below). If a hard pre-spawn gate is wanted, the declared estimate is available in the same handler and `{deny}` is one line; it is deliberately not wired. |
| **`capability-graph-guard.cjs`** (18 KB, PreToolUse + SubagentStart + SubagentStop) | Enforced the same graph, but *needs the caller's model, which is in no PreToolUse payload*. It maintained an `agent_id → model` registry across SubagentStart/SubagentStop — and the real SubagentStart payload carries `subagent_config: null`, so the registry alone resolves nothing. Denied a violating edge; rewrote the advisor's model through the `updatedInput` envelope. | `e.parentModel` **is** the caller's model, pinned on the event. Three files of payload archaeology collapse into `rungOf(e.parentModel)`. Every violating edge is rewritten rather than denied; only a Haiku parent is refused. `advisor` is `min(4, parentRung + 1)`, uncapped, as the rule requires. | **Nothing functional** — this is the clean win. The registry, the SubagentStart/SubagentStop wiring and the `updatedInput` envelope all disappear. One thing changes in kind: the guard's deny was *final* for a violating edge, the supervisor's rewrite is *silent correction*, so a model that intended Opus gets Haiku and is told so only through the HUD/`ui.log` line, not through a tool error. |
| **`fable-delegate-guard.cjs`** (16 KB, PreToolUse on edit/shell tools) | Blocked nothing. Briefed a Fable main loop once per session on delegation economics via `additionalContext`, and logged hand-work for `--report`. Its retirement evidence: 1,046 events, 714 `# FABLE_OK` overrides, 266 shell denials (including `npm test` and a read-only grep), edit denials retried 5–7× on one file — *"a model treats a deny like a transient error."* | The economics live in the `AbovePrompt` HUD and `/supervisor`: reserved vs charged tokens, live subagents with calls and tokens, the last routing decision. Advisory that stays visible costs no tokens per tool call and cannot be retried against. | **The once-per-session text briefing**, which reached the model's context; the HUD reaches the *human*. `prompt.section`/`prompt.context` — the events that would put text into the model's system prompt — are withheld from the user tier on this machine (`sec-default@builtin`), so a Mod cannot reproduce the injected briefing at all. `prompt.submit` hidden context is the available substitute and is deliberately not used here (it would spend tokens every turn). |

---

## What it proves

- `agent.spawn` is a sufficient seam for the whole routing problem: the parent's model, the requested
  model, the agent type, the prompt and the `# EST:` marker are all on one event, and `model` is
  rewritable. The four guards' shared workaround — reconstructing "who is calling, on what model"
  from registries and transcript tails — is unnecessary.
- **A rewrite is strictly better than a deny for a routing violation.** The spawn still happens, on a
  legal model, and no retry loop starts. The contrast is in the same evidence set: two rewritten
  spawns produced zero retries, while one denied tool call produced four retries of the same call
  before the exit tool was exempted.
- **The upward edge works in the same handler as the downward one.** `advisor` requested with
  `model haiku` from a Sonnet loop was rewritten *up* to Opus and core started
  `claude-opus-5[1m]` — one function, both directions, no separate envelope.
- **`$.store` makes the estimate self-correcting across sessions.** Four consecutive sessions each
  opened with the previous session's median for `haiku-scout` and reserved against it
  (`17,000 → 26,704 → 22,902 → 22,902`), with no external calibration pass.
- Subagent cost is *measurable* in-session: `turn.step` and `turn.complete` carry `usage` per
  `agentId`, so a declared estimate can be scored against the real number in the same session that
  made it, and the prior can refit itself in `$.store`.
- `tool.call` scoped by `agentId` gives per-subagent enforcement that a PreToolUse hook cannot
  express, because a PreToolUse hook has no way to attribute a call to a particular live subagent.

## What it does NOT prove

- **The Fable rung.** Every observed spawn had a Sonnet parent. `Fable → Opus/Sonnet/Haiku`,
  `Opus → Fable` advisor escalation and the `FABLE_CAP = 3` counter are implemented but **never
  fired**; there is no Fable spawn anywhere in the evidence.
- **The Haiku-parent deny.** A Haiku loop cannot dispatch the Agent tool at all in this build, so the
  `haiku-is-a-leaf` branch — the only `agent.spawn` `{deny}` in the module — has never executed.
  Treat it as untested code.
- **That a tool-call deny actually stops an over-budget subagent.** It does not. The denied agent
  keeps trying (see the retry finding in Evidence); what the cap buys is a hard ceiling on *that
  agent's* real work, not an orderly shutdown. The exit tool had to be exempted so the agent could
  finish at all.
- **Displacing the real guards.** Nothing in the production harness was changed, and the probes had
  to turn one of the four off (`CAPABILITY_GRAPH_GUARD=off`) to get the event at all. A real
  migration means removing four `settings.json` entries, which this prototype does not do.
- **The `agent-model-guard` Workflow lint.** No Workflow script was run through this Mod.
- **Cost in dollars.** `$.session.usage().cost.usd` is whole-session, not per-subagent; the ledger is
  in weighted tokens, not money. The `weigh()` discount (`0.1 ×` cache reads) is inherited from
  `subagent-budget-guard`, not re-derived here.
- **Concurrent subagents.** Every probe spawned agents one at a time. Two live rows in the ledger, and
  two hooks racing on the same `$.store` key, were never exercised.

---

## API assumptions

Every event and `$` method used, with its status from `MOD_CAPABILITY_MAP.md`:

| Used | Status in the capability map | Observed here |
|---|---|---|
| `on("session.start")` | CONFIRMED WORKING [RUN] | yes — `session.start settled in 46.8ms` |
| `on("agent.spawn")` + `next({...e, model})` | CONFIRMED (model forced, `agentId` returned) [RUN] | yes — rewrite observed |
| `agent.spawn` `{deny}` | §9 [DECL] | **no** — coded, never fired |
| `e.parentModel` (pinned) | §12 CONFIRMED [RUN] | yes |
| `on("turn.step")` async generator, `r.usage`, `e.agentId` | CONFIRMED [RUN] | yes |
| `on("turn.complete")`, `e.usage`, `e.agentId` | CONFIRMED incl. subagent turns [RUN] | yes |
| `on("tool.call")` `{deny}` scoped by `e.agentId` | CONFIRMED [RUN] (deny), `agentId` pinned [RUN] | counting yes, deny no |
| `on("command.run", {command})` + `$.command.register({immediate:true})` | CONFIRMED [RUN, registered] | yes |
| `on("ui.render", {component:"AbovePrompt", surface:"terminal"})` + `$.ui.resolve` | CONFIRMED drawn [RUN] | yes (interactive) |
| `$.store.get` / `$.store.set` | **PRESENT BUT EXPERIMENTAL [DECL]** | yes — round-tripped |
| `$.clock.every` | **PRESENT BUT EXPERIMENTAL [DECL]** | yes |
| `$.fs.write` | CONFIRMED [RUN] | yes |
| `$.session.id` / `$.session.usage` | CONFIRMED [RUN] | yes |
| `$.ui.log` / `$.ui.status` / `$.ui.invalidate` | CONFIRMED [RUN] | yes (`ui.status` is a no-op headless: *"no status row in a headless session"*) |
| `register(on, options)` from `plugin.json` `userConfig` | **[DECL], not exercised** | **yes — newly confirmed**, see Evidence |

Assumptions that are *policy*, not API, and would be wrong in another harness:

- Model rung is decided by substring: `fable` > `opus` > `sonnet` > `haiku`. A model id containing
  none of those is treated as **Opus** (reason `parent-model-unrecognised-assumed-opus`) — the
  conservative choice, since it permits Sonnet and Haiku children.
- `fork` inherits the parent and its `model` is ignored by the engine, so a fork is passed through
  untouched with reason `fork-inherits-parent`.
- `advisor` is the only upward edge and is never capped.
- `LEAN_TYPES` is a hard-coded list of this harness's lean agent types.

---

## Failure behaviour

- **A hook throws.** The engine skips that hook and the chain continues beneath it; the transcript
  gets one dim line and `~/.claude/debug/<session>.txt` gets the reason. Concretely: if `decide()`
  threw, the spawn would proceed **unrouted** — fail-open. Every `$` call that can fail at runtime
  (`$.fs.write`, `$.store.set`, `$.session.usage`) is wrapped in `try/catch` so a full log directory
  or a store write error cannot take the routing with it.
- **The API is missing or renamed.** The loader statically scans the module; an unknown event name in
  `on("...")` or a `$` method that does not exist fails the *load*, and `claude plugin validate`
  reports it before a session ever starts. A field that vanishes (say `parentModel`) does not fail
  the load — `rungOf(undefined)` returns 0 and the `parent-model-unrecognised-assumed-opus` branch
  takes over, which routes everything as if the parent were Opus. That is the designed degradation.
- **Panes cannot draw.** This uses `AbovePrompt`, not `$.ui.open`, precisely because an unasked pane
  waits unplaced below 144 terminal columns. The `AbovePrompt` band always draws. In headless (`-p`)
  mode there is no UI at all: `ui.render` never fires, `$.ui.status` logs *"no status row in a
  headless session; kept for the next surface"*, and `$.ui.log` goes to the debug log. Enforcement
  and the JSONL are unaffected — the HUD is the only thing that is display-only.
- **The engine disables function hooks.** After N worker crashes the engine turns function hooks off
  for the session. The supervisor then enforces nothing; there is no residual file-based fallback, by
  design. The production guards it supersedes would have to stay armed during any real migration.

## Migration path if the API changes

Four functions are the adapter boundary; everything else is policy or presentation.

| Function | Depends on | If the API changes |
|---|---|---|
| `rungOf(model)` | model-id strings | the only place model naming is understood |
| `decide(e, fableUsed)` | `e.parentModel`, `e.model`, `e.subagentType`, `e.fork` | pure function of the event; the whole routing policy, testable without the engine |
| `weigh(usage)` | `TurnUsage` field names (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`) | one function to change if the usage shape moves |
| `flush($)` / `persist($)` | `$.fs.write`, `$.store.set` | the only I/O; swap for `$.http.fetch` or a different store here |

The event surface itself is five lines (`on("agent.spawn")`, `on("turn.step")`, `on("turn.complete")`,
`on("tool.call")`, plus the two UI registrations). If `agent.spawn` loses its rewritability, the same
`decide()` output feeds `{deny}` with the reasons as the message — i.e. it degrades exactly into what
`capability-graph-guard` does today. The `C:\Projects\claude-mods-rnd\adapter\claude-runtime` shared
adapter is *not* used: this prototype hooks engine events directly, so there is one less moving part
between the policy and the engine.

---

## Evidence

All of it from the real `claude` binary on this machine, 2026-09-16. Raw files in
`prototypes/supervisor/evidence/`; the plugin's own JSONL in `prototypes/supervisor/logs/`.

### 0. Validation

`claude plugin validate C:\Projects\claude-mods-rnd\prototypes\supervisor --json` → exit 0:

```
"success": true
"./index.tsx hooks: session.start, agent.spawn, turn.step, turn.complete, tool.call,
                    command.run{command=supervisor}, ui.render{component=AbovePrompt, surface=terminal}"
```

First attempt failed on the manifest, not the module: `userConfig.maxSubagentCalls.title` — the field
key is **`title`**, not `label`.

### 1. Load (headless smoke, session `5095533d`) — `evidence/01-*`

```
[DEBUG] hooks module supervisor loaded (worker, environment 2, tier user); events: session.start,agent.spawn,turn.step,turn.complete,tool.call,command.run,ui.render
[DEBUG] hooks module supervisor session.start settled in 46.8ms (worker hop, next() included)
[DEBUG] plugin supervisor: no pluginConfigs["supervisor" or "supervisor@inline"]
```

and yet `01-smoke-log.jsonl` line 1: `"maxCalls":40,"maxCallsSource":"userConfig"`. With no stored
config at all, `register(on, options)` still received the manifest's declared **default**. Zero hook
failures in the log (`grep -iE "fail|error|skip|refus|threw"` over the 34 supervisor lines: empty).

### 2. Routing, both directions (session `b49fdd17`) — `evidence/02-*`

A Sonnet main loop asked for one Opus `haiku-scout` and one Haiku `advisor`. The engine's own debug
lines are the proof — a hook, not the guard chain, changed the model:

```
[DEBUG] agent.spawn haiku-scout: model opus -> haiku by a hook
[DEBUG] agent.spawn advisor:     model haiku -> opus by a hook
```

`02-routing-log.jsonl`, trimmed:

```json
{"kind":"route","route":{"type":"haiku-scout","parent":"claude-sonnet-5","parentRung":"sonnet",
 "requested":"opus","model":"haiku","action":"rewrite",
 "reasons":["upward-edge-not-in-graph","downgraded-to-highest-child-rung"],
 "resolvedModel":"claude-haiku-4-5-20251001"},"reserved":26704,"reservedFrom":"learned n=1"}

{"kind":"route","route":{"type":"advisor","parent":"claude-sonnet-5","parentRung":"sonnet",
 "requested":"haiku","model":"opus","action":"rewrite",
 "reasons":["advisor-upward-edge","advisor-uncapped","advisor-model-overridden","set-one-rung-above-parent"],
 "resolvedModel":"claude-opus-5[1m]"},"reserved":17000,"reservedFrom":"prior lean"}
```

`resolvedModel` is what core returned, so the rewrite was not merely accepted: an actual Haiku
subagent and an actual Opus advisor ran. Neither spawn was denied; both happened, on legal models.

Settlements in the same file, declared vs measured:

```json
{"kind":"settle","type":"advisor",    "calls":1,"declared":17000,"reserved":17000,"measured":21081,"delta":4081, "newMedian":21081}
{"kind":"settle","type":"haiku-scout","calls":2,"declared":28704,"reserved":26704,"measured":19099,"delta":-9605,"newMedian":22902}
```

**Cross-session learning is observed, not assumed.** Session 1 wrote `median(haiku-scout)=26,704`;
session 2 opened with `"priorTypes":["haiku-scout"]` and reserved `26704` with
`"reservedFrom":"learned n=1"` instead of the 17,000 default; the third session read
`"learned n=2"` (22,902), the fourth `"learned n=3"`. Nothing in `~/.claude` was touched to do it —
`$.store` is the plugin's own store.

### 3. Per-subagent call cap (session `8cdb1f2a`) — `evidence/03-*`

Run with `--settings evidence/03-overbudget-pluginconfig.json`, i.e.
`{"pluginConfigs":{"supervisor@inline":{"options":{"maxSubagentCalls":2}}}}`. The plugin read it:
`"maxCalls":2,"maxCallsSource":"userConfig"`. A `haiku-scout` was told to run four Bash commands.

```json
{"kind":"budget-deny","agentId":"ac5a57984baf998b2","type":"haiku-scout","tool":"Bash","call":3,"max":2}
{"kind":"settle","type":"haiku-scout","calls":4,"measured":14104,"reason":"answer"}
```

and from the engine:

```
[DEBUG] tool.call Bash toolu_01QHThiVTzDadLLgPDPcQ9JE: resolved by a hooks module (deny: supervisor: subagent over budget)
```

Calls 1 and 2 ran; call 3 was refused; the agent still completed normally. The parent loop's own
tool calls were untouched — the cap is scoped by `agentId`.

**Finding that changed the code.** The first version of this probe
(`evidence/03a-overbudget-handback-retries.jsonl`, session `a84aa6e6`) denied *every* further call,
including `SubagentHandback` — the tool a subagent uses to return its answer. The log shows the agent
retrying the handback **four times** (calls 4, 5, 6, 7) against a deny it could not satisfy:

```json
{"kind":"budget-deny","tool":"SubagentHandback","call":4,"max":2}
{"kind":"budget-deny","tool":"SubagentHandback","call":5,"max":2}
{"kind":"budget-deny","tool":"SubagentHandback","call":6,"max":2}
{"kind":"budget-deny","tool":"SubagentHandback","call":7,"max":2}
```

That is `fable-delegate-guard`'s documented pathology reproduced in miniature — *"a model treats a
deny like a transient error"* — and it burned more tokens than it saved. `EXEMPT_TOOLS` now excludes
the handback from the cap, and the rerun above settles in four calls instead of seven.

### 4. HUD and `/supervisor` (interactive, pty, session `5a8bb286`) — `evidence/04-hud-screens.txt`

`python tools\pty_drive.py ... --model sonnet --allowedTools Agent,Task,Read,Bash --debug`,
150×45 cells. The `AbovePrompt` band, live and then settled:

```
╭────────────────────────────────────────────────────────────────────────────────────────────────╮
│ SUBAGENT SUPERVISOR  spawns=1 rewritten=1 denied=0 live=1  · reserved 21.7k / charged 21.7k  · 5h 58%  · $0.201
│ ROUTE advisor  haiku → opus  [advisor-upward-edge, advisor-uncapped, advisor-model-overridden, set-one-rung-above-parent]
│ LIVE  af9f18a7 advisor claude-opus-5[1m] calls=0/40 tok=0.0k (reserved 21.7k)
╰────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────╮
│ SUBAGENT SUPERVISOR  spawns=1 rewritten=1 denied=0 live=0  · reserved 21.7k / charged 19.3k  · 5h 59%  · $0.410
│ ROUTE advisor  haiku → opus  [advisor-upward-edge, advisor-uncapped, advisor-model-overridden, set-one-rung-above-parent]
│ DONE  af9f18a7 advisor claude-opus-5[1m] calls=1 measured=19.3k vs declared 21.7k
╰────────────────────────────────────────────────────────────────────────────────────────────────╯
```

`/supervisor` typed into the composer:

```
supervisor: SUBAGENT SUPERVISOR · session 5a8bb286-aae5-49ce-a66d-32185e108ff7
  spawns=1  rewritten=1  passed=0  denied=0  over-budget=0  live=0
  reserved=21,709 tok  charged=19,301 tok  (an agent that never completes is charged its full reservation)
  main loop: 3 turns, ... weighted tok  · context 8% · five-hour 58% · cost $0.445
ROUTING LOG (1 decisions)
   25.4s  advisor   parent=claude-sonnet-5 requested=haiku    -> opus   [advisor-upward-edge, advisor-uncapped,
                                                                        advisor-model-overridden, set-one-rung-above-parent]  agent=af9f18a7
LEDGER (* = live, still accruing)
  agent    type                model                     calls      declared   reserved   measured
  af9f18a7 advisor             claude-opus-5[1m]         1/40         21,709     21,709     19,301  delta=-2,408
PRIORS ($.store supervisor.ledger, learned medians across sessions)
  haiku-scout           n=4   median=   22,902   default=17,000
  advisor               n=3   median=   21,081   default=17,000
```

`evidence/04a-hud-screens-before-fixes.txt` is the first capture, kept because it shows two defects
the render found and this one does not: `5h 57.99999999999999%` (unrounded `percentUsed`) and
`claude-opus-5[1m]1/40` (a 9-wide model column against a 17-character model id).

### 5. Final verification on the shipped code (session `43a478a8`) — `evidence/05-*`

Sections 2–4 were each captured before a later edit (the handback exemption, the two display fixes,
the advisor/fable-counter line). This run is the `index.tsx` that ships, re-running the section-2
prompt end to end:

```
[DEBUG] agent.spawn haiku-scout: model opus -> haiku by a hook
[DEBUG] agent.spawn advisor:     model haiku -> opus by a hook
```

```json
{"kind":"session","maxCalls":40,"maxCallsSource":"userConfig","priorTypes":["haiku-scout","advisor"]}
{"kind":"route","route":{"type":"haiku-scout","requested":"opus","model":"haiku","action":"rewrite",
 "reasons":["upward-edge-not-in-graph","downgraded-to-highest-child-rung"]},"reservedFrom":"learned n=4"}
{"kind":"settle","type":"haiku-scout","calls":2,"declared":24902,"reserved":22902,"measured":11124,"delta":-13778}
{"kind":"route","route":{"type":"advisor","requested":"haiku","model":"opus","action":"rewrite",
 "reasons":["advisor-upward-edge","advisor-uncapped","advisor-model-overridden","set-one-rung-above-parent"]},"reservedFrom":"learned n=3"}
{"kind":"settle","type":"advisor","calls":1,"declared":21081,"reserved":21081,"measured":5161,"delta":-15920}
```

`claude plugin validate ... --json` on the same tree: `"success": true` (`evidence/00-validate.json`).

### 6. What had to be turned off

`CAPABILITY_GRAPH_GUARD=off` for every probe. The production `capability-graph-guard` denies a
Sonnet→Opus Agent call at `PreToolUse`, which is *before* the engine raises `agent.spawn`, so without
its documented per-session off switch the prototype never receives the event it exists to correct.
That is itself a result: **the classic guard and the Mod cannot both be armed on the same edge** —
the deny wins, because it happens first.


---

## Files

```
prototypes/supervisor/
  .claude-plugin/plugin.json    manifest + userConfig field maxSubagentCalls (number, default 40)
  hooks/hooks.json              { "modules": ["./index.tsx"] }
  hooks/index.tsx               the whole Mod
  logs/<sessionId>.jsonl        routing log (written at run time)
  evidence/                     dogfood outputs, debug excerpts, screen snapshots
  README.md                     this file
```
