#!/usr/bin/env node
'use strict';
/**
 * engine/context/cli.cjs — inspect and resolve the semantic context graph.
 *
 *   node cli.cjs resolve <name...>        the dependency closure, load order, why each is there
 *   node cli.cjs explain <name>           the dependency tree with reasons (requires/suggests/links)
 *   node cli.cjs impact <name>            reverse dependencies: what changes when this module does
 *   node cli.cjs graph                    lint: cycles, orphans, missing deps, oversized, fanout, stale
 *   node cli.cjs select --prompt "..."    what the deterministic selector would pick, and why
 *   node cli.cjs bundle --prompt "..."    select + resolve + pack + render: what a hook would inject
 *   node cli.cjs show <name>              print one module's content (what `bundle` would inject for it)
 *   node cli.cjs list                     every module: name, root, tokens, triggers
 *   node cli.cjs report [--days N]        the ledger: what was loaded, deduped, rejected; eager baseline
 *
 * Flags: --config <file> (default: $CONTEXT_GRAPH_CONFIG or ~/.claude/hooks/context-graph.json)
 *        --cwd <dir> --client <id> --files a,b --agent <type> --budget <tokens> --json --no-optional
 * Exit 0 ok, 1 lint errors or unknown module, 2 usage.
 */
const fs = require('fs');
const path = require('path');
const ctx = require('./index.cjs');

function parseArgs(argv) {
  const out = { _: [], json: false, optional: true, files: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--json') out.json = true;
    else if (a === '--no-optional') out.optional = false;
    else if (a === '--config') out.config = argv[++i];
    else if (a === '--cwd') out.cwd = argv[++i];
    else if (a === '--client') out.client = argv[++i];
    else if (a === '--prompt') out.prompt = argv[++i];
    else if (a === '--agent') out.agent = argv[++i];
    else if (a === '--files') out.files = String(argv[++i] || '').split(',').filter(Boolean);
    else if (a === '--budget') out.budget = Number(argv[++i]);
    else if (a === '--days') out.days = Number(argv[++i]);
    else if (a === '--ledger') out.ledger = argv[++i];
    else if (a.startsWith('--')) { console.error(`unknown flag ${a}`); process.exit(2); }
    else out._.push(a);
  }
  return out;
}

function defaultConfig() {
  return process.env.CONTEXT_GRAPH_CONFIG || path.join(ctx.config.home(), '.claude', 'hooks', 'context-graph.json');
}

