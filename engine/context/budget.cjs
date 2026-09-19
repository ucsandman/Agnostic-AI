'use strict';
/**
 * engine/context/budget.cjs — pack a resolved closure into a hard token budget.
 *
 * Two passes over the topological order: every REQUIRED module first (targets
 * and their transitive `requires`), then the optional ones by priority. A
 * module that does not fit is rejected, and anything that requires it is
 * rejected with it (prerequisites before dependent knowledge: a dependent
 * without its prerequisite is worse than nothing). A module already in the
 * session's context (same hash) is skipped and counted as duplicate context
 * avoided; a changed hash is reloaded as `refreshed`.
 *
 * Trust rule: when any target is repo-trust, `sensitivity: private` modules are
 * dropped from the bundle (`private-in-repo-bundle`), so content that came with
 * a repository can never pull private context into the same context window.
 *
 * Secret rule: `opts.findSecrets(text)` (the harness's own pattern set) runs on
 * every module body; a hit drops the module (`secret-shape`) and is reported
 * with kind and length only, never the value.
 */
const { estimateTokens } = require('./graph.cjs');

function pack(resolved, opts = {}) {
  const budget = Math.max(0, opts.budgetTokens === undefined ? 2500 : opts.budgetTokens);
  const maxModules = opts.maxModules || 6;
  const already = opts.already || {}; // name -> hash
  const findSecrets = typeof opts.findSecrets === 'function' ? opts.findSecrets : null;
  const banner = opts.bannerTokens || 0; // per-module header cost the renderer adds
  const anyRepoTarget = [...resolved.nodes.values()].some((n) => n.because.some((b) => b.kind === 'target') && n.module.trust === 'repo');

  const loaded = [];
  const deduped = [];
  const rejected = [];
  const rejectedNames = new Set();
  let used = 0;

  const consider = (name) => {
    const node = resolved.nodes.get(name);
    const m = node.module;
    const because = node.because.map((b) => b.kind === 'target' ? 'target' : `${b.kind}:${b.from}`);
    // a required prerequisite that was rejected sinks its dependents
    const sunk = (m.edges || []).filter((e) => e.kind === 'requires' && !e.missing && !e.dropped && rejectedNames.has(e.to)).map((e) => e.to);
    if (sunk.length) { rejected.push({ name, tokens: m.tokens, reason: 'prerequisite-rejected', detail: sunk, because }); rejectedNames.add(name); return; }
    if (anyRepoTarget && m.sensitivity === 'private') { rejected.push({ name, tokens: m.tokens, reason: 'private-in-repo-bundle', because }); rejectedNames.add(name); return; }
    if (findSecrets) {
      const hits = findSecrets(m.content) || [];
      if (hits.length) { rejected.push({ name, tokens: m.tokens, reason: 'secret-shape', detail: hits.map((h) => ({ kind: h.kind || h.key || 'secret', len: h.len || (h.value ? String(h.value).length : undefined) })), because }); rejectedNames.add(name); return; }
    }
    if (already[name] === m.hash) { deduped.push({ name, tokens: m.tokens, because }); return; }
    const cost = m.tokens + banner;
    if (loaded.length >= maxModules) { rejected.push({ name, tokens: m.tokens, reason: 'max-modules', because }); rejectedNames.add(name); return; }
    if (used + cost > budget) { rejected.push({ name, tokens: m.tokens, reason: 'over-budget', detail: { remaining: budget - used }, because }); rejectedNames.add(name); return; }
    used += cost;
    loaded.push({ name, tokens: m.tokens, hash: m.hash, required: node.required, refreshed: Boolean(already[name] && already[name] !== m.hash), because, module: m });
  };

  const required = resolved.order.filter((n) => resolved.nodes.get(n).required);
  const optional = resolved.order.filter((n) => !resolved.nodes.get(n).required);
  for (const n of required) consider(n);
  // optional: keep topological order among themselves but let priority decide who goes first
  // when the budget cannot take all of them (stable: sort by priority desc, then order index)
  const idx = new Map(optional.map((n, i) => [n, i]));
  const byPriority = [...optional].sort((a, b) => resolved.nodes.get(b).module.priority - resolved.nodes.get(a).module.priority || idx.get(a) - idx.get(b));
  const chosen = new Set();
  let remaining = budget - used;
  for (const n of byPriority) { const c = resolved.nodes.get(n).module.tokens + banner; if (c <= remaining && chosen.size + loaded.length < maxModules) { chosen.add(n); remaining -= c; } }
  for (const n of optional) { if (chosen.has(n)) consider(n); else if (already[n] === resolved.nodes.get(n).module.hash) deduped.push({ name: n, tokens: resolved.nodes.get(n).module.tokens, because: ['optional'] }); else { rejected.push({ name: n, tokens: resolved.nodes.get(n).module.tokens, reason: loaded.length + chosen.size >= maxModules ? 'max-modules' : 'over-budget', because: resolved.nodes.get(n).because.map((b) => `${b.kind}:${b.from}`) }); } }

  return {
    loaded, deduped, rejected,
    tokens: { budget, used, loaded: loaded.reduce((s, x) => s + x.tokens, 0), deduped: deduped.reduce((s, x) => s + x.tokens, 0), rejected: rejected.reduce((s, x) => s + x.tokens, 0) },
  };
}

module.exports = { pack, estimateTokens };
