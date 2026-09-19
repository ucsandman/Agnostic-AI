#!/usr/bin/env node
// context-graph-bench.cjs — replay real user prompts from recent transcripts
// through the context-graph selector and report what it would have loaded,
// against the eager baseline (what every session loads regardless).
//
//   node ~/.claude/tools/tokflow/context-graph-bench.cjs [--days 14] [--limit 300] [--json]
//
// No side effects: the hook's session state and ledger are never touched; the
// engine's bundle() is called directly with an empty "already" set per session
// (so dedup within a session is simulated in order, as the hook would see it).
// Token counts are the engine's estimate (4 chars/token), the same estimator the
// hook's ledger uses, so the two are comparable; neither is a billed figure.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const HOME = os.homedir();
const PROJECTS = path.join(HOME, '.claude', 'projects');
const CONFIG = process.env.CONTEXT_GRAPH_CONFIG || path.join(HOME, '.claude', 'hooks', 'context-graph.json');
const args = process.argv.slice(2);
const flag = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const DAYS = Number(flag('--days', 14));
const LIMIT = Number(flag('--limit', 300));
const JSON_OUT = args.includes('--json');

const cfgRaw = JSON.parse(fs.readFileSync(CONFIG, 'utf8'));
const engine = require(cfgRaw.engine || 'C:/Projects/agnostic-ai/engine/context/index.cjs');
const cfg = engine.config.load(CONFIG);
const since = Date.now() - DAYS * 86400000;

