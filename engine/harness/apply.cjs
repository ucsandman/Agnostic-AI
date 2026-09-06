/**
 * engine/harness/apply.cjs — render the captured bundle into every other client.
 *
 * One guarded write per file, one ComponentResult per component, one row per
 * target. The source client is never written to: it is the thing being copied.
 * Everything a target could not take lands in `dropped` with a reason, which is
 * what `npm run explain` prints.
 *
 * Contract for `ctx` and ComponentResult: engine/harness/README.md.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const common = require('./common.cjs');
const bundleMod = require('./bundle.cjs');
const { loadRegistry, loadPort } = require('./capture.cjs');

const ROOT = common.ROOT;
const DEFAULT_STORAGE = path.join(ROOT, 'storage');
const TARGETS_DIR = path.join(__dirname, 'targets');

const GLYPH = { synced: '✓', written: '●', stale: '✗', skipped: '!', unsupported: '-', error: 'E', source: '=' };
const ABBR = { rules: 'ru', identity: 'id', hooks: 'ho', skills: 'sk', agents: 'ag', commands: 'cm', mcp: 'mc', permissions: 'pm' };
// Worst-first: a target's headline status is the worst thing that happened to it.
const SEVERITY = ['error', 'stale', 'skipped', 'written', 'synced', 'unsupported'];

const LEGEND = `legend: ${GLYPH.synced} synced  ${GLYPH.written} written  ${GLYPH.stale} stale  ${GLYPH.skipped} skipped (hand-edited)  ${GLYPH.unsupported} unsupported  ${GLYPH.error} error  ${GLYPH.source} source`;

function readState(file) {
  const state = common.readJSON(file);
  if (!state || typeof state !== 'object' || !state.targets) return { version: 1, targets: {} };
  return state;
}

/** Load `targets/<adapter>.cjs`, naming the missing module when it is not there. */
function loadTargetAdapter(adapterId) {
  const file = path.join(TARGETS_DIR, `${adapterId}.cjs`);
  try {
    return require(file);
  } catch (err) {
    if (!fs.existsSync(file)) {
      throw new Error(`missing module engine/harness/targets/${adapterId}.cjs — no render adapter for "${adapterId}" (it must export { id, components, <component>(ctx) })`);
    }
    throw err;
  }
}

/** Which registry entries this run writes to, and why. Throws on an unknown --to id. */
function selectTargets(registry, { to, port }) {
  if (Array.isArray(to) && to.length) {
    const known = new Set(registry.map((t) => t.id));
    const unknown = to.filter((id) => !known.has(id));
    if (unknown.length) throw new Error(`unknown target id(s): ${unknown.join(', ')} (known: ${registry.map((t) => t.id).join(', ')})`);
    return registry.filter((t) => to.includes(t.id));
  }
  const policy = (port && port.targets) || 'installed';
  if (Array.isArray(policy)) return registry.filter((t) => policy.includes(t.id));
  if (policy === 'all') return registry.slice();
  return registry.filter((t) => t.installed);
}

function rollUp(components) {
  const seen = new Set(Object.values(components).map((r) => r.status));
  for (const status of SEVERITY) if (seen.has(status)) return status;
  return 'synced';
}

function countFiles(report) {
  const totals = { written: 0, wouldWrite: 0, unchanged: 0, skipped: 0, dropped: 0 };
  for (const target of Object.values(report.targets)) {
    for (const result of Object.values(target.components || {})) {
      for (const file of result.files || []) {
        if (file.action === 'written' || file.action === 'linked') totals.written++;
        else if (file.action === 'would-write' || file.action === 'would-link') totals.wouldWrite++;
        else if (file.action === 'unchanged') totals.unchanged++;
        else if (String(file.action || '').startsWith('skipped')) totals.skipped++;
      }
      totals.dropped += (result.dropped || []).length;
    }
  }
  return totals;
}

/** The compact matrix: one row per target, one cell per component. */
function formatTable(report) {
  const ids = Object.keys(report.targets);
  const nameWidth = Math.max(6, ...ids.map((id) => report.targets[id].name.length));
  const head = ['Target'.padEnd(nameWidth), ...bundleMod.COMPONENTS.map((c) => ABBR[c])].join(' ') + '  dropped';
  const lines = [head, '-'.repeat(head.length)];
  for (const id of ids) {
    const t = report.targets[id];
    const cells = bundleMod.COMPONENTS.map((c) => {
      if (t.status === 'source') return GLYPH.source.padEnd(2);
      const result = (t.components || {})[c];
      return (result ? GLYPH[result.status] || '?' : GLYPH.unsupported).padEnd(2);
    });
    const dropped = String(t.dropped || 0).padStart(7);
    const note = t.status === 'source' ? '  source of truth' : t.installed ? (t.note ? `  ${t.note}` : '') : '  not installed';
    lines.push(`${t.name.padEnd(nameWidth)} ${cells.join(' ')} ${dropped}${note}`);
  }
  const totals = report.totals;
  const verb = report.mode === 'apply' ? 'files written' : 'files would change';
  const changed = report.mode === 'apply' ? totals.written : totals.wouldWrite;
  lines.push('');
  lines.push(`${ids.length} targets, ${changed} ${verb}, ${totals.unchanged} unchanged, ${totals.skipped} skipped, ${totals.dropped} dropped  [${report.mode}]`);
  lines.push(LEGEND);
  return lines.join('\n');
}

