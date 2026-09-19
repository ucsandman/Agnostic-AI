#!/usr/bin/env node
// context-graph.cjs — dependency-aware context loading, four events, one hook.
//
//   UserPromptSubmit  select modules from the prompt, cwd and files touched this
//                     session; resolve their dependency closure; inject the
//                     bundle under a hard budget; remember what is in context.
//   PreToolUse Agent  stash the subagent brief (type + prompt) for SubagentStart.
//   SubagentStart     resolve for the agent type + its brief; inject into the
//                     child's context with its own (smaller) budget.
//   SessionStart      compact: re-inject the modules that were in context before
//                     the summary pass (compaction drops injected context);
//                     clear: forget the session's loaded set.
//
// Engine (client-neutral, tested): ../context/ in this repository.
// Config: hooks/context-graph.json (roots = trust allowlist, budgets).
// Ledger: logs/context-graph.jsonl (one row per event; `--report` summarises).
// State: state/context-graph/<session>.json (loaded set, session tokens, briefs).
// Fail-open: any error exits 0 with no output and one ledger row.
//
//   node hooks/context-graph.cjs --report [--days N]
//   node hooks/context-graph.cjs --client codex     (the ported copy; default claude)
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const HOME = process.env.USERPROFILE || process.env.HOME || os.homedir();
const CLAUDE_DIR = path.join(HOME, '.claude');
// Config: CONTEXT_GRAPH_CONFIG, else the private overlay (<claude home>/overlay/context-graph.json),
// else the portable default beside this hook. Relative `engine` and root paths resolve against the
// config file's own directory, so the default works from any checkout location.
const OVERLAY_CONFIG = path.join(CLAUDE_DIR, 'overlay', 'context-graph.json');
const CONFIG = process.env.CONTEXT_GRAPH_CONFIG || (fs.existsSync(OVERLAY_CONFIG) ? OVERLAY_CONFIG : path.join(__dirname, 'context-graph.json'));
const HOME_SLUG = CLAUDE_DIR.replace(/[:\\/.]/g, '-');
function resolveConfigPaths(cfg) {
  const base = path.dirname(CONFIG);
  const fix = (p) => (typeof p === 'string' && !/^(~|\{|\/|[A-Za-z]:)/.test(p) ? path.resolve(base, p) : p);
  if (cfg.engine) cfg.engine = fix(cfg.engine); // roots and {homeSlug} are the engine's job (engine/context/config.cjs)
  cfg.eagerBaseline = (cfg.eagerBaseline || []).map((p) => fix(String(p).replace(/\{homeSlug\}/g, HOME_SLUG)));
  return cfg;
}
const LEDGER = process.env.CONTEXT_GRAPH_LEDGER || path.join(CLAUDE_DIR, 'logs', 'context-graph.jsonl');
const STATE_DIR = process.env.CONTEXT_GRAPH_STATE || path.join(CLAUDE_DIR, 'state', 'context-graph');
const STATE_TTL_MS = 7 * 24 * 3600 * 1000;
const MAX_BRIEFS = 8;

const argv = process.argv.slice(2);
const flag = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };

