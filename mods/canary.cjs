#!/usr/bin/env node
/*
 * mods/canary.cjs — the Mods leg of the harness canary (L1/L2 applied to the Function Hooks layer).
 *
 *   node ~/.claude/mods/canary.cjs            # full check (called by hooks/guard-canary.ps1, ~20h throttle)
 *   node ~/.claude/mods/canary.cjs --json     # machine-readable
 *   node ~/.claude/mods/canary.cjs --quick    # no `claude` subprocesses (used by the first-prompt liveness hook)
 *
 * A silent Mod failure must not look healthy, so every check states what it looked at and how much:
 *   installed     both plugins are in settings.enabledPlugins and the marketplace is registered
 *   validate      `claude plugin validate` passes for claude-runtime and harness-mods (skipped with --quick)
 *   version       `claude --version` equals the pinned build the layer was verified on (skipped with --quick)
 *   tests         hooks/lib tests pass (node --test), incl. the secret-pattern drift check (skipped with --quick)
 *   last-session  the newest sessions/<id>.json is recent, reports runtime=true, canary ok, and every
 *                 `mod`-mode guard armed; the layer's own judgement (canary-status.json) agrees
 *   config        mods-config.json parses and names only known modes
 * Exit 0 healthy, 1 unhealthy, 2 broken. Writes mods/state/canary-leg.json either way.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawnSync } = require('child_process');

const HOME = process.env.USERPROFILE || os.homedir();
const CLAUDE = path.join(HOME, '.claude');
const MODS = path.join(CLAUDE, 'mods');
const STATE = path.join(MODS, 'state');
const PIN_VERSION = '2.1.273';
const GUARDS = ['routing', 'contextNudge', 'secretRedaction', 'subagentAccounting', 'readCache'];
const args = process.argv.slice(2);
const QUICK = args.includes('--quick');
const AS_JSON = args.includes('--json');
const MAX_HB_AGE_MS = 7 * 24 * 3600 * 1000; // a week without any session is "unknown", not "broken"

const results = {};
const notes = [];
function check(name, ok, note) { results[name] = !!ok; if (note) notes.push(name + ': ' + note); }
function readJson(p) { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; } }
function run(cmd, cmdArgs, timeout) {
  const r = spawnSync(cmd, cmdArgs, { encoding: 'utf8', timeout: timeout || 60000, shell: process.platform === 'win32' });
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') };
}

// installed
const settings = readJson(path.join(CLAUDE, 'settings.json')) || {};
const ep = settings.enabledPlugins || {};
check('installed', ep['claude-runtime@harness-mods'] === true && ep['harness-mods@harness-mods'] === true && !!(settings.extraKnownMarketplaces || {})['harness-mods'],
  'claude-runtime=' + ep['claude-runtime@harness-mods'] + ' harness-mods=' + ep['harness-mods@harness-mods'] + ' marketplace=' + !!(settings.extraKnownMarketplaces || {})['harness-mods']);

// config
const cfg = readJson(path.join(MODS, 'mods-config.json'));
const modes = cfg && cfg.guards ? cfg.guards : null;
const badModes = modes ? Object.keys(modes).filter((g) => !['classic', 'shadow_mod', 'mod'].includes(modes[g])) : GUARDS;
check('config', !!modes && badModes.length === 0, modes ? Object.keys(modes).map((g) => g + '=' + modes[g]).join(' ') : 'mods-config.json unreadable');

// last session
let hbFiles = [];
try { hbFiles = fs.readdirSync(path.join(STATE, 'sessions')).filter((f) => f.endsWith('.json')).map((f) => ({ f, m: fs.statSync(path.join(STATE, 'sessions', f)).mtimeMs })).sort((a, b) => b.m - a.m); } catch (_) {}
const hb = hbFiles.length ? readJson(path.join(STATE, 'sessions', hbFiles[0].f)) : null;
const enforcing = modes ? GUARDS.filter((g) => modes[g] === 'mod') : [];
if (!hb) {
  check('last-session', false, 'no session heartbeat found (scanned ' + hbFiles.length + ' files): the Mod has never written one');
} else {
  const age = Date.now() - (Number(hb.ts) || 0);
  const notArmed = enforcing.filter((g) => !(hb.armed && hb.armed[g] === true));
  const canaryOk = hb.canary ? hb.canary.ok === true : false;
  check('last-session', hb.runtime === true && canaryOk && notArmed.length === 0 && age < MAX_HB_AGE_MS,
    'session ' + String(hb.sessionId).slice(0, 8) + ' ' + Math.round(age / 60000) + ' min ago · runtime=' + hb.runtime + ' · canary=' + (hb.canary ? (hb.canary.ok ? 'ok' : 'FAIL ' + (hb.canary.failures || []).join('; ')) : 'n/a') + ' · busEvents=' + (hb.status ? hb.status.busEvents : '?') + ' · toolCalls=' + (hb.status ? hb.status.toolCalls : '?') + (notArmed.length ? ' · NOT ARMED: ' + notArmed.join(',') : '') + ' · scanned=' + hbFiles.length);
}
const layer = readJson(path.join(STATE, 'canary-status.json'));
check('layer-self-check', !!layer && layer.ok === true, layer ? (layer.ok ? 'ok' : 'FAIL ' + (layer.failures || []).join('; ')) : 'no canary-status.json');

if (!QUICK) {
  const v = run('claude', ['--version'], 30000);
  const ver = (v.out.match(/(\d+\.\d+\.\d+)/) || [])[1] || null;
  check('version', ver === PIN_VERSION, 'installed ' + ver + ' vs pinned ' + PIN_VERSION + (ver && ver !== PIN_VERSION ? ' — re-run lab/probe* and update RUNTIME_PIN before trusting mod mode' : ''));
  for (const p of ['claude-runtime', 'harness-mods']) {
    const r = run('claude', ['plugin', 'validate', path.join(MODS, p), '--json'], 90000);
    let ok = false; let msg = 'no json';
    try { const j = JSON.parse(r.out.slice(r.out.indexOf('{'))); ok = j.success === true; msg = ok ? 'ok' : JSON.stringify((j.contents || []).flatMap((c) => c.errors || [])).slice(0, 200); } catch (_) { msg = r.out.slice(0, 160); }
    check('validate-' + p, ok, msg);
  }
  const t = run('node', ['--test', path.join(MODS, 'harness-mods', 'tests', 'lib.test.mjs')], 60000);
  const pass = (t.out.match(/ℹ pass (\d+)/) || [])[1]; const fail = (t.out.match(/ℹ fail (\d+)/) || [])[1];
  check('tests', t.status === 0 && fail === '0', 'pass=' + pass + ' fail=' + fail);
}

const ok = !Object.values(results).includes(false);
const out = { ranAt: new Date().toISOString(), ok, quick: QUICK, results, notes, enforcing };
try { fs.mkdirSync(STATE, { recursive: true }); fs.writeFileSync(path.join(STATE, 'canary-leg.json'), JSON.stringify(out, null, 2)); } catch (_) {}
if (AS_JSON) console.log(JSON.stringify(out));
else {
  console.log('mods canary: ' + (ok ? 'OK' : 'FAIL') + ' · ' + Object.keys(results).map((k) => k + '=' + (results[k] ? 'ok' : 'FAIL')).join(' '));
  for (const n of notes) console.log('  ' + n);
  if (!ok && enforcing.length) console.log('  ' + enforcing.join(',') + ' are in mod mode: the classic guards keep enforcing until a heartbeat proves the Mod armed them (hooks/lib/mods-mode.cjs).');
}
process.exit(ok ? 0 : 1);
