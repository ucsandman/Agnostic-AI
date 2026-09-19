#!/usr/bin/env node
// Token usage per Claude Code session, from transcript JSONL usage fields.
//   node usage.cjs <transcript.jsonl> [...]     one or more files
//   node usage.cjs --recent 5                   the 5 most recently modified transcripts under ~/.claude/projects
// Prints the fixed context of the first call (system prompt + first message), per-call
// context, totals, cache re-creation on later calls, and injected system-reminder/tool-result volume.
const fs = require('fs');
const os = require('os');
const path = require('path');
let files = process.argv.slice(2);
if (files[0] === '--recent') {
  const n = +files[1] || 5; const root = path.join(os.homedir(), '.claude', 'projects'); const all = [];
  for (const d of fs.readdirSync(root, { withFileTypes: true })) if (d.isDirectory()) for (const f of fs.readdirSync(path.join(root, d.name))) if (f.endsWith('.jsonl')) { const p = path.join(root, d.name, f); all.push([fs.statSync(p).mtimeMs, p]); }
  files = all.sort((a, b) => b[0] - a[0]).slice(0, n).map(x => x[1]);
}
if (!files.length) { console.log('usage: node usage.cjs <transcript.jsonl>... | --recent N'); process.exit(1); }
for (const file of files) {
  if (!fs.existsSync(file)) { console.log('missing', file); continue; }
  const lines = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean);
  const byId = new Map(); const order = []; let userMsgs = 0, remChars = 0, toolResChars = 0, model = '';
  for (const l of lines) {
    let j; try { j = JSON.parse(l); } catch { continue; }
    if (j.type === 'assistant' && j.message && j.message.usage) {
      const id = j.message.id || j.uuid; const u = j.message.usage; model = j.message.model || model;
      if (!byId.has(id)) order.push(id);
      byId.set(id, { in: u.input_tokens || 0, cc: u.cache_creation_input_tokens || 0, cr: u.cache_read_input_tokens || 0, out: u.output_tokens || 0 });
    }
    if (j.type === 'user' && j.message) {
      userMsgs++;
      const c = j.message.content; const blocks = Array.isArray(c) ? c : [{ type: 'text', text: String(c) }];
      for (const b of blocks) {
        const txt = b.type === 'text' ? b.text : b.type === 'tool_result' ? (typeof b.content === 'string' ? b.content : JSON.stringify(b.content || '')) : '';
        if (!txt) continue;
        if (b.type === 'tool_result') toolResChars += txt.length;
        remChars += (txt.match(/<system-reminder>[\s\S]*?<\/system-reminder>/g) || []).reduce((s, m) => s + m.length, 0);
      }
    }
  }
  const calls = order.map(id => byId.get(id));
  if (!calls.length) { console.log('no usage in', path.basename(file)); continue; }
  const first = calls[0]; const ctx = calls.map(c => c.in + c.cc + c.cr);
  const sum = k => calls.reduce((s, c) => s + c[k], 0);
  let misses = 0, lost = 0, prev = null;
  for (const c of calls) { if (prev && c.cr < 0.9 * (prev.cr + prev.cc)) { misses++; lost += prev.cr + prev.cc - c.cr; } prev = c; }
  console.log(`\n=== ${path.basename(file)}  model=${model}  api_calls=${calls.length}  user_msgs=${userMsgs}`);
  console.log(`fixed context (first call): ${first.in + first.cc + first.cr} tok  (cache_read=${first.cr} cache_create=${first.cc})`);
  console.log(`context per call: min=${Math.min(...ctx)} avg=${Math.round(ctx.reduce((a, b) => a + b, 0) / ctx.length)} max=${Math.max(...ctx)}`);
  console.log(`totals: cache_read=${sum('cr')} cache_create=${sum('cc')} uncached_in=${sum('in')} out=${sum('out')}`);
  console.log(`cache prefix lost on later calls: ${misses}/${Math.max(0, calls.length - 1)} calls, ${lost} tok  (a loss right after compaction is expected)`);
  console.log(`injected: system-reminder ~${Math.round(remChars / 4)} tok, tool_result ~${Math.round(toolResChars / 4)} tok`);
}
