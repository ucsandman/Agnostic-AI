#!/usr/bin/env node
// Per-API-call prompt-cache trace for one Claude Code transcript. A call whose cache_read is
// below 90% of the previous call's (cache_read + cache_create) lost its cached prefix; the row
// shows what preceded it so the cause (compaction, a catalog change, a system-reminder) is visible.
//   node cachetrace.cjs <transcript.jsonl> [all]     "all" prints every call, not only the misses
const fs = require('fs');
const path = require('path');
const [file, showAll] = process.argv.slice(2);
if (!file) { console.log('usage: node cachetrace.cjs <transcript.jsonl> [all]'); process.exit(1); }
const lines = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean);
const calls = new Map(); const order = [];
let lastUser = { kind: '-', head: '', len: 0 };
for (const l of lines) {
  let j; try { j = JSON.parse(l); } catch { continue; }
  if (j.type === 'user' && j.message) {
    const c = j.message.content; const blocks = Array.isArray(c) ? c : [{ type: 'text', text: String(c) }];
    let kind = blocks.some(b => b.type === 'tool_result') ? 'tool_result' : 'human';
    const txt = blocks.map(b => b.type === 'text' ? b.text : b.type === 'tool_result' ? (typeof b.content === 'string' ? b.content : JSON.stringify(b.content || '')) : '').join(' ');
    if (/<system-reminder>/.test(txt)) kind += '+sysrem';
    if (/<command-name>/.test(txt)) kind += '+slash';
    if (/skills are available|tools just became available|deferred tools are now available/.test(txt)) kind += '+CATALOG';
    if (/This session is being continued from a previous conversation/.test(txt)) kind += '+COMPACTION';
    lastUser = { kind, head: txt.replace(/\s+/g, ' ').slice(0, 110), len: txt.length };
  }
  if (j.type === 'system' || j.type === 'summary') lastUser = { kind: 'sys:' + (j.subtype || j.type), head: String(j.content || j.summary || '').slice(0, 110), len: 0 };
  if (j.type === 'assistant' && j.message && j.message.usage) {
    const id = j.message.id || j.uuid; const u = j.message.usage;
    if (!calls.has(id)) order.push(id);
    calls.set(id, { cr: u.cache_read_input_tokens || 0, cc: u.cache_creation_input_tokens || 0, in: u.input_tokens || 0, out: u.output_tokens || 0, prev: calls.has(id) ? calls.get(id).prev : lastUser, ts: j.timestamp });
  }
}
let prev = null, misses = 0, lost = 0, n = 0;
console.log(`=== ${path.basename(file)}  calls=${order.length}`);
for (const id of order) {
  const c = calls.get(id); n++;
  const expected = prev ? prev.cr + prev.cc : 0;
  const miss = prev && c.cr < 0.9 * expected;
  if (miss) { misses++; lost += expected - c.cr; }
  if (showAll || miss) console.log(`${String(n).padStart(3)} ${(c.ts || '').slice(11, 19)} read=${String(c.cr).padStart(6)} create=${String(c.cc).padStart(6)} in=${String(c.in).padStart(4)} out=${String(c.out).padStart(5)} ${miss ? 'MISS(-' + (expected - c.cr) + ')' : '      '} prev=${c.prev.kind}${c.prev.len ? '(' + c.prev.len + 'c)' : ''} :: ${c.prev.head}`);
  prev = c;
}
console.log(`misses=${misses}/${Math.max(0, order.length - 1)}  cached-prefix tokens lost=${lost}`);
