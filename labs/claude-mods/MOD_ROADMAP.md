# MOD_ROADMAP — what to do about function hooks, and why

Assumes Anthropic may change or gate the API at any time (R1, R2). Every "DO NOW" item is reversible and
lives behind `--plugin-dir` or a feature flag; nothing below rewrites a production project around the API.

## Prototype outcomes that shaped this roadmap (Phase 17/18, see `DOGFOOD.md` and `prototypes/*/README.md`)
- `supervisor`: routing rewrites in both directions proven (`opus -> haiku`, `haiku -> opus` for advisor), budget learns across sessions (`reservedFrom: learned n=4`), per-agent call cap denies; needs the classic capability-graph guard disarmed to run, and must exempt `SubagentHandback`.
- `costclaw-live`: cache interception proven headless (4th/5th `Read` served, ~5,276 tokens saved on a 10 KB file), HUD live; misses reads done through `Bash wc/cat` (intercept by target next); rate-card cost under-reports the engine's ledger by ~35 %.
- `prodguard`: five production-shaped commands denied before execution headless (1.7–8 ms vs 1,099 ms classic median; classic chain never ran), `$.ui.ask` approval with Contain rewrite proven interactively; policy core is a separate file with zero `$` references and 21 passing pure tests; containment must explain itself to the model via `context[]`.

## DO NOW

| Item | Why now | Evidence |
|---|---|---|
| **Fix the two dogfood divergences in the prototypes** (target-keyed interception; `context[]` on every rewrite/containment; exempt `SubagentHandback`) | cheap, and they are the difference between "clever" and "trusted" | `DOGFOOD.md` findings 1, 2, 4 |
| **Keep the adapter as the only raw-API surface** (`adapter/claude-runtime`) and make every new Mod a consumer of `runtime.emit` / `$.runtime.*` | A single file absorbs API churn; consumers proved to work without knowing Anthropic's events | echo consumer received 16 normalised events; noun added via `engine.create` |
| **Use the X-RAY + BLACK BOX during real sessions** (`lab/xray`) | The `next.trace` pipeline and the timeline are the only view of what plugins actually do; needed before trusting any guard migration | 1,240 events / session, ordering lesson (recorder outermost) |
| **Run the three prototypes on real work for a week, in observe mode** (`supervisor`, `costclaw-live`, `prodguard`) alongside the production harness, logging only | The rules exist; what is missing is measured agreement between the Mod's verdicts and the classic guards' | `next.trace` + JSONL audit lines make the comparison mechanical |
| **Add a Mods leg to `guard-canary.ps1` before any classic guard is retired** | A guard whose failure mode is silence reads as clean; the canary is the only L1 instrument | archaeology A #36 |
| **Make the four routing guards' logic a Mod that rewrites instead of denies, measured not declared** (`prototypes/supervisor` → harness, behind a flag) | Largest single harness win; deletes the retry pathology (714 overrides, 5–7× retries) | `agent.spawn` rewrite + per-agent usage CONFIRMED |
| **Detection → redaction for secrets** (port `secret-guard` patterns to a `tool.call` result replacer) | Both watchers say they cannot redact; the 2026-09-06 incident | result replacement CONFIRMED |
| **`$.session.usage()` footer replacing the `%TEMP%` statusline IPC** (only the read side; keep `statusline.ps1` until the managed-settings wiring is understood) | Deletes context-nudge, session-count, skill-telemetry's re-derivation | usage CONFIRMED in 0.1–0.4 ms |
| **Jev experiment the day the key exists** (`creds mint typesafe --open`; `python experiments/jev/run_judge.py jev`) | Everything else is ready; cost capped in code | states + questions frozen |
| **Agnostic AI: add `supports` to `targets.json` + README + `universal-adapter.cjs`** (declaration only, no behaviour change yet) | Mods create the first real capability asymmetry; the porter must be able to say so | archaeology A §3b table |

## PREPARE INTERFACES NOW (no Mods dependency yet; makes the switch a one-file change)

