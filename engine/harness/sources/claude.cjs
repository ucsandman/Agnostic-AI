/**
 * engine/harness/sources/claude.cjs — capture the Claude Code harness into the
 * client-neutral bundle.
 *
 * Claude Code is the canonical dialect (hook events, tool names, matcher syntax),
 * so capture is a read + normalise, not a translation. Capture is COMPLETE: every
 * hook, skill and server the client has lands in the bundle. What a given target
 * refuses to carry is that target's decision, made in targets/<id>.cjs from
 * core/port.json, so `explain` can name the client that dropped it.
 *
 * Nothing here is machine-specific: every path comes from `home` or from the
 * expanded `claude` entry of core/templates/targets.json.
 */

const fs = require('fs');
const path = require('path');
const common = require('../common.cjs');
const bundleLib = require('../bundle.cjs');

const ID = 'claude';
const EDIT_TOOLS = /^(?:Edit|Write|MultiEdit|NotebookEdit)$/;
/** How many levels of `@import` are inlined: the rules file's own, plus one more. */
const IMPORT_DEPTH = 2;

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

/** True when `child` is `parent` or lives under it (case- and separator-insensitive). */
function inside(child, parent) {
  if (!child || !parent) return false;
  const c = common.plainPath(child);
  const p = common.plainPath(parent);
  return c === p || c.startsWith(p.endsWith('/') ? p : `${p}/`);
}

/**
 * The registry path when there is one, else the conventional one under `home`.
 * loadRegistry() expands every entry against the home it is given, and a host
 * may point a client at a config dir outside that home (CLAUDE_CONFIG_DIR):
 * that path is the one to read, never a silent fallback to ~/.claude.
 */
const pick = (registryPath, fallback) => (registryPath ? registryPath : fallback);

function surfaces(home, target = {}) {
  const claudeDir = pick(target.home, path.join(home, '.claude'));
  return {
    claudeDir,
    rulesFile: path.join(claudeDir, 'CLAUDE.md'),
    identityFile: pick(target.traitsFile, path.join(claudeDir, 'SOUL.md')),
    settingsFile: pick(target.hooksConfigFile, path.join(claudeDir, 'settings.json')),
    agentsDir: pick(target.agentsDir, path.join(claudeDir, 'agents')),
    commandsDir: pick(target.commandsDir, path.join(claudeDir, 'commands')),
    skillsDir: pick(target.skillsDir, path.join(claudeDir, 'skills')),
    mcpFile: pick(target.mcpConfigFile, path.join(home, '.claude.json')),
    projectMcpFile: path.join(claudeDir, '.mcp.json'),
  };
}

// ---------------------------------------------------------------------------
// Rules: CLAUDE.md with every @import inlined
// ---------------------------------------------------------------------------

/** `@~/x`, `@C:/x`, `@./x`, `@x` -> an absolute path, resolved against the importing file's directory. */
function resolveImport(spec, home, baseDir) {
  if (spec === '~') return home;
  if (spec.startsWith('~/') || spec.startsWith('~\\')) return path.join(home, spec.slice(2));
  if (path.isAbsolute(spec)) return path.resolve(spec);
  return path.resolve(baseDir, spec);
}

/**
 * Drop the header a generated file opens with: the `# Title` line and, when the
 * next non-blank line announces it, the `GENERATED ...` provenance line. The
 * bundle carries one agreement, not a stack of per-file title pages.
 */
