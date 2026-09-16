#!/usr/bin/env node
/**
 * mods-mode-probe.cjs — the classic side of the Mods migration (hooks/lib/mods-mode.cjs).
 *
 * Per L1 each rule is seen failing on purpose: a classic guard stands down for a decision ONLY when
 * mode=mod AND a fresh heartbeat armed that guard for the session; every other state enforces.
 * Uses its own temp config/sessions/shadow dirs so it never touches the live ~/.claude/mods/state.
 *
 *   node hooks/tests/mods-mode-probe.cjs
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const mm = require('../lib/mods-mode.cjs');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'mods-mode-probe-'));
const configPath = path.join(tmp, 'mods-config.json');
const sessionsDir = path.join(tmp, 'sessions');
const shadowDir = path.join(tmp, 'shadow');
fs.mkdirSync(sessionsDir);
const write = (o) => fs.writeFileSync(configPath, JSON.stringify(o));
const hb = (sid, o) => fs.writeFileSync(path.join(sessionsDir, sid + '.json'), JSON.stringify(o));
const opts = (env) => ({ configPath, sessionsDir, shadowDir, env: env || {} });

let fails = 0;
function check(name, got, want) {
  const pass = got === want;
  if (!pass) fails++;
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name.padEnd(64)} want=${want} got=${got}`);
}

const SID = 'probe-session';
const now = Date.now();

write({ version: 1, guards: { routing: 'mod', secretRedaction: 'shadow_mod' } });
check('mod but no heartbeat → ENFORCE', mm.standsDown('routing', SID, opts()).standDown, false);
hb(SID, { ts: now, armed: { routing: false } });
check('mod, heartbeat not armed → ENFORCE', mm.standsDown('routing', SID, opts()).standDown, false);
hb(SID, { ts: now - 7 * 3600 * 1000, armed: { routing: true } });
check('mod, armed but stale (7h) → ENFORCE', mm.standsDown('routing', SID, opts()).standDown, false);
hb(SID, { ts: now, armed: { routing: true } });
check('mod, armed, fresh → STAND DOWN', mm.standsDown('routing', SID, opts()).standDown, true);
check('shadow_mod, armed, fresh → ENFORCE (shadow never yields)', mm.standsDown('secretRedaction', SID, opts()).standDown, false);
check('unset guard → default shadow_mod → ENFORCE', mm.standsDown('contextNudge', SID, opts()).standDown, false);
check('HARNESS_MODS=off → ENFORCE', mm.standsDown('routing', SID, opts({ HARNESS_MODS: 'off' })).standDown, false);
check('HARNESS_MOD_ROUTING=classic → ENFORCE', mm.standsDown('routing', SID, opts({ HARNESS_MOD_ROUTING: 'classic' })).standDown, false);
write({ version: 1, guards: { routing: 'classic' } });
check('config classic, env mod, armed → STAND DOWN (env wins)', mm.standsDown('routing', SID, opts({ HARNESS_MOD_ROUTING: 'mod' })).standDown, true);
fs.writeFileSync(configPath, '{broken');
check('broken config → ENFORCE (never opens a decision)', mm.standsDown('routing', SID, opts()).standDown, false);
fs.unlinkSync(configPath);
check('missing config → ENFORCE', mm.standsDown('routing', SID, opts()).standDown, false);
check('env mod with missing config, armed → STAND DOWN', mm.standsDown('routing', SID, opts({ HARNESS_MOD_ROUTING: 'mod' })).standDown, true);
check('unknown env value → classic → ENFORCE', mm.standsDown('routing', SID, opts({ HARNESS_MOD_ROUTING: 'bogus' })).standDown, false);

mm.recordShadow(SID, { subsystem: 'routing', action: 'Agent x', key: 'k', mode: 'shadow_mod', decision: 'deny', reasonCodes: ['probe'] }, opts());
const rows = fs.readFileSync(path.join(shadowDir, SID + '.classic.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
check('recordShadow writes one classic row', rows.length, 1);
check('row carries side=classic and the decision', rows[0].side + ':' + rows[0].decision, 'classic:deny');
check('signature is stable', mm.signatureOf('s', 't', 'p', 'm') === mm.signatureOf('s', 't', 'p', 'm'), true);
check('signature distinguishes the requested model', mm.signatureOf('s', 't', 'p', 'opus') !== mm.signatureOf('s', 't', 'p', 'haiku'), true);

fs.rmSync(tmp, { recursive: true, force: true });
console.log(`\n${18 - fails} passed / ${fails} failed`);
process.exit(fails ? 1 : 0);
