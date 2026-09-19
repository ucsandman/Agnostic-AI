'use strict';
// repeat-guard-probe.cjs — does the repeat-tool-call guard actually fire?
// Run: node hooks/tests/repeat-guard-probe.cjs

const { spawnSync } = require('child_process');
const HOOK = require('path').join(__dirname, '..', 'repeat-tool-guard.cjs');

let seq = 0;
const session = () => `probe-${Date.now()}-${seq++}`;

function call(sessionId, tool, input, args = []) {
  const r = spawnSync('node', [HOOK, ...args], {
    input: JSON.stringify({ session_id: sessionId, tool_name: tool, tool_input: input }),
    encoding: 'utf8',
  });
  const out = (r.stdout || '').trim();
  if (!out) return null;
  try { return JSON.parse(out).hookSpecificOutput.additionalContext; } catch { return out; }
}

const CASES = [];
const add = (name, actual, want) => CASES.push([name, actual, want]);

// 1. Three identical calls: silent, silent, reminder.
{
  const s = session();
  const a = call(s, 'Bash', { command: 'npm test' });
  const b = call(s, 'Bash', { command: 'npm test' });
  const c = call(s, 'Bash', { command: 'npm test' });
  add('call 1 silent', a === null, true);
  add('call 2 silent', b === null, true);
  add('call 3 reminds', typeof c === 'string' && /3 times in a row/.test(c), true);
}

// 2. A different call resets the chain.
{
  const s = session();
  call(s, 'Bash', { command: 'npm test' });
  call(s, 'Bash', { command: 'npm test' });
  call(s, 'Bash', { command: 'ls' });
  add('different call resets', call(s, 'Bash', { command: 'npm test' }) === null, true);
}

// 3. Argument key order must not hide a repeat.
{
  const s = session();
  call(s, 'Grep', { pattern: 'x', path: 'src' });
  call(s, 'Grep', { path: 'src', pattern: 'x' });
  add('key order canonicalised', typeof call(s, 'Grep', { pattern: 'x', path: 'src' }) === 'string', true);
}

// 4. A transparent tool between two repeats does not launder the loop.
{
  const s = session();
  call(s, 'Grep', { pattern: 'y' });
  call(s, 'TodoWrite', { todos: [] });
  call(s, 'Grep', { pattern: 'y' });
  add('TodoWrite is transparent', typeof call(s, 'Grep', { pattern: 'y' }) === 'string', true);
}

// 5. Exempt tools never fire (polling is legitimate).
{
  const s = session();
  for (let i = 0; i < 4; i++) call(s, 'TaskOutput', { id: 'abc' });
  add('TaskOutput exempt', call(s, 'TaskOutput', { id: 'abc' }) === null, true);
}

// 6. Escalation: the 5th identical call gets the detailed form.
{
  const s = session();
  let last = null;
  for (let i = 0; i < 5; i++) last = call(s, 'Read', { file_path: 'a.txt' });
  add('call 5 escalates', typeof last === 'string' && /STOP REPEATING/.test(last), true);
}

// 7. A user prompt resets the chain.
{
  const s = session();
  call(s, 'Bash', { command: 'x' });
  call(s, 'Bash', { command: 'x' });
  call(s, 'Bash', { command: 'x' }, []);
  call(s, 'Bash', { command: 'x' }, ['--reset']);
  add('--reset clears the chain', call(s, 'Bash', { command: 'x' }) === null, true);
}

// 8. The off switch works.
{
  const s = session();
  process.env.REPEAT_GUARD_OFF = '1';
  let last = null;
  for (let i = 0; i < 4; i++) last = call(s, 'Bash', { command: 'z' });
  delete process.env.REPEAT_GUARD_OFF;
  add('REPEAT_GUARD_OFF disables', last === null, true);
}

// 9. Sessions do not bleed into each other.
{
  const a = session();
  const b = session();
  call(a, 'Bash', { command: 'q' });
  call(a, 'Bash', { command: 'q' });
  add('sessions isolated', call(b, 'Bash', { command: 'q' }) === null, true);
}

// 10. A streak of identical FAILING calls gets the "keeps failing, fix the input" text (paper §A.4).
{
  const s = session();
  const fail = { session_id: s, tool_name: 'Bash', tool_input: { command: 'pytest -x' }, hook_event_name: 'PostToolUseFailure' };
  let last = null;
  for (let i = 0; i < 3; i++) {
    const r = spawnSync('node', [HOOK], { input: JSON.stringify(fail), encoding: 'utf8' });
    const out = (r.stdout || '').trim();
    last = out ? JSON.parse(out).hookSpecificOutput : null;
  }
  add('failing streak names the failure', !!last && /keeps failing the same way/.test(last.additionalContext), true);
  add('failing streak answers on the failure event', !!last && last.hookEventName === 'PostToolUseFailure', true);
}

// 11. A success inside the streak breaks the failing tail: the text is the plain repeat reminder.
{
  const s = session();
  const mk = (ev) => ({ session_id: s, tool_name: 'Bash', tool_input: { command: 'make' }, hook_event_name: ev });
  spawnSync('node', [HOOK], { input: JSON.stringify(mk('PostToolUseFailure')), encoding: 'utf8' });
  spawnSync('node', [HOOK], { input: JSON.stringify(mk('PostToolUse')), encoding: 'utf8' });
  const r = spawnSync('node', [HOOK], { input: JSON.stringify(mk('PostToolUseFailure')), encoding: 'utf8' });
  const out = JSON.parse((r.stdout || '').trim()).hookSpecificOutput.additionalContext;
  add('mixed streak is the plain reminder', /3 times in a row with identical/.test(out) && !/keeps failing/.test(out), true);
}

// 12. Every threshold fire is logged (L2: a verdict carries its volume).
{
  const logFile = require('path').join(require('os').tmpdir(), `repeat-guard-probe-${Date.now()}.jsonl`);
  const s = session();
  for (let i = 0; i < 3; i++) spawnSync('node', [HOOK], { input: JSON.stringify({ session_id: s, tool_name: 'Grep', tool_input: { pattern: 'k' } }), encoding: 'utf8', env: { ...process.env, REPEAT_GUARD_LOG: logFile } });
  let rows = [];
  try { rows = require('fs').readFileSync(logFile, 'utf8').trim().split('\n').map((l) => JSON.parse(l)); } catch {}
  add('threshold fire is logged', rows.length === 1 && rows[0].tool === 'Grep' && rows[0].count === 3 && rows[0].failing === false, true);
  try { require('fs').unlinkSync(logFile); } catch {}
}

let failed = 0;
for (const [name, actual, want] of CASES) {
  const ok = actual === want;
  if (!ok) failed++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(want)})`}`);
}
console.log(`\n${CASES.length - failed}/${CASES.length} passed`);
process.exit(failed ? 1 : 0);
