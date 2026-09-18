#!/usr/bin/env node
// precompact-extract.cjs — PreCompact hook (auto | manual)
// Scans the tail of the session transcript right before compaction and extracts:
// 1. Explicit decisions ("decided to", "choice:", etc.)
// 2. Stated solutions, fixes and root causes
// 3. Stashes them into the active project's memory/context or daily memory file.
// Fail-open: Never blocks compaction.
//
// Fixed 2026-09-18: the hook read `evt.transcript`, a field the PreCompact payload
// never carries (it carries `transcript_path`), so it exited on every compaction
// and had never written a line. It now reads the transcript file's tail.
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');

const TAIL_BYTES = 512 * 1024;

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

const transcript = readTranscriptText(evt);
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
  // Fall back to the auto-memory store's context dir (the same one MEMORY.md routes to)
  memDir = path.join(os.homedir(), '.claude', 'projects', 'C--Users-sandm--claude', 'memory', 'context');
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

/**
 * Human and assistant TEXT from the transcript tail, tool payloads skipped: the
 * patterns above look for what was said, and tool output is where they false-match.
 * Inline `transcript`/`content` fields are still honoured for callers that pass them.
 */
function readTranscriptText(e) {
  if (typeof e.transcript === 'string' && e.transcript) return e.transcript;
  if (typeof e.content === 'string' && e.content) return e.content;
  const p = e.transcript_path;
  if (!p) return '';
  let raw;
  try {
    const fd = fs.openSync(p, 'r');
    try {
      const size = fs.fstatSync(fd).size;
      const len = Math.min(size, TAIL_BYTES);
      const buf = Buffer.alloc(len);
      fs.readSync(fd, buf, 0, len, size - len);
      raw = buf.toString('utf8');
    } finally { fs.closeSync(fd); }
  } catch { return ''; }
  const out = [];
  for (const line of raw.split('\n')) {
    let j; try { j = JSON.parse(line); } catch { continue; }
    if (j.type !== 'user' && j.type !== 'assistant') continue;
    const c = j.message && j.message.content;
    if (typeof c === 'string') out.push(c);
    else if (Array.isArray(c)) for (const b of c) if (b && b.type === 'text' && typeof b.text === 'string') out.push(b.text);
  }
  return out.join('\n');
}
