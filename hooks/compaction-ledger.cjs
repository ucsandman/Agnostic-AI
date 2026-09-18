#!/usr/bin/env node
// compaction-ledger.cjs — PreCompact + PostCompact (auto | manual)
//
// One JSONL row per compaction event, carrying the token counts Claude Code hands
// the hook (`context_window_stats`), so the questions "how often does this harness
// compact, at what size, and how much does each pass free" have an answer in data.
// The 2026-09-02 token audit had to infer "0 compaction events" from transcript
// shapes; this records them at the source. arXiv:2609.20804 found compaction's
// value is preventing overflow, so the ledger is also how a change to
// `autoCompactWindow` gets judged: rows before vs rows after.
//
// Observation only: writes nothing to the model, never blocks.
//   node hooks/compaction-ledger.cjs --report
// Env: COMPACTION_LEDGER_LOG overrides the path.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const LOG = process.env.COMPACTION_LEDGER_LOG || path.join(os.homedir(), '.claude', 'logs', 'compaction.jsonl');

if (process.argv.includes('--report')) { report(); process.exit(0); }

let evt;
try { evt = JSON.parse(fs.readFileSync(0, 'utf8')); } catch { process.exit(0); }
const event = evt.hook_event_name;
if (event !== 'PreCompact' && event !== 'PostCompact') process.exit(0);

const s = evt.context_window_stats || {};
try {
  fs.mkdirSync(path.dirname(LOG), { recursive: true });
  fs.appendFileSync(LOG, JSON.stringify({
    ts: new Date().toISOString(),
    session: String(evt.session_id || '').slice(0, 8),
    event,
    reason: evt.compaction_reason || evt.trigger || null,
    input_tokens: num(s.input_tokens), output_tokens: num(s.output_tokens), total_tokens: num(s.total_tokens), max_tokens: num(s.max_tokens),
    cwd: evt.cwd || null,
  }) + '\n');
} catch {}
process.exit(0);

function num(v) { return typeof v === 'number' && Number.isFinite(v) ? v : null; }

function report() {
  let rows = [];
  try { rows = fs.readFileSync(LOG, 'utf8').trim().split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean); } catch {}
  const pre = rows.filter((r) => r.event === 'PreCompact');
  const post = rows.filter((r) => r.event === 'PostCompact');
  console.log(`compaction-ledger: ${rows.length} rows (${pre.length} pre, ${post.length} post)`);
  const days = {};
  for (const r of pre) { const d = String(r.ts).slice(0, 10); (days[d] = days[d] || { n: 0, auto: 0, before: [] }).n++; if (r.reason === 'auto') days[d].auto++; if (r.total_tokens) days[d].before.push(r.total_tokens); }
  // pair each PreCompact with the next PostCompact of the same session for tokens freed
  const freed = [];
  for (const p of pre) {
    const q = post.find((x) => x.session === p.session && x.ts > p.ts);
    if (q && p.total_tokens && q.total_tokens) freed.push(p.total_tokens - q.total_tokens);
  }
  for (const d of Object.keys(days).sort()) {
    const b = days[d];
    const mean = b.before.length ? Math.round(b.before.reduce((a, x) => a + x, 0) / b.before.length) : null;
    console.log(`  ${d}  compactions=${b.n}  auto=${b.auto}  mean-context-before=${mean === null ? '?' : mean}`);
  }
  if (freed.length) console.log(`  tokens freed per pass: mean ${Math.round(freed.reduce((a, x) => a + x, 0) / freed.length)} over ${freed.length} paired passes`);
}
