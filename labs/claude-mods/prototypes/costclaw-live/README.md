# COSTCLAW LIVE

> "Claude is wasting tokens RIGHT NOW."

A Claude Code **function-hooks module** that does live what [`C:\Projects\costclaw`](file:///C:/Projects/costclaw)
does post-hoc over `~/.claude/projects/**.jsonl` — and then **acts on one finding instead of filing it**.

The action is the point. costclaw's `REDUNDANT_TARGET_THRASH` can tell you, a week later, that `Read`
hit one file 14 times. This plugin sees the 4th identical `Read` of a file nothing has written to,
**answers the call from its own cache, and the tool never runs**. The model is told, in a hidden
context block, that the result came from cache. That is the only waste signal in the whole costclaw
rule set whose fix is free.

---

## What it is

| Requirement | Where |
|---|---|
| Per-request usage, per model, session cost in USD | `turn.step` hook, ported `normalizeUsage` + rate card |
| Per-request cache hit rate + early-third/late-third decay | `turn.step`, `cacheDecay()` |
| `(tool, target)` ledger with request index and result size | `tool.call` hook, ported `targetFor` / `commandTarget` |
| Repeated reads graded high/medium/low | ported AgentLens `classifyRun` |
| Tool loops, result bloat (> 20k chars) | `toolLoopStatus()`, `RESULT_BLOAT_CHARS` |
| **Intervention: Nth identical Read served from cache** | `tool.call` returns `{result, context}` without `next` |
| HUD above the prompt | `ui.render` `{component: "AbovePrompt", surface: "terminal"}` |
| `/costclaw` findings with evidence | `$.command.register` + `command.run` |
| `$.session.usage()` cross-check | `turn.complete` |

### Ported, not imported

A hooks module has no `require` and no `import` of repo code, so every reused piece is a **copy**,
with its origin named in the header of `hooks/index.tsx`:

| Ported from | What |
|---|---|
| `C:\Projects\costclaw\packages\engine\src\pricing.ts` | `PRICES_PER_MTOK` (snapshot `2026-09-14`), `canonicalModel`/`priceFor`/`isKnownModel`/`isPremiumModel`, `readCounter`, **`normalizeUsage`** (TTL split, invalid-counter rejection, the four conflict warnings), `pricingMultiplier`, `costForNormalizedUsage`, `uncachedInputExposureForNormalizedUsage`, `cacheHitRate`, `roundMoneyHalfUp` |
| `C:\Projects\costclaw\packages\engine\src\parser.ts:65-100` | `commandTarget()` (the `cd X && …` hop stripper, dated 2026-09-11) and `targetFor()` |
| `archaeology\clones\AgentLens\src\repeated-runs.js` | `classifyRun()` / `detectRepeatedRuns()` — the high/medium/low confidence taxonomy |
| `C:\Projects\costclaw\packages\engine\src\optimizer.ts:10-37` | `REDUNDANT_TARGET_MIN_FIRES=10`, `HEAVY_TOOL_FIRES=100`, `DECAY_DROP=0.25`, `LATE_FLOOR=0.5`, `severityForSavings` bands |

**Deliberately NOT ported: costclaw's two share gates** (`HEAVY_TOOL_MIN_SHARE = 0.6`,
`REDUNDANT_TARGET_MIN_SHARE = 0.25`). Their comment records why they exist — "raw counts flagged 52%
of real sessions", 2026-09-11 — i.e. they are a false-positive suppressor for a reader that cannot
see the request boundary. AgentLens solved the same problem by *grading the evidence* instead of
raising the bar, and `turn.step` **is** the request boundary. So the gates are dropped and
`classifyRun`'s `requestSpread` does the work; low-confidence runs (everything inside one model
request — a parallel batch) never produce a dollar figure, exactly as AgentLens's header demands.

### costclaw's dollar rule, kept

costclaw attaches `estimatedMonthlySavingsUsd` **only where one is derivable**, `0` otherwise —
"never invented". Kept verbatim in spirit. Every `$` this plugin prints comes from measured chars or
measured tokens times the dated rate card:

