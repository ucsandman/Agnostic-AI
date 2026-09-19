#!/usr/bin/env node
// Self-check for context-graph.cjs: drives every event with real JSON payloads
// against a temp module root and proves it injects, dedups, stashes a subagent
// brief, re-injects after compaction, resets on clear, stays silent on a miss
// and on bad input (L1: the miss and the bad-input cases are the negative
// controls). Prints the wall time per event. Run:
//   node ~/.claude/hooks/tests/context-graph-probe.cjs
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const HOOK = path.join(__dirname, '..', 'context-graph.cjs');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'context-graph-probe-'));
const mods = path.join(dir, 'mods'); fs.mkdirSync(mods);
const w = (f, t) => fs.writeFileSync(path.join(mods, f), t);
w('creds.md', '---\nname: creds\ndescription: creds\ncontext:\n  triggers:\n    keywords: [secrets, BASH_ENV]\n    paths: ["**/hooks/**"]\n    commands: [load-secrets]\n  requires: [shell-model]\n---\nCreds load through BASH_ENV.\n');
w('shell-model.md', '---\nname: shell-model\ndescription: shell\n---\nBash is non-login; PowerShell is -NoProfile.\n');
w('scout.md', '---\nname: scout\ndescription: scout brief rules\ncontext:\n  triggers:\n    agents: [haiku-scout]\n---\nReport paths, never opinions.\n');
w('leak.md', '---\nname: leak\ndescription: has a secret\ncontext:\n  triggers:\n    keywords: [leaky]\n---\nkey sk-ant-' + 'a'.repeat(40) + '\n');
const cfgFile = path.join(dir, 'cfg.json');
fs.writeFileSync(cfgFile, JSON.stringify({ version: 1, client: 'claude', engine: 'C:/Projects/agnostic-ai/engine/context/index.cjs', roots: [{ id: 't', path: mods, scope: 'user', trust: 'user' }], budget: { turnTokens: 2500, sessionTokens: 12000, subagentTokens: 800 }, selection: { threshold: 2, minPromptChars: 12 } }));
const env = { ...process.env, CONTEXT_GRAPH_CONFIG: cfgFile, CONTEXT_GRAPH_LEDGER: path.join(dir, 'ledger.jsonl'), CONTEXT_GRAPH_STATE: path.join(dir, 'state') };

let pass = 0, fail = 0;
function run(label, evt, expect, extraEnv) {
  const t = Date.now();
  const r = spawnSync('node', [HOOK], { input: typeof evt === 'string' ? evt : JSON.stringify(evt), encoding: 'utf8', env: { ...env, ...(extraEnv || {}) } });
  const ms = Date.now() - t;
  let ctxText = '';
  try { ctxText = JSON.parse(r.stdout).hookSpecificOutput.additionalContext; } catch {}
  const ok = expect(ctxText, r);
  console.log(`${ok ? 'PASS' : 'FAIL'} ${label} (${ms} ms, ${ctxText.length} chars injected, exit ${r.status})`);
  if (!ok) { console.log('  stdout: ' + r.stdout.slice(0, 300)); console.log('  stderr: ' + r.stderr.slice(0, 300)); fail++; } else pass++;
  return ctxText;
}
const base = { session_id: 'probe-s1', cwd: 'C:\\Projects\\thing', transcript_path: path.join(dir, 'none.jsonl') };

run('prompt hit injects creds with its prerequisite first', { ...base, hook_event_name: 'UserPromptSubmit', prompt: 'where do secrets get loaded via BASH_ENV' },
  (t) => t.includes('▸ shell-model') && t.includes('▸ creds') && t.indexOf('shell-model') < t.indexOf('▸ creds') && t.includes('why: keyword "secrets", "BASH_ENV"'));
