/**
 * engine/harness/targets/generic.cjs — the default adapter.
 *
 * Every registry entry in core/templates/targets.json without its own
 * `adapter` is rendered by this module. It carries the surfaces that almost
 * every client shares (a rules file, a skills directory, a markdown commands
 * directory, a markdown agents directory, an `mcpServers` JSON file) and
 * declares the rest unsupported with a reason.
 *
 * A specific adapter reuses these components with
 *   module.exports = Object.assign({}, generic, { id, hooks(ctx) {...} });
 * so a client only writes the code for the surfaces it does differently.
 *
 * Contract: engine/harness/README.md -> "Adapter contract".
 */

const fs = require('fs');
const path = require('path');
const common = require('../common.cjs');
const { stripSections } = common;

const COMPONENTS = ['rules', 'identity', 'hooks', 'skills', 'agents', 'commands', 'mcp', 'permissions'];

// ---------------------------------------------------------------------------
// Shared helpers (exported so claude/gemini/agy/cursor reuse them verbatim)
// ---------------------------------------------------------------------------

/** The mutable per-target ownership record inside `storage/harness-state.json`. */
function owned(ctx, kind) {
  ctx.state.owned = ctx.state.owned || {};
  const id = ctx.target.id;
  ctx.state.owned[id] = ctx.state.owned[id] || {};
  if (!Array.isArray(ctx.state.owned[id][kind])) ctx.state.owned[id][kind] = [];
  return ctx.state.owned[id][kind];
}

/** Derive the ComponentResult status from what actually happened to the files. */
function statusFrom(files, ctx) {
  const actions = files.map((f) => f.action);
  if (actions.includes('skipped-hand-edited')) return 'skipped';
  if (actions.some((a) => a === 'written' || a === 'linked' || a === 'pruned' || a === 'removed')) return 'written';
  if (actions.some((a) => a === 'would-write' || a === 'would-link' || a === 'would-prune')) return ctx.check || ctx.dryRun ? 'stale' : 'written';
  return 'synced';
}

const result = (ctx, files, dropped, note) => {
  const out = { status: statusFrom(files, ctx), files, dropped };
  if (note) out.note = note;
  return out;
};

const unsupported = (note) => ({ status: 'unsupported', files: [], dropped: [], note });

/** Expand a registry path that may or may not already be absolute. */
const at = (ctx, p) => (p ? common.expandPath(p, ctx.home) : '');

/** Canonical JSON (keys sorted, compact) so an inserted object is recognisable on re-read. */
function canonical(v) {
  if (Array.isArray(v)) return v.map(canonical);
  if (v && typeof v === 'object') {
    const o = {};
    for (const k of Object.keys(v).sort()) o[k] = canonical(v[k]);
    return o;
  }
  return v;
}
const stableKey = (v) => JSON.stringify(canonical(v));

/**
 * Read a JSON file the user also owns.
 * missing -> {}, unparseable -> null (the caller must then touch nothing).
 */
function readUserJson(file) {
  if (!fs.existsSync(file)) return {};
  const parsed = common.readJSON(file);
  return parsed === undefined ? null : parsed || {};
}

const writeUserJson = (ctx, file, obj) =>
  ctx.write(file, JSON.stringify(obj, null, 2) + '\n', { region: true });

/**
 * Replace the hook groups this harness owns inside a client's event map and add
 * the new ones. Groups the user (or another tool) put there are never touched:
 * ownership is the exact canonical JSON of what we inserted last time.
 *
 * `events` is mutated in place. Returns the new owned-key list.
 */
function applyOwnedGroups(events, ownedKeys, next) {
  const previous = new Set(ownedKeys);
  for (const [event, groups] of Object.entries(events)) {
    if (!Array.isArray(groups)) continue;
    const kept = groups.filter((g) => !previous.has(stableKey(g)));
    if (kept.length) events[event] = kept;
    else delete events[event];
  }
  const keys = [];
  for (const [event, groups] of Object.entries(next)) {
    for (const g of groups) {
      events[event] = events[event] || [];
      events[event].push(g);
      keys.push(stableKey(g));
    }
  }
  return keys;
}

