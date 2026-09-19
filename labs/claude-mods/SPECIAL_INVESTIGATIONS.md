# SPECIAL_INVESTIGATIONS — Phases 5–12 answered with evidence

Status vocabulary: **CONFIRMED** (run today), **EXPERIMENTAL** (declared, not exercised), **NOT POSSIBLE**
(on this build / this machine), per `MOD_CAPABILITY_MAP.md`. Repository facts come from `archaeology/*.md`
with file:line citations there.

## Phase 5 — LegCli: from quota-aware wrapper to runtime-aware supervisor

What Leg knows today (all from outside the process): OAuth-token usage poll every 60 s, a `--settings`
file of classic hooks, git status every 6 s, and a transcript tail that **discards every subagent line**
(`src/taps/claude.mjs:72 if (j.isSidechain) continue`). Its handoff is `killTree()` at an arbitrary
instant.

| Concept | Signal Leg lacks | Mod supply | Status |
|---|---|---|---|
| LIVE ACTIVITY STATE | phase of work | `ModelStep.toolUses`, `ToolRequested`, `turn.step` chunk kinds (text vs thinking vs tool) | CONFIRMED (stream read, chunk counts) |
| SAFE HANDOFF BOUNDARIES | "turn closed, nothing in flight" | `turn.complete` (main, `reason`), no open `ToolRequested` without `ToolCompleted`, no running `SubagentStarted` | CONFIRMED |
| End a turn cleanly | `killTree()` | `$.turn.abort({turnId})` → `turn.complete.reason === "aborted"` | **CONFIRMED** (`lab/spike-handoff`, `snapshot/…/spike-handoff.log`) |
| ADAPTIVE CHECKPOINTS | 2-minute poll | write on `TurnCompleted`, `SubagentCompleted`, a test-shaped `ToolCompleted`, `UsageChanged` crossing | CONFIRMED (bundle written at turn.complete with git status, files, tool calls, 864 bytes, zero model calls) |
| PREDICTIVE HANDOFF | 5h/7d % only | `$.session.usage()` five_hour %, context %, plus a drift score from `$.session.messages()` (context-health-bar model) | CONFIRMED signals; drift model to port |
| Subagent visibility | none | `SubagentStarted/Completed` with usage per `agentId` | CONFIRMED |
| Where the feed lands | — | a sixth tap `src/taps/mod.mjs` calling `recordUsage/markLimited/updateSession/appendEvent` | design, archaeology C §1 |

The "most convincing safe prototype": `lab/spike-handoff` (abort after N calls + bundle at boundary) is
the primitive; `prototypes/supervisor` carries the subagent half. Full Leg integration is a Phase-19
"PREPARE INTERFACES NOW" item because Leg launches Claude with `--settings`; the same launch adds
`--plugin-dir`.

## Phase 6 — context-handoff-bundle as a live flight recorder

The repo's own limiting sentence: "The CLI cannot see the conversation — only you can." The flight-recorder
table (archaeology C §2) shows **12 of 15 bundle fields fill from events with no model**; only
`findings[].summary/confidence` and `recommendations` still need one small-model call per turn.
Evidence: the spike bundle above lists files touched with read/write counts and every tool call, written
inside `turn.complete`. Token measurement stops being `chars/4`: `$.session.usage()` gives the real first-turn
input of a resumed session, so the "97 % saved" claim becomes measurable. Cross-session drift (`drift.py`)
stays essential: the recorder cannot see the window where no hook was running.

## Phase 7 — CostClaw LIVE and claude-code-audit

6 of costclaw's 8 rules are computable live from `turn.step` usage + `tool.call`; `windows.ts` (rate-window
inference) is deleted by `$.session.usage()`; `read-sessions.ts` by `agent.spawn`/`$.session.repo()`. The
adapter seam is `packages/engine/src/parser.ts:210 rebuildSessionUsage()` (exported); the one blocker is the
unexported `targetFor`. The intervention that only a Mod can make: serving the Nth identical Read from cache
(result replacement, CONFIRMED in Phase 1). Implemented as `prototypes/costclaw-live` (see its README and
evidence). claude-code-audit is costclaw's previous generation; nothing to port.

## Phase 8 — Agnostic runtime contract + claude-harness

