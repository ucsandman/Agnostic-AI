// usage.mjs — native session usage → decisions. Pure state machine.
//
// context-nudge.py fires once per crossing of 80% and re-arms when the context drops below it; it
// learns the number from a %TEMP% file the statusline writes. This is the same rule over
// $.session.usage().context, which the Mod reads directly after every main-loop turn.
//
// The ceiling is the AUTO-COMPACT window when one is set, not the model's raw window (2026-09-18):
// with `autoCompactWindow` 500k on a 1M model, 80% of the window (800k) is a point the session can
// never reach, so the nudge never fired and auto-compaction — a summarisation request over the
// whole history — always ran before Wes had the cheaper choice (`/clear` is free; arXiv:2609.20804
// stages the cheap action before the expensive one). 80% of 500k is where the choice still exists.

export const CONTEXT_THRESHOLD = 80;
export const CONTEXT_CLEAR = 92;

export function newNudgeState() { return { armed: false, fired: 0, lastPercent: null, ceiling: null }; }

/** The token count the nudge measures against: the smaller of the window and the auto-compact window. */
function ceilingOf(usage, opts) {
  const window = usage && usage.context && typeof usage.context.window === "number" && usage.context.window > 0 ? usage.context.window : null;
  const acw = opts && typeof opts.autoCompactWindow === "number" && opts.autoCompactWindow > 0 ? opts.autoCompactWindow : null;
  if (!window) return null; // no reported window → no ceiling; percentOf falls back to the native percent
  return acw ? Math.min(window, acw) : window;
}

/** Percent of the effective ceiling, or the native percent when tokens are not reported. */
function percentOf(usage, opts) {
  const ctx = usage && usage.context;
  if (!ctx) return null;
  const ceiling = ceilingOf(usage, opts);
  if (typeof ctx.tokens === "number" && ceiling) return Math.round((ctx.tokens / ceiling) * 100);
  return typeof ctx.percent === "number" ? Math.round(ctx.percent) : null;
}

/** Feed a new usage snapshot; returns the nudge text to attach on the next prompt, or null. */
export function onUsage(state, usage, opts) {
  const pct = percentOf(usage, opts);
  state.lastPercent = pct;
  state.ceiling = ceilingOf(usage, opts);
  if (pct === null) return null;
  if (pct >= CONTEXT_THRESHOLD && !state.armed) {
    state.armed = true;
    state.fired++;
    const acw = opts && typeof opts.autoCompactWindow === "number" && opts.autoCompactWindow > 0 ? opts.autoCompactWindow : null;
    const window = usage.context.window;
    const compactsAt = !!(acw && window && acw < window && typeof usage.context.tokens === "number");
    const of = compactsAt ? "the auto-compact window (compaction runs at " + fmt(acw) + " of a " + fmt(window) + " window)" : "the context window";
    const verb = pct >= CONTEXT_CLEAR ? "use /clear if the next task is unrelated, /compact if continuing" : "if the next task is unrelated to this thread use /clear; if continuing the same task use /compact";
    return "[context-budget] This session is at ~" + pct + "% of " + of + " (" + fmt(usage.context.tokens) + " of " + fmt(state.ceiling) + "). Tell Wes once, briefly: " + verb + ". /clear is free; auto-compaction is a summarisation request over the whole history, and long contexts are billed every turn even when cached.";
  }
  if (pct < CONTEXT_THRESHOLD && state.armed) state.armed = false;
  return null;
}

export function rateLimit(usage, kind) {
  const r = usage && Array.isArray(usage.rateLimits) ? usage.rateLimits.find((x) => x.kind === kind) : null;
  return r ? Math.round(r.percentUsed) : null;
}

export function costUsd(usage) {
  return usage && usage.cost && typeof usage.cost.usd === "number" ? usage.cost.usd : null;
}

/** One-line summary for the band / status file. */
export function summary(usage) {
  if (!usage) return "usage n/a";
  const ctx = usage.context && typeof usage.context.percent === "number" ? Math.round(usage.context.percent) + "%" : "?";
  const five = rateLimit(usage, "five_hour"), week = rateLimit(usage, "seven_day"), usd = costUsd(usage);
  return "ctx " + ctx + " · 5h " + (five === null ? "?" : five + "%") + " · 7d " + (week === null ? "?" : week + "%") + " · " + (usd === null ? "$?" : "$" + usd.toFixed(2));
}

function fmt(n) { return typeof n === "number" ? String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",") : "?"; }