/** Every hook handler in the bundle, flattened, with the port exclusions applied. */
function portedHandlers(ctx, event, group) {
  const excludes = ((ctx.port.hooks && ctx.port.hooks.exclude) || []).map((e) => ({ re: new RegExp(e.match), reason: e.reason }));
  const kept = [];
  const dropped = [];
  for (const h of group.hooks || []) {
    if (h.type !== 'command' || !h.command) continue;
    const hit = excludes.find((e) => e.re.test(h.command));
    // the drop names the script, never the command line: a command can carry an argument nobody should log
    if (hit) { dropped.push({ item: `${event}: ${scriptName(h.command)}`, reason: hit.reason }); continue; }
    // the shim splits a chain on ' ++ '; a command carrying it would run as two
    if (h.command.includes(' ++ ')) { dropped.push({ item: `${event}: ${scriptName(h.command)}`, reason: "the command contains ' ++ ', the shim's chain separator" }); continue; }
    kept.push(h);
  }
  return { kept, dropped };
}

/** The script a hook command runs, for a drop line (the same rule as the Codex adapter). */
function scriptName(command) {
  const m = String(command).match(/([A-Za-z0-9_-]+)\.(?:cjs|mjs|js|ps1|py|sh)\b/);
  return m ? m[1] : String(command).trim().split(/\s+/)[0];
}

/** Client-dialect hooks the operator added for this target only (core/port.json hooks.extra). */
const extraGroups = (ctx) => ((ctx.port.hooks && ctx.port.hooks.extra) || {})[ctx.target.id] || {};

/** Translate a Claude matcher through a token map. undefined = match all, null = drop the group. */
function translateMatcher(matcher, map, { keepUnknown }) {
  if (matcher == null || matcher === '' || matcher === '*') return undefined;
  const out = [];
  for (const token of String(matcher).split('|')) {
    const known = Object.prototype.hasOwnProperty.call(map, token);
    const mapped = known ? map[token] : keepUnknown ? token : null;
    if (!mapped) continue;
    for (const t of String(mapped).split('|')) if (!out.includes(t)) out.push(t);
  }
  return out.length ? out.join('|') : null;
}

/** `node "<shim>" --client <c> --event <e> -- cmd1 ++ cmd2` */
function shimCommand(client, event, commands) {
  const shim = common.shimPath().replace(/\\/g, '/');
  return `node "${shim}" --client ${client} --event ${event} -- ${commands.join(' ++ ')}`;
}

/** Largest timeout in a chain, or undefined when the source set none. */
function chainTimeout(handlers) {
  const values = handlers.map((h) => h.timeout).filter((t) => typeof t === 'number');
  return values.length ? Math.max(...values) : undefined;
}

/** A generated markdown file is ours when the state says we wrote it. */
const weWroteIt = (ctx, kind, file) =>
  owned(ctx, kind).includes(file) || Object.prototype.hasOwnProperty.call(ctx.state.files || {}, file);

/** Delete generated files this adapter created that no longer have a source. */
function pruneFiles(ctx, kind, keep) {
  const files = [];
  const keepSet = new Set(keep);
  for (const file of owned(ctx, kind)) {
    if (keepSet.has(file) || !fs.existsSync(file)) continue;
    if (ctx.check || ctx.dryRun) { files.push({ path: file, action: 'would-prune' }); continue; }
    if (ctx.backup) ctx.backup(file);
    fs.rmSync(file, { force: true });
    delete ctx.state.files[file];
    files.push({ path: file, action: 'pruned' });
  }
  if (!ctx.check && !ctx.dryRun) ctx.state.owned[ctx.target.id][kind] = keep;
  return files;
}

