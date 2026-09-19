# PORTFOLIO_RUNTIME_MAP — one runtime layer, many products (Phases 13 + 14)

## 0. The claim, and the evidence it now rests on

**One shared adapter should sit between Anthropic's early-access function-hook API and every Practical
Systems product.** Products consume a normalised event bus and a small typed interface; only the adapter
touches the raw API. This is no longer a proposal: `adapter/claude-runtime/` is built and was exercised
live on 2026-09-16 (see `MOD_CAPABILITY_MAP.md` §20, first paragraph):

- `engine.create` adds `$.runtime` = `{ emit, supports, judge, snapshot }` to every plugin loaded after it.
- A second plugin (`adapter/consumers/echo`) that knows nothing about Anthropic's events hooked
  `on("runtime.emit")` and received all 16 normalised events of a session, in order, with `agentId`.
- `$.runtime.judge()` ran the same typed questions through three backends behind one interface:
  deterministic stub (0 ms), the session's own small model in-process via `$.model.complete` (**1,099 ms**),
  and TypeSafe Jev via `$.http.fetch` (code path complete; blocked on a key that is not on this machine).
- `$.runtime.supports()` is **probed**, not asserted: on this machine it reports `classicEvents: false`
  and `systemPromptRewrite: false` because `$.settings.read({source:"policy"})` is non-empty (the managed
  file that seats `sec-default`), `uiInjection: false` in a headless run, `true` under the terminal.
- `lab/spike-handoff` proved `$.turn.abort` ends a turn cleanly (`turn.complete.reason === "aborted"`) and
  that a handoff bundle can be written at a **turn boundary** from the bus alone, with no model call.

## 1. The layer diagram, as built

```
                         Claude Code 2.1.273 (function hooks, early access)
                                            │
            ┌───────────────────────────────┴────────────────────────────────┐
            │  adapter/claude-runtime  (ONE plugin; the only code that reads  │
            │  raw engine events; ~330 lines)                                 │
            │   • hooks: engine.create, session.start, prompt.submit,         │
            │     turn.start/step/complete, tool.check, tool.call, agent.spawn│
            │   • $.runtime.emit(ev)      → the bus (event `runtime.emit`)    │
            │   • $.runtime.supports()    → probed capability set             │
            │   • $.runtime.judge(req)    → stub | model | jev                 │
            │   • $.runtime.snapshot()    → ring buffer                        │
            │   • events/<session>.jsonl  → replay / Discovery Loop feed       │
            └───────────────────────────────┬────────────────────────────────┘
                                            │  on("runtime.emit")  ·  $.runtime.*
        ┌──────────────┬────────────────────┼────────────────────┬──────────────────┐
   supervisor      costclaw-live         prodguard          spike-handoff        (next) giti-edge,
   (LegCLI /       (CostClaw)            (DashClaw ×        (LegCLI /            memory-feed,
    harness         HUD + cache          offlocal)           handoff bundle)      replay-pane,
    routing)        interceptor          approvals                                declick-arm
```

Consumers may still hook engine events directly when the adapter would only forward them (the three
Phase-17 prototypes do both: raw where they must intercept, bus where they observe). The rule that
matters: **a consumer that only hooks `runtime.emit` and calls `$.runtime.*` survives an API change
untouched.**

## 2. `ClaudeRuntimeEvent` — derived only from events Anthropic exposes

| Normalised event | Derived from (engine event) | Fields |
|---|---|---|
| `SessionStarted` | `session.start` (+ `$.session.model/usage`, `$.settings.read`) | cwd, surface, isInteractive, model, `supports` |
| `PromptSubmitted` | `prompt.submit` | origin kind (16 values), chars, preview, turnId |
| `TurnStarted` | `turn.start` | turnId, chars |
| `ModelStep` | `turn.step` (stream result) | turnId, index, model, effort, messageCount, chunks, ms, stopReason, toolUses, usage |
| `ContextChanged` | `turn.step` (main loop) | messageCount, contextTokens (= input + cache_read + cache_creation) |
| `PermissionRequested` | `tool.check` | tool, input, decision, reason, rule, byPlugin (from `next.trace`) |
| `ToolRequested` / `ToolCompleted` | `tool.call` before/after `next` | tool, tool_use_id, args / ms, denied, isError, textChars, preview, middleware trace |
| `FileObserved` / `FileModified` | `tool.call` on Read/Grep/Glob vs Write/Edit/NotebookEdit | path |
| `SubagentStarted` / `SubagentCompleted` | `agent.spawn` / `turn.complete` with `agentId` | childAgentId, type, model, requested vs resolved model, promptChars / reason, durationMs, usage |
| `TurnCompleted` | `turn.complete` (main) | reason, durationMs, usage, answerChars |
| `UsageChanged` | `$.session.usage()` after each main turn | context %, window, five_hour/seven_day %, cost USD |
| `ErrorOccurred` | `tool.call` throw or `isError` | tool, error text |
| `SessionEnded` | **not derivable** for a user plugin here (`classic.SessionEnd` withheld); approximate from the last `TurnCompleted` + a `$.clock.every` liveness tick | — |