- repeated read / result bloat → measured result chars ÷ 4 × the primary model's `input` rate (an
  **upper bound**: those tokens might have landed as a cache read on a later request; labelled `~`);
- cache decay → the late third's own `uncachedInputExposureForNormalizedUsage`, scaled by the
  shortfall share (costclaw `ruleMarathonSession`'s own arithmetic);
- tool loops → **no dollar figure**. `HEAVY_TOOL_LOOPS` prints `(no dollar figure is derivable)`.

---

## costclaw's 8 rules: LIVE / NEEDS-HISTORY / OBSOLETE, and what is implemented here

| # | costclaw rule (`optimizer.ts`) | Verdict live | Implemented in this plugin? |
|---|---|---|---|
| 1 | `BAD_CACHE_HIT` — 3 consecutive sessions under 50% hit | **NEEDS-HISTORY** (cross-session; `$.store` makes it live from session 4) | **No.** Per-session hit rate is computed and shown; the 3-session streak is not kept. |
| 2 | `HOT_PROJECT` — one project ≥60% of spend | **NEEDS-HISTORY** (cross-project) | **No.** `$.session.repo()` is captured so the key exists; nothing is aggregated. |
| 3 | `HEAVY_TOOL_LOOPS` — ≥100 fires AND ≥60% share | **LIVE** (two counters over `tool.call`) | **Yes**, `HEAVY_TOOL_FIRES=100` kept, share gate dropped, plus AgentLens consecutive-run grading. No dollar figure. |
| 4 | `REDUNDANT_TARGET_THRASH` — same `(tool,target)` ≥10 AND ≥25% share | **LIVE**, and the cheapest real win | **Yes — and it intervenes.** Reported from 2 fires with a confidence grade; `REDUNDANT_TARGET_MIN_FIRES=10` upgrades the ruleId. The cache-serve fires at the configurable `serveAfter` (default 4). |
| 5 | `SHORT_SESSION_BLOAT` — <10 min AND ≥$5 | **LIVE** (a tripwire, not a postmortem) | **No.** `state.startedAt` and `state.costUsd` are both tracked, so it is ~6 lines; out of scope for this build. |
| 6 | `MARATHON_SESSION` — ≥40 turns, cache hit drops ≥25pp early→late, late <50% | **LIVE** (`turnCache` is literally per-request usage) | **Yes**, `DECAY_DROP`/`LATE_FLOOR` kept verbatim; `MARATHON_MIN_TURNS` 40 → `MARATHON_MIN_REQUESTS` 6 (see caveat below). Does **not** call `$.session.compact()`. |
| 7 | `MODEL_MISROUTE` — premium model on a trivial session | **OBSOLETE as a finding.** Every predicate is a property of a *finished* session; live the rule inverts into a router on `agent.spawn` / `turn.step` | **No**, by design. `isPremiumModel()` is ported and each request is tagged `premium`, so the predicate is available; this plugin never rewrites a model. |
| 8 | `WORKFLOW_COST` — delegated spend ≥$5 and its share | **LIVE and strictly better** (`agentId` replaces costclaw's directory-nesting inference) | **Partly.** Every request records its `agentId`, so the per-agent ledger is one `groupBy` away; the rule itself is not implemented. |
| — | `windows.ts computeWindowStats` (5-hour / 7-day inference from 15-min cost buckets) | **OBSOLETE** — `$.session.usage().rateLimits` returns the real numbers | **N/A.** Not ported; the real `five_hour` / `seven_day` percentages are read and printed. |
| — | `burnClock` (day × 6-hour rhythm, ≥7 active days) | **NEEDS-HISTORY** | No. |
| — | `RULE_ERROR` (per-rule try/catch) | LIVE | Replaced by the engine: a hook that throws is skipped and the chain continues. |

**Added here, not in costclaw:** `RESULT_BLOAT` (a single tool result > 20,000 chars) and
`SERVED_FROM_CACHE` (the intervention's own ledger, the only finding with a **negative** dollar
figure — money not spent).

**Caveat on #6:** costclaw needs 40 turns before it trusts thirds, because it is about to publish a
*monthly* figure. Live, at request 6 (2 per third) the plugin claims only a decay **signal** with its
own numbers printed next to it, never a monthly figure. That is a deliberate loosening, named here.

---

## Architecture

```
                                  ┌──────────────────────── ENGINE (claude 2.1.273) ────────────────────────┐
  user prompt ──▶ turn.start ──▶  │   turn.step  ×N      tool.call  ×M      turn.complete      ui.render    │
                                  └──┬──────────────────────┬───────────────────┬──────────────────┬───────┘
                                     │                      │                   │                  │
  ══════════════════════════ hooks chain: prepend ▸ USER(this plugin) ▸ append ▸ builtin ▸ core ═══════════════
                                     │                      │                   │                  │
  hooks/index.tsx, registration order (first = outermost within this plugin):
                                     │                      │                   │                  │
  1 on("turn.step")  ◀───────────────┘                      │                   │                  │
      requestIndex += 1          ── THE REQUEST BOUNDARY ──▶ │  (every tool.call below belongs to it)
      for await (c of next(e)) yield c ;  r = await stream.result
      normalizeUsage(r.usage) ▸ costForNormalizedUsage ▸ uncachedInputExposure ▸ cacheHitRate
      push state.requests[] ─────────────────────────────────────────────┐
                                                                         │
  2 on("tool.call") ◀────────────────────────────────────────┘           │
      target = targetFor(e.tool, e)                                      │
      Write/Edit/NotebookEdit  ──▶ drop readCache[target], mark mutated   │
      Read & cached & nth >= serveAfter & !mutated & $.fs.stat unchanged  │
          ──▶ RETURN { result: <first call's result>, context:[ … ] }     │   ◀── tool never runs
      otherwise  r = await next(e)                                        │
          ──▶ targetCount, targetRequests(Set of request idx), toolEvents │
          ──▶ chars > 20000 ? state.bloat                                 │
          ──▶ first successful Read ? readCache[key] = {result,size,mtime}│
                                                                         │
  3 on("turn.complete") ◀──────────────────────────────────┐             │
      $.session.usage() ▸ context % · five_hour % · cost ──┼──▶ cross-check vs our own sum
      $.fs.write evidence/live-<sessionId>.jsonl           │             │
                                                           │             ▼
  4 on("ui.render", {AbovePrompt, terminal}) ◀─────────────┘   efficiencyScore() ▸ buildFindings()
      $.ui.resolve(e) ▸ <Box borderStyle="round" borderColor="cyan"> … </Box>
                                                                         │
  5 on("command.run", {command:"costclaw"}) ──▶ { text: full report } ◀───┘
  6 on("session.start") ──▶ $.command.register ▸ $.store.get ▸ $.clock.every(2000) ▸ $.ui.status
```

**Middleware position.** One plugin, user tier. Six registrations on six distinct events, so the
registration order above only fixes nesting *within* this plugin, not against other plugins. If you
load it alongside a recorder such as `lab/demos/blackbox`, **put the recorder first**: this plugin
answers a served `Read` without calling `next`, so anything nested beneath it never sees that call
(the lesson `lab/README.md` records from `guardian` vs `blackbox`).

### Efficiency score — the rubric (deterministic, this plugin's own)

Start at 100 and deduct. A component with no evidence yet is **not assessed** and deducts nothing —
costclaw `scoring.ts:28 makeCheck`'s discipline, because early in a session almost nothing is
assessable. The HUD footer names the skipped components rather than implying full marks.

| Component | Max | Rule | Assessed once |
|---|---|---|---|
| `cache` | −30 | `max(0, 0.80 − sessionHitRate) × 100 × 0.5`, capped | ≥ 2 model requests |
| `repeats` | −25 | 3 per redundant same-target call, **high/medium confidence only** | ≥ 1 tool call |
| `loop` | −20 | `active` −20, `emerging` −10, `none` 0 | ≥ 3 tool calls |
| `bloat` | −15 | 5 per tool result over 20,000 chars | ≥ 1 tool call |
| `decay` | −10 | −10 when `DECAY_DROP` crossed **and** late third < `LATE_FLOOR` | ≥ 6 model requests |

Observed: 5 reads of one file, 3 of them real → 4 redundant → −12 → **88/100**.

---

## Run it

Validate:

```powershell
claude plugin validate C:\Projects\claude-mods-rnd\prototypes\costclaw-live --json
```

Interactive (the HUD):

```powershell
claude --plugin-dir C:\Projects\claude-mods-rnd\prototypes\costclaw-live
```

then ask it to read one file several times, and run `/costclaw`. `/costclaw serve 3` lowers the
cache-serve threshold; `/costclaw serve 10` raises it.

Headless, reproducing the intervention exactly (bash; `BATCH_GUARD_LIMIT` / `REPEAT_GUARD_OFF`
relax **the production harness's own** `~/.claude` guards, which otherwise deny the 4th consecutive
single `Read` — see "Failure behaviour"):

```bash
BATCH_GUARD_LIMIT=99 REPEAT_GUARD_OFF=1 claude \
  --plugin-dir C:/Projects/claude-mods-rnd/prototypes/costclaw-live \
  -p "Do these steps strictly one at a time, never in parallel. Use the Read tool for every Read step; never substitute Bash. The file is C:/Projects/claude-mods-rnd/prototypes/costclaw-live/evidence/probe-target.txt 1) Read the file 2) Run the Bash command: echo s2 # SEQ: probe 3) Read the file again 4) Run the Bash command: echo s4 # SEQ: probe 5) Read the file again 6) Run the Bash command: echo s6 # SEQ: probe 7) Read the file again with the Read tool 8) Read the file again with the Read tool. Then say DONE and quote verbatim any extra note that came with any tool result." \
  --model haiku --allowedTools "Bash,Read" --debug
```

Interactive via pty (captures the HUD to a file):

```bash
BATCH_GUARD_LIMIT=99 REPEAT_GUARD_OFF=1 python C:/Projects/claude-mods-rnd/tools/pty_drive.py \
  C:/Projects/claude-mods-rnd/prototypes/costclaw-live/evidence/pty-hud.txt 25 \
  "C:/Projects/claude-mods-rnd/prototypes/costclaw-live" \
  '<the same prompt>|||WAIT:6|||KEYS:/costclaw\r|||WAIT:10' 90 "" --allowedTools Read,Bash --debug
```

Every run appends a machine-readable ledger at
`prototypes/costclaw-live/evidence/live-<sessionId>.jsonl`
(`kind` ∈ `start | request | tool | cached | served | invalidate | bloat | usage-check | findings`).
The `findings` row is written at every main-loop `turn.complete` and is the **only** way a headless
(`-p`) run can read the findings, since there is no HUD and no `/costclaw` there.

---

## What it proves

1. **A hook can answer a tool call with a previous call's result and the model accepts it.**
   Session `ad705704`: five `Read` calls on one file; the ledger holds **3** `tool` rows (requests
   1, 3, 5) and **2** `served` rows (requests 7 and 9, `nth` 4 and 5). The model's own report:
   > `Read #4 … System-reminders: **tool.call hook additional context: costclaw-live: served from cache, file unchanged since first read (saved ~22 tokens)**`

   Engine debug log:
   > `[costclaw-live] $.ui.log: ⟦costclaw-live⟧ SERVED FROM CACHE  read #4 of …probe-target.txt  saved ~22 tokens ($0.000022)  · file unchanged since request #1`

2. **The guard refuses when the file changed** (this is the check made to fail on purpose; a cache
   that never declines has been run, not verified). Session `f7bb2c37`: the same five-read sequence
   with a `Bash` append between read 3 and read 4 — which does **not** trip the in-session
   Write/Edit flag, so only the `$.fs.stat` size+mtime comparison can catch it. Result: **5** `tool`
   rows, **0** `served` rows; reads 4 and 5 carry `chars: 108` against the cached `87`, and the model
   reported "Read 4: 5 lines … APPENDED-LINE-9999 present". Session `8749421a` covers the other
   branch: an `Edit` on the path emits `{"kind":"invalidate","tool":"Edit",…,"requestId":6}`.

3. **Per-request cost accounting works and disagrees with the engine by a stated amount.** Session
   `ced1cacd`, 9 requests. The ledger's `usage-check` row at `turn.complete`:
   `{"oursUsd":0.1034,"engineUsd":0.1351664,"deltaUsd":-0.0318,"contextPercent":34,"contextTokens":67650,"contextWindow":200000,"rateLimits":[{"kind":"five_hour",…56},{"kind":"seven_day",…13}],"requests":9}`.
   `/costclaw`, run a few seconds later against a fresher `$.session.usage()`, printed
   `ours $0.10 · engine $.session.usage().cost $0.15 · delta -$0.05` followed by the DISCREPANCY line
   explaining it (ours starts at plugin load and is list-price; neither is an invoice) — the two
   snapshots differ because the engine's figure kept moving, which is itself the point of printing
   both. Model breakdown on screen: `claude-haiku-4-5-20251001 requests 9 · in 74 · out 931 ·
   cacheR 495564 · cacheW 39294 · $0.10`, and
   `9x Cache writes without TTL metadata were estimated at the standard five-minute rate` —
   `turn.step`'s `TurnUsage` is the four-field shape, so the ported `normalizeUsage` takes its legacy
   branch and **says so** instead of silently guessing.

4. **The HUD draws, in the required format** (pty session `ced1cacd`, 150 columns):

   ```
   ╭────────────────────────────────────────────────────────────────────────────────────────────────╮
   │ COSTCLAW LIVE · efficiency 88/100 · repeated reads 4 (~6330 tok) · cache health 93% ·           │
   │                 tool loop none · context 34% · $0.10                                           │
   │ REPEATED_TARGET [high] $0.0063 — Read hit …/fixtures/probe-hud.txt 5x                          │
   │ SERVED_FROM_CACHE [high] -$0.0053 — 2 Read calls answered by costclaw-live, not by the tool    │
   │ all components assessed · saved so far ~5276 tok ($0.0053) · serve-after 4 · /costclaw …       │
   ╰────────────────────────────────────────────────────────────────────────────────────────────────╯
   ```

   With a 10 KB file the two served reads kept **~5,276 tokens ($0.0053)** out of the context.

5. **`/costclaw` prints evidence, not assertions** — which file, how many times, **which request
   indices**, the confidence grade, the threshold that did or did not fire, and `decay NOT ASSESSED
   (n/6 requests)` where there is not enough evidence yet.

6. **Result bloat fires on a real result.** Session `ca13ccc2`:
   `{"kind":"bloat","tool":"Read","target":"…/probe-bloat.txt","chars":55317,"tokens":13830}`.

7. **AgentLens's confidence grading becomes a fact.** Every `(tool,target)` carries the set of
   request indices it spanned, taken from `turn.step`, so `requestSpread >= 3 && targetSpread <= 1`
   → `high` is measured, not inferred from repeated `requestId` strings in a JSONL file. Session
   `99dff7b0`, the `findings` row:

   ```
   REPEATED_TARGET high 0.00633 | Read hit …/fixtures/probe-hud.txt 5x
     | 5 Read calls across 5 model requests on the same target — strong signal of
       repeated work without progress. requests=[1,3,5,7,8]
   SERVED_FROM_CACHE high -0.005276 | 2 Read calls answered by costclaw-live, not by the tool
     | #7 …/probe-hud.txt (read 4) ~2638 tok · #8 …/probe-hud.txt (read 5) ~2638 tok
   ```

   Note `requests=[1,3,5,7,8]` — five distinct model requests, so the run is `high` and is allowed a
   dollar figure. Had all five landed inside one request (a parallel batch) it would have graded
   `low` and carried none. The same session reproduces **88/100** headlessly, matching the pty run.

## What it does NOT prove

- **Not an invoice reconciliation.** The delta against `$.session.usage().cost` was −$0.05 on $0.15.
  Our sum covers only requests seen since the plugin loaded and uses a list-price snapshot.
- **`~chars/4` is not a tokenizer.** Every saving figure is an estimate, printed with `~`, and the
  dollar figure is an *upper bound* (the tokens might have been served as a cache read anyway).
- **The cache-serve was exercised on small and 10 KB files, one path, one `offset`/`limit`
  combination**, with `serveAfter` 4. Not exercised: `offset`/`limit` variants (they key separately
  and were never collided), a file deleted between reads, a subagent reading the same file
  (`e.agentId` is recorded but the serve path is not agent-scoped), concurrent parallel reads of the
  same path inside one request.
- **`MARATHON_SESSION` never fired.** The decay branch was only observed in its `not fired` and
  `NOT ASSESSED` states; no session here lost cache. The firing branch is untested.
- **`HEAVY_TOOL_LOOPS` (≥100 fires) never fired**, and no `high`-confidence consecutive run ever
  formed — every session here interleaved `Bash` between `Read`s, so `detectRepeatedRuns` saw runs of
  1. `tool loop` stayed `none` throughout. The `active`/`emerging` branches are untested at runtime.
- **`$.store` persistence across sessions was not verified.** `/costclaw serve <n>` writes it and
  `session.start` reads it, but no two-session test was run.
- **No subagent was spawned**, so `agentId` attribution on `turn.step` is carried but unexercised.
- **Nothing was measured about whether the intervention makes the model *worse*** — a stale-but-
  unchanged file is by definition the same bytes, but the model also loses the fresh
  `system-reminder`s a real `Read` carries.
- **Known human-surface defect: the `/costclaw` report is ~45 lines and does not fit a 45-row
  terminal.** In the pty capture the `SCORE`, `FINDINGS` and `REPEATED` sections scrolled off the
  top; only `INTERVENTIONS` downward stayed on screen. The HUD band carries the top-five findings so
  nothing is unreachable, but the report itself wants paging or a `$.ui.open` pane (which needs ≥110
  columns from a command, per §10) before it is a good human artifact.

---

## API assumptions

Status column is from `MOD_CAPABILITY_MAP.md` §20 as of build 2.1.273.

| Event / method | Used for | Capability-map status |
|---|---|---|
| `on("turn.step")` async generator, `next(e)` stream + `stream.result` | per-request usage, the request boundary | **CONFIRMED [RUN]** |
| `on("tool.call")` — observe + `await next(e)` | ledger, bloat, caching | **CONFIRMED [RUN]** |
| `on("tool.call")` — **answer without `next`**, `{result, context}` | the intervention | **CONFIRMED [RUN]** (result replacement + hidden context); verified again here |
| `on("turn.complete")` | usage cross-check, evidence flush | **CONFIRMED [RUN]** |
| `on("ui.render", {component:"AbovePrompt", surface:"terminal"})` + `$.ui.resolve` | HUD | **CONFIRMED [RUN]** — the band always draws |
| `on("command.run", {command:"costclaw"})` → `{text}` | the report | **CONFIRMED [RUN]** |
| `on("session.start")` | boot, register, timer | **CONFIRMED [RUN]** |
| `$.command.register({immediate:true})` | `/costclaw` | **CONFIRMED [RUN]** |
| `$.session.usage()` → `{context, rateLimits, cost}` | context %, five-hour %, cost | **CONFIRMED [RUN]** |
| `$.session.id()`, `$.session.repo()` | evidence filename, project key | **CONFIRMED [RUN]** |
| `$.fs.stat(path)` → `{kind, size, mtimeMs}` | the unchanged check | op event, **[RUN] here** (`fs.*` listed §2c) |
| `$.fs.write(path, text)` | evidence JSONL | **CONFIRMED [RUN]** |
| `$.ui.log` / `$.ui.status` / `$.ui.invalidate` | transcript lines, status row, redraw | **CONFIRMED [RUN]** |
| `$.clock.every(2000, fn)` | status refresh | **[DECL]** in §20 (experimental) — **[RUN] here**, ticked for the whole pty session |
| `$.store.get` / `$.store.set` | `serveAfter` across sessions | **[DECL]** in §20 — read/written here, **cross-session persistence not verified** |
| `plugin.json` `userConfig` → `register(on, options)` | `serveAfter` default | **[DECL]** — declared and accepted by the validator; a value was never set through `/config`, so the `options` path is unexercised |

Not used, deliberately: `classic.*`, `prompt.section`, `prompt.context`, `skill.prompt` (withheld from
the user tier on this machine); `agent.spawn` / `tool.check` / `$.session.compact()` (the natural next
steps — see below); `$.http.fetch` (this plugin never leaves the process).

---

## Failure behaviour

- **A hook throws** → the engine skips that frame and the chain continues; the debug log names the
  plugin, the event and the reason. Observed count of hook failures across the **5** session debug
  logs from these runs (`ad705704`, `f7bb2c37`, `8749421a`, `ca13ccc2`, `ced1cacd`): **0 each**
  (`grep -icE 'hooks module (failed|threw)|hook failed|costclaw-live.*(threw|failed)'`). Concretely:
  if `turn.step` throws, the model request still happens and only the accounting is lost; if the
  `tool.call` frame throws *before* `next`, the tool runs normally.
- **`$.fs.stat` fails or the path is not a plain file** → `statUnchanged` returns `false` and the
  call goes to the real tool. The cache-serve is fail-open toward "run the tool", never toward
  serving a stale result.
- **A `Write`/`Edit`/`NotebookEdit` is *attempted*** on a cached path → the cache entry is dropped
  **before** `next(e)`, so an edit that is later denied by another hook still invalidates. Observed:
  session `8749421a` logged `invalidate` at request 6 for an `Edit` that a harness guard then denied.
  Conservative on purpose.
- **Headless (`-p`)** → there is no UI. `$.ui.status` does not throw; the engine logs
  `no status row in a headless session; kept here: <text>`. `ui.render` never fires. The evidence
  JSONL is therefore the headless output channel.
- **Terminal too narrow** → irrelevant here: `AbovePrompt` always draws. This plugin never calls
  `$.ui.open`, so the ≥144-column pane restriction does not apply.
- **`$.store` missing or refused** → `readServeAfter` catches and returns the default 4.
- **An unpriced model** → `priceFor` falls back to Sonnet-class rates, `isKnownModel` is false, and
  `/costclaw` prints `(NO RATE-CARD ENTRY — priced at the fallback, figure is an estimate)` plus an
  `UNPRICED MODELS:` line. It does not silently pretend.
- **The production harness's own guards fight the dogfood, not the plugin.** `~/.claude/hooks/batch-guard.cjs`
  denies the 4th consecutive one-at-a-time call and `repeat-tool-guard.cjs` denies repeated identical
  calls — which is exactly the shape of this probe. The first headless attempt was denied at read 3
  and the model silently substituted `Bash head -1`. Both guards read env vars
  (`BATCH_GUARD_LIMIT`, `REPEAT_GUARD_OFF`), set per child process for the probe runs only; no file
  under `~/.claude` was modified.

---

## Migration path if the API changes

Four functions are the whole adapter boundary. Everything else is pure and portable.

| Boundary | Function in `hooks/index.tsx` | Depends on |
|---|---|---|
| Usage in | the body of `on("turn.step")` | `stream.result.usage` being `{input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens, model}`. If the engine ever adds the `cache_creation.ephemeral_5m/1h` split, **nothing changes** — `normalizeUsage` already handles both and stops emitting `CACHE_TTL_ASSUMED_WARNING`. |
| Tool args in | `targetFor(e.tool, e)` | `tool.call`'s envelope spreading the tool's arguments onto `e`. A nested `e.input` shape needs one line: `targetFor(e.tool, e.input)`. |
| Intervention out | the `return { result, context }` inside `on("tool.call")` | result-replacement and hidden context surviving. If `context` is dropped, the serve still works and the model is merely not told; if `result` validation tightens, cache `r` whole and return that object instead of `r.result`. |
| Filesystem truth | `statUnchanged($, path, entry)` | `$.fs.stat` returning `{kind, size, mtimeMs}`. Swap for a content hash (`$.fs.read` + `crypto.subtle`) if `stat` ever goes. |

The ported engine code (`normalizeUsage`, `costForNormalizedUsage`, `targetFor`, `classifyRun`,
`efficiencyScore`, `buildFindings`) touches no `$` at all and would move to another host unchanged.

**Where this goes next**, in the order the archaeology argues for: `$.session.compact()` when the
decay rule fires (the only costclaw remedy the harness exposes as an action); `agent.spawn` as the
`MODEL_MISROUTE` router instead of a finding; spendwall's `evaluatePolicies` on `tool.check`, with
this plugin's `recoverable` figure as `EvalContext.amountCents`.

---

## Evidence

All under `prototypes/costclaw-live/evidence/`.

| File | What is in it |
|---|---|
| `live-ad705704-….jsonl` | **The intervention.** 3 `tool` Read rows (req 1,3,5) + 2 `served` rows (req 7,9, `nth` 4/5, 22 tok each); `usage-check` `ours 0.0812 / engine 0.1011844 / delta -0.0199`, context 22% (43900/200000), five_hour 53%, seven_day 12% |
| `headless-2-served-from-cache.txt` | the model's own report quoting `tool.call hook additional context: costclaw-live: served from cache …` on reads 4 and 5 |
| `live-f7bb2c37-….jsonl` | **The negative control.** 5 `tool` Read rows, **0** `served`; reads 4–5 `chars:108` vs cached `87` |
| `headless-4-negative-control-file-changed.txt` | the model reporting 5 lines and `APPENDED-LINE-9999` present on reads 4 and 5 |
| `live-8749421a-….jsonl` + `headless-3-…txt` | `invalidate` on an attempted `Edit` at request 6 |
| `live-ca13ccc2-….jsonl` + `headless-5-result-bloat.txt` | `RESULT_BLOAT`: 55,317 chars, ~13,830 tokens, request 1 |
| `live-ced1cacd-….jsonl` | the pty session's ledger: 9 requests, ~5,276 tokens saved, `usage-check` `ours 0.1034 / engine 0.1351664 / delta -0.0318` |
| `live-99dff7b0-….jsonl` + `headless-7-findings-snapshot.txt` | the `findings` row with `requests=[1,3,5,7,8]`, confidence `high`, score 88/100 — the same numbers the HUD showed, reproduced headlessly |
| `pty-hud.txt` | every 5-second screen snapshot of the interactive run — the HUD band and the full `/costclaw` report |
| `debug-ad705704-costclaw-lines.txt` | the 79 engine debug lines naming this plugin, including `hooks module costclaw-live loaded (worker, environment 2, tier user); events: turn.step,tool.call,turn.complete,ui.render,command.run,session.start` and `tool.call settled in 897.5ms (worker hop, next() included)` |
| `live-725114f0-….jsonl` + `headless-6-served-after-money-fix.txt` | the re-run that confirmed the sub-cent `money()` fix: `saved ~22 tokens ($0.000022)` instead of `($0.00)` |
| `probe-target.txt` | the 79-byte fixture the headless runs read |
| `../fixtures/probe-hud.txt` (10 KB), `probe-stat.txt`, `probe-bloat.txt` (54 KB) | the pty, negative-control and bloat fixtures |