function loadEngine(cfg) {
  const p = process.env.CONTEXT_GRAPH_ENGINE || cfg.engine || path.join(__dirname, '..', 'context', 'index.cjs');
  return { engine: require(p), path: p };
}
function findSecrets(text) {
  try {
    const { PATTERNS } = require(path.join(__dirname, 'lib', 'secret-patterns.cjs'));
    const hits = [];
    for (const [kind, re] of PATTERNS) { re.lastIndex = 0; let m; while ((m = re.exec(text))) hits.push({ kind, len: m[0].length }); }
    return hits;
  } catch { return []; }
}
function clientOf(evt) {
  if (flag('--client')) return flag('--client');
  if (process.env.CONTEXT_GRAPH_CLIENT) return process.env.CONTEXT_GRAPH_CLIENT;
  const t = String(evt.transcript_path || '').replace(/\\/g, '/');
  if (/\/\.codex\//.test(t)) return 'codex';
  if (/\/\.gemini\//.test(t)) return 'gemini';
  return 'claude';
}
function sid(evt) { return String(evt.session_id || 'nosession').replace(/[^\w-]/g, '').slice(0, 80); }
function statePath(evt) { return path.join(STATE_DIR, sid(evt) + '.json'); }
function readState(evt) {
  try { return { loaded: {}, used: 0, briefs: [], ...JSON.parse(fs.readFileSync(statePath(evt), 'utf8')) }; } catch { return { loaded: {}, used: 0, briefs: [] }; }
}
function writeState(evt, st) {
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    st.updated = new Date().toISOString();
    fs.writeFileSync(statePath(evt), JSON.stringify(st));
    for (const f of fs.readdirSync(STATE_DIR)) { const fp = path.join(STATE_DIR, f); try { if (Date.now() - fs.statSync(fp).mtimeMs > STATE_TTL_MS) fs.unlinkSync(fp); } catch {} }
  } catch {}
}
function ledger(row) {
  try { fs.mkdirSync(path.dirname(LEDGER), { recursive: true }); fs.appendFileSync(LEDGER, JSON.stringify({ ts: new Date().toISOString(), ...row }) + '\n'); } catch {}
}
/** Files this session read or edited: the tool_use inputs in the transcript tail. */
function filesTouched(transcriptPath, limit = 40) {
  try {
    const size = fs.statSync(transcriptPath).size;
    const start = Math.max(0, size - 384 * 1024);
    const fd = fs.openSync(transcriptPath, 'r');
    const buf = Buffer.alloc(size - start);
    fs.readSync(fd, buf, 0, buf.length, start);
    fs.closeSync(fd);
    const out = new Set();
    for (const line of buf.toString('utf8').split('\n')) {
      if (!line.includes('tool_use')) continue;
      try {
        const o = JSON.parse(line);
        for (const c of (o.message && o.message.content) || []) {
          if (c.type !== 'tool_use' || !c.input) continue;
          const p = c.input.file_path || c.input.path || c.input.notebook_path;
          if (p) out.add(String(p));
        }
      } catch {}
    }
    return [...out].slice(-limit);
  } catch { return []; }
}
function emit(eventName, text) {
  process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: eventName, additionalContext: text } }) + '\n');
}
function summarise(packed) {
  return { loaded: packed.loaded.map((l) => ({ name: l.name, tokens: l.tokens, required: l.required, because: l.because })), deduped: packed.deduped.map((d) => ({ name: d.name, tokens: d.tokens })), rejected: packed.rejected.map((r) => ({ name: r.name, tokens: r.tokens, reason: r.reason })), tokens: packed.tokens };
}

