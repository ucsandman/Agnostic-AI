# MOD_INVENTIONS — the unfair advantage (Phase 15) and things not yet thought of (Phase 16)

Everything below is ranked against the real API (`MOD_CAPABILITY_MAP.md`). Where an idea needs a
capability marked EXPERIMENTAL or NOT POSSIBLE, it says so. No numeric scores; the ranking is stated in
prose where it changes a decision.

## Phase 15 — technical compounding advantages, in the order they compound

The question was: what can be built now, from existing code, that someone starting after Mods go
mainstream would find hard? The honest filter: an advantage counts only if it is **code + measured
constants + incident history**, not an idea. Ideas are free; calibrated thresholds and failure logs are not.

1. **A tuned policy corpus with provenance.** 49 harness guards, each with the dated incident that created
   it; DashClaw's 20 evaluators and 20 policy packs whose comments record why `rm -rf node_modules` must not
   grade like `rm -rf /c/Users`, why an unanchored `/format/` produced 1,759 false approvals in a week;
   costclaw's share gates that exist because raw counts flagged 52 % of real sessions; `secret-guard`'s
   placeholder allowlist tuned over months. A newcomer gets the API; they do not get eight months of
   false-positive tuning. Under Mods the enforcement point improves and the corpus ports as data.
2. **The enforcement point plus the decision layer, already separated.** spendwall's `evaluatePolicies`,
   offlocal's `evaluatePolicy`, DashClaw's `evidence.ts`, declick's `policy.mjs`, agnostic-agent's
   `guards.json` are all pure functions with tests. Mods provide `tool.call`/`tool.check`; the portfolio
   provides five interchangeable deciders. Most teams will build the decider and the hook as one tangle.
3. **Cross-agent portability with a capability contract.** agnostic-ai already renders one harness into
   five hook dialects (Codex near-clone, Gemini/agy `++`-chained with last-reason-wins, Cursor) and knows the
   dearly-bought facts (Codex `trusted_hash`, Gemini has no "ask"). Adding `supports.*` makes it the only
   thing that can say "this guard is a Mod on Claude and a shim on Gemini" without lying. Mods make Claude
   Code the richest backend; a Claude-only competitor cannot make that claim at all.
4. **Ground truth for cost.** Four independent parsers of the same JSONL (tokentrail → claude-code-audit →
   costclaw; spend, calibrate, tokflow) converge on the same dedupe rule and rate card; `calibrate.cjs` has 49
   measured spawn records; the subagent break-even (~5 calls lean, ~15 general-purpose) is measured. A live
   HUD built on `turn.step` usage plus that pricing is defensible on day one; a newcomer's HUD is a guess.
5. **Handoff infrastructure that survives the session.** Leg owns the launch of four CLIs, the merge queue,
   worktrees, fixture-classified limit outcomes and a stamped resume pointer whose freshness is recomputed
   from git. The bundle format has anchors, drift and quality scoring. Mods add the missing signals; the
   machinery that acts on them exists and is exercised daily.
6. **Two receipt anchors and a compliance mapper nobody else has wired.** Ed25519 receipts (DashClaw),
   DNSSEC TXT receipts (GroundLock), calldata receipts (TreasuryClaw), and a 666-line SOC2/ISO/GDPR/NIST
   mapper that consumes exactly the verdict stream `tool.check` produces. "Prove what your agent was allowed
   to do" as a config line is a product a newcomer would need a year to assemble.
7. **Verification discipline as instruments.** `guard-canary`, `enforcement_liveness_probe`, `prove`,
   `gitradar`'s loud-error rows, `verification_contract`'s sticky FLAG, solver's independent best-response.
   Under Mods these become a continuously self-verifying policy layer (`$.clock.every` canary +
   `next.trace`). Everyone else ships a hook and assumes it fired.
8. **A memory policy that resists prompt injection by design** (recurrence gate, provenance tags, lint)
   with a runtime now able to feed it honest `[observed]` candidates and one machine-verifiable `[stated]`
   source. Most "agent memory" products will auto-promote and be poisoned.
9. **An evaluation loop with a real confirmation gate** (Discovery Loop: seeds, paired matrix, hash-bound
   promotion, human publication) into which a Mod can pour observations. The industry pattern will be
   "telemetry dashboard"; this is "telemetry → hypothesis → experiment → promotion" with the promotion
   already refusing stale hashes.
10. **The x-ray itself.** `lab/xray` and the adapter's event log are the first instruments that show the
    chain (`next.trace`) with per-link ms and outcome. Debugging a middleware stack without it is guesswork.

## Phase 16 — ten (plus) capabilities the API makes plausible

Ranked by novelty × feasibility × fit with existing code; the first five are the "holy shit" tier.

### 1. The permission-flip audit (and the reason to ship `plugin.register` gates first)
A user-tier plugin turned `ask` into `allow` in a headless session (CONFIRMED). That is a supply-chain
attack surface: any plugin a person installs can silently widen permissions. The invention is the defence,
built from the same primitive: a **first-loaded gatekeeper plugin** that hooks `plugin.register` and refuses
any later module whose scanned `uses.events` include `tool.check` or `agent.spawn` unless its provenance is
allow-listed, and hooks `tool.check` to record every plugin-authored verdict (via `next.trace`) into an audit
pane. Nobody else will ship the gate before they ship the plugins. Depends on `plugin.register` refuse
(EXPERIMENTAL: fires, refusal not exercised) and `next.trace` (CONFIRMED).

