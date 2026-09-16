/**
 * engine/harness/capture.cjs — read ONE live client into the neutral bundle.
 *
 * The source client is the harness the user actually drives. Everything else is
 * a rendering of it. Nothing here knows a client format: the per-client reader
 * is `sources/<id>.cjs` and the contract is engine/harness/README.md.
 *
 * Also the home of `loadRegistry()` — the target list with every path expanded
 * and `installed` decided by what is on disk. apply and status both read it.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const { ROOT, expandPath } = require('./common.cjs');
const bundleMod = require('./bundle.cjs');

const TARGETS_FILE = path.join(ROOT, 'core', 'templates', 'targets.json');
const PORT_FILE = path.join(ROOT, 'core', 'port.json');
const SOURCES_DIR = path.join(__dirname, 'sources');

/** Registry fields that hold a path and therefore get expanded against `home`. */
const PATH_FIELDS = [
  'home', 'rulesFile', 'traitsFile', 'hooksConfigFile', 'skillsDir',
  'agentsDir', 'commandsDir', 'mcpConfigFile', 'permissionsFile',
];

/**
 * The target registry with every path field expanded to an absolute path and
 * `installed` read from disk. A target with no `home` (the generic system card)
 * is a file we own, so it is always installed.
 */
function loadRegistry(home = os.homedir(), { file = TARGETS_FILE, targets = null } = {}) {
  const raw = Array.isArray(targets) ? { targets } : JSON.parse(fs.readFileSync(file, 'utf8'));
  return (raw.targets || []).map((t) => {
    const target = Object.assign({}, t);
    for (const field of PATH_FIELDS) if (t[field]) target[field] = expandPath(t[field], home);
    if (Array.isArray(t.sharedSkillDirs)) target.sharedSkillDirs = t.sharedSkillDirs.map((p) => expandPath(p, home));
    target.installed = t.home ? fs.existsSync(target.home) : true;
    return target;
  });
}

/** core/port.json — the port policy. Missing file = defaults, never a crash. */
function loadPort(file = PORT_FILE) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (_) {
    return { source: 'auto', targets: 'installed' };
  }
}

/**
 * Which client is the source of truth, decided from disk alone: the rules file
 * a user of that client necessarily has. Returns null when neither is present.
 */
function detectSource(home = os.homedir()) {
  if (fs.existsSync(path.join(home, '.claude', 'CLAUDE.md'))) return 'claude';
  if (fs.existsSync(path.join(home, '.codex', 'AGENTS.md'))) return 'codex';
  return null;
}

function resolveSourceId({ from, port, home }) {
  if (from) return from;
  if (port && port.source && port.source !== 'auto') return port.source;
  const detected = detectSource(home);
  if (detected) return detected;
  throw new Error('no source client found; pass --from');
}

/** Load `sources/<id>.cjs`, telling the user exactly which module is missing. */
function loadSourceAdapter(id) {
  const file = path.join(SOURCES_DIR, `${id}.cjs`);
  try {
    return require(file);
  } catch (err) {
    if (!fs.existsSync(file)) {
      throw new Error(`missing module engine/harness/sources/${id}.cjs — no capture adapter for source client "${id}" (it must export { id, capture({ home, target, port }) })`);
    }
    throw err;
  }
}

/**
 * capture({ from, home, port, outDir, registry, sources }) -> { bundle, warnings, dir }
 * Reads the source client and writes <repo>/harness/ (or outDir).
 *
 * `registry` is an already-expanded target list (loadRegistry()) for a host
 * that ships its own; `sources` maps a source id to an adapter module and
 * replaces the require, the way `adapters` does for apply().
 */
function capture({ from, home = os.homedir(), port, outDir, registry, sources = {} } = {}) {
  const policy = port || loadPort();
  const id = resolveSourceId({ from, port: policy, home });
  const target = (registry || loadRegistry(home)).find((t) => t.id === id);
  if (!target) throw new Error(`source client "${id}" is not in the target registry`);

  const adapter = sources[id] || loadSourceAdapter(id);
  if (typeof adapter.capture !== 'function') throw new Error(`engine/harness/sources/${id}.cjs does not export capture()`);

  const result = adapter.capture({ home, target, port: policy }) || {};
  const bundle = result.bundle;
  if (!bundle) throw new Error(`engine/harness/sources/${id}.cjs returned no bundle`);
  const warnings = result.warnings || [];
  // Whatever the adapter kept, a credential does not travel: free text is
  // redacted, an unsafe handler or server or a malformed item is dropped with
  // a warning, and save() still refuses anything that slipped through.
  warnings.push(...bundleMod.sanitize(bundle));

  bundle.manifest.source = bundle.manifest.source && bundle.manifest.source !== 'unknown' ? bundle.manifest.source : id;
  bundle.manifest.sourceHome = bundle.manifest.sourceHome || (target.home || home);
  bundle.manifest.capturedAt = new Date().toISOString();

  const dir = bundleMod.save(bundle, outDir || bundleMod.DEFAULT_DIR);
  return { bundle, warnings, dir };
}

module.exports = { capture, detectSource, resolveSourceId, loadRegistry, loadPort, TARGETS_FILE, PORT_FILE };
