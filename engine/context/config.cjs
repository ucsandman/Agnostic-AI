'use strict';
/**
 * engine/context/config.cjs — the context-graph config file and its defaults.
 *
 * A client's config names the roots modules are read from, the budgets, the
 * selection thresholds and the client id. Roots are the trust allowlist: a
 * module can only come from a listed root, and a `perRepo` root is expanded
 * from the working directory at resolve time (Claude Code's `projects/<slug>`
 * layout by default; `{slug}` and `{cwd}` are the placeholders).
 *
 * Machine paths live in the client's config, never in this engine.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

const DEFAULTS = {
  version: 1,
  client: 'claude',
  roots: [],
  budget: { turnTokens: 2500, sessionTokens: 12000, maxModulesPerTurn: 6, maxClosure: 24, maxDepth: 8, maxModuleTokens: 1500, maxFanout: 8 },
  selection: { threshold: 2, maxTargets: 4, maxCandidates: 5 },
  stale: { afterDays: 120 },
};

function home() { return process.env.CONTEXT_GRAPH_HOME || process.env.USERPROFILE || process.env.HOME || os.homedir(); }
function expand(p, vars = {}) {
  let s = String(p || '').replace(/^~(?=[\\/]|$)/, home());
  for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(v === undefined || v === null ? '' : String(v));
  return path.normalize(s);
}

/** Claude Code's project slug: every path separator, colon or dot becomes `-` (C:\Users\x\.claude -> C--Users-x--claude). */
function slugOf(cwd) { return String(cwd || '').replace(/[:\\/.]/g, '-'); }

function load(file) {
  let raw = {};
  if (file && fs.existsSync(file)) raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  const cfg = {
    ...DEFAULTS, ...raw,
    budget: { ...DEFAULTS.budget, ...(raw.budget || {}) },
    selection: { ...DEFAULTS.selection, ...(raw.selection || {}) },
    stale: { ...DEFAULTS.stale, ...(raw.stale || {}) },
    roots: Array.isArray(raw.roots) ? raw.roots : [],
    file: file || null,
  };
  return cfg;
}

/**
 * concreteRoots(cfg, { cwd }) -> roots with `~`, `{slug}` and `{cwd}` expanded.
 * A `perRepo` root that expands to a missing directory is dropped (no repo
 * memory yet). Every concrete root carries `repo` = the cwd basename when it
 * is per-repo, so repo-scoped modules bind to it.
 */
function concreteRoots(cfg, ctx = {}) {
  const cwd = ctx.cwd ? path.resolve(ctx.cwd) : null;
  const vars = { slug: cwd ? slugOf(cwd) : '', cwd: cwd || '' };
  const out = [];
  const seen = new Set();
  for (const r of cfg.roots) {
    if (r.enabled === false) continue;
    if (r.perRepo && !cwd) continue;
    const p = expand(r.path, vars);
    if (r.perRepo && !fs.existsSync(p)) continue;
    const key = path.resolve(p).toLowerCase();
    if (seen.has(key)) continue; // a per-repo root that expands onto a listed root (cwd = the harness itself)
    seen.add(key);
    out.push({ ...r, path: p, repo: r.perRepo ? path.basename(cwd) : (r.repo || null), scope: r.perRepo ? 'repo' : (r.scope || 'user'), trust: r.trust || 'user' });
  }
  return out;
}

module.exports = { DEFAULTS, load, expand, concreteRoots, slugOf, home };
