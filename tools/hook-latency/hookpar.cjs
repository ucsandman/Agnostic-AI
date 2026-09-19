#!/usr/bin/env node
// Wall-clock cost of one Claude Code event: run every hook that matches it concurrently
// (as Claude Code does) with a synthetic payload, N times. Reports the slowest members.
//   node hookpar.cjs PreToolUse Bash 2
//   node hookpar.cjs PostToolUse Read
//   node hookpar.cjs UserPromptSubmit
// Reads ~/.claude/settings.json. Hooks see a fake session id; guards that read the
// transcript get "no transcript" and should still exit fast.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const [ev = 'PreToolUse', tool = 'Bash', iters = '2'] = process.argv.slice(2);
const home = os.homedir();
const settings = JSON.parse(fs.readFileSync(path.join(home, '.claude', 'settings.json'), 'utf8'));
const SID = 'hook-latency-probe';
const base = { session_id: SID, transcript_path: path.join(home, '.claude', 'projects', 'probe', SID + '.jsonl'), cwd: process.cwd(), permission_mode: 'default', hook_event_name: ev, tool_name: tool, tool_use_id: 'toolu_probe' };
const input = JSON.stringify(ev === 'UserPromptSubmit' ? { ...base, prompt: 'list the files in this directory' }
  : ev === 'PostToolUse' ? { ...base, tool_input: { command: 'git status --short' }, tool_response: { stdout: 'M x\n', stderr: '' } }
  : { ...base, tool_input: tool === 'Bash' ? { command: 'git status --short' } : { file_path: path.join(process.cwd(), 'README.md') } });
function matches(m, t) { if (!m || m === '*') return true; try { return new RegExp(`^(${m})$`).test(t); } catch { return m.split('|').includes(t); } }
const cmds = [];
for (const g of settings.hooks && settings.hooks[ev] || []) for (const c of g.hooks || []) if (c.command && (ev === 'UserPromptSubmit' || matches(g.matcher, tool))) cmds.push(c.command);
if (!cmds.length) { console.log(`${ev}/${tool}: 0 hooks registered`); process.exit(0); }
(async () => {
  for (let i = 0; i < +iters; i++) {
    const t0 = Date.now(); const per = [];
    await Promise.all(cmds.map(cmd => new Promise(res => {
      const p = spawn(cmd, { shell: true, env: process.env });
      p.stdin.end(input); p.stdout.resume(); p.stderr.resume();
      p.on('close', () => { per.push([Date.now() - t0, cmd.replace(/.*[\/\\]/, '').replace(/"$/, '')]); res(); });
      p.on('error', () => res());
    })));
    per.sort((a, b) => b[0] - a[0]);
    console.log(`${ev}/${tool} run${i + 1}: ${cmds.length} hooks in parallel => wall ${Date.now() - t0} ms; slowest: ${per.slice(0, 4).map(p => `${p[1]}=${p[0]}`).join(', ')}`);
  }
})();
