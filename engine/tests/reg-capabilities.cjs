#!/usr/bin/env node
/**
 * engine/tests/reg-capabilities.cjs — capability negotiation (2026-09-16).
 *
 * Claude Code with the Function Hooks layer (~/.claude/mods) has capabilities no other target has;
 * targets.json now says so explicitly in a `supports` block and universal-adapter.cjs exposes
 * capabilitiesOf(client) / requires(client, feature) so a porter DROPS a Mods-only artefact with a
 * recorded reason instead of pretending Codex, Gemini, agy or a file-only target can run it.
 * Hermetic: reads only the repo's own templates.
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const targets = JSON.parse(fs.readFileSync(path.join(ROOT, 'core', 'templates', 'targets.json'), 'utf8')).targets;
const ua = require(path.join(ROOT, 'engine', 'hooks', 'universal-adapter.cjs'));

const KEYS = ['toolInterception', 'toolResultMutation', 'runtimeEvents', 'subagentEvents', 'uiInjection', 'dynamicPermissions', 'contextSignals', 'usageSignals', 'middleware', 'runtimeMemory', 'checkpointing', 'semanticJudgment'];
const BOOL = KEYS.slice(0, 10);
let n = 0;
function check(name, fn) { n++; try { fn(); console.log(`  ✓ ${name}`); } catch (e) { console.log(`  ✗ ${name}\n    ${e.message}`); process.exitCode = 1; } }

console.log('reg-capabilities');
check(`every target (${targets.length}) has a supports block with exactly the 12 keys and valid values`, () => {
  for (const t of targets) {
    assert.ok(t.supports && typeof t.supports === 'object', `${t.id}: no supports`);
    assert.deepStrictEqual(Object.keys(t.supports).sort(), KEYS.slice().sort(), `${t.id}: keys`);
    for (const k of BOOL) assert.strictEqual(typeof t.supports[k], 'boolean', `${t.id}.${k}`);
    assert.ok(['none', 'file-level'].includes(t.supports.checkpointing), `${t.id}.checkpointing`);
    assert.ok(Array.isArray(t.supports.semanticJudgment) && t.supports.semanticJudgment.includes('stub'), `${t.id}.semanticJudgment`);
  }
});
check('Claude Code declares the Function-Hooks set (result mutation, usage/context signals, middleware, runtime memory)', () => {
  const c = ua.capabilitiesOf('claude');
  for (const k of ['toolInterception', 'toolResultMutation', 'runtimeEvents', 'subagentEvents', 'dynamicPermissions', 'contextSignals', 'usageSignals', 'middleware', 'runtimeMemory']) assert.strictEqual(c[k], true, k);
  assert.strictEqual(c.checkpointing, 'file-level');
  assert.ok(c.semanticJudgment.includes('jev'));
});
check('Codex keeps its best supported behaviour and nothing more (no result mutation, no usage signals)', () => {
  const c = ua.capabilitiesOf('codex');
  assert.strictEqual(c.toolInterception, true);
  assert.strictEqual(c.toolResultMutation, false);
  assert.strictEqual(c.usageSignals, false);
});
check('a file-only target drops a Mods-only artefact with a recorded reason; Claude passes; an unknown client is all-false, never a throw', () => {
  const fileOnly = targets.find((t) => !t.supports.toolInterception);
  assert.ok(fileOnly, 'no file-only target to test against');
  assert.deepStrictEqual(ua.requires(fileOnly.id, 'toolResultMutation'), { ok: false, reason: 'dropped: target lacks toolResultMutation' });
  assert.deepStrictEqual(ua.requires('claude', 'toolResultMutation'), { ok: true, reason: null });
  const u = ua.capabilitiesOf('no-such-client');
  assert.deepStrictEqual(Object.keys(u).sort(), KEYS.slice().sort());
  assert.strictEqual(u.toolInterception, false);
});
check('README capability table matches targets.json (L1: edit one cell and this fails)', () => {
  const readme = fs.readFileSync(path.join(ROOT, 'README.md'), 'utf8');
  const start = readme.indexOf('<!-- capabilities:start -->'), end = readme.indexOf('<!-- capabilities:end -->');
  assert.ok(start > 0 && end > start, 'README lacks the capabilities table markers');
  const table = readme.slice(start, end);
  for (const t of targets) {
    const row = table.split('\n').find((l) => l.startsWith(`| ${t.id} `));
    assert.ok(row, `README row for ${t.id}`);
    const cells = row.split('|').map((s) => s.trim()).filter(Boolean);
    const want = [t.id, ...BOOL.map((k) => (t.supports[k] ? 'yes' : 'no')), t.supports.checkpointing, t.supports.semanticJudgment.join(',')];
    assert.deepStrictEqual(cells, want, `README row for ${t.id} differs from targets.json`);
  }
});
console.log(`[reg-capabilities] ${n} checks, exit ${process.exitCode || 0}`);
