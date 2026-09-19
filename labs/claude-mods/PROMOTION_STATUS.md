# PROMOTION_STATUS — every Function Hook capability, by lifecycle state

As of 2026-09-16 22:30, Claude Code 2.1.273. Vocabulary: LAB ONLY · INTERFACE PREPARED · SHADOW READY ·
SHADOW RUNNING · PROMOTION CANDIDATE · MOD DEFAULT · BLOCKED · WAIT FOR API · DO NOT PROMOTE.

## MOD DEFAULT (live in `~/.claude/mods`, config `mods-config.json`)

### 1. Mods canary + heartbeat (the liveness layer)
- **Classic path replaced:** none replaced; adds the Mods leg to `guard-canary.ps1`, a first-prompt witness (`hooks/mods-liveness.cjs`), a statusline badge, `/mods`.
- **Fallback:** the canary leg is classic (node), runs even when the plugin is gone; the liveness hook speaks when no heartbeat exists.
- **Rollback:** `claude plugin disable harness-mods@harness-mods`; remove the `mods-liveness` entry from `settings.json` UserPromptSubmit; the canary leg then reports FAIL (by design) until removed from `guard-canary.ps1`.
- **Evidence:** full canary OK on 8 legs (installed, config, last-session, layer-self-check, version, validate×2, tests); liveness hook spoke in this very session (started before the install: "wrote no heartbeat"), stayed silent on healthy sessions; badge `MOD OK rou:M ctx:M sec:M sub:M rea:M` on the pty dogfood statusline.
- **Limitations:** the pin is a warning, not a gate: after a Claude update the Mod keeps running until re-probed.

### 2. Native session usage (`contextNudge`)
- **Replaced:** `context-nudge.py` reading `%TEMP%\claude_ctx_<sid>.txt` (the statusline→hook IPC file).
- **Fallback:** `context-nudge.py` still wired; enforces unless `mod` + armed (arming requires `$.session.usage()` to answer with a context window).
- **Rollback:** `"contextNudge": "classic"` or `HARNESS_MOD_CONTEXT_NUDGE=classic`.
- **Evidence:** `$.session.usage()` probed every session (context %, window 1,000,000, five_hour %, seven_day %, cost USD); state machine tested (once per crossing, re-arm, /clear at 92 %); the attach path is the CONFIRMED `prompt.submit context[]`. The 80 % crossing itself was not reached in any probe (max 8 %).
- **Limitations:** the statusline still writes the `%TEMP%` file (harmless; delete with the statusline rewrite, not in this sprint).

### 3. Rewrite explanations (`explain.mjs`, used by routing, cache serve, redaction)
- **Replaced:** nothing classic; fixes the R&D divergence (silent rewrites).
- **Evidence:** Run B and the pty dogfood: the parent reported "requested opus, ran on haiku" with reason codes from the Agent result's hidden context; cache serve and redaction results carry one-line notes; the redaction note tells the model not to reprint and to say which credential.
- **Limitations:** `agent.spawn` results carry no `context[]`, so the explanation rides on the parent's Agent `tool.call` result (after the subagent finishes).

### 4. Measured subagent accounting (`subagentAccounting`)
- **Replaced:** the declared-only view of `subagent-budget-guard`; `calibrate.cjs` transcript refits remain valid.
- **Fallback:** classic `--post` logging unchanged; historical log preserved (new rows are `decision:"measured"`, ignored by calibrate).
- **Rollback:** `"subagentAccounting": "classic"`.
- **Evidence:** 12 settles across 4 sessions with per-agent usage; learned medians `haiku-scout n=6 → 17,192`, `advisor n=2 → 18,039` in `$.store`; prediction errors −1.5k…−2.3k tokens vs the declared `# EST:` cost (the shipped 17k lean prior is ~10 % high for haiku-scout on this machine).

### 5. Supervisor routing (`routing`)
- **Replaced:** `agent-model-guard` Agent/Task branch, `capability-graph-guard` PreToolUse verdict (+ advisor updatedInput rewrite), `subagent-budget-guard` pre-spawn check.
- **Fallback:** all three still wired; each yields only under `mod` + armed heartbeat (18-check probe).
- **Rollback:** `"routing": "classic"` or `HARNESS_MOD_ROUTING=classic`.
- **Evidence:** Run A (shadow) + Run B (mod) + pty dogfood: 8 decisions in mod mode, every one matched intended policy (pass, upward→rewrite, undeclared→rewrite, advisor→one rung up, no-EST→deny once then anti-thrash pass, Fable cap in tests); 17 classic stand-downs logged; zero unintended retries; the parent learned the real model every time.
- **Limitations:** the Fable rung and the Haiku-parent deny are unit-tested only (no Fable-main probe was affordable at 98 % five-hour usage); concurrent subagents not exercised; the Workflow lint stays classic.