/** Render one markdown file per bundle item into a client directory, then prune. */
function renderMarkdownDir(ctx, kind, dir, items, metaFor) {
  const files = [];
  const dropped = [];
  const keep = [];
  for (const item of items) {
    const file = path.join(dir, `${item.name}.md`);
    if (fs.existsSync(file) && !weWroteIt(ctx, kind, file)) {
      dropped.push({ item: `${kind.slice(0, -1)} ${item.name}`, reason: `${common.tildePath(file, ctx.home)} already exists and was not created by the harness` });
      continue;
    }
    // No `header` claim here: `---` starts every frontmatter file, so claiming it
    // would make ctx.write treat a hand-edited agent as ours and overwrite it.
    // Ownership of these files is state.owned / state.files, which is exact.
    const res = ctx.write(file, common.renderFrontmatter(metaFor(item), item.body));
    files.push({ path: file, action: res.action });
    // Still wanted even when the write was refused: a hand-edited file must be
    // left for the user to resolve, never pruned as if the bundle had dropped it.
    keep.push(file);
  }
  files.push(...pruneFiles(ctx, kind, keep));
  return { files, dropped };
}

// ---------------------------------------------------------------------------
// MCP rendering
// ---------------------------------------------------------------------------

// Which JSON shape a client wants for a non-stdio server.
//   typed  -> { type: "http"|"sse", url, headers }   (Claude Code)
//   plain  -> { url, headers }                       (Cursor, Windsurf, Cline)
//   gemini -> { httpUrl } for http, { url } for sse  (Gemini CLI, Antigravity)
const HTTP_SHAPE = { gemini: 'gemini', agy: 'gemini', cursor: 'plain', windsurf: 'plain', cline: 'plain' };

// Clients that expand ${VAR} in an MCP value themselves. The rest get a note
// naming the variables the user has to have exported.
const EXPANDS_ENV = new Set(['claude', 'cursor']);

function renderServer(id, s) {
  if (s.transport === 'stdio') {
    const out = { command: s.command };
    if (s.args && s.args.length) out.args = s.args;
    if (s.env && Object.keys(s.env).length) out.env = s.env;
    if (s.cwd) out.cwd = s.cwd;
    return out;
  }
  const shape = HTTP_SHAPE[id] || 'typed';
  const headers = s.headers && Object.keys(s.headers).length ? s.headers : null;
  let out;
  if (shape === 'gemini') out = s.transport === 'http' ? { httpUrl: s.url } : { url: s.url };
  else if (shape === 'plain') out = { url: s.url };
  else out = { type: s.transport, url: s.url };
  if (headers) out.headers = headers;
  return out;
}

function renderOpencodeServer(s) {
  if (s.transport === 'stdio') {
    const out = { type: 'local', command: [s.command, ...(s.args || [])], enabled: true };
    if (s.env && Object.keys(s.env).length) out.environment = s.env;
    return out;
  }
  if (s.transport !== 'http') return null;
  const out = { type: 'remote', url: s.url, enabled: true };
  if (s.headers && Object.keys(s.headers).length) out.headers = s.headers;
  return out;
}

const envRefs = (s) => {
  const names = [];
  for (const v of [...Object.values(s.env || {}), ...Object.values(s.headers || {})]) {
    const m = /^\$\{([A-Za-z0-9_]+)\}$/.exec(String(v));
    if (m && !names.includes(m[1])) names.push(m[1]);
  }
  return names;
};

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function rules(ctx) {
  const file = at(ctx, ctx.target.rulesFile);
  if (!file) return unsupported('no rules file in the target registry');
  const preamble = String(ctx.target.preamble || '').trim();
  const drop = (ctx.port.rules && ctx.port.rules.dropSectionsForTargets) || [];
  const parts = [];
  if (preamble) parts.push(preamble);
  parts.push(stripSections(ctx.bundle.rules, drop));
  // A target-specific addendum (core/port.json rules.addenda.<id> -> a markdown file in the repo).
  const addendumRel = ctx.port.rules && ctx.port.rules.addenda && ctx.port.rules.addenda[ctx.target.id];
  const addendum = addendumRel ? common.readText(path.resolve(ctx.port.baseDir || common.ROOT, addendumRel)) : null;
  if (addendum && addendum.trim()) parts.push('---\n\n' + addendum.trim());
  if (ctx.bundle.identity && !ctx.target.traitsFile) parts.push('---\n\n' + ctx.bundle.identity.trim());
  parts.push(`<!-- ${common.GENERATED_MARK} from the ${ctx.bundle.manifest.source} harness -->`);
  let content = parts.join('\n\n') + '\n';
  // README rule 1: a file this adapter owns says so on its first line, which is
  // also how ctx.write recognises the file as ours after a hand edit. A
  // frontmatter file (Cursor's .mdc) has to keep `---` first, so there the claim
  // stays in the body and ownership falls back to the header line below.
  // A frontmatter preamble (Cursor's .mdc) has to keep `---` first, so it carries
  // no first-line claim and ctx.write falls back to state.files, which also means
  // a hand edit there is reported instead of overwritten.
  if (!preamble.startsWith('---') && !content.split('\n', 1)[0].includes(common.GENERATED_MARK)) {
    content = `<!-- ${common.GENERATED_MARK}. Do not edit; edit the source client and re-run the port. -->\n${content}`;
  }
  const res = ctx.write(file, content);
  return result(ctx, [{ path: file, action: res.action }], [], drop.length ? `dropped section(s): ${drop.join(', ')}` : undefined);
}