function main(argv) {
  const args = parseArgs(argv);
  const cmd = args._[0];
  if (!cmd) { console.log(fs.readFileSync(__filename, 'utf8').split('\n').slice(3, 21).join('\n').replace(/^ \* ?/gm, '')); return 2; }
  const cfgFile = args.config || defaultConfig();
  const cfg = ctx.config.load(cfgFile);
  if (args.client) cfg.client = args.client;
  const cwd = args.cwd || process.cwd();
  const roots = ctx.config.concreteRoots(cfg, { cwd });
  const graph = ctx.loadGraph(roots, { staleAfterDays: cfg.stale.afterDays });
  const cli = `node ${path.resolve(__filename).replace(/\\/g, '/')}`;
  const p = (o) => console.log(JSON.stringify(o, null, 2));

  if (cmd === 'list') {
    const rows = [...graph.modules.values()].sort((a, b) => a.root.localeCompare(b.root) || a.name.localeCompare(b.name)).map((m) => ({ name: m.name, root: m.root, scope: m.scope, tokens: m.tokens, explicit: m.explicit, stale: m.stale, requires: m.requires, suggests: m.suggests, links: m.wikilinks.length, triggers: [...m.triggers.keywords, ...m.triggers.index].slice(0, 6) }));
    if (args.json) { p(rows); return 0; }
    for (const r of rows) console.log(`${r.name.padEnd(48)} ${r.root.padEnd(14)} ${String(r.tokens).padStart(5)} tok ${r.explicit ? 'ctx ' : '    '}${r.stale ? 'STALE ' : ''}${r.requires.length ? 'requires ' + r.requires.join(',') + ' ' : ''}${r.links ? '[[' + r.links + ']] ' : ''}${r.triggers.length ? '· ' + r.triggers.join(', ') : ''}`);
    console.log(`${rows.length} modules from ${roots.length} roots (config ${cfgFile})`);
    return 0;
  }
  if (cmd === 'graph') {
    const l = ctx.lint(graph, { maxModuleTokens: cfg.budget.maxModuleTokens, maxFanout: cfg.budget.maxFanout });
    if (args.json) { p({ ...l, cycles: graph.cycles }); return l.errors.length ? 1 : 0; }
    console.log(`context graph: ${l.stats.modules} modules (${l.stats.explicit} with context: blocks), ${l.stats.edges} edges, ${l.stats.tokens.toLocaleString()} tokens total`);
    for (const r of l.stats.roots) console.log(`  root ${r.id}: ${r.modules} modules`);
    for (const e of l.errors) console.log(`  ERROR ${e.check}: ${e.name || (e.members && e.members.join(' -> ')) || ''}${e.to ? ' -> ' + e.to : ''}${e.detail ? ' (' + e.detail + ')' : ''}${e.file ? '  ' + e.file : ''}`);
    for (const w of l.warnings) console.log(`  warn ${w.check}: ${w.name || w.root || ''}${w.to ? ' -> ' + w.to : ''}${w.other ? ' ~ ' + w.other : ''}${w.tokens ? ' ' + w.tokens + ' tok' : ''}${w.ageDays ? ' ' + w.ageDays + 'd' : ''}${w.edges ? ' ' + w.edges + ' edges' : ''}${w.detail ? ' (' + w.detail + ')' : ''}`);
    console.log(`${l.errors.length} errors, ${l.warnings.length} warnings`);
    return l.errors.length ? 1 : 0;
  }
  if (cmd === 'explain') {
    const name = args._[1];
    if (!name) { console.error('explain <name>'); return 2; }
    if (!graph.modules.has(name)) { console.error(`${name}: not a module`); return 1; }
    const lines = ctx.explain(graph, name, { optional: args.optional, maxDepth: cfg.budget.maxDepth, maxClosure: cfg.budget.maxClosure });
    if (args.json) { p(lines); return 0; }
    console.log(lines.join('\n'));
    return 0;
  }
  if (cmd === 'impact') {
    const name = args._[1];
    if (!name) { console.error('impact <name>'); return 2; }
    if (!graph.modules.has(name)) { console.error(`${name}: not a module`); return 1; }
    const rows = ctx.impact(graph, name);
    if (args.json) { p(rows); return 0; }
    if (!rows.length) { console.log(`${name}: nothing depends on it`); return 0; }
    console.log(`${rows.length} module${rows.length === 1 ? '' : 's'} depend on ${name} (=> requires, -> suggests/links):`);
    for (const r of rows) console.log(`  ${r.direct ? 'direct  ' : 'indirect'} ${r.path.join('  ')}`);
    return 0;
  }
  if (cmd === 'resolve' || cmd === 'show') {
    const names = args._.slice(1);
    if (!names.length) { console.error(`${cmd} <name...>`); return 2; }
    const unknown = names.filter((n) => !graph.modules.has(n));
    if (unknown.length) { console.error(`not a module: ${unknown.join(', ')}`); return 1; }
    if (cmd === 'show') {
      const r = ctx.bundle({ cfg, signals: { cwd, client: cfg.client }, targets: names, budgetTokens: args.budget, optional: args.optional, cli, tag: 'context-graph' });
      if (args.json) { p({ loaded: r.packed.loaded.map(({ module, ...x }) => x), rejected: r.packed.rejected, order: r.resolved.order }); return 0; }
      console.log(r.text || `(nothing to show: ${ctx.summary(r.packed)})`);
      return 0;
    }
    const res = ctx.resolve(graph, names, { optional: args.optional, maxDepth: cfg.budget.maxDepth, maxClosure: cfg.budget.maxClosure });
    if (args.json) { p({ order: res.order, nodes: [...res.nodes].map(([n, v]) => ({ name: n, required: v.required, because: v.because, tokens: v.module.tokens, stale: v.module.stale })), missing: res.missing, degraded: res.degraded, cycles: res.cycles, truncated: res.truncated }); return 0; }
    let total = 0;
    for (const n of res.order) { const v = res.nodes.get(n); total += v.module.tokens; console.log(`${String(res.order.indexOf(n) + 1).padStart(2)}. ${n.padEnd(44)} ${String(v.module.tokens).padStart(5)} tok  ${v.required ? 'required' : 'optional'}  ${v.because.map((b) => b.kind === 'target' ? 'target' : b.kind + ' of ' + b.from).join(', ')}`); }
    console.log(`${res.order.length} modules, ${total.toLocaleString()} tokens${res.missing.length ? '; missing: ' + res.missing.map((m) => m.name + (m.from ? ' (from ' + m.from + ')' : '')).join(', ') : ''}${res.cycles.length ? '; CYCLE: ' + res.cycles.map((c) => c.join(' -> ')).join(' | ') : ''}${res.truncated ? '; truncated' : ''}`);
    return res.cycles.length || res.degraded.length ? 1 : 0;
  }
  if (cmd === 'select' || cmd === 'bundle') {
    const signals = { prompt: args.prompt || '', cwd, client: cfg.client, files: args.files, agent: args.agent };
    if (cmd === 'select') {
      const s = ctx.select(graph, signals, { ...cfg.selection, home: ctx.config.home() });
      if (args.json) { p(s); return 0; }
      console.log(`targets (score >= ${cfg.selection.threshold}):`);
      for (const t of s.targets) console.log(`  ${t.name.padEnd(44)} ${t.score}  ${t.reasons.map((r) => r.signal + ' ' + r.hits.join('/')).join(', ')}`);
      if (s.candidates.length) { console.log('candidates (below threshold or over maxTargets):'); for (const c of s.candidates) console.log(`  ${c.name.padEnd(44)} ${c.score}  ${c.reasons.map((r) => r.signal + ' ' + r.hits.join('/')).join(', ')}`); }
      if (!s.targets.length && !s.candidates.length) console.log('  (no module matched)');
      return 0;
    }
    const r = ctx.bundle({ cfg, signals, budgetTokens: args.budget, optional: args.optional, cli, tag: 'context-graph' });
    if (args.json) { p({ targets: r.targets, selection: r.selection, order: r.resolved.order, loaded: r.packed.loaded.map(({ module, ...x }) => x), deduped: r.packed.deduped, rejected: r.packed.rejected, tokens: r.packed.tokens, chars: r.text.length }); return 0; }
    console.log(r.text || `(nothing to inject: ${r.targets.length ? ctx.summary(r.packed) : 'no module matched'})`);
    return 0;
  }
  if (cmd === 'report') {
    const file = args.ledger || process.env.CONTEXT_GRAPH_LEDGER || path.join(ctx.config.home(), '.claude', 'logs', 'context-graph.jsonl');
    return report(file, args, cfg, graph);
  }
  console.error(`unknown command ${cmd}`);
  return 2;
}