/**
 * apply({ bundle, bundleDir, home, port, to, check, dryRun, force, storageDir, adapters, log, quiet }) -> report
 *
 * `adapters` maps a target id (or an adapter id) to an already-loaded module and
 * replaces the require — the tests inject stubs through it.
 */
function apply(options = {}) {
  const {
    bundleDir, home = os.homedir(), to, check = false, dryRun = false, force = false,
    adapters = {}, quiet = false,
  } = options;
  const log = options.log || ((line) => { if (!quiet) console.log(line); });
  const storageDir = options.storageDir || DEFAULT_STORAGE;

  const bundle = options.bundle || bundleMod.load(bundleDir || bundleMod.DEFAULT_DIR);
  if (!bundle) throw new Error('no bundle captured yet; run npm run capture');
  const port = options.port || loadPort();

  const registry = loadRegistry(home);
  const selected = selectTargets(registry, { to: Array.isArray(to) ? to : to ? String(to).split(',') : null, port });
  const sourceId = bundle.manifest && bundle.manifest.source;

  const stateFile = path.join(storageDir, 'harness-state.json');
  const backupsDir = path.join(storageDir, 'backups');
  const state = readState(stateFile);
  const readOnly = Boolean(check || dryRun);

  const report = {
    appliedAt: new Date().toISOString(),
    source: sourceId || null,
    mode: check ? 'check' : dryRun ? 'dry-run' : 'apply',
    bundle: {
      source: sourceId || null,
      capturedAt: (bundle.manifest && bundle.manifest.capturedAt) || null,
      components: (bundle.manifest && bundle.manifest.components) || {},
    },
    targets: {},
  };

  for (const target of selected) {
    const row = {
      id: target.id,
      name: target.name,
      category: target.category || 'Agent',
      installed: target.installed,
      adapter: target.adapter || 'generic',
      home: target.home || null,
      status: 'synced',
      components: {},
      dropped: 0,
    };
    report.targets[target.id] = row;

    if (target.id === sourceId) {
      row.status = 'source';
      row.note = 'source of truth; never written';
      continue;
    }

    let adapter = adapters[target.id] || adapters[target.adapter || 'generic'];
    if (!adapter) {
      try {
        adapter = loadTargetAdapter(target.adapter || 'generic');
      } catch (err) {
        row.status = 'error';
        row.error = err.message;
        row.note = err.message;
        for (const component of bundleMod.COMPONENTS) row.components[component] = { status: 'error', files: [], dropped: [], error: err.message };
        continue;
      }
    }

    const targetState = state.targets[target.id] || (state.targets[target.id] = {});
    targetState.files = targetState.files || {};
    targetState.drift = targetState.drift || {};
    targetState.owned = targetState.owned || {};

    const ctx = {
      target,
      bundle,
      port,
      home,
      // check is the "write nothing" flag adapters gate every deletion and prune
      // on, so a --dry-run must set it too. dryRun stays separate: it only means
      // "say more about what would change".
      check: readOnly,
      dryRun: Boolean(dryRun),
      force: Boolean(force),
      state: targetState,
      write: common.makeWriter({ state: targetState, backupsDir, tag: target.id, check: readOnly, force, log }),
      link: (src, dest) => common.link(src, dest, { check: readOnly }),
      log,
    };

    for (const component of bundleMod.COMPONENTS) {
      if (typeof adapter[component] !== 'function') {
        row.components[component] = { status: 'unsupported', files: [], dropped: [], note: `adapter has no ${component}` };
        continue;
      }
      let result;
      try {
        result = adapter[component](ctx) || {};
      } catch (err) {
        result = { status: 'error', error: err.message };
      }
      result.files = result.files || [];
      result.dropped = result.dropped || [];
      result.status = result.status || 'synced';
      row.components[component] = result;
      row.dropped += result.dropped.length;
    }
    row.status = rollUp(row.components);
  }

  report.totals = Object.assign({ targets: selected.length }, countFiles(report));
  report.totals.syncedTargets = Object.values(report.targets).filter((t) => t.status === 'synced' || t.status === 'source').length;
  report.stale = Object.values(report.targets).some((t) =>
    Object.values(t.components || {}).some((r) =>
      r.status === 'stale' || r.status === 'written' ||
      (r.files || []).some((f) => f.action === 'would-write' || f.action === 'would-link')));

  if (!readOnly) {
    fs.mkdirSync(storageDir, { recursive: true });
    fs.writeFileSync(stateFile, JSON.stringify(state, null, 2) + '\n', 'utf8');
  }
  fs.mkdirSync(storageDir, { recursive: true });
  fs.writeFileSync(path.join(storageDir, 'harness-report.json'), JSON.stringify(report, null, 2) + '\n', 'utf8');

  log(formatTable(report));
  return report;
}

module.exports = { apply, selectTargets, formatTable, loadTargetAdapter, readState, GLYPH, ABBR, LEGEND, DEFAULT_STORAGE };
