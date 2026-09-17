#!/usr/bin/env node
// slow-command-guard.test.cjs — the guard's own regression suite.
//
//   node ~/.claude/hooks/tests/slow-command-guard.test.cjs
//
// Exists because the guard denied a `node -e` one-liner whose script body contained `.find(` on
// 2026-09-17: `\bfind\b` matched the word anywhere in the command, including inside quotes and as a
// JS method call. A guard that denies work it has no opinion about trains you to reach for the
// override marker, which is the same failure as having no guard. Both directions are asserted here:
// the false positives must pass AND every genuinely slow root-scoped search must still be denied.
'use strict';
const { spawnSync } = require('child_process');
const path = require('path');

const HOOK = path.join(__dirname, '..', 'slow-command-guard.cjs');

// [label, command, shouldDeny]
const CASES = [
  // False positives the 2026-09-17 fix addresses.
  ['node -e whose script body contains .find(', 'node canary.cjs --json | node -e "j.notes.find(n=>n.startsWith(\'version:\'))"', false],
  ['the bare word find inside a quoted string', 'echo "use the Grep tool to find things"', false],
  ['a find scoped to a repo-relative path', 'find ./src -name "*.ts"', false],
  ['a find scoped below home', 'find ~/.claude/mods -name "*.mjs"', false],
  ['grep -r scoped to one repo', 'grep -r "TODO" ./packages', false],
  ['a word ending in find', 'npm run prefind', false],

  // The behaviour the guard exists for. These must still be denied.
  ['find rooted at home', 'find ~ -name "claude-code.d.ts"', true],
  ['find rooted at C:/Projects', 'find C:/Projects -name "*.svg"', true],
  ['find rooted at a bash-style home', 'find /c/Users/sandm -name "*.json"', true],
  ['rg at the home root', 'rg "TODO" ~', true],
  ['grep -r at C:\\Projects', 'grep -r "foo" C:\\Projects', true],
  ['find at a root in a pipeline', 'ls | find /c/Users/sandm -name x', true],
  ['find at a root after &&', 'cd /tmp && find ~ -name "*.log"', true],

  // The documented escape hatch still works.
  ['SLOW_OK override on a real root search', 'find ~ -name "*.ts" # SLOW_OK', false],
];

let failed = 0;
for (const [label, command, shouldDeny] of CASES) {
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify({ tool_name: 'Bash', tool_input: { command } }),
    encoding: 'utf8',
  });
  const denied = (r.stdout || '').includes('"deny"');
  const ok = denied === shouldDeny;
  if (!ok) failed++;
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + (denied ? 'DENY ' : 'allow') + '  ' + label);
}

console.log('\n' + (failed
  ? failed + ' of ' + CASES.length + ' FAILED'
  : 'all ' + CASES.length + ' passed (' + CASES.filter((c) => c[2]).length + ' deny, ' + CASES.filter((c) => !c[2]).length + ' allow)'));
process.exit(failed ? 1 : 0);