### 6. Secret redaction (`secretRedaction`)
- **Replaced:** `tool-output-secret-watch.cjs` (detect-only, after the fact).
- **Fallback:** the classic watch still wired; alerts again the moment the Mod stops arming.
- **Rollback:** `"secretRedaction": "classic"`.
- **Evidence:** two headless sessions with fake Anthropic + Stripe shapes in a `cat` result: the model received `<REDACTED:anthropic:73>` / `<REDACTED:stripe-live:40>`; transcript 0 raw values; adapter event log 0 raw values (after the `text`-field leak was closed); classic watch stood down; patterns are the harness's single source (drift test).
- **Limitations:** vendor-prefixed shapes only (by design); `MessageDisplay` (model text) stays classic detect-only.

### 7. Read cache (`readCache`)
- **Replaced:** nothing classic (new).
- **Rollback:** `"readCache": "classic"`.
- **Evidence:** 3rd exact Read served in three sessions (~61 tok each, context note attached); Edit→Read invalidation observed (the post-edit Read returned the new content); `wc -l` counted as observation #4 of the file.
- **Limitations:** exact identical calls only; savings small per hit by design (serve-after 3).

## INTERFACE PREPARED / SHADOW READY (other repos)

| Item | Repo | State | Evidence |
|---|---|---|---|
| CostClaw shared grain + live helpers | costclaw `packages/engine/src/{targets,live}.ts` | INTERFACE PREPARED (merged into the engine; 316 tests, typecheck clean; drift test vs the harness copy) | `npm test` 24 files / 316 passed |
| LegCli runtime tap | leg `src/taps/mod.mjs`, `docs/runtime-tap.md` | INTERFACE PREPARED (11 tests; one-line wiring in attach.mjs documented, not applied: file owned by another live session) | `node --test test/taps-mod.test.mjs` 11/11, eslint clean |
| Handoff bundle from events | context-handoff-bundle `from_events.py` | INTERFACE PREPARED (module CLI; 3 new tests; cli.py wiring documented, not applied: file dirty from another sprint) | bundle written from Run B events; `pytest` green |
| Discovery Loop runtime ingest | discovery-loop `runtime_ingest.py` | SHADOW RUNNING as observations (dry-run over real events: 1 disagreement, 3 cache interventions, 3 routing prediction errors) | 3 tests green |
| Agnostic-AI capability negotiation | agnostic-ai `targets.json supports`, `capabilitiesOf/requires`, README table | MOD DEFAULT for the declaration (behaviour change only where a porter calls `requires`) | reg-capabilities 5/5; suite green |
| offlocal pure policy entry | offlocalai-mcp `src/policy-core.ts` (`exports ./policy`), `docs/state-json-contract.md` | INTERFACE PREPARED | 293 tests, build emits `dist/policy-core.js` |
| DashClaw Mod transport | DashClaw `docs/mod-transport.md` | INTERFACE PREPARED (tokens + protocol documented; pure re-export boundary NOT built) | — |
| prodguard (production intent + environment + policy) | rnd `prototypes/prodguard` + `evidence/shadow-compare.mjs` | SHADOW READY (replays real sessions through the pure core; no enforcement) | 21/21 core tests; replay over 2 sessions |
| Jev / `$.runtime.judge()` | rnd adapter + `experiments/jev` | LAB ONLY as a signal (Jev 32/36 @238 ms; stub 35/36) | `summary-jev.json` |

## WAIT FOR API
`prompt.section` / `prompt.context` / `skill.prompt` / `attribution.text` / `classic.*` from the user tier (withheld by sec-default on this machine); `turn.step` model rewrite inside a turn (effect unverified); `session.compact` message rewriting; panes as primary UI.

## DO NOT PROMOTE (this sprint, by rule)
Automatic production approvals; destructive command authorization; purchases; Jev-backed security policy; automatic Discovery Loop promotion; self-modifying harness policy; automatic durable memory promotion; broad tool-result virtualization; deterministic transcript replay claims; automatic deployment.
