'use strict';
/**
 * engine/context/graph.cjs — the semantic context graph: modules are markdown
 * files with frontmatter, edges are declared dependencies plus [[wikilinks]],
 * and resolution is a deterministic dependency closure in load order.
 *
 * Nothing here reads a client, a prompt or a budget. `select.cjs` picks
 * targets (may be heuristic); this file turns targets into an ordered closure
 * (never heuristic). Zero dependencies.
 *
 * A module is any `.md` file under a configured root whose frontmatter carries
 * a `name` (memory files already do) or that the root's index lists. The
 * optional `context:` block refines it: see frontmatter.cjs for the schema.
 *
 * Edge kinds:
 *   requires  hard prerequisite: loaded before the module, or the module is
 *             flagged `degraded` when the prerequisite is missing or rejected.
 *   suggests  soft: loaded after every hard edge, budget permitting.
 *   wikilink  `[[name]]` in the body: an implicit `suggests`.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const fm = require('./frontmatter.cjs');

const DEFAULT_STALE_DAYS = 120;
const TOKEN_CHARS = 4; // chars per token, the estimator every count in this engine uses

function estimateTokens(text) { return Math.ceil(String(text || '').length / TOKEN_CHARS); }
function sha(text) { return crypto.createHash('sha1').update(String(text), 'utf8').digest('hex').slice(0, 12); }
function list(v) { if (v === undefined || v === null || v === '') return []; return Array.isArray(v) ? v.map(String).map((s) => s.trim()).filter(Boolean) : [String(v).trim()].filter(Boolean); }
function days(v) {
  if (v === undefined || v === null || v === '') return null;
  const m = String(v).match(/^(\d+)\s*(d|days?)?$/i);
  return m ? Number(m[1]) : null;
}
function realpath(p) { try { return fs.realpathSync.native(p); } catch { return path.resolve(p); } }
function within(child, parent) {
  const rel = path.relative(parent, child);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}
function slugOf(file) { return path.basename(file).replace(/\.md$/i, ''); }

/** Read `name | file | triggers | hook` tables and `- [Title](file.md) — hook` lists from an index. */
function parseIndex(text, dir) {
  const byFile = new Map();
  for (const line of String(text).split(/\r?\n/)) {
    const row = line.match(/^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|/);
    if (row && !/^-+$/.test(row[1]) && row[1] !== 'name' && row[1] !== 'what') {
      const file = row[2].trim();
      if (/\.md$/i.test(file)) byFile.set(path.resolve(dir, file), { name: row[1].trim(), triggers: row[3].split(',').map((s) => s.trim()).filter(Boolean) });
      continue;
    }
    const li = line.match(/^-\s*\[([^\]]+)\]\(([^)]+\.md)\)/);
    if (li) byFile.set(path.resolve(dir, li[2]), { name: li[1].trim(), triggers: [] });
  }
  return byFile;
}

function walk(dir, include, out = [], depth = 0) {
  let entries = [];
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const p = path.join(dir, e.name);
    let isDir = e.isDirectory();
    if (e.isSymbolicLink()) { try { isDir = fs.statSync(p).isDirectory(); } catch { continue; } } // a link is followed; loadGraph's realpath check decides
    if (isDir) { if (!e.name.startsWith('.') && depth < 12) walk(p, include, out, depth + 1); continue; }
    if (!/\.md$/i.test(e.name)) continue;
    out.push(p);
  }
  return out;
}

// Glob to regex, left to right so a double star is never re-tokenised:
// double-star-slash = any directories, double star = anything, star = one segment, ? = one char.
function globToRe(glob) {
  const s = String(glob).replace(/\\/g, '/');
  let re = '';
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === '*' && s[i + 1] === '*') { if (s[i + 2] === '/') { re += '(?:.*/)?'; i += 2; } else { re += '.*'; i += 1; } }
    else if (c === '*') re += '[^/]*';
    else if (c === '?') re += '[^/]';
    else re += '.+^$(){}|[]\\'.includes(c) ? '\\' + c : c;
  }
  return new RegExp('^' + re + '$', 'i');
}
function matchesInclude(file, root, include) {
  if (!include || !include.length) return true;
  const rel = path.relative(root, file).replace(/\\/g, '/');
  return include.some((g) => globToRe(g).test(rel));
}

