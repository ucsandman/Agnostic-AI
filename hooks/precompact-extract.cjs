#!/usr/bin/env node
// precompact-extract.cjs — PreCompact hook (auto | manual)
// Scans the active conversation/transcript right before compaction and extracts:
// 1. Explicit decisions ("decided to", "choice:", etc.)
// 2. Open debt or unverified tasks
// 3. Stashes them into the active project's memory/context or daily memory file.
// Fail-open: Never blocks compaction.
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

if (!input.trim()) process.exit(0);

let evt;
try {
  evt = JSON.parse(input);
} catch {
  process.exit(0);
}

const transcript = evt.transcript || evt.content || '';
if (!transcript || transcript.length < 50) process.exit(0);

const cwd = evt.cwd || process.cwd();
const dateStr = new Date().toISOString().slice(0, 10);

// Look for decision / resolution patterns in the text
const PATTERNS = [
  /(?:decided|decision|chose|agreed)\s+(?:to\s+)?([^\r\n.]{15,120})/gi,
  /(?:solution|fix)\s+(?:was|is)\s*:?\s*([^\r\n.]{15,120})/gi,
  /(?:root cause)\s*(?:was|is)\s*:?\s*([^\r\n.]{15,120})/gi
];

const findings = [];
for (const re of PATTERNS) {
  let m;
  while ((m = re.exec(transcript)) !== null) {
    const item = m[1].trim();
    if (item.length >= 15 && !findings.includes(item)) {
      findings.push(item);
    }
  }
}

if (findings.length === 0) process.exit(0);

// Determine target memory location
let memDir = path.join(cwd, '.agents', 'memory', 'context');
if (!fs.existsSync(path.dirname(memDir))) {
  // Fall back to home claude memory
  memDir = path.join(os.homedir(), '.claude', 'memory', 'context');
}

try {
  fs.mkdirSync(memDir, { recursive: true });
  const targetFile = path.join(memDir, `precompact-${dateStr}.md`);
  const header = fs.existsSync(targetFile) ? '' : `# Pre-Compaction Context Snapshot (${dateStr})\n\n`;
  const entries = findings.slice(0, 5).map(f => `- [observed] (${new Date().toISOString()}) ${f}`).join('\n') + '\n';
  fs.appendFileSync(targetFile, header + entries, 'utf8');
} catch {
  // Fail-open
}

process.exit(0);