run('same prompt again: everything already in context, nothing injected', { ...base, hook_event_name: 'UserPromptSubmit', prompt: 'where do secrets get loaded via BASH_ENV' }, (t) => t === '');
run('negative control: a prompt that matches nothing injects nothing', { ...base, hook_event_name: 'UserPromptSubmit', prompt: 'make the landing page button blue' }, (t) => t === '');
run('negative control: a slash command is ignored', { ...base, hook_event_name: 'UserPromptSubmit', prompt: '/mods status please now' }, (t) => t === '');
run('negative control: a machine turn (loop_wakeup) is ignored', { ...base, hook_event_name: 'UserPromptSubmit', source: 'loop_wakeup', prompt: 'secrets BASH_ENV secrets BASH_ENV' }, (t) => t === '');
run('secret shape in a module body is never injected', { ...base, hook_event_name: 'UserPromptSubmit', prompt: 'the leaky leaky module' }, (t) => t === '' || !t.includes('sk-ant-'));
run('PreToolUse Agent stashes the brief silently', { ...base, hook_event_name: 'PreToolUse', tool_name: 'Agent', tool_input: { subagent_type: 'haiku-scout', prompt: 'list every file that mentions BASH_ENV secrets' } }, (t, r) => t === '' && r.stdout === '');
run('SubagentStart gets its type module plus the brief-selected one', { ...base, hook_event_name: 'SubagentStart', agent_type: 'haiku-scout', agent_id: 'a1' },
  (t) => t.includes('for this haiku-scout') && t.includes('▸ scout') && t.includes('▸ creds'));
run('SessionStart compact re-injects the session set (required only)', { ...base, hook_event_name: 'SessionStart', source: 'compact' }, (t) => t.includes('re-injected after compaction') && t.includes('▸ creds') && t.includes('▸ shell-model'));
run('SessionStart clear resets; the next hit injects again', { ...base, hook_event_name: 'SessionStart', source: 'clear' }, (t) => t === '');
run('after clear the same prompt injects again', { ...base, hook_event_name: 'UserPromptSubmit', prompt: 'where do secrets get loaded via BASH_ENV' }, (t) => t.includes('▸ creds'));
run('PreToolUse Edit on a matching path injects by path (once)', { ...base, session_id: 'probe-s2', hook_event_name: 'PreToolUse', tool_name: 'Edit', tool_input: { file_path: 'C:\\Users\\x\\.claude\\hooks\\thing.cjs' } }, (t) => t.includes('▸ creds') && t.includes('why: path'));
run('the same Edit again injects nothing', { ...base, session_id: 'probe-s2', hook_event_name: 'PreToolUse', tool_name: 'Edit', tool_input: { file_path: 'C:\\Users\\x\\.claude\\hooks\\thing.cjs' } }, (t) => t === '');
run('PreToolUse Bash on a matching command injects by command (the retired dynamic-recall path)', { ...base, session_id: 'probe-s3', hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: 'cat ~/.claude/LOAD-SECRETS.sh | wc -l' } }, (t) => t.includes('▸ creds') && t.includes('why: command "load-secrets"'));
run('a Bash command with no trigger injects nothing', { ...base, session_id: 'probe-s3', hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: 'git status' } }, (t) => t === '');
run('bad JSON exits 0 with no output', '{not json', (_t, r) => r.status === 0 && r.stdout === '');
run('missing engine exits 0 with no output', { ...base, hook_event_name: 'UserPromptSubmit', prompt: 'secrets BASH_ENV please' }, (_t, r) => r.status === 0 && r.stdout === '', { CONTEXT_GRAPH_ENGINE: path.join(dir, 'nope.cjs') });

const rows = fs.readFileSync(path.join(dir, 'ledger.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
const okLedger = rows.some((r) => r.event === 'prompt' && r.packed && r.packed.loaded.length === 2) && rows.some((r) => r.event === 'subagent') && rows.some((r) => r.event === 'session:compact') && rows.some((r) => r.event === 'prompt' && r.packed && r.packed.deduped.length === 2);
console.log(`${okLedger ? 'PASS' : 'FAIL'} ledger has prompt/subagent/compact rows with loaded and deduped accounting (${rows.length} rows)`);
okLedger ? pass++ : fail++;
console.log(`\n${pass} passed, ${fail} failed`);
try { fs.rmSync(dir, { recursive: true, force: true }); } catch {}
process.exit(fail ? 1 : 0);
