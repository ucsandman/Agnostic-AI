'use strict';
// post-edit-diagnostics-probe.cjs — does the post-edit check fire on a broken file and
// stay silent on a clean one? Both directions, per language. Run:
//   node hooks/tests/post-edit-diagnostics-probe.cjs

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const HOOK = 'C:/Users/sandm/.claude/hooks/post-edit-diagnostics.cjs';
const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'ped-probe-'));
const LOG = path.join(DIR, 'log.jsonl');

function call(tool, file, extraEnv = {}) {
  const r = spawnSync('node', [HOOK], {
    input: JSON.stringify({ session_id: 'probe', tool_name: tool, tool_input: { file_path: file } }),
    encoding: 'utf8',
    env: { ...process.env, POST_EDIT_DIAG_LOG: LOG, ...extraEnv },
  });
  const out = (r.stdout || '').trim();
  if (!out) return null;
  try { return JSON.parse(out).hookSpecificOutput.additionalContext; } catch { return out; }
}
function write(name, text) { const p = path.join(DIR, name); fs.writeFileSync(p, text); return p; }

const CASES = [];
const add = (name, actual, want) => CASES.push([name, actual, want]);

// node: broken vs clean
{
  const bad = write('bad.cjs', 'const x = ;\n');
  const good = write('good.cjs', 'const x = 1;\nmodule.exports = x;\n');
  const a = call('Write', bad);
  add('node: syntax error is reported', typeof a === 'string' && /SyntaxError|Unexpected token/.test(a), true);
  add('node: clean file is silent', call('Edit', good) === null, true);
}

// python: undefined name + syntax error vs clean (skipped with a note if ruff is absent)
{
  const has = !spawnSync('ruff', ['--version'], { encoding: 'utf8' }).error;
  if (has) {
    const bad = write('bad.py', 'def f():\n    return undefined_name_xyz\n');
    const syn = write('syn.py', 'def f(:\n    pass\n');
    const good = write('good.py', 'def f():\n    return 1\n');
    const a = call('Edit', bad);
    add('python: undefined name is reported', typeof a === 'string' && /F821|undefined/i.test(a), true);
    const b = call('Write', syn);
    add('python: syntax error is reported', typeof b === 'string' && /SyntaxError|invalid-syntax|E999/i.test(b), true);
    add('python: clean file is silent', call('MultiEdit', good) === null, true);
  } else {
    console.log('note: ruff not installed, python cases skipped (the hook is silent without it)');
  }
}

// json: broken vs clean
{
  const bad = write('bad.json', '{"a": 1,}');
  const good = write('good.json', '{"a": 1}');
  add('json: parse error is reported', typeof call('Write', bad) === 'string', true);
  add('json: clean file is silent', call('Write', good) === null, true);
}

// scope: other tools and other extensions are ignored; the off switch works
{
  const bad = write('bad2.cjs', 'const y = ;\n');
  add('Read is not a write: ignored', call('Read', bad) === null, true);
  add('.ts is left to the LSP plugin', call('Edit', write('x.ts', 'const a: number = ;')) === null, true);
  add('POST_EDIT_DIAG_OFF disables', call('Edit', bad, { POST_EDIT_DIAG_OFF: '1' }) === null, true);
  add('missing file is silent', call('Edit', path.join(DIR, 'nope.cjs')) === null, true);
}

// the log carries every run, clean or not (L2)
{
  let rows = [];
  try { rows = fs.readFileSync(LOG, 'utf8').trim().split('\n').map((l) => JSON.parse(l)); } catch {}
  add('every check is logged', rows.length >= 5 && rows.some((r) => r.ok === false) && rows.some((r) => r.ok === true), true);
}

let failed = 0;
for (const [name, actual, want] of CASES) {
  const ok = actual === want;
  if (!ok) failed++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(want)})`}`);
}
try { fs.rmSync(DIR, { recursive: true, force: true }); } catch {}
console.log(`\n${CASES.length - failed}/${CASES.length} passed`);
process.exit(failed ? 1 : 0);
