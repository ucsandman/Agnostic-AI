#!/usr/bin/env node
/*
 * mods/shadow-report.cjs — pair the classic and Mod comparison rows and answer the Phase-19 questions.
 *
 *   node ~/.claude/mods/shadow-report.cjs                # every session in mods/state/shadow
 *   node ~/.claude/mods/shadow-report.cjs --session <id> # one session
 *   node ~/.claude/mods/shadow-report.cjs --json
 *
 * Rows: state/shadow/<session>.classic.jsonl (written by the classic guards through
 * hooks/lib/mods-mode.cjs) and state/shadow/<session>.mod.jsonl (written by harness-mods). Both use
 * the row shape in harness-mods/hooks/lib/shadow.mjs and join on (session, subsystem, key).
 * A classic-only routing row means the classic guard denied BEFORE agent.spawn existed, so the Mod
 * never saw it; a mod-only row means the Mod decided where the classic side has no hook (redaction
 * of a result, a cache serve, a settle). Every count carries the volume it came from (L2).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME = process.env.USERPROFILE || os.homedir();
const DIR = path.join(HOME, '.claude', 'mods', 'state', 'shadow');
const args = process.argv.slice(2);
const only = args.includes('--session') ? args[args.indexOf('--session') + 1] : null;
const AS_JSON = args.includes('--json');

function readRows(file) {
  try { return fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch (_) { return null; } }).filter(Boolean); } catch (_) { return []; }
}
let files = [];
try { files = fs.readdirSync(DIR).filter((f) => f.endsWith('.jsonl') && (!only || f.startsWith(only))); } catch (_) {}
const rows = files.flatMap((f) => readRows(path.join(DIR, f)));
const sessions = new Set(rows.map((r) => r.session));

const by = {};
for (const r of rows) {
  const k = [r.session, r.subsystem, r.key].join('|');
  (by[k] = by[k] || { classic: [], mod: [] })[r.side === 'classic' ? 'classic' : 'mod'].push(r);
}
const norm = (d) => (d === 'rewrite' ? 'deny' : d);
const out = { files: files.length, rows: rows.length, sessions: sessions.size, bySubsystem: {} };
for (const k of Object.keys(by)) {
  const c = by[k].classic, m = by[k].mod;
  const sub = k.split('|')[1];
  const s = out.bySubsystem[sub] = out.bySubsystem[sub] || { keys: 0, paired: 0, agree: 0, disagree: 0, classicOnly: 0, modOnly: 0, modRewrites: 0, modDenies: 0, classicDenies: 0, modEnforced: 0, latencyMs: { classic: [], mod: [] }, disagreements: [], reasonCodes: {} };
  s.keys++;
  // the classic side may write several rows per key (three guards judge one spawn); a deny anywhere is the classic verdict
  const cDecision = c.length ? (c.some((r) => r.decision === 'deny') ? 'deny' : c.some((r) => r.decision === 'rewrite') ? 'rewrite' : 'allow') : null;
  const mRow = m[0] || null;
  const mDecision = mRow ? mRow.decision : null;
  if (c.length && mRow) {
    s.paired++;
    if (norm(cDecision) === norm(mDecision) || (sub !== 'routing' && cDecision === mDecision)) s.agree++;
    else { s.disagree++; s.disagreements.push({ key: k, classic: cDecision, mod: mDecision, reasons: mRow.reasonCodes, classicReasons: c.flatMap((r) => r.reasonCodes) }); }
  } else if (c.length) s.classicOnly++;
  else s.modOnly++;
  if (mDecision === 'rewrite') s.modRewrites++;
  if (mDecision === 'deny') s.modDenies++;
  if (cDecision === 'deny') s.classicDenies++;
  if (mRow && mRow.enforced) s.modEnforced++;
  for (const r of c) if (typeof r.latencyMs === 'number') s.latencyMs.classic.push(r.latencyMs);
  if (mRow && typeof mRow.latencyMs === 'number') s.latencyMs.mod.push(mRow.latencyMs);
  for (const code of (mRow ? mRow.reasonCodes : [])) s.reasonCodes[code] = (s.reasonCodes[code] || 0) + 1;
}
const med = (a) => { const s = a.slice().sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : null; };
for (const sub of Object.keys(out.bySubsystem)) { const s = out.bySubsystem[sub]; s.latencyMs = { classicMedian: med(s.latencyMs.classic), modMedian: med(s.latencyMs.mod), nClassic: s.latencyMs.classic.length, nMod: s.latencyMs.mod.length }; }

if (AS_JSON) { console.log(JSON.stringify(out, null, 2)); process.exit(0); }
console.log(`shadow report: ${out.rows} rows from ${out.files} files across ${out.sessions} sessions`);
if (!out.rows) { console.log('  (no rows yet: run sessions with guards in shadow_mod or mod)'); process.exit(0); }
for (const sub of Object.keys(out.bySubsystem)) {
  const s = out.bySubsystem[sub];
  console.log(`\n${sub}: keys=${s.keys} paired=${s.paired} agree=${s.agree} disagree=${s.disagree} classic-only=${s.classicOnly} mod-only=${s.modOnly} · mod rewrites=${s.modRewrites} mod denies=${s.modDenies} classic denies=${s.classicDenies} · mod enforced=${s.modEnforced} · latency median classic=${s.latencyMs.classicMedian}ms (n=${s.latencyMs.nClassic}) mod=${s.latencyMs.modMedian}ms (n=${s.latencyMs.nMod})`);
  const codes = Object.entries(s.reasonCodes).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v]) => `${k}=${v}`).join(' ');
  if (codes) console.log(`  reason codes: ${codes}`);
  for (const d of s.disagreements.slice(0, 10)) console.log(`  DISAGREE ${d.key}: classic=${d.classic} [${d.classicReasons.join(',')}] mod=${d.mod} [${(d.reasons || []).join(',')}]`);
}