/** Extract one `## Heading` section (heading line included) from a body. */
function section(body, heading) {
  if (!heading) return body;
  const lines = String(body).split(/\r?\n/);
  const level = (heading.match(/^#+/) || ['##'])[0].length;
  const want = heading.trim().toLowerCase();
  const start = lines.findIndex((l) => { const t = l.trim().toLowerCase(); return t === want || t.startsWith(want + ' '); }); // "## Rules" also matches "## Rules (why)"
  if (start < 0) return null;
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i++) {
    const m = lines[i].match(/^(#+)\s/);
    if (m && m[1].length <= level) { end = i; break; }
  }
  return lines.slice(start, end).join('\n').trim();
}

function wikilinks(body) {
  const out = new Set();
  // a [[name]] inside a code span or fenced block is prose about links, not a link
  const prose = String(body).replace(/```[\s\S]*?```/g, '').replace(/`[^`\n]*`/g, '');
  const re = /\[\[([A-Za-z0-9][A-Za-z0-9._-]*)\]\]/g;
  let m;
  while ((m = re.exec(prose))) out.add(m[1]);
  return [...out];
}

/**
 * loadGraph(roots, opts) -> graph
 *   roots: [{ id, path, scope: 'harness'|'user'|'repo', trust: 'harness'|'user'|'repo',
 *             index?: 'MEMORY.md', include?: ['people/**'], repo?: '<id>' }]
 * Every root is resolved to its real path; a file that resolves outside its root
 * (a symlink out) is excluded with reason `outside-root`.
 */
function loadGraph(roots, opts = {}) {
  const now = opts.now ? new Date(opts.now).getTime() : Date.now();
  const staleDays = opts.staleAfterDays || DEFAULT_STALE_DAYS;
  const modules = new Map();
  const errors = [];
  const warnings = [];
  const excluded = [];

  for (const root of roots || []) {
    const rootPath = realpath(root.path);
    if (!fs.existsSync(rootPath)) { warnings.push({ root: root.id, reason: 'root-missing', path: root.path }); continue; }
    const index = root.index ? parseIndex(safeRead(path.join(rootPath, root.index)), rootPath) : new Map();
    for (const file of walk(rootPath, null)) {
      if (root.index && path.resolve(file) === path.resolve(rootPath, root.index)) continue;
      if (!matchesInclude(file, rootPath, root.include)) continue;
      const real = realpath(file);
      if (!within(real, rootPath)) { excluded.push({ file, reason: 'outside-root', root: root.id }); continue; }
      const text = safeRead(file);
      if (text === null) continue;
      const { meta, body } = fm.parse(text);
      const idx = index.get(path.resolve(file));
      // Claude Code's memory writer re-serialises unknown top-level keys under `metadata:`, so both homes count
      const ctx = (meta && typeof meta.context === 'object' && meta.context) || (meta && meta.metadata && typeof meta.metadata.context === 'object' && meta.metadata.context) || null;
      if (!ctx && !(meta && meta.name) && !idx) continue; // plain markdown, not a module
      const name = String((meta && meta.name) || (idx && idx.name && /^[a-z0-9][a-z0-9._-]*$/i.test(idx.name) ? idx.name : slugOf(file))).trim();
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(name)) { errors.push({ name, file, reason: 'invalid-name' }); continue; }
      const sec = ctx && ctx.section ? section(body, ctx.section) : body;
      if (sec === null) { errors.push({ name, file, reason: 'section-not-found', detail: ctx.section }); continue; }
      const content = String(sec).trim();
      const triggers = ctx && ctx.triggers && typeof ctx.triggers === 'object' ? ctx.triggers : {};
      const modifiedRaw = (meta && meta.metadata && meta.metadata.modified) || (meta && meta.modified) || null;
      let modified = modifiedRaw ? Date.parse(modifiedRaw) : NaN;
      if (Number.isNaN(modified)) { try { modified = fs.statSync(file).mtimeMs; } catch { modified = now; } }
      const staleAfter = ctx && ctx.stale_after !== undefined ? days(ctx.stale_after) : null;
      const ageDays = Math.floor((now - modified) / 86400000);
      const mod = {
        name,
        description: String((meta && meta.description) || '').trim(),
        file,
        root: root.id,
        scope: (ctx && ctx.scope) || root.scope || 'user',
        trust: root.trust || 'user',
        repo: root.repo || null,
        clients: list(ctx && ctx.clients),
        priority: ctx && typeof ctx.priority === 'number' ? ctx.priority : 50,
        sensitivity: (ctx && ctx.sensitivity) || 'normal',
        staleAfterDays: staleAfter === null ? staleDays : staleAfter,
        ageDays,
        stale: ageDays > (staleAfter === null ? staleDays : staleAfter),
        modified: new Date(modified).toISOString().slice(0, 10),
        requires: list(ctx && ctx.requires),
        suggests: list(ctx && ctx.suggests),
        wikilinks: wikilinks(content).filter((w) => w !== name),
        triggers: {
          keywords: list(triggers.keywords),
          paths: list(triggers.paths),
          repos: list(triggers.repos),
          tools: list(triggers.tools),
          agents: list(triggers.agents),
          commands: list(triggers.commands),
          index: idx ? idx.triggers : [],
        },
        explicit: Boolean(ctx),
        section: (ctx && ctx.section) || null,
        content,
        chars: content.length,
        tokens: ctx && typeof ctx.tokens === 'number' ? ctx.tokens : estimateTokens(content),
        hash: sha(content),
      };
      if (modules.has(name)) { errors.push({ name, file, reason: 'duplicate-name', detail: modules.get(name).file }); continue; }
      modules.set(name, mod);
    }
  }

  // edges, in a second pass so names resolve regardless of root order
  for (const m of modules.values()) {
    m.edges = [];
    const add = (to, kind) => {
      if (to === m.name) { errors.push({ name: m.name, file: m.file, reason: 'self-dependency', detail: kind }); return; }
      if (m.edges.some((e) => e.to === to && e.kind === kind)) return;
      const target = modules.get(to);
      if (!target) { m.edges.push({ to, kind, missing: true }); return; }
      // a repo-trust module may only reach into its own root: content that came
      // with a repository never pulls harness or user context along
      if (m.trust === 'repo' && target.root !== m.root) { m.edges.push({ to, kind, dropped: 'cross-root-edge-from-repo-trust' }); return; }
      m.edges.push({ to, kind });
    };
    for (const r of m.requires) add(r, 'requires');
    for (const s of m.suggests) if (!m.requires.includes(s)) add(s, 'suggests');
    for (const w of m.wikilinks) if (!m.requires.includes(w) && !m.suggests.includes(w)) add(w, 'wikilink');
  }
  const graph = { modules, errors, warnings, excluded, roots: roots || [] };
  graph.cycles = findCycles(graph, ['requires']);
  graph.softCycles = findCycles(graph).filter((c) => !graph.cycles.some((h) => h.join() === c.join()));
  return graph;
}

function safeRead(p) { try { return fs.readFileSync(p, 'utf8'); } catch { return null; } }

function liveEdges(m, kinds) {
  return (m.edges || []).filter((e) => !e.missing && !e.dropped && (!kinds || kinds.includes(e.kind)));
}

/** Tarjan SCC over every live edge; a cycle is an SCC of size > 1. Sorted for determinism. */
function findCycles(graph, kinds) {
  const names = [...graph.modules.keys()].sort();
  let index = 0;
  const idx = new Map(), low = new Map(), onStack = new Set(), stack = [];
  const cycles = [];
  function strong(v) {
    idx.set(v, index); low.set(v, index); index++; stack.push(v); onStack.add(v);
    for (const e of liveEdges(graph.modules.get(v), kinds).sort((a, b) => a.to.localeCompare(b.to))) {
      const w = e.to;
      if (!graph.modules.has(w)) continue; // outside this (sub)graph: a truncated closure
      if (!idx.has(w)) { strong(w); low.set(v, Math.min(low.get(v), low.get(w))); }
      else if (onStack.has(w)) low.set(v, Math.min(low.get(v), idx.get(w)));
    }
    if (low.get(v) === idx.get(v)) {
      const comp = [];
      let w;
      do { w = stack.pop(); onStack.delete(w); comp.push(w); } while (w !== v);
      if (comp.length > 1) cycles.push(comp.sort());
    }
  }
  for (const n of names) if (!idx.has(n)) strong(n);
  return cycles.sort((a, b) => a[0].localeCompare(b[0]));
}

/**
 * resolve(graph, targets, opts) -> { order, nodes, missing, degraded, cycles, truncated, reasons }
 *   order   module names, prerequisites first, deterministic
 *   nodes   Map name -> { module, required: bool, because: [{ from, kind }] }
 *   opts.optional (default true) follow suggests/wikilinks; opts.maxDepth; opts.maxClosure
 * Cycles are reported and broken deterministically (the edge into the
 * lexicographically smallest member of the cycle is ignored for ordering).
 */
function resolve(graph, targets, opts = {}) {
  const optional = opts.optional !== false;
  const maxDepth = opts.maxDepth || 8;
  const maxClosure = opts.maxClosure || 24;
  const nodes = new Map();
  const missing = [];
  const reasons = [];
  let truncated = false;
  const queue = [];
  for (const t of [...new Set(targets)].sort()) {
    const m = graph.modules.get(t);
    if (!m) { missing.push({ name: t, from: null, kind: 'target' }); continue; }
    nodes.set(t, { module: m, required: true, because: [{ from: null, kind: 'target' }], depth: 0 });
    queue.push(t);
  }
  // breadth-first expansion: required edges always, optional edges when asked
  while (queue.length) {
    const name = queue.shift();
    const node = nodes.get(name);
    if (node.depth >= maxDepth) { truncated = true; reasons.push({ name, reason: 'max-depth', depth: node.depth }); continue; }
    for (const e of (node.module.edges || [])) {
      if (e.dropped) { reasons.push({ name, to: e.to, reason: e.dropped }); continue; }
      if (e.missing) { missing.push({ name: e.to, from: name, kind: e.kind }); continue; }
      const hard = e.kind === 'requires' && node.required;
      if (!hard && !optional) continue;
      // associations are one hop: an optional module brings its own prerequisites, not its links
      if (!node.required && e.kind !== 'requires') continue;
      if (!nodes.has(e.to)) {
        if (nodes.size >= maxClosure) { truncated = true; reasons.push({ name, to: e.to, reason: 'max-closure' }); continue; }
        nodes.set(e.to, { module: graph.modules.get(e.to), required: hard, because: [{ from: name, kind: e.kind }], depth: node.depth + 1 });
        queue.push(e.to);
      } else {
        const n = nodes.get(e.to);
        if (!n.because.some((b) => b.from === name && b.kind === e.kind)) n.because.push({ from: name, kind: e.kind });
        if (hard && !n.required) { n.required = true; queue.push(e.to); } // promote: its own requires now hard
      }
    }
  }
  // a cycle of hard edges is a modeling error and is reported; mutual [[links]] are normal in a
  // memory store, so soft cycles only shape the ordering (lint warns about them)
  const sub = { modules: new Map([...nodes].map(([k, v]) => [k, v.module])) };
  const cycles = findCycles(sub, ['requires']);
  const order = topo(nodes, findCycles(sub));
  const degraded = [];
  for (const name of nodes.keys()) {
    const miss = missing.filter((x) => x.from === name && x.kind === 'requires').map((x) => x.name);
    if (miss.length) degraded.push({ name, missingRequired: miss });
  }
  return { order, nodes, missing, degraded, cycles, truncated, reasons };
}

/** Kahn over dependency -> dependent edges restricted to `nodes`; ties broken by name. */
function topo(nodes, cycles) {
  const inCycle = new Map();
  for (const c of cycles || []) for (const n of c) inCycle.set(n, c[0]);
  const names = [...nodes.keys()].sort();
  const indeg = new Map(names.map((n) => [n, 0]));
  const dependents = new Map(names.map((n) => [n, []]));
  for (const n of names) {
    for (const e of liveEdges(nodes.get(n).module)) {
      if (!nodes.has(e.to)) continue;
      // break a cycle by ignoring edges that point at the cycle's smallest member from inside it
      if (inCycle.has(n) && inCycle.get(n) === inCycle.get(e.to) && e.to === inCycle.get(e.to)) continue;
      indeg.set(n, indeg.get(n) + 1);
      dependents.get(e.to).push(n);
    }
  }
  const ready = names.filter((n) => indeg.get(n) === 0);
  const order = [];
  while (ready.length) {
    ready.sort();
    const n = ready.shift();
    order.push(n);
    for (const d of dependents.get(n)) { indeg.set(d, indeg.get(d) - 1); if (indeg.get(d) === 0) ready.push(d); }
  }
  for (const n of names) if (!order.includes(n)) order.push(n); // unreachable through a cycle: append, deterministic
  return order;
}

/** explain(graph, name) -> lines: why each module in the closure is there. */
function explain(graph, name, opts = {}) {
  const r = resolve(graph, [name], opts);
  const lines = [];
  if (!graph.modules.has(name)) return [`${name}: not a module`];
  for (const n of r.order) {
    const node = r.nodes.get(n);
    const m = node.module;
    const why = node.because.map((b) => b.kind === 'target' ? 'the target' : `${b.kind === 'requires' ? 'required' : b.kind === 'suggests' ? 'suggested' : 'linked [[..]]'} by ${b.from}`).join('; ');
    lines.push(`${n}  (${m.tokens} tok, ${m.scope}/${m.trust}${m.stale ? ', STALE ' + m.ageDays + 'd' : ''})  ${why}${node.required ? '' : '  [optional]'}`);
    for (const e of m.edges) {
      if (e.missing) lines.push(`  ! ${e.kind} ${e.to}: missing`);
      else if (e.dropped) lines.push(`  ! ${e.kind} ${e.to}: dropped (${e.dropped})`);
    }
  }
  if (r.cycles.length) lines.push(`cycles: ${r.cycles.map((c) => c.join(' -> ')).join(' | ')}`);
  if (r.truncated) lines.push(`truncated: ${r.reasons.map((x) => x.reason + (x.to ? ' at ' + x.to : '')).join(', ')}`);
  return lines;
}

/** impact(graph, name) -> modules that depend on `name`, transitively, with the path. */
function impact(graph, name) {
  const out = [];
  const seen = new Set([name]);
  const queue = [[name, []]];
  while (queue.length) {
    const [cur, trail] = queue.shift();
    for (const m of [...graph.modules.values()].sort((a, b) => a.name.localeCompare(b.name))) {
      const e = (m.edges || []).find((x) => x.to === cur && !x.missing && !x.dropped);
      if (!e || seen.has(m.name)) continue;
      seen.add(m.name);
      const path = [...trail, `${m.name} ${e.kind === 'requires' ? '=>' : '->'} ${cur}`];
      out.push({ name: m.name, kind: e.kind, direct: cur === name, path });
      queue.push([m.name, path]);
    }
  }
  return out;
}

/**
 * lint(graph, opts) -> { errors, warnings, stats }
 * errors: duplicate names, missing required deps, cycles, self deps, invalid names, bad sections
 * warnings: orphans (no triggers, no dependents), oversized, fanout, stale, missing optional
 */
function lint(graph, opts = {}) {
  const maxTokens = opts.maxModuleTokens || 1500;
  const maxFanout = opts.maxFanout || 8;
  const errors = graph.errors.map((e) => ({ ...e, check: e.reason }));
  const warnings = graph.warnings.map((w) => ({ ...w, check: w.reason }));
  for (const x of graph.excluded) warnings.push({ check: 'outside-root', ...x });
  const dependents = new Map();
  for (const m of graph.modules.values()) for (const e of liveEdges(m)) dependents.set(e.to, (dependents.get(e.to) || 0) + 1);
  for (const m of [...graph.modules.values()].sort((a, b) => a.name.localeCompare(b.name))) {
    for (const e of m.edges) {
      if (e.missing && e.kind === 'requires') errors.push({ check: 'missing-required', name: m.name, to: e.to, file: m.file });
      else if (e.missing) warnings.push({ check: 'missing-optional', name: m.name, to: e.to, kind: e.kind, file: m.file });
      else if (e.dropped) warnings.push({ check: e.dropped, name: m.name, to: e.to, file: m.file });
    }
    const hasTrigger = Object.values(m.triggers).some((t) => t.length);
    if (!hasTrigger && !dependents.get(m.name)) warnings.push({ check: 'orphan', name: m.name, file: m.file, detail: 'no triggers and nothing depends on it: reachable only by explicit name' });
    if (m.tokens > maxTokens) warnings.push({ check: 'oversized', name: m.name, tokens: m.tokens, file: m.file, detail: `over ${maxTokens} tok; set context.section or split` });
    const fan = liveEdges(m).length;
    if (fan > maxFanout) warnings.push({ check: 'fanout', name: m.name, edges: fan, file: m.file });
    if (m.stale) warnings.push({ check: 'stale', name: m.name, ageDays: m.ageDays, file: m.file });
  }
  for (const c of graph.cycles) errors.push({ check: 'cycle', members: c });
  for (const c of graph.softCycles || []) warnings.push({ check: 'soft-cycle', name: c.join(' <-> '), detail: 'mutual links or suggests; ordering breaks it at the smallest member' });
  // near-duplicate concepts: identical descriptions or names differing only by punctuation
  const byKey = new Map();
  for (const m of graph.modules.values()) {
    const key = m.name.toLowerCase().replace(/[^a-z0-9]/g, '');
    if (byKey.has(key)) warnings.push({ check: 'similar-name', name: m.name, other: byKey.get(key) }); else byKey.set(key, m.name);
  }
  const stats = {
    modules: graph.modules.size,
    explicit: [...graph.modules.values()].filter((m) => m.explicit).length,
    edges: [...graph.modules.values()].reduce((n, m) => n + liveEdges(m).length, 0),
    tokens: [...graph.modules.values()].reduce((n, m) => n + m.tokens, 0),
    roots: graph.roots.map((r) => ({ id: r.id, modules: [...graph.modules.values()].filter((m) => m.root === r.id).length })),
  };
  return { errors, warnings, stats };
}

module.exports = { loadGraph, resolve, explain, impact, lint, findCycles, topo, estimateTokens, section, parseIndex, globToRe, TOKEN_CHARS, DEFAULT_STALE_DAYS };