function main() {
  let evt;
  try { evt = JSON.parse(fs.readFileSync(0, 'utf8')); } catch { return; }
  const event = evt.hook_event_name;
  const t0 = Date.now();
  const cfg = readConfig();
  const { engine, path: enginePath } = loadEngine(cfg);
  const client = clientOf(evt);
  cfg.client = client;
  const cli = `node ${path.resolve(path.dirname(enginePath), 'cli.cjs').replace(/\\/g, '/')}`;
  const cwd = evt.cwd || process.cwd();
  const st = readState(evt);
  const base = { session: sid(evt), event: event === 'UserPromptSubmit' ? 'prompt' : event === 'SubagentStart' ? 'subagent' : event === 'SessionStart' ? 'session:' + evt.source : event, client, cwd };

  if (event === 'PreToolUse') {
    const input = evt.tool_input || {};
    if (evt.tool_name === 'Agent' || evt.tool_name === 'Task') {
      if (!input.subagent_type) return;
      st.briefs = [...(st.briefs || []), { type: String(input.subagent_type), prompt: String(input.prompt || '').slice(0, 4000), ts: Date.now() }].slice(-MAX_BRIEFS);
      writeState(evt, st);
      return;
    }
    // Edit/Write: the file being changed is the signal; Bash/PowerShell: the command text
    // (triggers.commands). Either way a matching module loads before the call, once per session.
    const file = input.file_path || input.notebook_path;
    const command = evt.tool_name === 'Bash' || evt.tool_name === 'PowerShell' ? String(input.command || '') : '';
    if (!file && !command) return;
    // required closure only: a tool call is one narrow signal, so associations (suggests, wikilinks) wait for a prompt
    const r = engine.bundle({ cfg, signals: { cwd, client, files: file ? [String(file)] : [], command, tools: [evt.tool_name], pathsFromCwd: false }, optional: false, already: st.loaded, sessionUsed: st.used, findSecrets, cli, tag: 'context-graph' });
    if (!r.targets.length) return;
    for (const l of r.packed.loaded) st.loaded[l.name] = l.hash;
    st.used = (st.used || 0) + r.packed.tokens.loaded;
    writeState(evt, st);
    ledger({ ...base, event: 'pretool', tool: evt.tool_name, file: file ? String(file) : undefined, command: command ? command.slice(0, 120) : undefined, targets: r.targets, packed: summarise(r.packed), chars: r.text.length, sessionUsed: st.used, ms: Date.now() - t0 });
    if (r.text) emit('PreToolUse', r.text);
    return;
  }

  if (event === 'SessionStart') {
    if (evt.source === 'clear') { writeState(evt, { loaded: {}, used: 0, briefs: [] }); ledger({ ...base, note: 'state reset' }); return; }
    if (evt.source !== 'compact') return;
    const names = Object.keys(st.loaded || {});
    if (!names.length) return;
    const r = engine.bundle({ cfg, signals: { cwd, client }, targets: names, optional: false, budgetTokens: cfg.budget.turnTokens, findSecrets, cli, tag: 'context-graph' });
    const text = r.text ? r.text.replace(/^\[context-graph\] /, '[context-graph] re-injected after compaction: ') : '';
    st.loaded = Object.fromEntries(r.packed.loaded.map((l) => [l.name, l.hash]));
    st.used = r.packed.tokens.loaded;
    writeState(evt, st);
    ledger({ ...base, targets: names, packed: summarise(r.packed), chars: text.length, ms: Date.now() - t0 });
    if (text) emit('SessionStart', text);
    return;
  }

  if (event === 'SubagentStart') {
    const type = String(evt.agent_type || '');
    const briefs = st.briefs || [];
    let i = briefs.findIndex((b) => b.type === type);
    if (i < 0 && briefs.length) i = 0;
    const brief = i >= 0 ? briefs.splice(i, 1)[0] : null;
    st.briefs = briefs;
    const r = engine.bundle({ cfg, signals: { prompt: brief ? brief.prompt : '', cwd, client, agent: type }, budgetTokens: cfg.budget.subagentTokens || 1200, findSecrets, cli, tag: 'context-graph' });
    writeState(evt, st);
    ledger({ ...base, agent: type, brief: Boolean(brief), targets: r.targets, packed: summarise(r.packed), chars: r.text.length, ms: Date.now() - t0 });
    if (r.text) emit('SubagentStart', r.text.replace(/^\[context-graph\] /, `[context-graph] for this ${type || 'subagent'}: `));
    return;
  }

  if (event !== 'UserPromptSubmit') return;
  if (evt.source && !['user', 'sdk'].includes(evt.source)) return; // wakeups and machine turns repeat; the human's turn is the signal
  const prompt = String(evt.prompt || '');
  if (/^\s*<task-notification>/.test(prompt)) return; // a Monitor / task wake-up carries no source field; its text is the tell (2026-09-19: 17 wake-ups each loaded modules)
  if (prompt.trim().startsWith('/') || prompt.length < (cfg.selection.minPromptChars || 12)) return;
  const files = filesTouched(evt.transcript_path);
  const r = engine.bundle({ cfg, signals: { prompt, cwd, client, files }, already: st.loaded, sessionUsed: st.used, findSecrets, cli, tag: 'context-graph' });
  for (const l of r.packed.loaded) st.loaded[l.name] = l.hash;
  st.used = (st.used || 0) + r.packed.tokens.loaded;
  writeState(evt, st);
  if (r.targets.length || r.packed.deduped.length) ledger({ ...base, targets: r.targets, candidates: r.selection ? r.selection.candidates.map((c) => c.name) : [], packed: summarise(r.packed), chars: r.text.length, sessionUsed: st.used, files: files.length, ms: Date.now() - t0 });
  if (r.text) emit('UserPromptSubmit', r.text);
}

function readConfig() {
  const { engine } = loadEngine(resolveConfigPaths(JSON.parse(fs.readFileSync(CONFIG, 'utf8'))));
  return engine.config.load(CONFIG);
}
function engineFile() { return process.env.CONTEXT_GRAPH_ENGINE || resolveConfigPaths(JSON.parse(fs.readFileSync(CONFIG, 'utf8'))).engine; }

if (argv.includes('--report')) {
  try {
    readConfig();
    const cliPath = path.resolve(path.dirname(engineFile()), 'cli.cjs');
    process.exit(require(cliPath).main(['report', '--config', CONFIG, '--ledger', LEDGER, ...(flag('--days') ? ['--days', flag('--days')] : []), ...(argv.includes('--json') ? ['--json'] : [])]));
  } catch (e) { console.error('context-graph --report: ' + e.message); process.exit(1); }
}

try { main(); } catch (e) { if (process.env.CONTEXT_GRAPH_DEBUG) console.error(e && e.stack || e); ledger({ event: 'error', error: String(e && e.message || e).slice(0, 300) }); }
process.exit(0);
