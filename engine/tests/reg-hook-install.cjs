#!/usr/bin/env node
/**
 * Regression: first-run must never write a Codex or Gemini hook file.
 *
 * 2026-08-18: first-run wrote a flat {"pre_tool_use": "..."} key into
 * ~/.codex/hooks.json. Codex never read that key, then repaired the file to
 * `hooks: {}` and every shared guard was gone. The write path is removed; these
 * clients get their hooks from `npm run port` in the format they actually read.
 *
 * So: every hook file this function sees must come back byte-identical, and the
 * reported guard flags must reflect the file's real contents, whatever shape it
 * is in (lifecycle format, flat format, or an empty object).
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { wireAgentHooks } = require('../setup/first-run.cjs');

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-hook-install-'));
let checked = 0;
try {
  for (const [directory, key] of [['.codex', 'codex'], ['.gemini/config', 'gemini']]) {
    const dir = path.join(home, directory);
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, 'hooks.json');

    // Lifecycle format: empty, then carrying both guards.
    for (const hooks of [{}, { PreToolUse: [{ hooks: [
      { type: 'command', command: 'node dashclaw-guard.cjs' },
      { type: 'command', command: 'node secret-guard.cjs' },
    ] }] }]) {
      const original = JSON.stringify({ hooks, owner: 'existing harness' }, null, 4) + '\n';
      fs.writeFileSync(file, original);
      const report = wireAgentHooks(home)[key];
      assert.equal(fs.readFileSync(file, 'utf8'), original, 'lifecycle config must remain byte-identical');
      assert.equal(report.present, true, `${key} must be reported present`);
      assert.equal(report.dashclawGuard, Boolean(hooks.PreToolUse));
      assert.equal(report.secretGuard, Boolean(hooks.PreToolUse));
      checked++;
    }

    // Flat format holding a foreign hook: the shape the old code overwrote.
    const flat = JSON.stringify({ pre_tool_use: 'node /somebody/else/hook.cjs', preToolUse: 'node /somebody/else/hook.cjs' }, null, 2) + '\n';
    fs.writeFileSync(file, flat);
    const flatReport = wireAgentHooks(home)[key];
    assert.equal(fs.readFileSync(file, 'utf8'), flat, 'a flat-format hook file must not be rewritten');
    assert.equal(flatReport.dashclawGuard, false, 'no agnostic guard is in that file, so none may be reported');
    assert.equal(flatReport.secretGuard, false);
    checked++;

    // No hook file at all: first-run must not create one.
    fs.rmSync(file);
    const absentReport = wireAgentHooks(home)[key];
    assert.equal(fs.existsSync(file), false, 'first-run must not create a hook file for this client');
    assert.equal(absentReport.present, true, 'the client is still installed');
    assert.equal(absentReport.dashclawGuard, false);
    checked++;

    // A backup of a file we never write is dead weight too.
    assert.equal(fs.existsSync(`${file}.bak`), false, 'no backup should be made for a file that is never written');
    checked++;
  }
} finally {
  fs.rmSync(home, { recursive: true, force: true });
}
console.log(`Hook installation preservation passed; checked=${checked}`);
