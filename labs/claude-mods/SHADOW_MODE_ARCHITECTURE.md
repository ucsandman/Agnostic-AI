# SHADOW_MODE_ARCHITECTURE — how a guard moves from classic to Mod without ever being owned twice

Built 2026-09-16 (Phase 2 sprint). Live in `C:\Users\sandm\.claude\mods\` (mirrored to `C:\Projects\claude-harness\mods\`).

## The layers

```
Claude Code 2.1.273 (Function Hooks, early access)
   │
   ├─ claude-runtime            ~/.claude/mods/claude-runtime   (installed plugin, loads FIRST)
   │    the ONE reader of Anthropic's raw events → runtime.emit bus + $.runtime.{emit,supports,judge,snapshot}
   │    + state/events/<session>.jsonl (the feed LegCli, handoff bundle, Discovery Loop consume)
   │
   ├─ harness-mods              ~/.claude/mods/harness-mods     (installed plugin, loads SECOND)
   │    hooks/index.tsx  = glue only (session.start, runtime.emit, agent.spawn, tool.call, prompt.submit,
   │                       turn.complete, command.run /mods, ui.render band)
   │    hooks/lib/*.mjs  = pure policy, node-tested (modes, explain, targets, redact, routing, budget,
   │                       shadow, usage, canary)
   │
   └─ classic hooks             ~/.claude/hooks/*.cjs|py|ps1 (unchanged policy, one new seam each)
        hooks/lib/mods-mode.cjs → standsDown(guard, sessionId)
```

Raw events are hooked in `harness-mods` only where the Mod must intercept (`agent.spawn`, `tool.call`,
`prompt.submit`); everything observational (subagent usage, session usage, traces) comes off the bus.
`claude-runtime` is byte-identical in shape to `adapter/claude-runtime` in this repo (only the log
directory default differs), so the API boundary stays one file.

## The three states, per guard (`~/.claude/mods/mods-config.json`)

| Mode | Classic hook | Mod | Comparison |
|---|---|---|---|
| `classic` | enforces | observes only (no rows written for that guard) | none |
| `shadow_mod` | enforces AND writes its verdict to `state/shadow/<session>.classic.jsonl` | computes what it WOULD do, writes `state/shadow/<session>.mod.jsonl`, never denies/rewrites | `node ~/.claude/mods/shadow-report.cjs` pairs rows on (session, subsystem, key) |
| `mod` | **stands down** for that decision (still installed) | enforces | Mod rows only |

Per-session override: `HARNESS_MOD_<GUARD>=classic|shadow_mod|mod` (`HARNESS_MOD_ROUTING`,
`HARNESS_MOD_CONTEXT_NUDGE`, `HARNESS_MOD_SECRET_REDACTION`, `HARNESS_MOD_SUBAGENT_ACCOUNTING`,
`HARNESS_MOD_READ_CACHE`) or `HARNESS_MODS=off` (everything classic). Both sides read the same names:
the Mod through `$.env.get` at `session.start`, the classic hooks through `process.env`.

## Why classic and Mod can never both own one decision

The classic hook stands down only when **all** of these hold (`hooks/lib/mods-mode.cjs`, mirrored by
`harness-mods/hooks/lib/modes.mjs classicStandsDown`, both unit-tested):

1. the guard's effective mode is `mod` (config or env; a broken/missing config reads as `classic`);
2. `state/sessions/<session_id>.json` exists — the heartbeat `harness-mods` writes at `session.start`
   and re-writes on every main-loop `turn.complete`;
3. that heartbeat's `armed[guard] === true` — the Mod arms a guard only after its own probes passed
   (`$.runtime` reachable, `$.session.usage()` answering, `$.store` round-trip);
4. the heartbeat is younger than 6 hours.

Anything else → the classic hook enforces exactly as before. Proven both ways on 2026-09-16:
`agent-model-guard`, `subagent-budget-guard`, `capability-graph-guard` and `tool-output-secret-watch`
each yield under `mod + armed` (exit 0, no output) and deny again under `HARNESS_MODS=off`, under an
unarmed heartbeat, and with no heartbeat. The session id is the same string on both sides (the Mod's
`$.session.id()` equals the classic payload's `session_id`; verified on five sessions).

The reverse hazard — the classic layer denying before the Mod's event exists — is exactly what shadow
mode measures: a `classic-only` routing row means the Mod never saw the spawn. Run A (shadow) recorded
two such rows; Run B (`mod`) recorded zero because the classic guards stood down 17 times.

## Silence cannot read as health

| Instrument | Where | What it catches |
|---|---|---|
| `harness-mods` self-judgement (`lib/canary.mjs judge`) | `state/sessions/<id>.json.canary`, `state/canary-status.json` | adapter noun missing, capability probe changed, usage/store unavailable, events not flowing, adapter not outermost, enforcement unreachable, hook failures, `mod` mode on an unhealthy layer |
| `hooks/mods-liveness.cjs` (UserPromptSubmit, first prompt) | `systemMessage` + `additionalContext`, `state/liveness.jsonl` | no heartbeat for this session (Function Hooks gone, plugin disabled, worker crash), unhealthy heartbeat, `mod` guards not armed |
| `mods/canary.cjs` (the Mods leg of `guard-canary.ps1`, ~20 h) | `state/canary-leg.json`, canary output line | plugins not installed/enabled, config invalid, last session unhealthy, `claude --version` ≠ pinned 2.1.273, `claude plugin validate` failing, pure tests failing (incl. secret-pattern drift) |
| statusline badge (`statusline.ps1`) | `MOD OK rou:M ctx:M sec:M sub:M rea:M` / `MOD FAIL …` / `MOD none` | every session, at a glance; `!` marks a `mod` guard that is not armed (classic enforcing) |
| `/mods`, `/mods shadow`, `/mods ledger`, `/mods rollback` | in-session command | live status, comparison, ledger, rollback recipe |

## The comparison row

```json
{ "ts", "session", "side": "classic|mod", "subsystem", "action", "key", "mode", "decision",
  "requestedValue", "resolvedValue", "reasonCodes": [], "wouldRewrite", "enforced",
  "latencyMs", "retryCount", "actualOutcome", "note" }
```
Routing keys are `signatureOf(session, type, prompt, requestedModel)` (FNV-1a, identical on both
sides); redaction keys are `tool_use_id`; cache keys are `path#n`; settles key on `agentId`. A classic
`deny` and a Mod `rewrite` count as agreement on the violation (the mechanism differs by design).

## Rollback

- one guard, all sessions: `"routing": "classic"` in `~/.claude/mods/mods-config.json`;
- one session: `HARNESS_MOD_ROUTING=classic` or `HARNESS_MODS=off`;
- the whole layer: `claude plugin disable harness-mods@harness-mods` (and `claude-runtime@harness-mods`);
- emergency: delete `~/.claude/mods/state/sessions/<id>.json` — classic enforces on the next call.
No classic code was deleted; every classic guard is still wired in `settings.json`.
