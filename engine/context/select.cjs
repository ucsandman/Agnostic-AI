'use strict';
/**
 * engine/context/select.cjs — target selection from deterministic signals.
 *
 * Selection may be heuristic; resolution (graph.cjs) never is. Every point a
 * module scores is attributable to one signal, and the result carries the
 * reasons so the injected bundle can say "loaded because ...".
 *
 * Signals (all optional):
 *   prompt   the user's text (or a subagent brief)
 *   cwd      working directory
 *   repo     repository id (directory basename or remote name)
 *   files    paths read or edited this session
 *   tools    tool names in play (PreToolUse mode)
 *   agent    subagent type (SubagentStart mode)
 *   client   claude | codex | gemini | ... (applicability filter)
 *
 * Scoring (points, capped per signal so one chatty module cannot dominate):
 *   explicit keyword hit   +2 each, cap 6     (context.triggers.keywords)
 *   index trigger hit      +1 each, cap 3     (MEMORY.md triggers column)
 *   path glob on cwd/files +3
 *   repo match             +3
 *   tool match             +2
 *   agent match            +3
 * Selected: score >= threshold (default 2), top maxTargets by (score, priority, name).
 * Candidates: 1 <= score < threshold, listed so the model can ask for them by name.
 */
const path = require('path');
const { globToRe } = require('./graph.cjs');

function norm(p) { return String(p || '').replace(/\\/g, '/').replace(/\/+$/, ''); }
function expandHome(p, home) { return String(p || '').replace(/^~(?=\/|$)/, norm(home || process.env.USERPROFILE || process.env.HOME || '')); }

function keywordHits(keywords, promptLower) {
  const hits = [];
  for (const k of keywords) {
    const kw = String(k).toLowerCase().trim();
    if (!kw) continue;
    const alnum = /^[a-z0-9][a-z0-9 _-]*[a-z0-9]$|^[a-z0-9]$/.test(kw);
    const re = alnum ? new RegExp('(^|[^a-z0-9])' + kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '($|[^a-z0-9])') : null;
    if (re ? re.test(promptLower) : promptLower.includes(kw)) hits.push(k);
  }
  return hits;
}

function pathHits(globs, paths, home) {
  const hits = [];
  for (const g of globs) {
    const re = globToRe(expandHome(g, home));
    for (const p of paths) {
      const n = norm(p);
      if (re.test(n) || re.test(n + '/')) { hits.push(g); break; }
    }
  }
  return hits;
}

function select(graph, signals = {}, opts = {}) {
  const threshold = opts.threshold === undefined ? 2 : opts.threshold;
  const maxTargets = opts.maxTargets || 4;
  const maxCandidates = opts.maxCandidates || 5;
  const client = signals.client || 'claude';
  const promptLower = String(signals.prompt || '').toLowerCase();
  // cwd counts as a path signal on a prompt; on a tool call only the file being touched does
  const paths = [...(signals.pathsFromCwd === false ? [] : [signals.cwd]), ...(signals.files || [])].filter(Boolean);
  const repo = signals.repo || (signals.cwd ? path.basename(norm(signals.cwd)) : null);
  const tools = new Set((signals.tools || []).map(String));
  const scored = [];
  const filtered = [];

  for (const m of graph.modules.values()) {
    if (m.clients.length && !m.clients.includes(client)) { filtered.push({ name: m.name, reason: `client ${client} not in [${m.clients.join(', ')}]` }); continue; }
    if (m.scope === 'repo' && m.repo && repo !== m.repo && !(signals.cwd && norm(signals.cwd).toLowerCase().includes(norm(m.repo).toLowerCase()))) {
      filtered.push({ name: m.name, reason: `repo-scoped to ${m.repo}` });
      continue;
    }
    const reasons = [];
    let score = 0;
    const kw = promptLower ? keywordHits(m.triggers.keywords, promptLower) : [];
    if (kw.length) { const pts = Math.min(6, kw.length * 2); score += pts; reasons.push({ signal: 'keyword', hits: kw, points: pts }); }
    // index triggers are written for a human reader; a 2-3 letter one ("cd", "rtk") hits every pasted command
    const ix = promptLower ? keywordHits(m.triggers.index.filter((k) => String(k).replace(/[^a-z0-9]/gi, '').length >= 4), promptLower) : [];
    if (ix.length) { const pts = Math.min(3, ix.length); score += pts; reasons.push({ signal: 'index-trigger', hits: ix, points: pts }); }
    const ph = paths.length ? pathHits(m.triggers.paths, paths, opts.home) : [];
    if (ph.length) { score += 3; reasons.push({ signal: 'path', hits: ph, points: 3 }); }
    if (repo && m.triggers.repos.some((r) => r.toLowerCase() === String(repo).toLowerCase())) { score += 3; reasons.push({ signal: 'repo', hits: [repo], points: 3 }); }
    const th = m.triggers.tools.filter((t) => tools.has(t));
    if (th.length) { score += 2; reasons.push({ signal: 'tool', hits: th, points: 2 }); }
    if (signals.agent && m.triggers.agents.some((a) => a === signals.agent || a === '*')) { score += 3; reasons.push({ signal: 'agent', hits: [signals.agent], points: 3 }); }
    if (score > 0) scored.push({ name: m.name, score, priority: m.priority, reasons });
  }
  scored.sort((a, b) => b.score - a.score || b.priority - a.priority || a.name.localeCompare(b.name));
  const targets = scored.filter((s) => s.score >= threshold).slice(0, maxTargets);
  const overflow = scored.filter((s) => s.score >= threshold).slice(maxTargets);
  const candidates = [...overflow, ...scored.filter((s) => s.score < threshold)].slice(0, maxCandidates);
  return { targets, candidates, filtered, signals: { client, repo, cwd: signals.cwd || null, prompt: promptLower.length, files: paths.length, agent: signals.agent || null } };
}

module.exports = { select, keywordHits, pathHits };