Nothing above is invented; each row names the Anthropic event it comes from.

## 3. Capability negotiation — `supports`, and what each product does with it

| Flag | Claude Code (Mods, this machine) | Claude Code (managed-settings machine) | Codex CLI | Gemini CLI / agy | 15 file-only targets | How it was decided |
|---|---|---|---|---|---|---|
| `toolInterception` | true | true | true (near-clone hook dialect) | true (shimmed, `++`-chained) | false | declared / agnostic-ai adapters |
| `toolResultMutation` | **true** | true | false | false | false | probed (REALITY BENDER) |
| `runtimeEvents` | true (34 engine + ~60 op events) | true | true (13 classic) | true (7 / 4) | false | declared |
| `subagentEvents` | **true** (agentId on every child event) | true | true (SubagentStart/Stop only) | false | false | probed |
| `uiInjection` | **true** (terminal) | true | false | false | false | probed per surface |
| `dynamicPermissions` | **true** (`tool.check` last word) | true | partial (rules file) | false (Gemini has no "ask") | false | probed |
| `contextSignals` / `usageSignals` | **true** | true | false | false | false | probed (`$.session.usage`) |
| `middleware` | true | true | false | false | false | declared |
| `runtimeMemory` | true (`$.store`) | true | false | false | false | probed |
| `checkpointing` | `file-level` only | file-level | none | none | none | declared (no engine restore) |
| `classicEvents` | **false** (sec-default) | false | n/a | n/a | n/a | probed via policy settings |
| `systemPromptRewrite` | **false** here | false | false | false | false | probed |
| `semanticJudgment` | `stub \| model \| jev` | same | stub only (subprocess) | stub only | stub | configured |

Product behaviour under negotiation (progressive enhancement, never lowest common denominator):
- **Agnostic AI** `apply.cjs`: render the Mod variant of a guard when the target's `supports.toolInterception && middleware` are true, the shim variant otherwise; record every drop with the flag that caused it (today it discovers gaps by failing the write). Add `supports` to `core/templates/targets.json` and the README field table in the same change (archaeology A §3b).
- **LegCli**: handoff at `turn.complete` when `usageSignals`; fall back to the OAuth poll when not; show subagent trees only when `subagentEvents`.
- **DashClaw adapter**: in-process deny when `toolInterception`; `tool.check` approval seam when `dynamicPermissions`; else keep the shell hook.
- **CostClaw LIVE**: HUD when `uiInjection`; JSONL only when not; cache interceptor only when `toolResultMutation`.
- **memory feed**: `[stated]` lines only when `prompt.submit` origin is available (`runtimeEvents`).

## 4. The generic judgment interface (Jev is one implementation)

```
runtime.judge({ state, questions: { id: { type: 'noul'|'choice'|'score', instructions, criteria } }, backend? })
  → { backend, latencyMs, answers: { id: {p_yes} | {choice, confidence, probabilities} | {score, confidence, probabilities} }, usage? }
```
`choose(...)`, `score(...)`, `verify(...)` are sugar over one `judge` call (one Choice / one Score / one
Noul). Backends measured on the 11-state battery in `experiments/jev/` (real captured runtime states with
ground truth from what happened next):

| Backend | Where it runs | Accuracy (36 labels) | Latency per state | Cost |
|---|---|---|---|---|
| stub (rules) | in the plugin | 35/36 | 0 ms | 0 |
| model (`$.model.complete`, haiku) | in-process, session credentials | not yet run on the battery (single live call: 1,099 ms) | ~1.1 s | subscription |
| haiku via `claude -p` | subprocess (old path) | 32/36 | ~40 s (CLI startup + hooks) | subscription |
| **Jev** (`jev-latest`) | HTTPS | **not run: no `TYPESAFE_API_KEY` on this machine** (495 keys scanned, vault + name search) | expected sub-second | ≤$1.25 authorised |

Honest reading: the labels were derived from mechanical facts (turn open, denials, repeated reads), so the
rule backend scores highest by construction. Jev's value would show on **ambiguous** states (is this
recovery or implementation? is this loop productive?) which the battery under-represents; the experiment is
ready to run the moment `creds mint typesafe --open` yields a key. Principle kept from the brief: policy
stays deterministic, judgments are signals, consequential actions go through `tool.check`/`$.ui.ask`.

