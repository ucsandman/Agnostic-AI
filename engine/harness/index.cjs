/**
 * engine/harness/index.cjs — the port engine as a library.
 *
 * This is the one file a host product requires. Everything a host may need to
 * own is an option, never a repo path:
 *
 *   const engine = require('agnostic-ai/engine/harness/index.cjs');
 *   engine.configure({ brand: { id, mark, region }, secretPatterns, shimPath });
 *   const registry = engine.loadRegistry(home, { targets: myTargets });
 *   const { bundle, warnings } = engine.capture({ from: 'claude', home, outDir, registry, port });
 *   const report = engine.apply({ bundle, home, registry, port, storageDir, to: ['codex'] });
 *   engine.status({ bundle, home, registry, port, storageDir });
 *
 * Nothing here reads `core/port.json`, `core/templates/targets.json` or
 * `core/safety/guards.json` when the host passes `port`, `registry` and
 * `secretPatterns`. The engine's own CLI (cli.cjs) is a thin caller of the
 * same functions with the repo's files as defaults.
 *
 * Node's ESM loader imports this file directly (`import engine from
 * '.../index.cjs'`), which is how a zero-dependency ESM host embeds it
 * without a build step.
 */

const common = require('./common.cjs');
const bundle = require('./bundle.cjs');
const capture = require('./capture.cjs');
const apply = require('./apply.cjs');
const status = require('./status.cjs');
const toml = require('./toml.cjs');

module.exports = {
  // configuration
  configure: common.configure,
  config: common.config,
  // the pipeline
  capture: capture.capture,
  apply: apply.apply,
  status: status.status,
  // registry and policy
  loadRegistry: capture.loadRegistry,
  loadPort: capture.loadPort,
  detectSource: capture.detectSource,
  selectTargets: apply.selectTargets,
  // reporting helpers
  formatTable: apply.formatTable,
  formatDropped: status.formatDropped,
  renderHtml: status.renderHtml,
  readState: apply.readState,
  // the modules themselves, for a host that needs the details
  common,
  bundle,
  toml,
  COMPONENTS: bundle.COMPONENTS,
  GLYPH: apply.GLYPH,
};
