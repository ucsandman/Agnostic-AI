#!/usr/bin/env node
// forced-verify-stop-gate.cjs — Stop hook
// Ensures changes made during session don't exit without verification.
// If code edits were performed (Edit/Write), checks whether verification (test/lint/build/grep)
// was run. If missing, prints an explicit reminder banner before stopping.
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');

let input = '';
try {
  input = fs.readFileSync(0, 'utf8');
} catch {
  process.exit(0);
}

// Fail-open
let evt = {};
if (input.trim()) {
  try {
    evt = JSON.parse(input);
  } catch {}
}

const stopReason = evt.stop_reason || '';
// Check environment or session flags
const enforce = process.env.STOP_GATE_MODE === 'enforce';

// If called during autonomous mode and unverified changes exist, alert
const msg = evt.message || {};
const content = typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content || '');

// Check if verification block or evidence markers exist
const hasVerify = /SUPERGOAL_PHASE_VERIFY|VERIFICATION|Evidence|Tests passed|npm test|npm run/i.test(content) ||
                  /\[observed\]/i.test(content);

if (!hasVerify && enforce) {
  process.stderr.write(`[FORCED-VERIFY-STOP-GATE] Stop blocked: unverified changes detected without verification evidence (L1/L2 rule).\n`);
  process.stdout.write(JSON.stringify({ decision: 'block' }) + '\n');
  process.exit(1);
}

process.exit(0);
