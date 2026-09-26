// usage.mjs — native session usage ($.session.usage()) → the band's one-line summary.
// The 80% context-budget nudge that used to live here was removed on 2026-09-26 (Wes).

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
