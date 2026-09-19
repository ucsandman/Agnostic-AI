'use strict';
/**
 * engine/context/index.cjs — the semantic context graph as a library.
 *
 *   const ctx = require('agnostic-ai/engine/context/index.cjs');
 *   const cfg = ctx.config.load('~/.claude/hooks/context-graph.json');
 *   const graph = ctx.loadGraph(ctx.config.concreteRoots(cfg, { cwd }), { staleAfterDays: cfg.stale.afterDays });
 *   const sel = ctx.select(graph, { prompt, cwd, client: cfg.client }, cfg.selection);
 *   const res = ctx.resolve(graph, sel.targets.map(t => t.name), { maxDepth, maxClosure });
 *   const packed = ctx.pack(graph, res, { budgetTokens, already, findSecrets });
 *   const text = ctx.renderBundle({ packed, selection: sel, resolved: res, cli });
 *
 * `bundle()` below does that whole chain in one call; it is what the Claude
 * Code hook runs on every prompt.
 */
const graph = require('./graph.cjs');
const { select } = require('./select.cjs');
const { pack } = require('./budget.cjs');
const render = require('./render.cjs');
const config = require('./config.cjs');

/**
 * bundle({ cfg, signals, targets, already, sessionUsed, findSecrets, cli, now })
 * -> { graph, selection, resolved, packed, text, targets }
 * targets: explicit names (skip selection); otherwise selection decides.
 */
function bundle(opts) {
  const cfg = opts.cfg;
  const roots = config.concreteRoots(cfg, { cwd: opts.signals && opts.signals.cwd });
  const g = graph.loadGraph(roots, { staleAfterDays: cfg.stale.afterDays, now: opts.now });
  let selection = null;
  let targets = opts.targets || [];
  if (!targets.length) {
    selection = select(g, { ...(opts.signals || {}), client: (opts.signals && opts.signals.client) || cfg.client }, { ...cfg.selection, home: config.home() });
    targets = selection.targets.map((t) => t.name);
  }
  const resolved = graph.resolve(g, targets, { maxDepth: cfg.budget.maxDepth, maxClosure: cfg.budget.maxClosure, optional: opts.optional !== false });
  const sessionUsed = opts.sessionUsed || 0;
  const turnBudget = Math.min(cfg.budget.turnTokens, Math.max(0, cfg.budget.sessionTokens - sessionUsed));
  const packed = pack(resolved, { budgetTokens: opts.budgetTokens === undefined ? turnBudget : opts.budgetTokens, maxModules: cfg.budget.maxModulesPerTurn, already: opts.already || {}, findSecrets: opts.findSecrets, bannerTokens: 40 });
  const text = render.renderBundle({ packed, selection, resolved, session: { used: sessionUsed, cap: cfg.budget.sessionTokens }, cli: opts.cli, tag: opts.tag });
  return { graph: g, selection, resolved, packed, text, targets, roots };
}

module.exports = { ...graph, select, pack, ...render, config, bundle };
