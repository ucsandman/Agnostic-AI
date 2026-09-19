#!/usr/bin/env node
// Per-hook cost: run each hook that fires on a Bash tool call or a prompt submit ALONE,
// with a synthetic payload, and print ms / exit code / stdout bytes (stdout = injected context).
//   node hooktime.cjs
// Reads ~/.claude/settings.json. Sequential, so the numbers are each hook's own cost;
// hookpar.cjs gives the event's wall clock under contention.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const home = os.homedir();
const settings = JSON.parse(fs.readFileSync(path.join(home, '.claude', 'settings.json'), 'utf8'));
const SID = 'hook-latency-probe';
const base = { session_id: SID, transcript_path: path.join(home, '.claude', 'projects', 'probe', SID + '.jsonl'), cwd: process.cwd(), permission_mode: 'default' };
const payloads = {
  PreToolUse: { ...base, hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: 'git status --short', description: 'status' }, tool_use_id: 'toolu_probe' },
  PostToolUse: { ...base, hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'git status --short' }, tool_response: { stdout: 'M x\n', stderr: '', interrupted: false }, tool_use_id: 'toolu_probe' },
  UserPromptSubmit: { ...base, hook_event_name: 'UserPromptSubmit', prompt: 'fix the failing test and push' },
};
function matches(m, tool) { if (!m || m === '*') return true; try { return new RegExp(`^(${m})$`).test(tool); } catch { return m.split('|').includes(tool); } }
const rows = [];
for (const ev of Object.keys(payloads)) {
  const input = JSON.stringify(payloads[ev]);
  for (const g of settings.hooks && settings.hooks[ev] || []) for (const c of g.hooks || []) {
    if (!c.command || !(ev === 'UserPromptSubmit' || matches(g.matcher, 'Bash'))) continue;
    const t0 = Date.now();
    const r = spawnSync(c.command, { shell: true, input, encoding: 'utf8', timeout: 60000, env: process.env });
    rows.push({ ev, ms: Date.now() - t0, code: r.status, out: (r.stdout || '').length, cmd: c.command.replace(home.replace(/\\/g, '/'), '~').replace(home, '~').slice(0, 90), err: (r.stderr || '').slice(0, 60).replace(/\s+/g, ' ') });
  }
}
rows.sort((a, b) => a.ev.localeCompare(b.ev) || b.ms - a.ms);
console.log('event             ms   exit  outB  command');
for (const r of rows) console.log(`${r.ev.padEnd(16)} ${String(r.ms).padStart(5)}  ${String(r.code).padStart(4)} ${String(r.out).padStart(5)}  ${r.cmd}${r.err ? '  | ' + r.err : ''}`);
const sum = ev => rows.filter(r => r.ev === ev).reduce((s, r) => s + r.ms, 0);
console.log(`\n${rows.length} hooks timed. SEQUENTIAL SUM  PreToolUse=${sum('PreToolUse')}ms  PostToolUse=${sum('PostToolUse')}ms  UserPromptSubmit=${sum('UserPromptSubmit')}ms`);
