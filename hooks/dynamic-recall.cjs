#!/usr/bin/env node
// dynamic-recall.cjs — PreToolUse [Write|Edit|MultiEdit|Bash|PowerShell]
// Matches the active file or command against known architectural rules and patterns,
// dynamically injecting guidance into additionalContext if relevant.
// Keeps global prompts lean and avoids cognitive bloat.
'use strict';
const fs = require('fs');
const path = require('path');

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

const tool = evt.tool_name || evt.toolName || '';
const toolInput = evt.tool_input || {};
const filePath = toolInput.file_path || toolInput.path || toolInput.TargetFile || '';
const cmd = toolInput.command || toolInput.CommandLine || '';
const target = String(filePath || cmd);

if (!target) process.exit(0);

const rules = [
  {
    matcher: /sitemap|robots|llms\.txt/i,
    tip: "SEO Floor Reminder: Public web surface changes require sitemap, robots.txt, llms.txt, canonical, and real title/meta descriptions."
  },
  {
    matcher: /\.env|secrets/i,
    tip: "Secrets Non-Negotiable: Never read or commit raw .env files. Always use .env.example with placeholders."
  },
  {
    matcher: /settings\.json|hooks\.json/i,
    tip: "Harness Integrity: Hook modifications require mirror-sync to claude-harness and test verification."
  }
];

// Each tip fires once per session: the reminder is re-read on every later turn anyway.
const sessionId = String(evt.session_id || 'nosession').replace(/[^\w-]/g, '');
const markDir = path.join(__dirname, '..', 'state', 'dynamic-recall');
let seen = new Set();
const markFile = path.join(markDir, `${sessionId}.json`);
try { seen = new Set(JSON.parse(fs.readFileSync(markFile, 'utf8'))); } catch {}

const hits = rules.filter(r => r.matcher.test(target) && !seen.has(r.tip));
if (hits.length === 0) process.exit(0);

try {
  fs.mkdirSync(markDir, { recursive: true });
  for (const h of hits) seen.add(h.tip);
  fs.writeFileSync(markFile, JSON.stringify([...seen]));
  for (const f of fs.readdirSync(markDir)) {
    const fp = path.join(markDir, f);
    if (Date.now() - fs.statSync(fp).mtimeMs > 7 * 24 * 3600 * 1000) fs.unlinkSync(fp);
  }
} catch {}

const contextStr = hits.map(h => `[DYNAMIC RECALL] ${h.tip}`).join('\n');
const output = {
  hookSpecificOutput: {
    hookEventName: 'PreToolUse',
    additionalContext: contextStr
  }
};

process.stdout.write(JSON.stringify(output) + '\n');
process.exit(0);