// 1. real prompts: human turns from main-thread transcripts, newest sessions first
const prompts = [];
for (const d of fs.readdirSync(PROJECTS)) {
  if (/scratchpad|Temp/i.test(d)) continue; // probe/toy sessions are not representative
  const dir = path.join(PROJECTS, d);
  let files = [];
  try { files = fs.readdirSync(dir).filter((f) => f.endsWith('.jsonl')).map((f) => ({ f: path.join(dir, f), m: fs.statSync(path.join(dir, f)).mtimeMs })).filter((x) => x.m >= since); } catch { continue; }
  for (const { f } of files.sort((a, b) => b.m - a.m).slice(0, 6)) {
    let cwd = null;
    for (const line of fs.readFileSync(f, 'utf8').split('\n')) {
      let o; try { o = JSON.parse(line); } catch { continue; }
      if (o.cwd) cwd = o.cwd;
      if (o.type !== 'user' || o.isMeta || typeof (o.message && o.message.content) !== 'string') continue;
      const text = o.message.content;
      // the hook skips machine turns by `source`; older transcripts lack the field, so skip them by shape
      if (text.length < 12 || text.trim().startsWith('/') || /^\[Subagent Context\]|^\(Continuing the same session|<system-reminder>|<command-name>|<task-notification>|<local-command-stdout>|^\[.{5,40}\] \[Subagent/.test(text)) continue;
      prompts.push({ session: path.basename(f, '.jsonl'), project: d, cwd: cwd || null, text: text.slice(0, 4000), ts: o.timestamp || null });
    }
  }
}
prompts.sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
const sample = prompts.slice(-LIMIT);

// 2. replay, per session in order, simulating the hook's session dedup + cap
const bySession = new Map();
const rows = [];
let t0 = Date.now();
for (const p of sample) {
  const st = bySession.get(p.session) || { already: {}, used: 0 };
  bySession.set(p.session, st);
  const r = engine.bundle({ cfg, signals: { prompt: p.text, cwd: p.cwd || HOME, client: cfg.client }, already: st.already, sessionUsed: st.used });
  for (const l of r.packed.loaded) st.already[l.name] = l.hash;
  st.used += r.packed.tokens.loaded;
  rows.push({ project: p.project, session: p.session.slice(0, 8), prompt: p.text.replace(/\s+/g, ' ').slice(0, 90), targets: r.targets, loaded: r.packed.loaded.map((l) => `${l.name}:${l.tokens}`), tokens: r.packed.tokens.loaded, deduped: r.packed.tokens.deduped, rejected: r.packed.rejected.map((x) => `${x.name}:${x.reason}`), candidates: r.selection ? r.selection.candidates.map((c) => c.name) : [] });
}
const ms = Date.now() - t0;

// 3. the eager baseline: files every session loads regardless of task
const eager = (cfg.eagerBaseline || []).map((f) => { const p = engine.config.expand(f); let chars = 0; try { chars = fs.readFileSync(p, 'utf8').length; } catch {} return { file: f, chars, tokens: Math.ceil(chars / 4) }; });
const eagerTokens = eager.reduce((s, e) => s + e.tokens, 0);
// what the migrated rules sections cost when they were standing text (bytes moved out of global-rules.md on 2026-09-19)
const modulesDir = engine.config.expand('C:/Projects/agnostic-ai/core/rules/modules');
const migrated = fs.existsSync(modulesDir) ? fs.readdirSync(modulesDir).filter((f) => f.endsWith('.md')).map((f) => { const t = fs.readFileSync(path.join(modulesDir, f), 'utf8'); const body = t.replace(/^---[\s\S]*?---\n/, ''); return { name: f.replace(/\.md$/, ''), tokens: Math.ceil(body.length / 4) }; }) : [];

const loadedTurns = rows.filter((r) => r.tokens > 0).length;
const totalLoaded = rows.reduce((s, r) => s + r.tokens, 0);
const totalDeduped = rows.reduce((s, r) => s + r.deduped, 0);
const sessions = bySession.size;
const perSession = [...bySession.values()].map((s) => s.used);
const byModule = {};
for (const r of rows) for (const l of r.loaded) { const [n, t] = l.split(':'); byModule[n] = byModule[n] || { loads: 0, tokens: 0 }; byModule[n].loads++; byModule[n].tokens += Number(t); }
const out = {
  window: { days: DAYS, prompts: sample.length, sessions, projects: new Set(sample.map((p) => p.project)).size, replayMs: ms },
  dynamic: { turnsWithLoad: loadedTurns, tokensLoaded: totalLoaded, tokensDeduped: totalDeduped, meanPerSession: sessions ? Math.round(perSession.reduce((a, b) => a + b, 0) / sessions) : 0, maxPerSession: Math.max(0, ...perSession), byModule },
  eager: { files: eager, tokensPerSession: eagerTokens, migratedModules: migrated, migratedTokens: migrated.reduce((s, m) => s + m.tokens, 0) },
  rows,
};
if (JSON_OUT) { console.log(JSON.stringify(out, null, 2)); process.exit(0); }
console.log(`context-graph bench: ${sample.length} real prompts from ${sessions} sessions across ${out.window.projects} projects, last ${DAYS} days (replayed in ${ms} ms)`);
console.log(`  eager baseline every session pays regardless of task: ${eagerTokens.toLocaleString()} tok (${eager.map((e) => path.basename(e.file) + ' ' + e.tokens.toLocaleString()).join(', ')})`);
console.log(`  rules text moved out of the always-loaded file into modules: ${out.eager.migratedTokens.toLocaleString()} tok (${migrated.map((m) => m.name + ' ' + m.tokens).join(', ')})`);
console.log(`  dynamic: ${loadedTurns} of ${sample.length} prompts loaded something; ${totalLoaded.toLocaleString()} tok loaded in total, ${totalDeduped.toLocaleString()} tok of repeats avoided by session dedup`);
console.log(`  per session: mean ${out.dynamic.meanPerSession.toLocaleString()} tok injected (max ${out.dynamic.maxPerSession.toLocaleString()}, cap ${cfg.budget.sessionTokens.toLocaleString()})`);
console.log(`  net per session vs. keeping the migrated text global: ${(out.eager.migratedTokens - out.dynamic.meanPerSession).toLocaleString()} tok (positive = the graph loads less than the standing text did; it also loads docs and memory the standing text never carried)`);
const top = Object.entries(byModule).sort((a, b) => b[1].loads - a[1].loads).slice(0, 12);
console.log('  most selected:');
for (const [n, v] of top) console.log(`    ${n.padEnd(44)} ${String(v.loads).padStart(3)} loads  ${v.tokens.toLocaleString().padStart(7)} tok`);
console.log('  sample of prompts that loaded something:');
for (const r of rows.filter((r) => r.tokens > 0).slice(-8)) console.log(`    [${r.project.slice(0, 28).padEnd(28)}] "${r.prompt}" -> ${r.loaded.join(', ')}`);
