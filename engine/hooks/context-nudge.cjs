#!/usr/bin/env node
/**
 * engine/hooks/context-nudge.cjs — once per high-context crossing, prompt Claude to advise /compact or /clear.
 *
 * Port of context-nudge.py (2026-09-19): the python spawn alone cost 5 s under load
 * and timed out on every prompt. Same behaviour: reads the live context percentage
 * that statusline.ps1 publishes to %TEMP%\claude_ctx_<session>.txt and fires once
 * per crossing of THRESHOLD (re-arms when the reading drops back below it).
 *
 * Stands down when mods-config.json runs contextNudge in "mod" mode and the Mod's
 * heartbeat for this session armed it (hooks/lib/mods-mode.cjs standsDown).
 * Fail-safe: any error means no output. Runs inside prompt-dispatch.cjs.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { standsDown } = require('./lib/mods-mode.cjs');

const THRESHOLD = 80;

function main(evt) {
  const sid = String(evt.session_id || '').trim();
  if (!sid) return '';
  try { if (standsDown('contextNudge', sid).standDown) return ''; } catch (_) { /* any doubt: enforce */ }
  const safe = sid.replace(/[^A-Za-z0-9_-]/g, '_');
  const tmp = process.env.TEMP || process.env.TMP || os.tmpdir();
  const pctFile = path.join(tmp, `claude_ctx_${safe}.txt`);
  const flag = path.join(tmp, `claude_ctxnudge_${safe}.flag`);
  let pct;
  try { pct = parseInt(fs.readFileSync(pctFile, 'utf8').trim(), 10); } catch (_) { return ''; }
  if (!Number.isFinite(pct)) return '';
  if (pct >= THRESHOLD && !fs.existsSync(flag)) {
    try { fs.writeFileSync(flag, '1'); } catch (_) {}
    return `[context-budget] This session is at ~${pct}% of the context window. Tell Wes once, briefly: if the next task is unrelated to this thread use /clear; if continuing the same task use /compact. Long contexts are billed every turn even when cached.`;
  }
  if (pct < THRESHOLD && fs.existsSync(flag)) { try { fs.unlinkSync(flag); } catch (_) {} }
  return '';
}

if (require.main === module) {
  let evt = {};
  try { evt = JSON.parse(fs.readFileSync(0, 'utf8')); } catch (_) {}
  let text = '';
  try { text = main(evt); } catch (_) {}
  if (text) process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: text } }));
  process.exit(0);
}

module.exports = { main, THRESHOLD };
