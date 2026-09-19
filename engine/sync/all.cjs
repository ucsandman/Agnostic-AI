#!/usr/bin/env node
/**
 * engine/sync/all.cjs — `npm run sync`: make the installed Claude Code home match this repository.
 *
 *   1. rules      core/rules + core/traits -> <home>/agnostic-rules.md (engine/sync/sync.cjs, primary client only)
 *   2. links      <home>/{hooks,mods,agents,workflows,tools} -> this repository (engine/setup/link.cjs)
 *   3. CLAUDE.md  @import + overlay/profile.md + preserved blocks (engine/sync/claude-md.cjs)
 *
 * Other clients are `npm run port`; the health of the result is `npm run doctor`.
 * Exit 1 if any step failed; every step still runs so one failure never hides the next.
 */
'use strict';
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const argv = process.argv.slice(2);
const check = argv.includes('--check');

const steps = [
  ['rules', ['engine/sync/sync.cjs', '--target', 'claude', ...(check ? ['--check'] : [])]],
  ['links', ['engine/setup/link.cjs', ...(check ? ['--check'] : [])]],
  ['CLAUDE.md', ['engine/sync/claude-md.cjs', ...(check ? ['--check'] : [])]],
];

let failed = 0;
for (const [name, args] of steps) {
  console.log(`\n== ${name} ==`);
  const r = spawnSync(process.execPath, args.map((a, i) => (i === 0 ? path.join(ROOT, a) : a)), { cwd: ROOT, stdio: 'inherit' });
  if (r.status !== 0) { failed++; console.log(`!! ${name} exited ${r.status}`); }
}
console.log(`\nsync: ${steps.length - failed} of ${steps.length} steps ok${check ? ' (check only)' : ''}`);
process.exit(failed ? 1 : 0);
