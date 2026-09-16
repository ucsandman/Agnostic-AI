// usage.mjs — native session usage → decisions. Pure state machine.
//
// context-nudge.py fires once per crossing of 80% and re-arms when the context drops below it; it
// learns the number from a %TEMP% file the statusline writes. This is the same rule over
// $.session.usage().context.percent, which the Mod reads directly after every main-loop turn.

export const CONTEXT_THRESHOLD = 80;
export const CONTEXT_CLEAR = 92;

export function newNudgeState() { return { armed: false, fired: 0, lastPercent: null }; }

/** Feed a new usage snapshot; returns the nudge text to attach on the next prompt, or null. */
export function onUsage(state, usage) {
  const pct = usage && usage.context && typeof usage.context.percent === "number" ? Math.round(usage.context.percent) : null;
  state.lastPercent = pct;
  if (pct === null) return null;
  if (pct >= CONTEXT_THRESHOLD && !state.armed) {
    state.armed = true;
    state.fired++;
    const verb = pct >= CONTEXT_CLEAR ? "use /clear if the next task is unrelated, /compact if continuing" : "if the next task is unrelated to this thread use /clear; if continuing the same task use /compact";
    return "[context-budget] This session is at ~" + pct + "% of the context window (" + fmt(usage.context.tokens) + " of " + fmt(usage.context.window) + "). Tell Wes once, briefly: " + verb + ". Long contexts are billed every turn even when cached.";
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
