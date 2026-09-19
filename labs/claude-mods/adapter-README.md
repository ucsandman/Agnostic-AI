# adapter/claude-runtime — the shared Claude runtime adapter (Phase 14 prototype)

**What it is.** One function-hooks plugin that reads Anthropic's raw engine events and republishes them as
`ClaudeRuntimeEvent`s on a bus every other plugin can hook (`runtime.emit`), plus a typed noun on `$`:
`$.runtime.emit / supports / judge / snapshot`. Products consume the bus and the noun; only this file
touches the early-access API.

```
 engine events ──► adapter/claude-runtime/hooks/index.ts ──► $.runtime.emit(ev) ──► on("runtime.emit") in any plugin
   session.start          probeSupports()  ─────────────►  $.runtime.supports()
   prompt.submit          stubJudge / modelJudge / jevJudge ► $.runtime.judge()
   turn.start/step/complete   ring buffer ──────────────►  $.runtime.snapshot()
   tool.check / tool.call     events/<sessionId>.jsonl  (flushed every 2 s and at turn end)
   agent.spawn
```

## Run

```
claude --plugin-dir C:\Projects\claude-mods-rnd\adapter\claude-runtime --plugin-dir C:\Projects\claude-mods-rnd\adapter\consumers\echo
```
Load the adapter **first** (chain order = `--plugin-dir` order; the noun exists for plugins loaded after it).
Options (per session, via `--settings <file>`):
`{"pluginConfigs":{"claude-runtime@inline":{"options":{"judgeBackend":"model"}}}}` — `stub` (default) | `model` | `jev`
(`jev` also needs `typesafeApiKey`, a sensitive field; not present on this machine).

## What it proves (observed 2026-09-16, build 2.1.273)
- `engine.create` can add a custom noun with methods; the engine reported `$.runtime (claude-runtime: emit, supports, judge, snapshot); $ built for sec-default,claude-runtime,runtime-echo`.
- A second plugin hooked `runtime.emit` and received all 16 normalised events of a session in order with `agentId` and `seq`; `$.runtime.supports()/judge()/snapshot()` worked from that plugin.
- The adapter answered its own `runtime.judge` event with a `$`-needing backend (`$.model.complete`, haiku, 1,099 ms in-process); the deterministic core still answers when the backend fails.
- `supports` is probed: on this machine `classicEvents=false`, `systemPromptRewrite=false` (managed settings present), `uiInjection=false` headless / `true` interactive, `usageSignals/contextSignals/runtimeMemory=true`.
- The JSONL log (`events/<sessionId>.jsonl`) is the replay/Discovery-Loop feed; `lab/spike-handoff` wrote a handoff bundle from `$.runtime.snapshot()` at `turn.complete` with no model call.

## What it does NOT prove
- Ordering guarantees between two consumers (declared: list order); `SessionEnded` (not derivable for a user plugin here; approximate from the last turn); behaviour on desktop/mobile surfaces; the `jev` backend end to end (no key); `turn.step` `effort`/`model` rewrites' effect on the request (accepted, unverified); persistence of `$.store` across sessions was written but not read back in a later session.

## API assumptions (status from MOD_CAPABILITY_MAP.md)
`engine.create` noun (CONFIRMED) · `runtime.*` noun events across plugins (CONFIRMED) · `session.start`, `prompt.submit`, `turn.start`, `turn.step` (stream), `turn.complete` (main + subagent), `tool.check`, `tool.call`, `agent.spawn` (all CONFIRMED) · `$.session.id/model/usage/messages`, `$.settings.read`, `$.store.set`, `$.fs.exists/read/write`, `$.clock.every`, `$.model.complete`, `$.http.fetch` (fetch: DECL only) · `plugin.json` `types` contract (validator CONFIRMED) · `userConfig` via `pluginConfigs` (CONFIRMED).

## Failure behaviour
- A hook throws → skipped, chain continues, the event is simply not emitted; the debug log names it.
- `$.runtime` missing (adapter not loaded) → consumer hooks on `runtime.emit` never fire and `$.runtime.*` is undefined: consumers must check `"runtime" in $` and fall back (the echo consumer does not; the prototypes do).
- Judge backend failure → falls through to the stub via `next(e)`.
- Event log write failure → rows are retried on the next flush.

## Migration path
- Event shapes change → edit this module; `types/index.d.ts` is the versioned contract (`RuntimeEvent.kind` additive-only).
- A capability disappears → `probeSupports` flips the flag; consumers branch on `supports`.
- The API disappears → the JSONL shape can be produced at lower fidelity by a transcript parser (costclaw's) or classic hooks; `SubagentCompleted.usage` and `UsageChanged` are the fields that would be lost.