function stripGeneratedHeader(text) {
  const lines = String(text).split(/\r?\n/);
  if (!/^#\s+\S/.test(lines[0] || '')) return String(text);
  let i = 1;
  while (i < lines.length && lines[i].trim() === '') i++;
  if (i < lines.length && lines[i].includes('GENERATED')) {
    i++;
    while (i < lines.length && lines[i].trim() === '') i++;
  }
  return lines.slice(i).join('\n');
}

/**
 * Inline `@<path>` import lines. An import is followed only when the resolved
 * file lives inside `home` or inside the repo: an agreement is allowed to be
 * assembled from the user's own harness and from this repo, and from nothing
 * else, because the result is copied verbatim into every other client.
 */
function inlineImports(text, { home, baseDir, level, warnings, where }) {
  const out = [];
  for (const line of String(text).split(/\r?\n/)) {
    const m = line.match(/^@(\S+)[ \t]*$/);
    if (!m) { out.push(line); continue; }
    const spec = m[1];
    const resolved = resolveImport(spec, home, baseDir);
    if (level <= 0) {
      warnings.push(`${where}: import ${spec} is nested deeper than ${IMPORT_DEPTH} levels; the line was dropped`);
      continue;
    }
    if (!inside(resolved, home) && !common.importRoots().some((root) => inside(resolved, root))) {
      warnings.push(`${where}: import ${spec} resolves outside the home directory and outside the allowed import roots; the line was dropped`);
      continue;
    }
    const raw = common.readText(resolved);
    if (raw == null) {
      warnings.push(`${where}: import ${spec} does not exist (${common.tildePath(resolved, home)}); the line was dropped`);
      continue;
    }
    const body = inlineImports(stripGeneratedHeader(raw), {
      home,
      baseDir: path.dirname(resolved),
      level: level - 1,
      warnings,
      where: common.tildePath(resolved, home),
    });
    out.push(body.trim());
  }
  return out.join('\n');
}

function captureRules(paths, home, warnings) {
  const raw = common.readText(paths.rulesFile);
  if (raw == null) throw new Error(`Claude Code rules file not found: ${paths.rulesFile}`);
  let body = inlineImports(raw, {
    home,
    baseDir: path.dirname(paths.rulesFile),
    level: IMPORT_DEPTH,
    warnings,
    where: common.tildePath(paths.rulesFile, home),
  });
  body = body.replace(/^#\s*CLAUDE\.md[^\n]*\r?\n+/m, '');
  return body.replace(/\n{3,}/g, '\n\n').trim();
}

// ---------------------------------------------------------------------------
// Hooks: settings.json -> the canonical dialect, copied as-is
// ---------------------------------------------------------------------------
function captureHooks(settings, warnings) {
  const events = {};
  const src = (settings && settings.hooks) || {};
  if (Array.isArray(src) || typeof src !== 'object') {
    warnings.push('settings.json: hooks is not an object; no hooks captured');
    return events;
  }
  for (const [event, groups] of Object.entries(src)) {
    if (!Array.isArray(groups)) {
      warnings.push(`settings.json: hooks.${event} is not an array; skipped`);
      continue;
    }
    const kept = [];
    for (const group of groups) {
      const handlers = [];
      for (const h of (group && group.hooks) || []) {
        if (!h || h.type !== 'command' || typeof h.command !== 'string' || !h.command.trim()) continue;
        const out = { type: 'command', command: h.command };
        if (h.timeout != null) out.timeout = h.timeout;
        if (h.statusMessage) out.statusMessage = h.statusMessage;
        if (h.async) out.async = true;
        handlers.push(out);
      }
      if (!handlers.length) continue;
      const out = {};
      if (group.matcher != null && group.matcher !== '') out.matcher = group.matcher;
      out.hooks = handlers;
      kept.push(out);
    }
    if (kept.length) events[event] = kept;
  }
  return events;
}

// ---------------------------------------------------------------------------
// MCP: ~/.claude.json (+ ~/.claude/.mcp.json) -> the neutral server shape
// ---------------------------------------------------------------------------
const TRANSPORTS = ['stdio', 'http', 'sse'];

function captureServers(source, into, warnings, origin) {
  for (const [server, raw] of Object.entries(source || {})) {
    if (!raw || typeof raw !== 'object') continue;
    if (Object.prototype.hasOwnProperty.call(into, server)) {
      warnings.push(`MCP server ${server}: also defined in ${origin}; the first definition wins`);
      continue;
    }
    const declared = String(raw.type || '').toLowerCase();
    const transport = TRANSPORTS.includes(declared) ? declared : (raw.url ? 'http' : 'stdio');
    if (raw.type && !TRANSPORTS.includes(declared)) {
      warnings.push(`MCP server ${server}: unknown type "${raw.type}"; captured as ${transport}`);
    }
    // A value that looks like a credential never enters the bundle: the bundle is
    // copied into every client's config, so one token here becomes N tokens on disk.
    const scrub = (obj, kind) => {
      if (!obj || typeof obj !== 'object') return undefined;
      const out = {};
      for (const [k, v] of Object.entries(obj)) {
        if (common.looksSecret(k, v)) {
          out[k] = `\${${k}}`;
          warnings.push(`MCP server ${server}: ${kind} ${k} looks like a secret; it stays out of the bundle, export ${k} in the environment of each client`);
        } else {
          out[k] = v;
        }
      }
      return Object.keys(out).length ? out : undefined;
    };
    const entry = { transport };
    if (transport === 'stdio') {
      if (raw.command) entry.command = raw.command;
      if (Array.isArray(raw.args) && raw.args.length) entry.args = raw.args.slice();
      if (raw.cwd) entry.cwd = raw.cwd;
    } else if (raw.url) {
      entry.url = raw.url;
    }
    const env = scrub(raw.env, 'env');
    if (env) entry.env = env;
    const headers = scrub(raw.headers, 'header');
    if (headers) entry.headers = headers;
    into[server] = entry;
  }
}

// ---------------------------------------------------------------------------
// Agents, commands, skills, permissions
// ---------------------------------------------------------------------------
function markdownFiles(dir, skip = []) {
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (_) { return []; }
  return entries
    .filter((e) => !e.isDirectory() && e.name.endsWith('.md') && !skip.includes(e.name))
    .map((e) => e.name)
    .sort();
}

function captureAgents(dir, warnings) {
  const agents = [];
  for (const file of markdownFiles(dir)) {
    const { meta, body } = common.parseFrontmatter(common.readText(path.join(dir, file)) || '');
    const name = meta.name || file.replace(/\.md$/, '');
    const tools = typeof meta.tools === 'string' ? meta.tools.trim() : '';
    const toolList = tools ? tools.split(',').map((t) => t.trim()).filter(Boolean) : [];
    // A missing `tools` field means "every tool", which includes the edit tools.
    const readonly = toolList.length > 0 && !toolList.some((t) => EDIT_TOOLS.test(t));
    if (!meta.description) warnings.push(`agent ${name}: no description in the frontmatter; the agent name is used instead`);
    const out = {
      name,
      description: meta.description || name,
      model: bundleLib.modelTier(meta.model || 'inherit'),
    };
    if (tools) out.tools = tools;
    if (readonly) out.readonly = true; // omitted when false: `readonly: false` reloads as the string "false"
    agents.push({ name, meta: out, body: String(body).trim() });
  }
  return agents;
}

function captureCommands(dir) {
  const commands = [];
  for (const file of markdownFiles(dir, ['README.md'])) {
    const { meta, body } = common.parseFrontmatter(common.readText(path.join(dir, file)) || '');
    const out = {};
    if (meta.description) out.description = meta.description;
    if (meta['argument-hint']) out['argument-hint'] = meta['argument-hint'];
    commands.push({ name: file.replace(/\.md$/, ''), meta: out, body: String(body).trim() });
  }
  return commands;
}

function captureSkills(dir, warnings) {
  const out = [];
  for (const skill of common.listSkills(dir)) {
    // Targets link the REAL directory: a chain of links through one client's
    // skills dir dies the moment that client is uninstalled.
    let real = skill.path;
    try { real = fs.realpathSync(skill.path).replace(/^\\\\\?\\/, ''); } catch (err) {
      warnings.push(`skill ${skill.name}: could not resolve its real directory (${err.message}); using ${skill.path}`);
    }
    out.push({ name: skill.name, path: real });
  }
  return out;
}

const stringList = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);

// ---------------------------------------------------------------------------
function capture({ home, target = {}, port } = {}) {
  void port; // capture is complete; exclusions are a per-target apply decision
  if (!home) throw new Error('capture({ home }) needs a home directory');
  const warnings = [];
  const paths = surfaces(home, target);
  const b = bundleLib.createBundle(ID, home);

  b.rules = captureRules(paths, home, warnings);

  const identity = common.readText(paths.identityFile);
  if (identity != null) b.identity = identity.trim();

  const settings = common.readJSON(paths.settingsFile);
  if (settings === undefined) warnings.push(`${common.tildePath(paths.settingsFile, home)} is not valid JSON; no hooks or permissions captured`);
  b.hooks.events = captureHooks(settings, warnings);

  const rootMcp = common.readJSON(paths.mcpFile);
  if (rootMcp === undefined) warnings.push(`${common.tildePath(paths.mcpFile, home)} is not valid JSON; no MCP servers captured from it`);
  captureServers(rootMcp && rootMcp.mcpServers, b.mcp.servers, warnings, common.tildePath(paths.mcpFile, home));
  const projectMcp = common.readJSON(paths.projectMcpFile);
  if (projectMcp === undefined) warnings.push(`${common.tildePath(paths.projectMcpFile, home)} is not valid JSON; skipped`);
  captureServers(projectMcp && projectMcp.mcpServers, b.mcp.servers, warnings, common.tildePath(paths.projectMcpFile, home));

  b.agents = captureAgents(paths.agentsDir, warnings);
  b.commands = captureCommands(paths.commandsDir);
  b.skills.sourceDir = paths.skillsDir;
  b.skills.skills = captureSkills(paths.skillsDir, warnings);

  const permissions = (settings && settings.permissions) || {};
  b.permissions = {
    allow: stringList(permissions.allow),
    deny: stringList(permissions.deny),
    ask: stringList(permissions.ask),
  };

  // Report, never throw: capture must show what it found even when one surface is
  // malformed, or the operator cannot see which surface to fix.
  for (const problem of bundleLib.validate(b)) warnings.push(`bundle: ${problem}`);
  return { bundle: b, warnings };
}

module.exports = { id: ID, capture };
