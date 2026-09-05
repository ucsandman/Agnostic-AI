#!/usr/bin/env node
// Exercise the actual stdin/stdout boundary without running the proposed tools.
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

let checked = 0;
for (const hook of ['dashclaw-guard.cjs', 'secret-guard.cjs']) {
  for (const tool of ['Bash', 'mcp__fs__read']) {
    for (const denied of [false, true]) {
      const input = {
        hook_event_name: 'PreToolUse',
        tool_name: tool,
        tool_input: denied ? { file_path: '.env' } : { command: 'git status --short' },
      };
      const result = spawnSync(process.execPath, [path.join(__dirname, '../hooks', hook)], {
        input: JSON.stringify(input), encoding: 'utf8', timeout: 10000, windowsHide: true,
      });
      assert.ifError(result.error);
      assert.equal(result.status, denied ? 2 : 0);
      const output = JSON.parse(result.stdout);
      assert.deepEqual(Object.keys(output), ['hookSpecificOutput']);
      assert.equal(output.hookSpecificOutput.hookEventName, 'PreToolUse');
      assert.equal(output.hookSpecificOutput.permissionDecision, denied ? 'deny' : 'allow');
      if (denied) {
        assert.ok(output.hookSpecificOutput.permissionDecisionReason);
        assert.ok(result.stderr.trim(), 'exit 2 must carry the denial on stderr');
      }
      checked++;
    }
  }
}
console.log(`Hook wire protocol passed; checked=${checked}`);
