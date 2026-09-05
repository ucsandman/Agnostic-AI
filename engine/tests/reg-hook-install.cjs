#!/usr/bin/env node
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
    for (const hooks of [{}, { PreToolUse: [{ hooks: [
      { type: 'command', command: 'node dashclaw-guard.cjs' },
      { type: 'command', command: 'node secret-guard.cjs' },
    ] }] }]) {
      const original = JSON.stringify({ hooks, owner: 'existing harness' }, null, 4) + '\n';
      fs.writeFileSync(file, original);
      const report = wireAgentHooks(home)[key];
      assert.equal(fs.readFileSync(file, 'utf8'), original, 'lifecycle config must remain byte-identical');
      assert.equal(report.dashclawGuard, Boolean(hooks.PreToolUse));
      assert.equal(report.secretGuard, Boolean(hooks.PreToolUse));
      checked++;
    }
  }
} finally {
  fs.rmSync(home, { recursive: true, force: true });
}
console.log(`Hook installation preservation passed; checked=${checked}`);