function identity(ctx) {
  const file = at(ctx, ctx.target.traitsFile);
  if (!file) return { status: 'synced', files: [], dropped: [], note: 'inlined in rules file' };
  if (!ctx.bundle.identity) return { status: 'synced', files: [], dropped: [], note: 'the bundle carries no identity file' };
  const body = `# ${path.basename(file)}\n\n<!-- ${common.GENERATED_MARK} from the ${ctx.bundle.manifest.source} harness -->\n\n${ctx.bundle.identity.trim()}\n`;
  const res = ctx.write(file, body);
  return result(ctx, [{ path: file, action: res.action }], []);
}

function skills(ctx) {
  const dir = at(ctx, ctx.target.skillsDir);
  if (!dir) return unsupported('client has no skills directory');
  // An older sync junctioned some clients' whole skills dir at a shared source
  // directory. Linking per skill inside it would write into the link's real
  // target, i.e. into another repo. Leave it alone and say so.
  const dirLink = common.readLinkTarget(dir);
  if (dirLink !== null) {
    return { status: 'skipped', files: [], dropped: [], note: `skills dir is a link to ${common.tildePath(dirLink, ctx.home)}; remove that link to get per-skill links` };
  }
  const exclude = (ctx.port.skills && ctx.port.skills.exclude) || {};
  const shared = (ctx.target.sharedSkillDirs || []).map((d) => at(ctx, d));
  const files = [];
  const dropped = [];
  const wanted = [];
  for (const skill of ctx.bundle.skills.skills || []) {
    if (exclude[skill.name]) { dropped.push({ item: `skill ${skill.name}`, reason: exclude[skill.name] }); continue; }
    const native = shared.find((d) => fs.existsSync(path.join(d, skill.name, 'SKILL.md')));
    if (native) { dropped.push({ item: `skill ${skill.name}`, reason: `already in the shared skills dir ${common.tildePath(native, ctx.home)}, which the client reads natively` }); continue; }
    wanted.push(skill);
  }
  const wantedNames = new Set(wanted.map((s) => s.name));

  // Prune first: a dangling link has to go before the same name is re-linked.
  for (const name of owned(ctx, 'skills')) {
    const dest = path.join(dir, name);
    const target = common.readLinkTarget(dest);
    if (target === null) continue;                       // a real directory or already gone: not ours to remove
    if (wantedNames.has(name) && fs.existsSync(target)) continue;
    if (ctx.check || ctx.dryRun) { files.push({ path: dest, action: 'would-prune' }); continue; }
    common.unlinkIfLink(dest);
    files.push({ path: dest, action: 'pruned' });
  }

  const linked = [];
  for (const skill of wanted) {
    const dest = path.join(dir, skill.name);
    const res = ctx.link(skill.path, dest);
    files.push({ path: dest, action: res.action });
    if (res.action === 'skipped-real-directory') dropped.push({ item: `skill ${skill.name}`, reason: 'a real directory already sits at that path' });
    else linked.push(skill.name);
  }
  if (!ctx.check && !ctx.dryRun) ctx.state.owned[ctx.target.id].skills = linked;
  return result(ctx, files, dropped, `${linked.length} skill(s) linked into ${common.tildePath(dir, ctx.home)}`);
}

