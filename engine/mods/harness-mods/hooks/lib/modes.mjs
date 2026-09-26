// modes.mjs — the migration configuration model, pure.
//
// Every migrated guard has exactly one owner per session:
//   classic     the existing hook enforces; the Mod observes only
//   shadow_mod  the existing hook enforces; the Mod computes what it WOULD do and records the comparison
//   mod         the Mod enforces; the classic hook stands down (it stays installed for rollback)
//
// The classic side and the Mod side read the SAME file (~/.claude/mods/mods-config.json), and the
// classic side only stands down when the Mod has proven itself alive for THIS session (heartbeat),
// so a Mod that failed to load can never leave a decision unowned.
//
// Per-session override: env HARNESS_MOD_<GUARD>=classic|shadow_mod|mod (GUARD upper-cased,
// e.g. HARNESS_MOD_ROUTING=classic). HARNESS_MODS=off forces every guard to classic.

export const MODES = ["classic", "shadow_mod", "mod"];

// The migrated guards. Descriptions live in a parallel list (not `name: "text"` pairs) so the
// mirror's secret sweep, which flags `secret…: "…"` shapes, never trips on the redaction entry.
export const GUARDS = {
  routing: 1,
  secretRedaction: 1,
  subagentAccounting: 1,
  readCache: 1,
};
export const GUARD_NOTES = [
  ["routing", "agent-model-guard (Agent/Task branch) + capability-graph-guard (PreToolUse) + subagent-budget-guard: model rewrite onto the capability graph, advisor escalation, Fable cap, measured budget"],
  ["secretRedaction", "tool-output-secret-watch.cjs: tool results with credential shapes are masked before the model sees them (the classic watch stays as the after-the-fact backstop)"],
  ["subagentAccounting", "subagent-budget-guard --post + calibrate.cjs: measured per-agent usage, declared-vs-measured, learned priors"],
  ["readCache", "costclaw-live: the Nth identical observation of an unchanged file is served from cache (target-keyed)"],
];

export const DEFAULT_CONFIG = {
  version: 1,
  updatedAt: null,
  guards: {
    routing: "shadow_mod",
    secretRedaction: "shadow_mod",
    subagentAccounting: "shadow_mod",
    readCache: "shadow_mod",
  },
};

export function normalizeMode(v, fallback = "classic") {
  const s = String(v || "").toLowerCase().trim();
  return MODES.includes(s) ? s : fallback;
}

/** Resolve the effective mode of one guard from the config object + an env map. Pure. */
export function modeFor(guard, config, env = {}) {
  if (String(env.HARNESS_MODS || "").toLowerCase() === "off") return "classic";
  const key = "HARNESS_MOD_" + String(guard).replace(/([a-z])([A-Z])/g, "$1_$2").toUpperCase();
  if (env[key]) return normalizeMode(env[key]);
  const g = config && config.guards ? config.guards[guard] : undefined;
  const dflt = DEFAULT_CONFIG.guards[guard] || "classic";
  return normalizeMode(g, dflt);
}

/** Every guard's effective mode. */
export function allModes(config, env = {}) {
  const out = {};
  for (const g of Object.keys(GUARDS)) out[g] = modeFor(g, config, env);
  return out;
}

/** Parse a config file's text; a broken file means classic everywhere (fail safe, never fail open). */
export function parseConfig(text) {
  try {
    const j = JSON.parse(text);
    if (!j || typeof j !== "object" || !j.guards || typeof j.guards !== "object") return { ...DEFAULT_CONFIG, guards: {}, broken: true };
    return j;
  } catch (err) {
    return { ...DEFAULT_CONFIG, guards: {}, broken: true };
  }
}

/**
 * Does the classic side stand down for this guard? Only when the mode is `mod` AND the heartbeat
 * says the Mod armed that guard in this session. `heartbeat` is the parsed sessions/<id>.json or null.
 */
// WIRE-DARK[the classic side implements this same rule in ~/.claude/hooks/lib/mods-mode.cjs; this mirror exists so tests/lib.test.mjs proves the two agree]
export function classicStandsDown(guard, config, env, heartbeat, nowMs = Date.now(), maxAgeMs = 6 * 3600 * 1000) {
  if (modeFor(guard, config, env) !== "mod") return { standDown: false, why: "mode is not mod" };
  if (!heartbeat || typeof heartbeat !== "object") return { standDown: false, why: "no heartbeat for this session" };
  if (!heartbeat.armed || heartbeat.armed[guard] !== true) return { standDown: false, why: "Mod did not arm " + guard };
  const age = nowMs - (Number(heartbeat.ts) || 0);
  if (!(age >= 0 && age <= maxAgeMs)) return { standDown: false, why: "heartbeat stale (" + Math.round(age / 60000) + " min)" };
  return { standDown: true, why: "mod armed " + guard + " for this session" };
}
