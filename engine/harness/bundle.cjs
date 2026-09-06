/**
 * engine/harness/bundle.cjs — the client-neutral harness bundle.
 *
 * On disk: <repo>/harness/ (gitignored by default; it holds machine paths).
 * In memory: the object returned by createBundle(). See README.md for the shape.
 */

const fs = require('fs');
const path = require('path');
const { ROOT, looksSecret, parseFrontmatter, renderFrontmatter } = require('./common.cjs');

const BUNDLE_VERSION = '1';
const DEFAULT_DIR = path.join(ROOT, 'harness');
const COMPONENTS = ['rules', 'identity', 'hooks', 'skills', 'agents', 'commands', 'mcp', 'permissions'];
const MODEL_TIERS = ['fable', 'opus', 'sonnet', 'haiku', 'inherit'];

function createBundle(source = 'unknown', sourceHome = '') {
  return {
    manifest: { version: BUNDLE_VERSION, source, sourceHome, capturedAt: null, components: {} },
    rules: '',
    identity: '',
    hooks: { dialect: 'claude', events: {} },
    mcp: { servers: {} },
    agents: [],      // [{ name, meta: { name, description, model, tools, readonly }, body }]
    commands: [],    // [{ name, meta: { description, 'argument-hint' }, body }]
    skills: { sourceDir: '', skills: [] },  // [{ name, path }]
    permissions: { allow: [], deny: [], ask: [] },
  };
}

function counts(bundle) {
  const hookCount = Object.values(bundle.hooks.events || {}).reduce((n, groups) => n + groups.reduce((m, g) => m + (g.hooks || []).length, 0), 0);
  return {
    rules: bundle.rules ? 1 : 0,
    identity: bundle.identity ? 1 : 0,
    hooks: hookCount,
    skills: bundle.skills.skills.length,
    agents: bundle.agents.length,
    commands: bundle.commands.length,
    mcp: Object.keys(bundle.mcp.servers).length,
    permissions: bundle.permissions.allow.length + bundle.permissions.deny.length + bundle.permissions.ask.length,
  };
}

/** Structural validation. Returns an array of problems (empty = valid). */
function validate(bundle) {
  const problems = [];
  if (!bundle || typeof bundle !== 'object') return ['bundle is not an object'];
  if (typeof bundle.rules !== 'string' || !bundle.rules.trim()) problems.push('rules.md is empty');
  if (!bundle.hooks || typeof bundle.hooks.events !== 'object') problems.push('hooks.json needs an events object');
  for (const [event, groups] of Object.entries((bundle.hooks && bundle.hooks.events) || {})) {
    if (!Array.isArray(groups)) { problems.push(`hooks.events.${event} must be an array`); continue; }
    groups.forEach((g, i) => {
      if (!Array.isArray(g.hooks)) problems.push(`hooks.events.${event}[${i}].hooks must be an array`);
      else g.hooks.forEach((h, j) => {
        if (h.type !== 'command' || typeof h.command !== 'string' || !h.command) problems.push(`hooks.events.${event}[${i}].hooks[${j}] needs type "command" and a command string`);
      });
    });
  }
  for (const [name, s] of Object.entries((bundle.mcp && bundle.mcp.servers) || {})) {
    if (!/^[A-Za-z0-9_.-]+$/.test(name)) problems.push(`mcp server name "${name}" is not a safe identifier`);
    if (!['stdio', 'http', 'sse'].includes(s.transport)) problems.push(`mcp.${name}.transport must be stdio, http or sse`);
    if (s.transport === 'stdio' && !s.command) problems.push(`mcp.${name} (stdio) needs a command`);
    if (s.transport !== 'stdio' && !s.url) problems.push(`mcp.${name} (${s.transport}) needs a url`);
    for (const [k, v] of Object.entries(s.env || {})) if (looksSecret(k, v)) problems.push(`mcp.${name}.env.${k} looks like a secret; capture must replace it with \${${k}}`);
    for (const [k, v] of Object.entries(s.headers || {})) if (looksSecret(k, v)) problems.push(`mcp.${name}.headers.${k} looks like a secret; capture must replace it with \${${k}}`);
  }
  for (const a of bundle.agents || []) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(a.name)) problems.push(`agent name "${a.name}" must be kebab-case`);
    if (!a.meta || typeof a.meta.description !== 'string') problems.push(`agent ${a.name} needs a description`);
  }
  for (const c of bundle.commands || []) if (!/^[A-Za-z0-9_-]+$/.test(c.name)) problems.push(`command name "${c.name}" is not a safe file name`);
  for (const s of (bundle.skills && bundle.skills.skills) || []) {
    if (!/^[A-Za-z0-9_.-]+$/.test(s.name)) problems.push(`skill name "${s.name}" is not a safe directory name`);
    if (!path.isAbsolute(s.path || '')) problems.push(`skill ${s.name} needs an absolute path`);
  }
  return problems;
}