### 2. Deterministic tool-side replay of a real session
Record every `tool.call` with args and result (CONFIRMED). Replay: load the record, and on each `tool.call`
whose (tool, args) matches the next recorded call, **answer without `next`** with the recorded result.
The model re-runs; the filesystem does not. Diff the two transcripts: same tools, different decisions →
the model changed; different tools → the prompt or context changed. `agent-pit`'s player scrubs it.
Not deterministic model re-run (no seed), and that is fine: the point is regression testing *your hooks
and prompts* against a frozen world. CONFIRMED primitives only.

### 3. Self-calibrating budgets
`# EST:` declarations become measurements: reserve at `agent.spawn`, settle at the child's `turn.complete`
(usage per `agentId`), keep a running median per subagent type in `$.store`, charge the full reservation
when a child never completes (discovery-loop's rule). The guard's constants refit themselves every session.
`prototypes/supervisor` is the first cut. CONFIRMED.

### 4. Detection becomes redaction
`tool.call` result replacement (CONFIRMED) and `turn.step` text-chunk rewriting (EXPERIMENTAL: stream read
CONFIRMED, chunk rewrite declared) turn both secret watchers from "alert after the transcript has it" into
"the model never sees it". The 2026-09-06 `env | grep ANTHROPIC` incident becomes impossible rather than
loud. The regex corpus already exists.

### 5. The context-pressure autopilot
`$.session.usage()` every turn (CONFIRMED) → at 45 % of window write the day's `[observed]` candidates to
the RAM tier, verify the write, then `$.session.compact()` (EXPERIMENTAL: declared, not run) with
`instructions` naming what to keep; at the same threshold `session.compact` hooks can rewrite `messages`
(EXPERIMENTAL) so tool outputs older than N turns are trimmed before the summariser sees them. Consolidation
happens because the context filled, not because someone remembered.

### 6. Just-in-time capability injection
Hidden context on `prompt.submit` and on `tool.call` results (CONFIRMED) keyed on what just happened: a third
identical retry → "you have `$.tool.register`ed tools X"; a large single-threaded plan → "spawn"; a fragile
file edit → giti's coupling note. Replaces the session-start capability card with the right card at the
right moment. Cost: zero unless triggered.

### 7. Attention director for parallel subagents
Railbird's arbiter (pin > soft-pin > heat leader with hysteresis > multiview) over per-`agentId`
`ModelStep`/`ToolCompleted` streams (CONFIRMED), rendered in an `AbovePrompt` band (CONFIRMED) or a Pane
(needs ≥144 cols). Four subagents, one human, one pane that shows the one that matters and auto-pins the
one you asked about.

### 8. Ambient production context
`.offlocal/state.json` read once; every shell command classified; `PROJECT · production · live` in the
band; `vercel deploy --prod` needs approval before the shell starts; containment rewrites it to a dry run.
`prototypes/prodguard`. CONFIRMED.

### 9. Result normalisation for every tool
declick's `capData()` (251 lines, zero imports) on every tool result: an 8 KB ceiling that keeps key names so
the model can ask narrower, with `meta.capped` telling it how; tighten the ceiling as context fills. Fixes
the measured 5.6 % nudge-follow rate by removing the nudge. CONFIRMED primitives.

### 10. The evidence gate for behavioural rules
"A rule works iff its correction bucket stops accruing" (`correction-tracker`) and "an insight is promoted
only after it changed an action" (soulcraft) become checkable: keep a candidate in `$.store`, watch the next
N `tool.call`s for the predicted behavioural difference, offer promotion only when observed. CONFIRMED
observation; the judgment "is this the predicted behaviour" is where `runtime.judge` earns its place.

### 11. A self-verifying policy layer
`$.clock.every` fires a canary `$.tool.call` through the chain (CONFIRMED mechanisms); `next.trace` shows
which link answered; a `ui.render` badge turns "enforcement is live" into a visible state instead of a
20-hour-old JSON file. The two probes that assume their own layer might be lying become the layer's heartbeat.

### 12. Trifecta enforcement
Deny Read/Bash on paths inside a configured connector and route to `mole.aggregate` through `$.mcp.call`
(EXPERIMENTAL: declared, no prompt) so rows never enter the context; every crossing recorded in a pane with
no payload. The only mechanism found that enforces the private-data + untrusted-content + outbound rule
instead of asking an agent to remember it.

### 13. Reputation for your own subagents
Agent-Reputation-Oracle's decayed, confidence-weighted composite over `SubagentStarted/Completed` events
(CONFIRMED) in `$.store`: "sonnet-implementer: 0.81 over 30 dispatches, confidence 0.6" at session start;
`agent.offer` hides a type whose cost-per-success says drop (EXPERIMENTAL: registered, not exercised by the model).

### 14. Two-phase consent for anything irreversible a Mod does
`confirm.ts` (preview + single-use token + TTL) behind `$.ui.ask`, because the permission dialog cannot be
drawn by plugins. Every Mod that flips a verdict or writes outside `$.store` should use it. CONFIRMED primitives.

### 15. An inbox that wakes the session
`$.clock.every` polls `agent-comms`; `[URGENT]` → `$.prompt.submit()` wakes an idle session (EXPERIMENTAL:
declared) with the message as the prompt; everything else waits behind the air gate for a quiet moment and
degrades to a footer count. The heartbeat protocol finally gets an event source.

### What each of these was impossible or brittle without
Every item above previously needed one of: a subprocess per event (no state, ~50 ms floor, 1.1 s under the
real harness), a transcript tail re-read, a `%TEMP%` file as IPC, an OAuth token read off disk, a prose rule
the model could forget, or a DOM scrape. The common denominator Mods remove is **being outside the session**.
