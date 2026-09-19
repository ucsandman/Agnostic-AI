#!/usr/bin/env node
/**
 * prompt-dispatch-probe.cjs — the one-process UserPromptSubmit chain and the wake-up guard.
 *
 *   node engine/hooks/tests/prompt-dispatch-probe.cjs
 *
 * Both directions per check (rule L1): the chain must run every hook in-process and
 * merge their answers; a hook that throws must be skipped, not kill the chain; the
 * wake-up guard must stay silent on human prompts and on the first two machine
 * wake-ups, fire on the third, and reset on the next human prompt. Uses a throwaway
 * session id and a scratch hook so nothing touches real state.
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const HOOKS = path.resolve(__dirname, '..');
const dispatch = require(path.join(HOOKS, 'prompt-dispatch.cjs'));
const wakeup = require(path.join(HOOKS, 'wakeup-guard.cjs'));

const SID = 'probe-prompt-dispatch-' + process.pid;
const payload = (prompt, extra = {}) => JSON.stringify({ hook_event_name: 'UserPromptSubmit', session_id: SID, cwd: HOOKS, transcript_path: '', prompt, ...extra });
const WAKE = '<task-notification>\n<task-id>x</task-id>\n<summary>Monitor event: "screenshots landing"</summary>\n</task-notification>';

let n = 0;
const check = (label, fn) => { n++; try { fn(); console.log(`  ok   ${label}`); } catch (e) { console.log(`  FAIL ${label}\n       ${e.message}`); process.exitCode = 1; } };

// Scratch hooks written next to the real ones so require() resolves the same lib paths.
const scratch = [];
const mk = (name, body) => { const p = path.join(HOOKS, name); fs.writeFileSync(p, body); scratch.push(p); return name; };
const A = mk('.probe-a.cjs', `const fs=require('fs');const d=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify({hookSpecificOutput:{hookEventName:'UserPromptSubmit',additionalContext:'A saw '+d.prompt}}));process.exit(0);`);
const B = mk('.probe-b.cjs', `console.log('[B] plain line');process.exit(0);`);
const C = mk('.probe-c.cjs', `throw new Error('C explodes');`);
const D = mk('.probe-d.cjs', `process.stdout.write(JSON.stringify({decision:'block',reason:'D blocks'}));`);
const E = mk('.probe-e.cjs', `module.exports={main:(p)=>'E main '+p.session_id};`);

console.log('prompt-dispatch probe');
try {
  const chain = [{ file: A }, { file: B }, { file: C }, { file: E, exportedMain: true }];
  const r = dispatch.dispatch(payload('hello'), { chain, noLedger: true });
  check('every hook in the chain runs in-process and its stdout is captured', () => {
    assert.strictEqual(r.results.length, 4);
    assert.ok(r.results[0].out.join('').includes('A saw hello'), 'A missing');
    assert.ok(r.results[1].out.join('').includes('[B] plain line'), 'B missing');
    assert.ok(r.results[3].out.join('').includes('E main ' + SID), 'E main missing');
  });
  check('a throwing hook is skipped with its error recorded; the chain continues', () => {
    assert.ok(/C explodes/.test(r.results[2].error), 'error not recorded: ' + r.results[2].error);
    assert.ok(r.results[3].out.length, 'hook after the throwing one did not run');
  });
  check('outputs merge into one additionalContext in chain order (JSON and plain lines alike)', () => {
    const ctx = r.answer.hookSpecificOutput.additionalContext;
    assert.ok(ctx.indexOf('A saw hello') < ctx.indexOf('[B] plain line') && ctx.indexOf('[B] plain line') < ctx.indexOf('E main'), ctx);
    assert.strictEqual(r.answer.decision, undefined);
  });
  check('a hook that blocks makes the merged answer block (negative: none blocked above)', () => {
    const b = dispatch.dispatch(payload('hello'), { chain: [{ file: A }, { file: D }], noLedger: true });
    assert.strictEqual(b.answer.decision, 'block');
    assert.strictEqual(b.answer.reason, 'D blocks');
  });
  check('stdin, stdout and process.exit are restored after the chain', () => {
    assert.strictEqual(typeof process.exit, 'function');
    assert.ok(!/HookExit/.test(String(process.exit)), 'process.exit still patched');
    assert.ok(fs.readFileSync(__filename, 'utf8').includes('prompt-dispatch-probe'), 'fs.readFileSync not restored');
  });
  check('the real CHAIN lists every UserPromptSubmit hook and each file exists', () => {
    const names = dispatch.CHAIN.map((e) => e.file);
    for (const want of ['wakeup-guard.cjs', 'context-nudge.cjs', 'scope-lock.cjs', 'fable-delegate-guard.cjs', 'mods-liveness.cjs', 'context-graph.cjs', 'repeat-tool-guard.cjs', 'correction-tracker.cjs', 'opus-handoff-inject.cjs']) assert.ok(names.includes(want), want + ' not in CHAIN');
    for (const f of names) assert.ok(fs.existsSync(path.join(HOOKS, f)), f + ' missing on disk');
  });
  check('the real chain runs end to end on a human prompt without a hook error', () => {
    const real = dispatch.dispatch(payload('probe: what changed?'), { noLedger: true });
    const errs = real.results.filter((x) => x.error).map((x) => x.name + ': ' + x.error);
    assert.deepStrictEqual(errs, [], errs.join('\n'));
    assert.strictEqual(real.results.length, dispatch.CHAIN.length);
  });

  // wake-up guard
  const state = path.join(wakeup.STATE_DIR, SID + '.json');
  const wg = (prompt) => wakeup.main(JSON.parse(payload(prompt)));
  check('wake-up guard: a human prompt is silent and leaves no streak', () => {
    assert.strictEqual(wg('fix the thing'), '');
    assert.ok(!fs.existsSync(state));
  });
  check('wake-up guard: machine wake-ups 1 and 2 are silent, 3 fires the directive', () => {
    assert.strictEqual(wg(WAKE), '');
    assert.strictEqual(wg(WAKE), '');
    const third = wg(WAKE);
    assert.ok(/\[wakeup-guard\] 3 consecutive/.test(third), third.slice(0, 80));
    assert.ok(/TaskStop/.test(third) && /delaySeconds >= 1200/.test(third));
  });
  check('wake-up guard: a fourth keeps firing with the count; a human prompt resets it', () => {
    assert.ok(/4 consecutive/.test(wg(WAKE)));
    assert.strictEqual(wg('ok thanks'), '');
    assert.ok(!fs.existsSync(state), 'streak file not removed');
    assert.strictEqual(wg(WAKE), '', 'streak did not restart at 1');
  });
  check('wake-up guard: source outside user/sdk counts as a machine turn even with plain text', () => {
    const s = JSON.parse(payload('anything', { source: 'wakeup', session_id: SID + '-src' }));
    wakeup.main(s); wakeup.main(s);
    assert.ok(/3 consecutive/.test(wakeup.main(s)));
    assert.strictEqual(wakeup.main(JSON.parse(payload('hi', { source: 'user', session_id: SID + '-src' }))), '');
  });
  check('wake-up guard: not a UserPromptSubmit event -> silent', () => {
    assert.strictEqual(wakeup.main({ hook_event_name: 'PreToolUse', session_id: SID, prompt: WAKE }), '');
  });
} finally {
  for (const p of scratch) try { fs.unlinkSync(p); } catch (_) {}
  for (const s of [SID, SID + '-src']) try { fs.unlinkSync(path.join(wakeup.STATE_DIR, s + '.json')); } catch (_) {}
}
console.log(`${n} checks, ${process.exitCode ? 'FAILED' : 'all passed'}`);
