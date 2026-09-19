# INTEGRATION_MATRIX — who consumes the runtime layer, through which seam, in what state

2026-09-16. Rows are repos; columns are the contract each one touches. "bus" = `runtime.emit` /
`$.runtime.*` inside Claude Code; "JSONL" = `~/.claude/mods/state/events/<session>.jsonl` (the same
events, on disk, for anything outside the process); "shadow" = `state/shadow/*.jsonl`; "raw" = a raw
engine event the consumer must hook to intercept.

| Repo | Seam | Reads | Writes / enforces | State | Tests | Files |
|---|---|---|---|---|---|---|
| `~/.claude/mods/claude-runtime` (adapter) | raw → bus + JSONL | all raw engine events | `runtime.emit`, `state/events/*.jsonl`, `$.runtime.supports/judge/snapshot` | MOD DEFAULT (installed, loads first) | validator | `mods/claude-runtime/**` (copy of `adapter/claude-runtime`, log dir changed) |
| `~/.claude/mods/harness-mods` | bus + raw (`agent.spawn`, `tool.call`, `prompt.submit`) | bus events, `$.session.usage`, `$.store` | routing rewrite/deny, redaction, cache serve, nudge context, heartbeat, shadow rows, ledger | MOD DEFAULT ×5 guards | 10 node tests + 18 classic probe checks | `mods/harness-mods/**`, `hooks/lib/mods-mode.cjs`, `hooks/mods-liveness.cjs`, `mods/canary.cjs`, `mods/shadow-report.cjs` |
| `~/.claude/hooks` classic guards | `mods-mode.cjs standsDown` | heartbeat + config | stand down per session; shadow rows | seam in 5 guards (`agent-model-guard`, `capability-graph-guard`, `subagent-budget-guard`, `context-nudge.py`, `tool-output-secret-watch`) | `mods-mode-probe.cjs` 18/18; fanout/guard probes green | frozen set relocked |
| `~/.claude/statusline.ps1`, `guard-canary.ps1` | heartbeat / `mods/canary.cjs` | `state/sessions/<id>.json`, `state/canary-leg.json` | badge; canary leg | MOD DEFAULT | canary 8/8 legs | — |
| costclaw | shared definitions | — | `targets.ts` (commandTarget, targetFor, observation, mutations), `live.ts` (rate-card attribution vs engine truth) | INTERFACE PREPARED (engine exports; harness carries a copy with a drift test) | 316 passed, typecheck clean | `packages/engine/src/{targets,live}.ts`, `tests/targets.test.ts`, README §Live runtime consumers |
| leg (LegCli) | JSONL + heartbeat | events, `sessions/<id>.json` | Leg-shaped signals: turnOpen, cleanBoundary, usage %, cost, subagents, `handoffAdvice` | INTERFACE PREPARED (tap built, not wired: `attach.mjs` owned by a live session) | 11/11 | `src/taps/mod.mjs`, `test/taps-mod.test.mjs`, `fixtures/runtime-events.jsonl`, `docs/runtime-tap.md` |
| context-handoff-bundle | JSONL | events | a bundle (structured evidence, capped lists, hashes) via the existing store | INTERFACE PREPARED (module CLI; cli.py wiring documented) | 79 passed (3 new) | `src/context_handoff_bundle/from_events.py`, `tests/test_from_events.py`, README |
| discovery-loop | JSONL + shadow + `subagents.jsonl` | events, comparison rows, measured ledgers | OBSERVATION rows through `summarize_development`; `--dry-run` writes nothing | SHADOW RUNNING (observations only) | 3 tests | `runtime_ingest.py`, `tests/test_runtime_ingest.py`, README |
| agnostic-ai | declaration | `targets.json supports` | `capabilitiesOf`, `requires` → recorded drops | MOD DEFAULT (declaration) | reg-capabilities 5/5; suite green | `core/templates/targets.json`, `engine/hooks/universal-adapter.cjs`, `engine/tests/reg-capabilities.cjs`, README table |
| offlocalai-mcp | pure policy export | `.offlocal/state.json` (documented contract) | `@offlocal/mcp/policy` (evaluatePolicy, defaultDecision, resolve*) | INTERFACE PREPARED | 293 passed; build emits `dist/policy-core.js` | `src/policy-core.ts`, `test/policy-core.test.ts`, `docs/state-json-contract.md`, package.json exports |
| DashClaw | wire tokens + protocol | `client_capabilities` (existing validation) | none | INTERFACE PREPARED (doc only; pure re-export boundary not built) | — | `docs/mod-transport.md` |
| prodguard (rnd prototype) | JSONL replay through the pure core | events | none (prints would-be decisions) | SHADOW READY | 21/21 core | `prototypes/prodguard/evidence/shadow-compare.mjs` |
| experiments/jev | `$.runtime.judge` backend | battery states | none | LAB ONLY (signal) | 32/36 | `experiments/jev/{results-jev.jsonl,summary-jev.json}` |

## Capability envelope (what each consumer may assume)

| Capability | Adapter probe | Consumers that branch on it |
|---|---|---|
| `usageSignals`, `contextSignals` | `$.session.usage()` at session.start | contextNudge arms only when true; LegCli tap falls back to its OAuth poll when the JSONL has no `UsageChanged` |
| `runtimeMemory` | `$.store` round-trip | learned priors persist only when true; otherwise per-session |
| `toolResultMutation` | declared true on 2.1.273 (REALITY BENDER, redaction runs) | redaction/cache serve; the canary flags a change |
| `subagentEvents` | `agentId` on child events | accounting; LegCli subagent tree |
| `classicEvents`, `systemPromptRewrite` | `$.settings.read({source:"policy"})` non-empty → false | nobody builds on them (managed machine) |

## Not integrated (deliberately, this sprint)

git-intelligence, markdown-agent-memory, declick: no seam added (secondary repos; the roadmap's "PREPARE INTERFACES" items stand).
