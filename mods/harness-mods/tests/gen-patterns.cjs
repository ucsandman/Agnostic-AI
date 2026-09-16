// gen-patterns.cjs — regenerates hooks/lib/secret-patterns.mjs from the harness's single source of
// secret shapes, ~/.claude/hooks/lib/secret-patterns.cjs. A hooks module may import only its own
// files, so the Mod carries a generated copy; tests/redact.test.mjs fails when the two drift.
//   node C:/Users/sandm/.claude/mods/harness-mods/tests/gen-patterns.cjs
'use strict';
const fs = require('fs');
const path = require('path');
const src = require('C:/Users/sandm/.claude/hooks/lib/secret-patterns.cjs');
const lines = [
  '// secret-patterns.mjs — GENERATED COPY of ~/.claude/hooks/lib/secret-patterns.cjs (a hooks module may',
  '// import only its own files). tests/redact.test.mjs fails when the two drift; regenerate with:',
  '//   node C:/Users/sandm/.claude/mods/harness-mods/tests/gen-patterns.cjs',
  'export const PATTERNS = [',
];
for (const [k, re] of src.PATTERNS) lines.push('  [' + JSON.stringify(k) + ', ' + re.toString() + '],');
lines.push('];', 'export const PLACEHOLDER = ' + src.PLACEHOLDER.toString() + ';', 'export default { PATTERNS, PLACEHOLDER };', '');
const out = path.join(__dirname, '..', 'hooks', 'lib', 'secret-patterns.mjs');
fs.writeFileSync(out, lines.join('\n'));
console.log('regenerated ' + out + ' (' + src.PATTERNS.length + ' patterns)');
