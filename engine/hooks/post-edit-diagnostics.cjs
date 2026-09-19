#!/usr/bin/env node
// post-edit-diagnostics.cjs — PostToolUse [Edit|Write|MultiEdit]
//
// Right after an edit lands, run the cheapest read-only check the file's language
// has and hand the findings back on the same tool result. A syntax error or an
// undefined name surfaces on the edit turn, not two turns later when a test run
// or a hook load fails for a reason the model then has to rediscover.
// arXiv:2609.20804 §2.4 held this fixed across every ablation ("post-edit
// diagnostics"); here it matters twice over, because a syntax error in one of
// these .cjs guards disables the guard silently.
//
//   .py               ruff check, error-only rules (syntax, undefined names, bad
//                     comparisons, misplaced statements) — the pyflakes subset
//   .js .cjs .mjs     node --check
//   .json             JSON.parse
//   .ts .tsx          skipped: the typescript-lsp plugin reports these itself
//
// Advisory only: additionalContext on findings, silence otherwise. Fail-open on a
// missing checker, a timeout or any error. Every run is logged so the value of the
// mechanism can be read from data:   node hooks/post-edit-diagnostics.cjs --report
//
// Env: POST_EDIT_DIAG_OFF=1 disables. POST_EDIT_DIAG_LOG overrides the log path.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const LOG = process.env.POST_EDIT_DIAG_LOG || path.join(os.homedir(), '.claude', 'logs', 'post-edit-diagnostics.jsonl');
const TIMEOUT_MS = 4000;
const MAX_CHARS = 1500;
const RUFF_RULES = 'E9,F63,F7,F82';

if (process.argv.includes('--report')) { report(); process.exit(0); }
if (process.env.POST_EDIT_DIAG_OFF === '1') process.exit(0);

let input;
try { input = JSON.parse(fs.readFileSync(0, 'utf8')); } catch { process.exit(0); }

const tool = input.tool_name || '';
if (!['Edit', 'Write', 'MultiEdit'].includes(tool)) process.exit(0);
const file = String((input.tool_input || {}).file_path || '');
if (!file || /node_modules|[\\/]\.git[\\/]/.test(file)) process.exit(0);
let text = null;
try { if (!fs.statSync(file).isFile()) process.exit(0); } catch { process.exit(0); }

const ext = path.extname(file).toLowerCase();
const t0 = Date.now();
let lang = null;
let findings = '';

try {
  if (ext === '.py') {
    lang = 'python';
    findings = run('ruff', ['check', '--isolated', '--no-cache', '--quiet', '--exit-zero', '--select', RUFF_RULES, '--output-format', 'concise', file]);
  } else if (ext === '.js' || ext === '.cjs' || ext === '.mjs') {
    lang = 'node';
    findings = run(process.execPath, ['--check', file]);
  } else if (ext === '.json') {
    lang = 'json';
    text = fs.readFileSync(file, 'utf8');
    try { JSON.parse(text); } catch (e) { findings = e.message; }
  }
} catch {
  process.exit(0); // any surprise: say nothing
}
if (!lang) process.exit(0);

findings = String(findings || '').trim();
if (findings.length > MAX_CHARS) findings = findings.slice(0, MAX_CHARS) + `\n… (${findings.length} chars)`;
log({ ts: new Date().toISOString(), session: String(input.session_id || '').slice(0, 8), tool, file, lang, ok: !findings, ms: Date.now() - t0, lines: findings ? findings.split('\n').length : 0 });
if (!findings) process.exit(0);

process.stdout.write(JSON.stringify({
  hookSpecificOutput: {
    hookEventName: 'PostToolUse',
    additionalContext: `[post-edit diagnostics] ${lang} check of ${file} reports:\n${findings}\nFix this before running tests or loading the file; the edit itself was applied.`,
  },
}));
process.exit(0);

/** Run a checker; a missing binary or a timeout is silence (null), never a finding. */
function run(cmd, args) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: TIMEOUT_MS, windowsHide: true, shell: false });
  if (r.error) return null; // ENOENT (checker not installed) or timeout: fail open
  const out = `${r.stdout || ''}${r.stderr || ''}`;
  // node --check prints nothing on success; ruff --exit-zero prints only findings.
  return out.replace(/^\s*All checks passed!?\s*$/m, '').trim();
}

function log(row) {
  try { fs.mkdirSync(path.dirname(LOG), { recursive: true }); fs.appendFileSync(LOG, JSON.stringify(row) + '\n'); } catch {}
}

function report() {
  let lines = [];
  try { lines = fs.readFileSync(LOG, 'utf8').trim().split('\n').filter(Boolean); } catch {}
  const days = {};
  for (const l of lines) {
    let r; try { r = JSON.parse(l); } catch { continue; }
    const d = String(r.ts || '').slice(0, 10);
    const b = (days[d] = days[d] || { runs: 0, findings: 0, ms: 0, langs: {} });
    b.runs++; if (!r.ok) b.findings++; b.ms += r.ms || 0; b.langs[r.lang] = (b.langs[r.lang] || 0) + 1;
  }
  console.log(`post-edit-diagnostics: ${lines.length} checks logged`);
  for (const d of Object.keys(days).sort()) {
    const b = days[d];
    console.log(`  ${d}  checks=${b.runs}  with-findings=${b.findings}  mean=${Math.round(b.ms / b.runs)}ms  ` + Object.entries(b.langs).map(([k, v]) => `${k}=${v}`).join(' '));
  }
}