## 5. The combinations, ranked by "whole ≫ parts"

| Combination | What the whole does that no part can | Mechanism (all CONFIRMED unless noted) |
|---|---|---|
| **LegCli + adapter + handoff bundle + context-health** | Hand off at a *clean boundary* for a *quality* reason, with a bundle the session itself wrote | `turn.complete` + `$.session.usage()` + `$.turn.abort` (proven in `lab/spike-handoff`); drift term from `$.session.messages()` |
| **DashClaw + offlocal + prodguard** | "Is this production?" before every shell command, with containment instead of denial | `tool.call` deny/rewrite + `tool.check`; `classifyAct` × `evaluatePolicy`; `$.ui.ask` for approval |
| **harness routing guards + Agent-Task-Router + costclaw + spendwall → supervisor** | Route subagents by measured cost and history; budget that learns | `agent.spawn` rewrite + per-agent `turn.complete.usage` + `$.store` |
| **costclaw + AgentLens + declick `capData` → CostClaw LIVE** | Prevent waste (serve a repeat read from cache; cap bloat) instead of reporting it | `tool.call` result replacement; `turn.step` usage |
| **agent-pit replay + adapter events + agnostic-agent undo** | "Git for agent execution" (record · replay-against-recorded-results · compare · debug · file-restore) | `events/*.jsonl` is already the record; answer-without-`next` is replay; `$.fs` snapshots are restore. NOT transcript restore, NOT deterministic model re-run |
| **Discovery Loop + adapter events + Jev/model judge** | Cheap screening of thousands of observations before a reasoning model sees any | `runtime.emit` → `research_memory` rows (observations only); `judge()` as the screener; `verification_contract` for any model review |
| **markdown-agent-memory + adapter + confirm.ts** | Better signals, same editorial policy, a clickable promote gate | `[observed]` from bus events into the RAM tier; `[stated]` only from `prompt.submit origin=composer`; pane + token gate (pane needs ≥144 cols) |
| **giti + discovery-loop dead-ends + adapter** | The two facts a fresh session re-derives, delivered at the edit | `tool.call` hidden context; `tool.check` ask above a regression threshold |
| **declick + adapter usage** | Tighten tool-result budgets as context fills | `tool.call` result replacement with `capData`; `$.session.usage()` |
| **guard-canary + liveness probe + adapter trace** | A policy layer that continuously proves it is enforcing | `$.clock.every` canary through `tool.call`; `next.trace` outcomes; `ui.render` badge |
| **Jev + LegCli / DashClaw / CostClaw** | Typed judgments as *telemetry* beside deterministic signals; escalate only disagreements | `runtime.judge` with the shared question definitions (`experiments/jev/questions.py`) |

## 6. What stays outside the adapter (and why)

- Anything that must survive a compromised or disabled plugin layer: `gate-freeze`, `guard-canary`,
  `creds-resolve`, `enforcement_liveness_probe` (archaeology A). The adapter is user-tier code.
- Cross-machine, cross-session state: DashClaw's ledger/approvals inbox, spendwall's rails, agent-comms'
  git transport, Leg's board and process liveness (`reapLost`). A Mod dies with its session.
- Secrets: the adapter never reads `.env`/vault; `creds` is called through `$.process.run`.
- Other CLIs: Codex/Gemini/agy keep agnostic-ai's shims; `supports` makes the asymmetry explicit.

## 7. Migration path when Anthropic changes the API

1. Event names/shapes change → edit `adapter/claude-runtime/hooks/index.ts` only; consumers see the same
   `RuntimeEvent`. The `types/index.d.ts` contract is the versioned public surface (`RuntimeEvent.kind`
   list is additive-only).
2. A capability disappears (e.g. result mutation) → `supports` flips to false; consumers already branch on
   it; the product degrades to its pre-Mods path (the shell hook, the CLI, the JSONL reader).
3. The whole API disappears → the adapter's event log format is what the products consumed; a classic-hook
   or transcript-parsing shim can produce the same JSONL at lower fidelity (`SubagentCompleted` and
   `UsageChanged` would be lost; everything else has a transcript-derivable equivalent — see costclaw's parser).
4. Re-verify per build: `snapshot/<version>/claude-code.d.ts` diffed against the extracted declarations;
   `lab/probe*` re-run; the capability map's status lists updated. The canary rule applies: the Mods leg of
   `guard-canary` must exist before any production guard moves.