function commands(ctx) {
  const dir = at(ctx, ctx.target.commandsDir);
  if (!dir) return unsupported('client has no slash-command directory');
  const { files, dropped } = renderMarkdownDir(ctx, 'commands', dir, ctx.bundle.commands, (c) => ({
    name: c.name,
    description: c.meta.description,
  }));
  return result(ctx, files, dropped);
}

function agents(ctx) {
  const dir = at(ctx, ctx.target.agentsDir);
  if (!dir) return unsupported('client has no subagent directory');
  const { files, dropped } = renderMarkdownDir(ctx, 'agents', dir, ctx.bundle.agents, (a) => ({
    name: a.name,
    description: a.meta.description,
    model: 'inherit',
    ...(String(a.meta.readonly) === 'true' ? { readonly: true } : {}),
  }));
  return result(ctx, files, dropped, 'model: inherit — the client picks the model, the harness only carries the role');
}

function mcp(ctx) {
  const file = at(ctx, ctx.target.mcpConfigFile);
  if (!file) return unsupported('client has no MCP configuration file');
  const format = ctx.target.mcpFormat || 'mcpServers-json';
  if (format !== 'mcpServers-json' && format !== 'opencode-json') {
    return unsupported(`mcpFormat "${format}" needs a client-specific adapter`);
  }
  const config = readUserJson(file);
  if (config === null) return { status: 'error', files: [{ path: file, action: 'unchanged' }], dropped: [], error: `${common.tildePath(file, ctx.home)} is not valid JSON; nothing was written` };

  const key = format === 'opencode-json' ? 'mcp' : 'mcpServers';
  config[key] = config[key] && typeof config[key] === 'object' ? config[key] : {};
  const servers = config[key];
  const exclude = (ctx.port.mcp && ctx.port.mcp.exclude) || {};
  const dropped = [];
  const previouslyOwned = owned(ctx, 'mcp');
  const nowOwned = [];
  const envNames = [];

  for (const [name, server] of Object.entries(ctx.bundle.mcp.servers || {})) {
    if (exclude[name]) { dropped.push({ item: `mcp ${name}`, reason: exclude[name] }); continue; }
    if (Object.prototype.hasOwnProperty.call(servers, name) && !previouslyOwned.includes(name)) {
      dropped.push({ item: `mcp ${name}`, reason: 'already configured by the user' });
      continue;
    }
    const rendered = format === 'opencode-json' ? renderOpencodeServer(server) : renderServer(ctx.target.id, server);
    if (!rendered) { dropped.push({ item: `mcp ${name}`, reason: `OpenCode has no ${server.transport} transport` }); continue; }
    servers[name] = rendered;
    nowOwned.push(name);
    for (const n of envRefs(server)) if (!envNames.includes(n)) envNames.push(n);
  }
  for (const name of previouslyOwned) {
    if (!nowOwned.includes(name) && Object.prototype.hasOwnProperty.call(servers, name)) delete servers[name];
  }
  if (!Object.keys(servers).length) delete config[key];

  const res = writeUserJson(ctx, file, config);
  if (!ctx.check && !ctx.dryRun) ctx.state.owned[ctx.target.id].mcp = nowOwned;
  const note = envNames.length && !EXPANDS_ENV.has(ctx.target.id)
    ? `${nowOwned.length} server(s); export ${envNames.join(', ')} yourself — this client does not expand \${VAR}`
    : `${nowOwned.length} server(s)`;
  return result(ctx, [{ path: file, action: res.action }], dropped, note);
}

const hooks = () => unsupported('client has no hook surface the harness can drive');
const permissions = () => unsupported('client has no machine-readable permission surface');

module.exports = {
  id: 'generic',
  components: COMPONENTS,
  rules, identity, hooks, skills, agents, commands, mcp, permissions,
  // internals reused by the client-specific adapters and by the tests
  _internals: {
    owned, statusFrom, result, unsupported, at, canonical, stableKey,
    readUserJson, writeUserJson, applyOwnedGroups, portedHandlers, extraGroups,
    translateMatcher, shimCommand, chainTimeout, weWroteIt, pruneFiles,
    renderMarkdownDir, renderServer, renderOpencodeServer, envRefs, HTTP_SHAPE,
  },
};
