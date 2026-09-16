// budget.mjs — measured subagent accounting. Pure state transitions over a ledger object.
//
// The classic guard DECLARED (# EST:) and could only log allow/deny; the runtime now gives per-agent
// usage on every turn.step / turn.complete (agentId), so each spawn is priced before it runs
// (reserved, from the learned prior) and settled after (measured), and the prior for that agent type
// refits itself as a running median kept in $.store across sessions. Constants are inherited from
// subagent-budget-guard (LEAN 17k / FULL 60k / cache reads weighted 0.1).

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

export function priorFor(ledger, type) {
  const p = ledger.priors[type];
  if (p && p.median > 0) return { tokens: p.median, source: "learned n=" + p.samples.length };
  return { tokens: isLean(type) ? LEAN_PRIOR : FULL_PRIOR, source: isLean(type) ? "prior lean" : "prior full" };
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
  p.samples.push(a.measured);
  if (p.samples.length > MAX_SAMPLES) p.samples.shift();
  p.median = medianOf(p.samples);
  ledger.priors[a.type] = p;
  ledger.lastActivityMs = nowMs;
  a.predictionError = a.declared === null || a.declared === undefined ? null : a.measured - a.declared;
  a.reserveError = a.measured - a.reserved;
  a.learnedPrior = p.median;
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
  };
}