function report(file, args, cfg, graph) {
  const days = args.days || 14;
  const since = Date.now() - days * 86400000;
  let rows = [];
  try { rows = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter((r) => r && Date.parse(r.ts) >= since); } catch { rows = []; }
  const sessions = new Set(rows.map((r) => r.session));
  const agg = { rows: rows.length, sessions: sessions.size, loaded: 0, loadedTokens: 0, deduped: 0, dedupedTokens: 0, rejected: 0, rejectedTokens: 0, turnsWithLoad: 0, turnsTotal: rows.filter((r) => r.event === 'prompt').length, byModule: {}, byReason: {} };
  for (const r of rows) {
    if (!r.packed) continue;
    agg.loaded += r.packed.loaded.length; agg.loadedTokens += r.packed.tokens.loaded;
    agg.deduped += r.packed.deduped.length; agg.dedupedTokens += r.packed.tokens.deduped;
    agg.rejected += r.packed.rejected.length; agg.rejectedTokens += r.packed.tokens.rejected;
    if (r.packed.loaded.length) agg.turnsWithLoad++;
    for (const l of r.packed.loaded) { agg.byModule[l.name] = agg.byModule[l.name] || { loads: 0, tokens: 0 }; agg.byModule[l.name].loads++; agg.byModule[l.name].tokens += l.tokens; }
    for (const x of r.packed.rejected) agg.byReason[x.reason] = (agg.byReason[x.reason] || 0) + 1;
  }
  const never = [...graph.modules.keys()].filter((n) => !agg.byModule[n]).sort();
  const eager = (cfg.eagerBaseline || []).map((f) => { const p = ctx.config.expand(f); let chars = 0; try { chars = fs.readFileSync(p, 'utf8').length; } catch {} return { file: f, chars, tokens: ctx.estimateTokens(' '.repeat(chars)) }; });
  const eagerTokens = eager.reduce((s, e) => s + e.tokens, 0);
  const out = { days, file, ...agg, neverLoaded: never, eagerBaseline: { files: eager, tokensPerSession: eagerTokens } };
  if (args.json) { console.log(JSON.stringify(out, null, 2)); return 0; }
  console.log(`context-graph ledger, last ${days} days (${file})`);
  console.log(`  ${agg.rows} rows across ${agg.sessions} sessions; ${agg.turnsWithLoad} of ${agg.turnsTotal} prompts loaded something`);
  console.log(`  loaded ${agg.loaded} modules / ${agg.loadedTokens.toLocaleString()} tok; deduped ${agg.deduped} / ${agg.dedupedTokens.toLocaleString()} tok (duplicate context avoided); rejected ${agg.rejected} / ${agg.rejectedTokens.toLocaleString()} tok`);
  if (Object.keys(agg.byReason).length) console.log(`  rejections by reason: ${Object.entries(agg.byReason).map(([k, v]) => k + ' ' + v).join(', ')}`);
  const top = Object.entries(agg.byModule).sort((a, b) => b[1].loads - a[1].loads).slice(0, 10);
  if (top.length) { console.log('  most loaded:'); for (const [n, v] of top) console.log(`    ${n.padEnd(44)} ${v.loads} loads, ${v.tokens.toLocaleString()} tok`); }
  console.log(`  never loaded in window: ${never.length} of ${graph.modules.size} modules${never.length ? ' (' + never.slice(0, 8).join(', ') + (never.length > 8 ? ', ...' : '') + ')' : ''}`);
  if (eager.length) console.log(`  eager baseline (loaded every session regardless): ${eagerTokens.toLocaleString()} tok from ${eager.length} files: ${eager.map((e) => path.basename(e.file) + ' ' + e.tokens.toLocaleString()).join(', ')}`);
  return 0;
}

if (require.main === module) process.exit(main(process.argv.slice(2)));
module.exports = { main, parseArgs };
