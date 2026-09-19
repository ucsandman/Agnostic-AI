#!/usr/bin/env node
/**
 * engine/hooks/wakeup-guard.cjs — stop a session from answering "Waiting." to every machine wake-up.
 *
 * A Monitor, a ScheduleWakeup or a task notification wakes the model as a prompt
 * (transcript: origin.kind = task-notification, the prompt text starts with
 * <task-notification>). Each wake-up re-reads the whole context. On 2026-09-19 a
 * Monitor on "screenshots landing" fired once per PNG: 17 wake-ups in 45 minutes,
 * each answered with "Waiting.", 1.4M tokens for a workflow that had done 0 of 12.
 *
 * Counts consecutive machine wake-ups per session (a human prompt resets the
 * streak) and, from the third one on, injects a directive: no text answer, stop
 * the Monitor if nothing has progressed, re-arm at >= 1200 s. Runs inside
 * prompt-dispatch.cjs; standalone it takes the same JSON on stdin.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const HOME = process.env.USERPROFILE || os.homedir();
const STATE_DIR = path.join(HOME, '.claude', 'state', 'wakeups');
const WARN_AT = 3;
const MAX_AGE_MS = 24 * 3600 * 1000;
const MACHINE_PROMPT = /^\s*(<task-notification>|<system-reminder>|\[Scheduled wake-?up|<<autonomous-loop)/i;

function isMachineTurn(evt) {
  if (evt.source && !['user', 'sdk'].includes(String(evt.source))) return true;
  return MACHINE_PROMPT.test(String(evt.prompt || ''));
}

function statePath(sid) { return path.join(STATE_DIR, String(sid).replace(/[^A-Za-z0-9_-]/g, '_') + '.json'); }

function cleanup() {
  try { for (const f of fs.readdirSync(STATE_DIR)) { const p = path.join(STATE_DIR, f); if (Date.now() - fs.statSync(p).mtimeMs > MAX_AGE_MS) fs.unlinkSync(p); } } catch (_) {}
}

function directive(n) {
  return `[wakeup-guard] ${n} consecutive machine wake-ups in this session (Monitor / ScheduleWakeup / task notification) with no human prompt between them. Every wake-up re-reads the whole context. Do not answer with a line like "Waiting.": if nothing changed, end the turn with no message and no tool call. If the thing you are waiting on has made no progress across these wake-ups, stop the Monitor and the stalled task (TaskStop) now, tell Wes in one line what stalled, and stop. A Monitor that fires per file is the wrong granularity: the workflow's own completion notification is enough. Re-arm only with ScheduleWakeup delaySeconds >= 1200.`;
}

/** Returns the additionalContext to inject ('' = nothing). Exported for the dispatcher and the probe. */
function main(evt, opts = {}) {
  const sid = String(evt.session_id || '').trim();
  if (!sid || evt.hook_event_name !== 'UserPromptSubmit') return '';
  const file = statePath(sid);
  let st = { streak: 0 };
  try { st = JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) {}
  if (!isMachineTurn(evt)) {
    if (st.streak) try { fs.unlinkSync(file); } catch (_) {}
    return '';
  }
  st.streak = (st.streak || 0) + 1;
  st.ts = Date.now();
  try { fs.mkdirSync(STATE_DIR, { recursive: true }); fs.writeFileSync(file, JSON.stringify(st)); } catch (_) {}
  if (st.streak === 1) cleanup();
  return st.streak >= (opts.warnAt || WARN_AT) ? directive(st.streak) : '';
}

if (require.main === module) {
  let evt = {};
  try { evt = JSON.parse(fs.readFileSync(0, 'utf8')); } catch (_) {}
  let text = '';
  try { text = main(evt); } catch (_) {}
  if (text) process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: text } }));
  process.exit(0);
}

module.exports = { main, isMachineTurn, directive, STATE_DIR, WARN_AT };