function save(bundle, dir = DEFAULT_DIR) {
  const problems = validate(bundle);
  if (problems.length) throw new Error(`refusing to save an invalid bundle:\n  - ${problems.join('\n  - ')}`);
  bundle.manifest.capturedAt = bundle.manifest.capturedAt || new Date().toISOString();
  bundle.manifest.components = counts(bundle);
  fs.mkdirSync(dir, { recursive: true });
  const w = (name, text) => fs.writeFileSync(path.join(dir, name), text, 'utf8');
  w('manifest.json', JSON.stringify(bundle.manifest, null, 2) + '\n');
  w('rules.md', bundle.rules.trimEnd() + '\n');
  if (bundle.identity) w('identity.md', bundle.identity.trimEnd() + '\n');
  else if (fs.existsSync(path.join(dir, 'identity.md'))) fs.unlinkSync(path.join(dir, 'identity.md'));
  w('hooks.json', JSON.stringify(bundle.hooks, null, 2) + '\n');
  w('mcp.json', JSON.stringify(bundle.mcp, null, 2) + '\n');
  w('skills.json', JSON.stringify(bundle.skills, null, 2) + '\n');
  w('permissions.json', JSON.stringify(bundle.permissions, null, 2) + '\n');
  for (const [sub, items] of [['agents', bundle.agents], ['commands', bundle.commands]]) {
    const subdir = path.join(dir, sub);
    fs.rmSync(subdir, { recursive: true, force: true });
    fs.mkdirSync(subdir, { recursive: true });
    for (const it of items) fs.writeFileSync(path.join(subdir, `${it.name}.md`), renderFrontmatter(it.meta, it.body), 'utf8');
  }
  return dir;
}

function load(dir = DEFAULT_DIR) {
  if (!fs.existsSync(path.join(dir, 'manifest.json'))) return null;
  const read = (name, fallback) => (fs.existsSync(path.join(dir, name)) ? fs.readFileSync(path.join(dir, name), 'utf8') : fallback);
  const json = (name, fallback) => { const t = read(name, null); return t == null ? fallback : JSON.parse(t); };
  const bundle = createBundle();
  bundle.manifest = json('manifest.json', bundle.manifest);
  bundle.rules = read('rules.md', '');
  bundle.identity = read('identity.md', '');
  bundle.hooks = json('hooks.json', bundle.hooks);
  bundle.mcp = json('mcp.json', bundle.mcp);
  bundle.skills = json('skills.json', bundle.skills);
  bundle.permissions = json('permissions.json', bundle.permissions);
  for (const sub of ['agents', 'commands']) {
    const subdir = path.join(dir, sub);
    if (!fs.existsSync(subdir)) continue;
    for (const f of fs.readdirSync(subdir).filter((n) => n.endsWith('.md')).sort()) {
      const { meta, body } = parseFrontmatter(fs.readFileSync(path.join(subdir, f), 'utf8'));
      bundle[sub].push({ name: f.replace(/\.md$/, ''), meta, body: body.trim() });
    }
  }
  const problems = validate(bundle);
  if (problems.length) throw new Error(`harness bundle at ${dir} is invalid:\n  - ${problems.join('\n  - ')}`);
  return bundle;
}

/**
 * Normalise a model reference into a tier when possible. "claude-opus-5" -> "opus",
 * "sonnet" -> "sonnet", "gpt-5.6-terra" -> unchanged (raw id, targets map by ladder or pass through).
 */
function modelTier(model) {
  const m = String(model || 'inherit').toLowerCase();
  for (const tier of MODEL_TIERS) if (m === tier || m.includes(tier)) return tier;
  return model;
}

module.exports = { BUNDLE_VERSION, DEFAULT_DIR, COMPONENTS, MODEL_TIERS, createBundle, counts, validate, save, load, modelTier };
