# PHASE2_DOGFOOD — the real harness with the Mod layer, measured

All runs 2026-09-16 on Claude Code 2.1.273 with the INSTALLED plugins (`~/.claude/mods`, no
`--plugin-dir`), the full classic hook chain (49 entries) still wired. Evidence files:
`~/.claude/mods/state/{sessions,shadow,events}/`, `~/.claude/logs/mods-mode.log`,
`snapshot/2.1.273/payloads/phase2-dogfood-screens.txt` (pty screens, 150×45).

## Runs

| # | Session | Mode | Main | What was exercised | Result |
|---|---|---|---|---|---|
| P1 | e484baaf | `--plugin-dir` regression | Sonnet | result replacement + context, spawn rewrite, agentId usage, `$.session.usage`, `$.store`, trace | all confirmed; API unchanged (d.ts identical) |
| I1 | 2ddea4fd | installed skeleton | Haiku | load order, heartbeat under the classic session_id | claude-runtime env 2, harness-mods env 3; heartbeat written |
| S1 | 98422ed6 | readCache+redaction `mod` (env) | Haiku | Read×3, `wc -l`, `cat` of a fixture with fake key shapes | read #3 served (~61 tok); model saw `<REDACTED:…>`; **leak found**: raw value in the adapter event log via `text`; classic watch alerted beneath |
| S2 | 95f81dd2 | same, after fixes | Haiku | same | 0 raw values in event log and transcript, 3 markers; classic watch stood down (3 log lines); canary OK |
| A | 5484030e | routing `shadow_mod` | Sonnet | 4 spawns (haiku ok, opus upward, model-less, advisor haiku) | classic denied 2 before `agent.spawn` fired (classic-only rows); classic rewrote advisor→opus; Mod agreed on the two it saw; 2 settles measured |
| B | d35ed493 | routing `mod` (env) | Sonnet | 5 spawns incl. no-EST + retry | pass · opus→haiku rewrite · undeclared→haiku · advisor haiku→opus · deny then anti-thrash pass; parent reported the real model with reason codes each time; classic stood down 17×; 5 settles |
| D | (pty) | all five `mod` (config) | Sonnet, interactive | Read×3 → serve; `wc`; Edit → Read (fresh content); spawn opus→haiku with explanation; `/mods`; `/mods ledger`; band + statusline badge | band `MODS ✓ …` above the prompt; statusline `MOD OK rou:M ctx:M sec:M sub:M rea:M`; `/mods` canary OK, bus 84, tool calls 8, hook errors 0; priors haiku-scout n=6 median 17,192, advisor n=2 18,039; the `cat` fixture turn did not run: the five-hour limit hit 100 % mid-run |

## Captures (the brief's list)

| Capture | Value |
|---|---|
| Event count | 24 (P1) · 29 (S2) · 84 (D) bus events per session; 55 shadow rows across 6 sessions |
| Hook failures | 0 in every heartbeat (`status.hookErrors`) |
| Latency | routing decision median 6 ms (n=8, Mod side, includes the spawn wait); classic PreToolUse chain median 1,099 ms per Bash call (§21 of the capability map) |
| Classic decision vs Mod decision | routing: 14 keys, 2 paired (both "disagreements" are join artefacts of shadow mode: the classic side rewrote the advisor input before the Mod saw it; identical prompts collided before the key included the model), 6 classic-only (denied beneath the event), 6 mod-only (mod mode, classic stood down) |
| Rewrites | 4 model rewrites (opus→haiku ×2, undeclared→haiku, advisor haiku→opus), 3 cache serves, 1 redaction (4 hits, 2 kinds) |
| Retry count | 1 by design (no-EST deny → anti-thrash pass); 0 unintended |
| Resolved model | always reported by the parent after the rewrite (`claude-haiku-4-5-20251001`, `claude-opus-5[1m]`) |
| Tool-result mutation | redaction ×1 session (4 values), cache serve ×3, explanation context on 5 results |
| Saved work | ~61 tokens per served Read (small by design: serve-after 3); the routing retry pathology (714 overrides / 5–7× retries in the classic log) did not appear |
| Subagent estimate error | −1,506 … −2,301 tokens vs declared (declared cost ~10 % high); learned median haiku-scout 17,192 (n=6) |
| Session cost | P1 $0.209 · D $0.39 (engine `cost.usd`); the rate card stays attribution-only |
| Context explanations | every rewrite/serve/redaction carried one; the model quoted them ("requested opus, ran on haiku", "served from cache", "secret redacted") |
| Canary state | OK in every session after S1's fix; the liveness hook spoke once, correctly, in the coordinating session that predates the install |

## Where classic and Mod disagreed

1. **Shadow mode cannot see what classic denies first.** 6 of 14 routing keys were classic-only: the
   classic PreToolUse deny fires before `agent.spawn` exists. This is the R&D finding 3 measured again
   and is exactly why the migration is per guard with a stand-down, not "both armed".
2. **Advisor rewrite ordering.** In shadow mode the classic `updatedInput` (advisor→opus) reaches the Mod
   as the *requested* model, so the Mod's "pass" pairs with classic "rewrite". In mod mode the Mod does the
   same rewrite itself (Run B: haiku→opus, reason `advisor-upward-edge`).
3. **Deny vs rewrite is a mechanism difference, not a policy one.** Every classic deny for an upward/peer
   edge became a Mod rewrite onto the same graph; the parent got a working subagent plus the reason.

## What failed and was fixed during the dogfood

- Raw secret value in the adapter event log through the replaced result's `text` field (S1) → the Mod
  now returns a fresh `{result, context}`; verified 0 in S2 and transcript.
- Classic secret watch alerting beneath a redaction (S1) → stand-down seam added; verified S2.
- Middleware-order check read the adapter's trace wrongly (the adapter is not in its own trace) → judge
  fixed; canary green.
- Shadow join key collided for identical prompts → key includes the requested model on both sides.
- Band abbreviation bug (`routi:M contextNconte:M`) seen on the pty screens → fixed to `rou/ctx/sec/sub/rea`.
- Haiku refused fixtures named `*secret*` and any prompt echoing a key shape (R20 twice) → fixtures are
  named neutrally and read through `cat`.

## What was not exercised

Fable-parent routing (five-hour usage at 98–100 % during the sprint), a real 80 % context crossing, a
production-shaped command through prodguard in the harness (prodguard stays a replay-only shadow), the
`$.ui.ask` containment dialog in the harness (prototype-only), concurrent subagents.