**Every hook in the live harness has a verdict** in archaeology A §1 (49 entries): KEEP 8, REIMPLEMENT AS
MOD 17, ENHANCE WITH MOD 9, REPLACE 9, HYBRID 4, plus the statusline (REPLACE) and the `%TEMP%` IPC channel
(delete). Load-bearing facts: four independent reimplementations of "what model am I"; `batch-guard`
re-reads 128 KB of transcript per call; `subagent-budget-guard`'s header says it "sees only tool_input —
never the files, never the result"; the two secret watchers say they cannot redact. Measured: 1,099 ms core
per Bash `echo` under the harness vs +0.1 ms for the same event from a function hook.

Could Agnostic AI become the portability layer with Mods as its first rich backend? **Yes, if it declares
the asymmetry.** `core/templates/targets.json` has no `supports` field; capability is encoded as file
presence, an `adapter` name and a `dialect` name. The four flags that matter most (`resultMutation`,
`uiInjection`, `contextSignals`, `usageSignals`) are false for all 20 targets today and Mods flip all four
for one. `universal-adapter.cjs`'s four-verb vocabulary is the seam where `capabilitiesOf(client)` attaches.
The demonstration pair required by the brief: `prototypes/supervisor` (harness capability made stronger by
middleware) and `adapter/claude-runtime` + `echo` (the same capability exposed through the runtime contract
to a consumer that never sees Anthropic's API).

## Phase 9 — DashClaw as the policy brain

DashClaw's policy core is transport-independent (the MCP server is a thin HTTP client) but not a library
(`evaluateGuard` needs Postgres + tenant). The **pure subset is drop-in**: `evidence.ts` (858 lines, zero
imports), `risk.ts`, `riskTemplates.ts`, `containment.ts`, 15 of 20 evaluators including
`delegation_constraint`/`role_constraint`. Today's integration costs a Node launcher + 2,625-line Python
parse + two HTTPS round trips per governed call and holds approvals in a 3,660 s subprocess.
Native mapping (CONFIRMED mechanisms): `block → {deny}` on `tool.call`; `require_approval → tool.check` or
`$.ui.ask`; `allow_contained → next({...e, command})`; audit capture from the bus; subagent governance via
`agent.spawn` + `agentId`. Prototype: `prototypes/prodguard`. What stays server-side: cross-session ledger,
approvals inbox, rate limits across sessions, Ed25519 receipts (`node:crypto` unavailable in-module).

## Phase 10 — offlocal: production as an ambient property

offlocal's `evaluatePolicy` is pure (60 lines) and its defaults are right (purchase clamp, destructive SQL
blocked everywhere, live writes need approval), but `src/` has **zero** matches for `--prod`, `wrangler`,
`git push`: it governs only its own 124 MCP tools. A Mod reads `.offlocal/state.json` once at
`session.start`, classifies each shell command (`classifyAct`) into a capability, runs the same
`evaluatePolicy`, and shows `PROJECT · ENV · live` in the band. Claude no longer has to remember to ask.
Prototype: `prototypes/prodguard` (demo registry, no real external action).

## Phase 11 — giti: a nervous system

giti has no MCP server; its knowledge answers only when a human runs `giti hotspots`. Reusable as-is:
`file-analyzer.ts` (`getHotspots`, `getFileCouplings`: co-change ≥5 changes each and >60 % co-occurrence),
`fts.ts` (dependency-free TF-IDF), `curator.ts` thresholds (0.5 + 0.1 per corroboration, lesson at 5,
preference at 10). Mod delivery: one `git log --name-only` per session via `$.process.run`, then on
`tool.call` Edit/Write attach "3 recorded regressions; co-changes with X 87 % of the time; X not opened" as
hidden result context; `tool.check` → `ask` above a threshold; `prompt.submit` → top-5 fragile files.
Status: CONFIRMED mechanisms (hidden context, tool.check verdict); prototype deferred (shortlist S7) in
favour of the three builds; caveat: on a young repo the table is silent — say "no signal", not "no risk".

## Phase 12 — budget-aware research → economic routing of runtime operations

`makeDecision` (named additive gains → stay-cheap overrides → one threshold → reason codes) generalises
beyond search with better inputs than it ever had: context %, five-hour %, cost USD, this session's failure
count. Applied per `turn.step` (rewrite `model`/`effort`; rewrite accepted, effect on the request
**unverified**) and per `agent.spawn` (rewrite the model instead of denying — CONFIRMED). Six routes the
runtime can now decide economically: cheap vs expensive model (`turn.step`, `agent.spawn`), local grep vs
semantic search vs web (`tool.call` answer-yourself), existing context vs reread (cache interceptor),
main vs subagent (`agent.spawn` deny/rewrite with measured priors), free vs paid API (`tool.check` +
spendwall-style ceiling), continue vs hand off (`turn.complete` + usage). Keep the reason codes visible.

