'use strict';
/*
 * mods-mode.cjs — the classic side of the Mods migration (CommonJS, for the .cjs guards).
 *
 * One question, asked by a classic guard before it enforces a decision the Function Hooks layer can
 * also own: "does the Mod own this decision in THIS session?"
 *
 *   standsDown(guard, sessionId) → { standDown, mode, why }
 *
 * True only when ALL of: mods-config.json says the guard is in `mod` mode (or the env override says
 * so), AND ~/.claude/mods/state/sessions/<sessionId>.json exists, is fresh, and says the Mod ARMED
 * that guard. Anything else (no heartbeat, stale, broken config, plugin disabled, Function Hooks gone
 * after an update) → the classic guard enforces exactly as before. So classic and Mod can never both
 * enforce one decision, and a decision can never be unowned.
 *
 * shadow_mod: the classic guard still enforces and records its verdict with recordShadow() so the
 * Mod's row for the same key can be paired offline (mods/state/shadow/<session>.classic.jsonl).
 *
 * Mirrors ~/.claude/mods/harness-mods/hooks/lib/modes.mjs (the Mod side); tests in
 * hooks/tests/mods-mode-probe.cjs assert the two agree.
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME = process.env.USERPROFILE || os.homedir();
const MODS = path.join(HOME, '.claude', 'mods');
const CONFIG = path.join(MODS, 'mods-config.json');
const SESSIONS = path.join(MODS, 'state', 'sessions');
const SHADOW = path.join(MODS, 'state', 'shadow');
const MODES = ['classic', 'shadow_mod', 'mod'];
const DEFAULTS = { routing: 'shadow_mod', contextNudge: 'shadow_mod', secretRedaction: 'shadow_mod', subagentAccounting: 'shadow_mod', readCache: 'shadow_mod' };
const MAX_AGE_MS = 6 * 3600 * 1000;

function normalizeMode(v, fallback) {
  const s = String(v || '').toLowerCase().trim();
  return MODES.includes(s) ? s : fallback;
}

function readConfig(opts = {}) {
  try {
    const j = JSON.parse(fs.readFileSync(opts.configPath || CONFIG, 'utf8'));
    if (!j || typeof j !== 'object' || !j.guards || typeof j.guards !== 'object') return { guards: {}, broken: true };
    return j;
  } catch (_) {
    return { guards: {}, broken: true, missing: true };
  }
}

function modeFor(guard, opts = {}) {
  const env = opts.env || process.env;
  if (String(env.HARNESS_MODS || '').toLowerCase() === 'off') return 'classic';
  const key = 'HARNESS_MOD_' + String(guard).replace(/([a-z])([A-Z])/g, '$1_$2').toUpperCase();
  if (env[key]) return normalizeMode(env[key], 'classic');
  const cfg = opts.config || readConfig(opts);
  if (cfg.broken) return 'classic'; // a broken or missing config never opens a decision
  return normalizeMode(cfg.guards[guard], DEFAULTS[guard] || 'classic');
}

function readHeartbeat(sessionId, opts = {}) {
  if (!sessionId) return null;
  try {
    const j = JSON.parse(fs.readFileSync(path.join(opts.sessionsDir || SESSIONS, String(sessionId) + '.json'), 'utf8'));
    return j && typeof j === 'object' ? j : null;
  } catch (_) {
    return null;
  }
}

function standsDown(guard, sessionId, opts = {}) {
  const mode = modeFor(guard, opts);
  if (mode !== 'mod') return { standDown: false, mode, why: 'mode is ' + mode };
  const hb = readHeartbeat(sessionId, opts);
  if (!hb) return { standDown: false, mode, why: 'no heartbeat for this session (Mod not loaded?)' };
  if (!hb.armed || hb.armed[guard] !== true) return { standDown: false, mode, why: 'Mod did not arm ' + guard };
  const age = (opts.now || Date.now()) - (Number(hb.ts) || 0);
  if (!(age >= 0 && age <= MAX_AGE_MS)) return { standDown: false, mode, why: 'heartbeat stale (' + Math.round(age / 60000) + ' min)' };
  return { standDown: true, mode, why: 'mod armed ' + guard + ' for this session' };
}

/** Append one classic-side comparison row (same shape as the Mod's lib/shadow.mjs row()). */
function recordShadow(sessionId, fields, opts = {}) {
  try {
    const dir = opts.shadowDir || SHADOW;
    fs.mkdirSync(dir, { recursive: true });
    const row = {
      ts: new Date().toISOString(), session: sessionId || null, side: 'classic',
      subsystem: fields.subsystem, action: fields.action, key: fields.key || null, mode: fields.mode || null,
      decision: fields.decision, requestedValue: fields.requestedValue === undefined ? null : fields.requestedValue,
      resolvedValue: fields.resolvedValue === undefined ? null : fields.resolvedValue,
      reasonCodes: fields.reasonCodes || [], wouldRewrite: !!fields.wouldRewrite, enforced: fields.enforced !== false,
      latencyMs: fields.latencyMs === undefined ? null : fields.latencyMs, retryCount: null,
      actualOutcome: fields.actualOutcome === undefined ? null : fields.actualOutcome, note: fields.note || null,
    };
    fs.appendFileSync(path.join(dir, (sessionId || 'no-session') + '.classic.jsonl'), JSON.stringify(row) + '\n', 'utf8');
  } catch (_) { /* never let the comparison break a guard */ }
}

/** Same FNV-1a signature the Mod uses (routing.mjs signatureOf) so routing rows pair. */
function signatureOf(sessionId, type, prompt, model) {
  const s = String(sessionId) + ' ' + String(type || '') + ' ' + String(model || '') + ' ' + String(prompt || '');
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, '0');
}

function log(guard, sessionId, verdict) {
  try {
    const dir = path.join(HOME, '.claude', 'logs');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, 'mods-mode.log'), `${new Date().toISOString()}\t${guard}\t${sessionId || '-'}\t${verdict.mode}\t${verdict.standDown ? 'STAND-DOWN' : 'ENFORCE'}\t${verdict.why}\n`);
  } catch (_) {}
}

module.exports = { MODES, DEFAULTS, CONFIG, SESSIONS, SHADOW, readConfig, modeFor, readHeartbeat, standsDown, recordShadow, signatureOf, log };
