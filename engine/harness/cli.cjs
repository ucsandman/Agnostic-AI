#!/usr/bin/env node
/**
 * engine/harness/cli.cjs — capture | apply | port | status | explain.
 *
 * Tiny argv loop, no dependencies. Exit 1 on an error and on `--check`
 * staleness, so CI and `npm run port:check` mean something.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { exec } = require('child_process');

const { capture } = require('./capture.cjs');
const { apply, DEFAULT_STORAGE } = require('./apply.cjs');
const { status, formatDropped } = require('./status.cjs');

const COMMANDS = ['capture', 'apply', 'port', 'status', 'explain'];

const USAGE = `agnostic harness porter — capture the client you actually use, apply it to every other one.

usage: node engine/harness/cli.cjs <command> [options]

commands:
  capture   read the source client into <repo>/harness/
  apply     render the bundle into every other selected client
  port      capture, then apply
  status    inspect every target and print the component matrix (writes nothing)
  explain   list every item the last run could not port, and why

options:
  --from <id>      source client (claude | codex); default core/port.json "source", else auto-detect
  --to <a,b>       only these target ids; default core/port.json "targets"
  --check          report only, write nothing to a client; exit 1 when anything is out of date
                   (with "port" the source is still re-captured into <repo>/harness/)
  --dry-run        like --check, and print every file that would change
  --force          overwrite target files that were hand-edited since the last run
  --home <dir>     home directory to read and write (default: this user's home)
  --bundle <dir>   bundle directory (default: <repo>/harness)
  --storage <dir>  state, backups and reports (default: <repo>/storage)
  --explain        with "status", also list every dropped item per target
  --json           print the report as JSON
  --html           write the status page to <storage>/harness-status.html
  --open           open the status page in a browser
  --help           this text

examples:
  node engine/harness/cli.cjs port                 # copy your harness to every installed client
  node engine/harness/cli.cjs port --check         # is anything out of date? (exit 1 = yes)
  node engine/harness/cli.cjs apply --to codex,gemini
  node engine/harness/cli.cjs status --html --open
`;

function parseArgs(argv) {
  const opts = { command: null, home: os.homedir(), storageDir: DEFAULT_STORAGE };
  const takesValue = { '--from': 'from', '--to': 'to', '--home': 'home', '--bundle': 'bundleDir', '--storage': 'storageDir' };
  const flags = { '--check': 'check', '--dry-run': 'dryRun', '--force': 'force', '--json': 'json', '--html': 'html', '--open': 'open', '--explain': 'explain', '--help': 'help', '-h': 'help' };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (takesValue[arg]) { opts[takesValue[arg]] = argv[++i]; continue; }
    if (flags[arg]) { opts[flags[arg]] = true; continue; }
    if (arg.startsWith('-')) throw new Error(`unknown option ${arg} (try --help)`);
    if (!opts.command) { opts.command = arg; continue; }
    throw new Error(`unexpected argument ${arg} (try --help)`);
  }
  if (opts.to) opts.to = String(opts.to).split(',').map((s) => s.trim()).filter(Boolean);
  if (opts.home) opts.home = path.resolve(opts.home);
  if (opts.storageDir) opts.storageDir = path.resolve(opts.storageDir);
  if (opts.bundleDir) opts.bundleDir = path.resolve(opts.bundleDir);
  return opts;
}

function openInBrowser(target) {
  const cmd = process.platform === 'win32' ? `start "" "${target}"` : process.platform === 'darwin' ? `open "${target}"` : `xdg-open "${target}"`;
  exec(cmd);
}

function runCapture(opts) {
  const { bundle, warnings, dir } = capture({ from: opts.from, home: opts.home, outDir: opts.bundleDir });
  if (opts.json) {
    console.log(JSON.stringify({ source: bundle.manifest.source, dir, components: bundle.manifest.components, warnings }, null, 2));
  } else {
    const counts = Object.entries(bundle.manifest.components).map(([k, v]) => `${k} ${v}`).join(', ');
    console.log(`captured ${bundle.manifest.source} -> ${dir}`);
    console.log(`  ${counts}`);
    for (const w of warnings) console.log(`  ! ${w}`);
  }
  return bundle;
}

function runApply(opts, bundle) {
  const report = apply({
    bundle,
    bundleDir: opts.bundleDir,
    home: opts.home,
    to: opts.to,
    check: Boolean(opts.check),
    dryRun: Boolean(opts.dryRun),
    force: Boolean(opts.force),
    storageDir: opts.storageDir,
    log: opts.json ? () => {} : undefined,
  });
  if (opts.json) console.log(JSON.stringify(report, null, 2));
  return report;
}

function runStatus(opts) {
  const result = status({
    home: opts.home,
    to: opts.to,
    bundleDir: opts.bundleDir,
    storageDir: opts.storageDir,
    json: Boolean(opts.json),
    explain: Boolean(opts.explain),
    html: Boolean(opts.html) || Boolean(opts.open),
  });
  if (opts.open && result.report && result.report.htmlFile) openInBrowser(result.report.htmlFile);
  return result;
}

function runExplain(opts) {
  const file = path.join(opts.storageDir, 'harness-report.json');
  if (!fs.existsSync(file)) {
    console.error(`no report at ${file}; run: npm run port`);
    return 1;
  }
  const report = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (opts.json) console.log(JSON.stringify(report, null, 2));
  else {
    console.log(`from ${file} (${report.mode}, ${report.appliedAt})`);
    console.log(formatDropped(report));
  }
  return 0;
}

function main(argv) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (err) {
    console.error(err.message);
    return 1;
  }
  if (opts.help) { console.log(USAGE); return 0; }
  if (!opts.command) { console.log(USAGE); return 1; }
  if (!COMMANDS.includes(opts.command)) { console.error(`unknown command "${opts.command}"\n\n${USAGE}`); return 1; }

  try {
    if (opts.command === 'capture') { runCapture(opts); return 0; }
    if (opts.command === 'apply') { const r = runApply(opts); return opts.check && r.stale ? 1 : 0; }
    if (opts.command === 'port') {
      const bundle = runCapture(opts);
      const r = runApply(opts, bundle);
      return opts.check && r.stale ? 1 : 0;
    }
    if (opts.command === 'status') {
      const r = runStatus(opts);
      if (r.syncState === 'no-bundle') return 1;
      return opts.check && r.syncState !== 'synced' ? 1 : 0;
    }
    if (opts.command === 'explain') return runExplain(opts);
  } catch (err) {
    console.error(`error: ${err.message}`);
    return 1;
  }
  return 0;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = { main, parseArgs, USAGE };
