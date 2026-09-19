# MOD_MIGRATION_PLAN — per guard, from classic subprocess hook to Function Hook

Status 2026-09-16 22:00. Mechanism: `SHADOW_MODE_ARCHITECTURE.md`. Live config: `~/.claude/mods/mods-config.json`.

## Lifecycle used

LAB (claude-mods-rnd prototype) → SHORT SHADOW (both sides write comparison rows; classic enforces) →
MOD DEFAULT (`"mod"` in mods-config.json; classic stands down per session only when the heartbeat
proves the Mod armed the guard) → CLASSIC FALLBACK RETAINED (nothing deleted; env/config rollback).

## Per guard

| Guard (Mod) | Classic path replaced | Shadow evidence | Mod default since | Rollback |
|---|---|---|---|---|
| routing | `agent-model-guard` Agent/Task branch (explicit model + Fable cap), `capability-graph-guard` PreToolUse verdict + advisor `updatedInput` rewrite, `subagent-budget-guard` pre-spawn EST/break-even | Run A (shadow, session 5484030e): 4 spawns; classic denied 2 (upward, model-less) before `agent.spawn` fired — classic-only rows; classic rewrote advisor→opus via updatedInput; Mod agreed on the two it saw. Run B (mod, session d35ed493): 6 decisions — pass, opus→haiku rewrite, undeclared→haiku, advisor haiku→opus, no-EST deny then anti-thrash pass; parent reported each rewrite with reason codes; classic stood down 17×; 5 ledgers settled (prediction error −1.5k…−2.3k tokens) | 2026-09-16 21:55 | `"routing": "classic"` / `HARNESS_MOD_ROUTING=classic` |
| contextNudge | `context-nudge.py` (reads `%TEMP%\claude_ctx_<sid>.txt` written by the statusline) | pure state machine tested (fires once per crossing of 80 %, re-arms, /clear wording ≥92 %); live crossing not reached in probes (max 6 %) — the nudge path is the CONFIRMED `prompt.submit context[]` | 2026-09-16 21:55 (usage probe must pass or the Mod does not arm it and classic keeps enforcing) | `"contextNudge": "classic"` |
| secretRedaction | `tool-output-secret-watch.cjs` (PostToolUse, detect-only, "already in the transcript") | sessions 98422ed6 and 95f81dd2: a `cat` of a fixture with fake Anthropic + Stripe shapes; the model received `<REDACTED:anthropic:73>` / `<REDACTED:stripe-live:40>`; transcript: 0 raw values, 3 markers; adapter event log: 0 raw values after the `text`-field fix; classic watch stood down (3 log lines) | 2026-09-16 21:55 | `"secretRedaction": "classic"` (the classic alert resumes) |
| subagentAccounting | `subagent-budget-guard --post` (log-only) + `calibrate.cjs` transcript refits | Run A/B: 7 settles with measured usage per agentId, learned medians (haiku-scout n=4 → 17,128; advisor n=1 → 18,399), rows appended to both `state/subagents.jsonl` and the classic calibration log with `decision:"measured"` (calibrate ignores them; history preserved) | 2026-09-16 21:55 | `"subagentAccounting": "classic"` stops the classic-log rows; nothing else changes |
| readCache | none classic (new capability; costclaw-live prototype) | sessions 98422ed6 / 95f81dd2: Read #3 of an unchanged fixture served from cache (~61 tok) with a context note; `wc -l` counted as observation #4 of the same file (target-keyed); pure tests cover Read→Read, Read→cat, Read→wc, Grep→Read, Read→Edit→Read invalidation | 2026-09-16 21:55 (serve-after = 3, exact identical calls only, size+mtime verified) | `"readCache": "classic"` |

## Not migrated (deliberately)

| Classic guard | Why it stays |
|---|---|
| `gate-freeze`, `guard-canary.ps1`, `creds-resolve`, `enforcement_liveness_probe.py` | the outer verification ring; must survive a disabled/compromised plugin layer |
| `secret-guard.cjs` (inputs), `rm-guard`, `slow-command-guard`, `security-tier-check`, `git-tree-guard`, `process-kill-guard`, `dev-server-guard`, `slopsquat-guard` | pure input analysis; a Mod gains ~1 s per call but changes no decision — a later batch, after the Mods canary has a release cycle of history |
| `fable-delegate-guard` briefing, `dynamic-recall`, `correction-tracker`, `precompact-extract`, `skill-telemetry`, `session-count` | advisory/telemetry; not decisions |
| DashClaw `dashclaw_pretool.py` (3660 s approval seam) | policy core stays server-side; prodguard is SHADOW READY (see INTEGRATION_MATRIX) |
| the Workflow lint in `agent-model-guard` | static JS analysis; unchanged |

## Version discipline

`harness-mods/hooks/lib/canary.mjs RUNTIME_PIN = { claudeVersion: "2.1.273", dtsSha256Prefix: "ab7a8a2d45f5d8d8" }`.
After a Claude update: `node ~/.claude/mods/canary.cjs` fails `version`; re-extract the declarations
(`snapshot/<ver>/`), re-run `lab/probe*` and the Phase-1 probe in `PHASE2_CHECKPOINT.md`, fix the
adapter first (never the consumers), then bump the pin. Until then every `mod` guard keeps working
(the pin is a warning, not a gate) but the canary is red on purpose.
