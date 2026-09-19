# DOGFOOD — Phase 18: the prototypes run together, on a real session

Session 2026-09-16 20:52–20:57 (Sonnet 5 main loop, 150×45 pty, `--debug`), five plugins in chain order:
`xray` → `claude-runtime` (adapter) → `supervisor` → `costclaw-live` → `prodguard`. Scripted scenario via
`tools/pty_drive.py`; screen snapshots in `snapshot/2.1.273/payloads/dogfood-all-screen-snapshots.txt`
(60 snapshots); engine debug log in `~/.claude/debug/` for session `5138a38e…`. 2,308 events observed by the
X-RAY, 0 hook errors across all five plugins, $0.56 spent.

## What was exercised and what happened

| Step | Intended path | Observed |
|---|---|---|
| Read the same fixture three times (separate turns) | CostClaw LIVE serves the 4th read from cache | **Divergence:** the model chose `Bash wc -l <file>` instead of `Read`, three times; the interceptor keys on `Read` and never fired. CostClaw LIVE still flagged `tool loop active` and `repeated reads 2`, efficiency 100 → 74. (In the builder's headless runs with `Read`, the 4th and 5th reads were served from cache; see `prototypes/costclaw-live/evidence/`.) |
| Spawn `haiku-scout` asking for `opus` | supervisor rewrites to haiku, reserves, settles | **Confirmed:** engine log `agent.spawn haiku-scout: model opus -> haiku by a hook`; reasons `[upward-edge-not-in-graph, downgraded-to-highest-child-rung]`; ledger `declared=21,099 reserved=19,099 measured=22,889 · median(haiku-scout)=20,994 (n=6)`; HUD `1 spawns · 1 rewritten · reserved 19.1k / charged 22.9k`; the subagent replied PONG; the parent reported "requested model was opus" (it never learns it was rewritten unless told). |
| `git push --force origin main` | prodguard blocks (`vcs_dangerous`) | **Not reached:** the model refused on its own ("hard stop … say 'yes, force push'"). The block path was proven in the builder's headless run (five denies "resolved by a hooks module"). Lesson R20 in practice: the model's refusal is not the boundary; the hook is, and it was not needed this time. |
| `git status` under the demo rule "every git action against production is reviewed" | `$.ui.ask` dialog, answer Contain | **Confirmed:** dialog `1. Allow once / 2. Deny / 3. Contain (dry-run)` held the call **33.4 s** until `3` was keyed; `⇄ CONTAINED → echo "[contained by prodguard] git status"`; `tool.check` on the rewritten command → allow; the model received the echo. **Divergence:** the model reported "Command was blocked by a hook… unexpected for a read-only command" — containment must attach a `context[]` explanation so the model knows it was contained, not blocked. |
| `/supervisor`, `/costclaw`, `/prodguard`, `/xray status` | each prints its state | **Confirmed:** routing log with reasons and the per-type median; findings; context + 4 rules + `totals: allow=3 block=0 asked=1 contained=1`; X-RAY `2265 events · 0 errors · SUBAGENTS: ae8a3afe haiku-scout calls=1`. |
| Middleware ordering | outer to inner as loaded | **Confirmed** by `next.trace` on every call: `Claude → [xray] → claude-runtime/user → supervisor/user → costclaw-live/user → prodguard/user → engine`; prodguard's 33,380 ms on the contained call is visible as its own link. |
| The adapter's noun as an event | X-RAY sees `runtime.emit` | **Confirmed:** X-RAY reported `unknown=1` — the one event outside its table was the adapter's `runtime.emit`. A plugin noun is a first-class event to a wildcard observer. |

## Findings that change the architecture
1. **Intercept by target, not by tool.** A "repeated read" is `Read`, `Bash cat/wc/head`, `Grep` on the same path; costclaw-live's cache must key on the resolved target (costclaw's `targetFor` already does; port that part).
2. **Every rewrite must explain itself to the model.** The supervisor's model rewrite and prodguard's containment both worked silently; the model then reasoned from a false belief ("requested opus", "blocked"). Attach a one-line `context[]` on the result (CONFIRMED path) whenever a hook changes what the model asked for.
3. **Classic and function guards cannot both be armed for the same decision.** The supervisor needed `CAPABILITY_GRAPH_GUARD=off` because the classic PreToolUse guard denies before `agent.spawn` exists; costclaw-live needed `BATCH_GUARD_LIMIT`/`REPEAT_GUARD_OFF` for its probe shape. Migration is per guard with a mode flag (roadmap "PREPARE INTERFACES").
4. **Per-agent tool caps must exempt `SubagentHandback`** (denying it produced four retries of the exit tool).
5. **`$.ui.ask` is a `tool.call` of `AskUserQuestion`**: it shows up in the X-RAY and in `tool.check`, it rejects headless with "no tool named AskUserQuestion", and it can hold a call as long as the human takes (33 s here, 28 s in MATRIX).
6. **A hooks module may import sibling files** (`policy-core.ts` with zero `$` references, verified by the validator's transitive `$` audit) — "one module per plugin" limits `hooks.json.modules`, not the import graph. This makes "policy independent of the hook glue" a machine-checkable property.
7. **Cost cross-check drifts**: costclaw-live's rate-card cost ran 35–40 % under the engine's own `cost.usd` (ours $0.34 vs engine $0.56) — the ported rate card or the cache-write accounting differs from the engine's ledger; use `$.session.usage().cost` as truth and the rate card only for attribution.
8. X-RAY formatting: `percentUsed` can be a float (`14.000000000000002%`); rounded now.

## What did not get exercised (still EXPERIMENTAL)
`tool.check {decision:'deny'}` as the *first* word (prodguard's `tool.call` deny always answered first); `agent.spawn {deny}` from a Haiku parent (Haiku cannot dispatch Agent); concurrent subagents; `$.store` read back in a later session (the supervisor's ledger *did* carry across its four headless sessions — `reservedFrom: "learned n=4"` — so `$.store` persistence is CONFIRMED by that evidence); panes at ≥144 columns (all three used the AbovePrompt band and toasts by design); `turn.step` model rewrite effect.

## Verdict
Three prototypes plus the adapter ran together for five turns with zero hook failures, correct middleware
order, one subagent routed and priced, one command contained through a human dialog, and live cost/usage on
screen throughout. The two divergences (tool-choice blindness, silent rewrites) are fixable in the
prototypes and are recorded in the roadmap; neither is an API limitation.