| Item | Interface to prepare | Why |
|---|---|---|
| **LegCli** | a sixth tap `src/taps/mod.mjs` that consumes the adapter's JSONL / board API through the existing `recordUsage/markLimited/updateSession/appendEvent`; a `--plugin-dir` argv option in `adapters/claude.mjs`; a handoff trigger at `warning && turn boundary` | `$.turn.abort` and bundle-at-boundary are proven; Leg keeps working without them |
| **context-handoff-bundle** | accept structured anchors (path + line range + hash) from a machine writer, bypassing `parse_anchor`; a `--from-events <jsonl>` save path | 12 of 15 fields fill from events; the CLI stays the only writer of bundle files |
| **CostClaw** | export `targetFor`/`commandTarget`; publish `packages/engine` as a pure module a Mod can copy from; keep the JSONL reader as the portable fallback | one private function blocks the live adapter |
| **DashClaw** | extract the pure subset (`evidence.ts`, `risk.ts`, `containment.ts`, 15 evaluators, packs) into an importable, dependency-free package; add a `client_capabilities: {mod: true}` envelope value; define the "park approval, wake session" protocol | the Python hook and the Mod must not run together; the wire schema already carries `client_capabilities` |
| **offlocalai-mcp** | export `evaluatePolicy`/`defaultDecision`/`resolve*` as a library entry; document `.offlocal/state.json` as a contract a Mod may read | the only missing half is shell-command awareness |
| **markdown-agent-memory** | a documented RAM-tier candidate line format for machine writers (`[observed <date>]` with a verbatim source), and a "promote" command that takes a token | keeps the editorial policy; gives the runtime a door |
| **declick** | port `output.mjs` `capData` to a zero-Node module (two lines), expose `policy.mjs` decisions as a function | the enforcement arm needs only those two |
| **giti** | a `giti export --json` of hotspots + couplings per repo (one git call) | a Mod reads it at session start |
| **Discovery Loop** | an `observations/` ingest path that accepts `_development_entry` rows from a JSONL, and a "runtime" problem plugin skeleton whose solver is `claude -p --plugin-dir` | observations now, confirmations later |
| **harness** | per-guard feature flags (`GUARD_<NAME>_MODE=classic|mod|both`) and the canary's Mods leg | staged migration without double enforcement |

## WAIT FOR API STABILITY

| Item | What must stabilise first |
|---|---|
| Retiring any classic guard | the gate (`tengu_plugin_hooks_modules`) graduating from GrowthBook default-false; one release cycle with no breaking change to `claude-code.d.ts` |
| System-prompt and context-block rewriting (`prompt.section/context`), skill prompt rewriting | withheld on managed-settings machines; behaviour on org policy unknown |
| `turn.step` chunk rewriting / model rewriting for routing inside a turn | rewrite accepted but effect unverified; needs a build whose debug log confirms the request model |
| `session.compact` message rewriting (as opposed to calling compact) | declared; a wrong `handle` mapping could corrupt the transcript |
| Panes as the primary UI (approvals, replay scrubber) | 144-column rule; `Client` surface modules; desktop/mobile surfaces untested |
| `$.mcp.call`-based enforcement (mole toolkit, trifecta) | moves a permission boundary; needs the gatekeeper plugin and an audit pane first |
| Publishing any Mod to a marketplace | the `sec-default`/`allowedMcpServers` interactions and `plugin.register` refusal semantics for third-party machines |

## DO NOT BUILD

| Item | Why not |
|---|---|
| A second generic event bus, dashboard or "observability platform" | the adapter + X-RAY + the products' own panes cover it; the value is in the policy corpus, not the plumbing |
| Deterministic model replay / "restore to turn N" | not possible: no seed, no engine-level transcript restore for plugins (capsule/rewind analysis) |
| Automatic memory promotion or self-rewriting production behaviour | the recurrence gate is prompt-injection defence; Discovery Loop's four gates exist for the same reason |
| A Mod that reads `.env`/vault or performs external sends | trifecta and secrets rules; use `creds` through `$.process.run`, keep sends behind hard stops |
| Porting classic-hook generators (AgentLens `hooks-gen`, DashClaw scope sync) | those events are unreachable for user plugins here; the replacement is a different artefact |
| Rebuilding tokentrail/claude-code-audit/2-part-memory/soulcraft as products | superseded or merged; take the idea (documented) not the repo |
| Anything that needs the permission dialog drawn by a plugin | not possible; use `tool.check` + `$.ui.ask` + the two-phase consent token |
