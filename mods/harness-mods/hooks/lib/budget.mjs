// budget.mjs — measured subagent accounting. Pure state transitions over a ledger object.
//
// The classic guard DECLARED (# EST:) and could only log allow/deny; the runtime now gives per-agent
// usage on every turn.step / turn.complete (agentId), so each spawn is priced before it runs
// (reserved, from the learned prior) and settled after (measured), and the prior for that agent type
// refits itself as a running median kept in $.store across sessions. Constants are inherited from
// subagent-budget-guard (LEAN 17k / FULL 60k / cache reads weighted 0.1).
//
// Two priors per type, never one (2026-09-18): OVERHEAD is what the spawn costs before its first
// tool call (the system prompt, the brief, the first model step) and is what the break-even rule in
// routing.mjs prices; TOTAL is the whole run and is what the ledger reserves. Until this split the
// learned median of the TOTAL was fed to the break-even rule as if it were overhead, so an opus-owner
// with a 2M-token history priced at ~53 tool calls to break even and was denied on first attempt.

export const LEAN_PRIOR = 17000;
export const FULL_PRIOR = 60000;
export const CACHE_DISCOUNT = 0.1;
export const MAX_SAMPLES = 20;
export const WARM_WINDOW_MS = 5 * 60 * 1000;
export const LEAN_TYPES = ["haiku-scout", "sonnet-implementer", "opus-owner", "advisor", "e2e-verifier", "explore", "plan", "statusline-setup", "security-reviewer", "fork"];

export function isLean(type) { return LEAN_TYPES.indexOf(String(type || "").toLowerCase()) >= 0; }

export function medianOf(arr) {
  const s = (arr || []).slice().sort((a, b) => a - b);
  const n = s.length;
  if (!n) return 0;
  return n % 2 ? s[(n - 1) / 2] : Math.round((s[n / 2 - 1] + s[n / 2]) / 2);
}

export function weigh(u) {
  if (!u) return 0;
  return (u.input_tokens || 0) + (u.output_tokens || 0) + (u.cache_creation_input_tokens || 0) + Math.round(CACHE_DISCOUNT * (u.cache_read_input_tokens || 0));
}

export function newLedger() {
  return { agents: {}, order: [], priors: {}, lastActivityMs: 0, totals: { spawns: 0, rewrites: 0, denies: 0, passes: 0, fable: 0 } };
}

/**
 * `tokens`/`source`: the spawn OVERHEAD prior (tokens before the first tool call) for the break-even
 * rule; `total`/`totalSource`: the whole-run prior the ledger reserves. A stored prior that only has
 * total samples (pre-split sessions) prices overhead from the classic constant, never from the total.
 */
export function priorFor(ledger, type) {
  const p = ledger.priors[type];
  const classic = isLean(type) ? LEAN_PRIOR : FULL_PRIOR;
  const classicSource = isLean(type) ? "prior lean" : "prior full";
  const hasOverhead = !!(p && p.overhead > 0 && Array.isArray(p.overheads));
  const hasTotal = !!(p && p.median > 0 && Array.isArray(p.samples));
  return {
    tokens: hasOverhead ? p.overhead : classic,
    source: hasOverhead ? "learned overhead n=" + p.overheads.length : classicSource,
    total: hasTotal ? p.median : classic,
    totalSource: hasTotal ? "learned total n=" + p.samples.length : classicSource,
  };
}

export function isWarm(ledger, nowMs) {
  return ledger.lastActivityMs > 0 && nowMs - ledger.lastActivityMs < WARM_WINDOW_MS;
}

/** Open a ledger row after the spawn resolved. */
export function open(ledger, row, nowMs) {
  ledger.agents[row.agentId] = {
    steps: 0, turns: 0, tokens: 0, measured: 0, durationMs: 0, calls: 0, settled: false, reason: "", startedMs: nowMs, ...row,
  };
  ledger.order.push(row.agentId);
  ledger.lastActivityMs = nowMs;
  return ledger.agents[row.agentId];
}

export function step(ledger, agentId, usage, nowMs) {
  const a = ledger.agents[agentId];
  if (!a) return null;
  a.steps++;
  a.tokens += weigh(usage);
  if (!a.calls) a.overhead = a.tokens; // everything spent before the first tool call is overhead
  ledger.lastActivityMs = nowMs;
  return a;
}

/** Settle on the subagent's turn.complete; refit the prior. Returns the settled row with its prediction error. */
export function settle(ledger, agentId, ev, nowMs) {
  const a = ledger.agents[agentId];
  if (!a) return null;
  a.turns++;
  a.measured += weigh(ev.usage);
  a.durationMs += ev.durationMs || 0;
  a.settled = true;
  a.reason = ev.reason || "";
  a.endedMs = nowMs;
  const p = ledger.priors[a.type] || { samples: [], median: 0 };
  if (!Array.isArray(p.overheads)) { p.overheads = []; p.overhead = 0; } // pre-split stored prior
  p.samples.push(a.measured);
  if (p.samples.length > MAX_SAMPLES) p.samples.shift();
  p.median = medianOf(p.samples);
  // A run that never called a tool is all overhead; one without a step row (no ModelStep seen) has no overhead sample.
  const overhead = a.overhead > 0 ? a.overhead : a.calls === 0 && a.steps === 0 ? 0 : a.measured;
  if (overhead > 0) {
    p.overheads.push(overhead);
    if (p.overheads.length > MAX_SAMPLES) p.overheads.shift();
    p.overhead = medianOf(p.overheads);
  }
  ledger.priors[a.type] = p;
  ledger.lastActivityMs = nowMs;
  a.predictionError = a.declared === null || a.declared === undefined ? null : a.measured - a.declared;
  a.reserveError = a.measured - a.reserved;
  a.learnedPrior = p.median;
  a.learnedOverhead = p.overhead;
  return a;
}

export function liveAgents(ledger) {
  return ledger.order.map((id) => ledger.agents[id]).filter((a) => a && !a.settled);
}

export function totals(ledger) {
  let reserved = 0, charged = 0;
  for (const id of ledger.order) { const a = ledger.agents[id]; if (!a) continue; reserved += a.reserved || 0; charged += a.settled ? a.measured : a.reserved || 0; }
  return { reserved, charged };
}

/** A row in the calibration log's vocabulary (subagent-budget-guard's .subagent-budget-log.jsonl). calibrate.cjs filters on decision allow|deny and ignores this. */
export function calibrationRow(sessionId, a, nowIso) {
  return {
    ts: nowIso, session: sessionId, decision: "measured", source: "harness-mods",
    type: a.type, model: a.model, requested: a.requested || null, rewritten: !!a.rewritten, agentId: a.agentId,
    est: a.est || null, declared: a.declared, reserved: a.reserved, reservedFrom: a.reservedFrom,
    measured: a.measured, predictionError: a.predictionError, reserveError: a.reserveError,
    calls: a.calls, steps: a.steps, durationMs: a.durationMs, reason: a.reason, learnedPrior: a.learnedPrior,
    overhead: a.overhead || 0, learnedOverhead: a.learnedOverhead || 0,
  };
}