## Agent Capsule + Rewind — "git for agent execution", honest scope

agent-capsule packs the **harness**, not sessions; its `runDoctor` (prints N/M) and `scanForSecrets` are the
reusable parts. rewind is an OBS replay booth; its **air gate** is the reusable part. Function hooks supply:
record (fully), replay-as-record (fully), replay-against-recorded-results (`tool.call` answer-without-next),
compare (JSON diff + usage), debug (`next.trace`), file-restore (`$.fs` snapshots — agnostic-agent `undo.py`
is the algorithm). NOT: transcript restore, deterministic model re-run (no seed exposed). The record
format and player already exist in agent-pit (`replay-utils.ts`, `replay-controller.ts`). The adapter's
`events/<session>.jsonl` is the record; a replay pane is shortlist S9.

## declick — the inverse question

Advisory routing measurably fails: `~/.declick/hooks/nudge-stats.json` = 36 nudges, 2 followed (5.6 %).
Viable (CONFIRMED mechanisms): answer an `mcp__*` call without `next` from `$.process.run(['declick','run',…])`
and return the trimmed envelope; `capData()` (251 lines, zero imports) on every tool result; `policy.json`
on `tool.check`; register one `declick` tool from manifests (`$.tool.register`, CONFIRMED; deniable by
`sec-default` under `allowedMcpServers`). Not viable: true aliasing (`tool` is pinned). Demonstration of
"Claude requests one operation, middleware selects a better path": `prototypes/costclaw-live` serves a
repeat Read from cache; `lab/demos/bender` replaces a result. A declick-specific arm is shortlist S10.

## markdown-agent-memory — signals, not decisions

The only safe door is the RAM tier (`memory/YYYY-MM-DD.md`): the policy already names daily notes as the
candidate area, the lint does not police RAM for provenance, and a machine can honestly write only
`[observed]` (from tool results) and `[stated]` (only from `prompt.submit` with `origin.kind === "composer"`,
verbatim). Four of the seven capture triggers are observable from the bus. Promotion stays editorial; the
consent primitive for a clickable promote is `leg-alexa-mcp/src/confirm.ts`. The missing "moment" is
2-part-memory-system's 45 %-of-window trigger, now `$.session.usage()` at `turn.complete` and
`$.session.compact()` after the write. Trifecta caution: a memory-writing hook that ingests untrusted content
must record verbatim with source, never summarise.

## Discovery Loop — observations yes, confirmations no

Runtime events map mechanically onto `research_memory._development_entry` (field table in archaeology E
§1); `family` = intervention class so recurring failures survive the 20-row window; `BudgetLedger`
reserve/settle on `agent.spawn`/`turn.complete`; `RoutingJournal` breakers on `turn.step`. The gate is
four-layered and the fourth (`dashboard.approve`) returns "Approval queued locally. No publication occurred."
The honest blocker: `compare_paired` needs ≥3 seeds on a rectangular matrix; a live session has no seed and
no incumbent arm, so runtime events are **OBSERVATION** and can drive **HYPOTHESIS**, but **EXPERIMENT →
VALIDATION** needs a replay harness (`claude -p --plugin-dir <mod>` as the "solver" over task fixtures). Jev
as the screener: `runtime.judge` over observation rows before a reasoning model sees any (ready; blocked on
the key). `verification_contract.py` should wrap any Mod review.

## TypeSafe Jev — status

Live docs read (`api.md`, `primitives`, `confidence`, SDK); SDK 0.6.0 installed; `experiments/jev/` has 11
reproducible states with ground truth, shared question definitions (TypeSafe wire shape), and three
backends. Stub 35/36, Haiku-via-CLI 32/36 at ~40 s/state, in-process `$.model.complete` judge 1.1 s (single
live call). **No `TYPESAFE_API_KEY` exists on this machine** (creds scan: 495 keys, 0 matches; name search of
`.env` files by key name: 0). Recipe added to the creds vault: `creds mint typesafe --open` opens
`https://console.typesafe.ai/settings/keys`. Cap enforced in code: 60,000 tokens. Spend so far: $0.
