#!/usr/bin/env node
/**
 * jobs/install.cjs — register (or re-point) the harness's scheduled jobs on Windows Task Scheduler.
 *
 *   node jobs/install.cjs            # show each job: registered action vs the action this repo wants
 *   node jobs/install.cjs --apply    # rewrite the action of every job that differs (never creates a trigger)
 *
 * The jobs are the repository's; their triggers (when they run) stay whatever the machine has,
 * so re-pointing a job after a checkout move changes the path and nothing else. A job that is not
 * registered is reported, not created: creating a schedule is the operator's decision
 * (`Register-ScheduledTask`, or the one-liner printed here).
 *
 * Private jobs (an operator's own briefings, watchdogs, audits) are not listed here; they live in
 * the private overlay and are registered from there.
 */
'use strict';
const path = require('path');
const os = require('os');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const W = (p) => path.join(ROOT, p).replace(/\//g, '\\');
const CHOME = (process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude')).replace(/\//g, '\\');
const BASH = 'C:\\Program Files\\Git\\bin\\bash.exe';

/** name -> { execute, args, workingDirectory?, note }. Args are the exact Task Scheduler argument string. */
const JOBS = {
  HarnessParitySync: { execute: 'pwsh.exe', args: `-NoProfile -ExecutionPolicy Bypass -File "${W('jobs/port-daily.ps1')}"`, note: 'daily: capture Claude Code, port to every other client' },
  ClaudeErrorLog: { execute: BASH, args: W('jobs/errorlog/harvest.sh'), note: 'daily 06:22: harvest deviations and assumptions from transcripts' },
  ClaudeAgentReaper: { execute: 'wscript.exe', args: `"${W('jobs/reapers/agent-reaper-launcher.vbs')}"`, note: 'orphaned agent processes' },
  ClaudeLspReaper: { execute: 'wscript.exe', args: `"${W('jobs/reapers/lsp-reaper-launcher.vbs')}"`, note: 'orphaned language servers' },
  WesErrorLog: { execute: 'wscript.exe', args: `"${W('jobs/errorlog/daily-launcher.vbs')}"`, note: 'the human daily error log form' },
  'Harness Health Monthly': { execute: 'cmd', args: `/c pwsh -NoProfile -File "${W('tools/harness-health/harness-health.ps1')}" > "${CHOME}\\harness-health-last.txt" 2>&1`, note: 'settings-layer health report' },
  CronwatchDaily: { execute: process.execPath, args: `"${W('tools/cronwatch/cronwatch.cjs')}" --all`, workingDirectory: W('tools/cronwatch'), note: 'scheduled-job health board' },
};
// Jobs another product chains into: only the argument that names a file in this repository changes.
const ARG_REWRITES = {
  NightlyMeditation: [[/--next-argument\s+"[^"]*run-nightly\.sh"/, `--next-argument "${W('jobs/meditation/run-nightly.sh')}"`]],
};

function ps(script) {
  const r = spawnSync('powershell', ['-NoProfile', '-Command', script], { encoding: 'utf8' });
  return { ok: r.status === 0, out: (r.stdout || '').trim(), err: (r.stderr || '').trim() };
}
function current(name) {
  const r = ps(`$t = Get-ScheduledTask -TaskName '${name.replace(/'/g, "''")}' -ErrorAction SilentlyContinue; if ($t) { $a = $t.Actions[0]; ConvertTo-Json @{ execute = $a.Execute; args = $a.Arguments; wd = $a.WorkingDirectory } -Compress }`);
  if (!r.ok || !r.out) return null;
  try { return JSON.parse(r.out); } catch (_) { return null; }
}
function setAction(name, execute, args, wd) {
  const q = (s) => `'${String(s || '').replace(/'/g, "''")}'`;
  const script = `$a = New-ScheduledTaskAction -Execute ${q(execute)} -Argument ${q(args)}${wd ? ` -WorkingDirectory ${q(wd)}` : ''}; Set-ScheduledTask -TaskName ${q(name)} -Action $a | Out-Null; 'ok'`;
  return ps(script);
}

function main() {
  if (process.platform !== 'win32') { console.log('jobs/install: Windows Task Scheduler only; nothing to do here'); return 0; }
  const apply = process.argv.includes('--apply');
  let differ = 0, missing = 0, changed = 0;
  const rows = [];
  for (const [name, want] of Object.entries(JOBS)) {
    const have = current(name);
    if (!have) { missing++; rows.push(`MISSING  ${name}: not registered. ${want.note}. Register with a trigger of your choice, action: ${want.execute} ${want.args}`); continue; }
    const same = String(have.execute).toLowerCase() === want.execute.toLowerCase() && String(have.args || '').trim() === want.args.trim() && (!want.workingDirectory || String(have.wd || '').toLowerCase() === want.workingDirectory.toLowerCase());
    if (same) { rows.push(`ok       ${name}`); continue; }
    differ++;
    if (apply) { const r = setAction(name, want.execute, want.args, want.workingDirectory); if (r.ok) { changed++; rows.push(`UPDATED  ${name} -> ${want.args}`); } else rows.push(`FAILED   ${name}: ${r.err.slice(0, 160)}`); }
    else rows.push(`DIFFERS  ${name}\n           has:  ${have.execute} ${have.args}\n           want: ${want.execute} ${want.args}`);
  }
  for (const [name, rules] of Object.entries(ARG_REWRITES)) {
    const have = current(name);
    if (!have) { rows.push(`absent   ${name} (chained by another product; nothing to re-point)`); continue; }
    let args = String(have.args || '');
    for (const [re, to] of rules) args = args.replace(re, to);
    if (args === String(have.args || '')) { rows.push(`ok       ${name}`); continue; }
    differ++;
    if (apply) { const r = setAction(name, have.execute, args, have.wd); if (r.ok) { changed++; rows.push(`UPDATED  ${name} -> ${args}`); } else rows.push(`FAILED   ${name}: ${r.err.slice(0, 160)}`); }
    else rows.push(`DIFFERS  ${name}\n           has:  ${have.args}\n           want: ${args}`);
  }
  console.log(rows.join('\n'));
  console.log(`\njobs: ${Object.keys(JOBS).length + Object.keys(ARG_REWRITES).length} known, ${differ} differ, ${missing} missing${apply ? `, ${changed} updated` : ' (run with --apply to re-point)'}`);
  return apply && changed !== differ ? 1 : 0;
}

if (require.main === module) process.exit(main());
module.exports = { JOBS, ARG_REWRITES };
