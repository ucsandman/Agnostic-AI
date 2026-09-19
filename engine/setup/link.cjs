#!/usr/bin/env node
/**
 * engine/setup/link.cjs — bind the installed Claude Code home to this repository.
 *
 * The harness has ONE implementation of each hook, tool, Mod, subagent and
 * workflow: the copy in this repository. Claude Code reads them from its own
 * home (~/.claude/hooks, ~/.claude/tools, ...), so the install is a directory
 * link per surface, not a copy. An edit in either place is the same file; a
 * commit happens here.
 *
 *   node engine/setup/link.cjs            # create or repair every link
 *   node engine/setup/link.cjs --check    # report only; exit 1 when a link is missing or points elsewhere
 *   node engine/setup/link.cjs --json     # machine-readable report (doctor reads this)
 *
 * A real directory already at the target is never deleted: it is moved to
 * <home>/.agnostic-migrated/<name>-<stamp>/ and anything it held that the
 * repository does not (runtime state, untracked files) is copied into the
 * repository directory so no state is lost. The doctor then lists what came
 * along, and the cleanup pass decides.
 *
 * Windows gets a junction (no privilege needed); other platforms a symlink.
 * The Claude home honours CLAUDE_CONFIG_DIR, like Claude Code itself.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');

/** Installed surface -> repository directory. Order matters only for the report. */
const LINKS = [
  { name: 'hooks', source: 'engine/hooks', what: 'guard hooks settings.json runs' },
  { name: 'mods', source: 'engine/mods', what: 'function-hook plugins (local marketplace "harness-mods")' },
  { name: 'agents', source: 'agents', what: 'subagent definitions' },
  { name: 'workflows', source: 'workflows', what: 'saved Workflow scripts' },
  { name: 'tools', source: 'tools', what: 'operator CLIs and pages' },
];

function claudeHome(home = os.homedir()) {
  return process.env.CLAUDE_CONFIG_DIR ? path.resolve(process.env.CLAUDE_CONFIG_DIR) : path.join(home, '.claude');
}

const same = (a, b) => path.resolve(a).toLowerCase().replace(/[\\/]+$/, '') === path.resolve(b).toLowerCase().replace(/[\\/]+$/, '');

function linkState(target, source) {
  let st;
  try { st = fs.lstatSync(target); } catch (_) { return { state: 'missing' }; }
  if (st.isSymbolicLink()) {
    let real;
    try { real = fs.realpathSync(target); } catch (_) { return { state: 'dangling' }; }
    return same(real, source) ? { state: 'ok', real } : { state: 'wrong-target', real };
  }
  if (st.isDirectory()) return { state: 'directory' };
  return { state: 'file' };
}

function copyMissing(from, to, carried, rel = '') {
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    const a = path.join(from, entry.name);
    const b = path.join(to, entry.name);
    const r = rel ? `${rel}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      if (!fs.existsSync(b)) { fs.cpSync(a, b, { recursive: true }); carried.push(r + '/'); }
      else copyMissing(a, b, carried, r);
    } else if (!fs.existsSync(b)) {
      fs.copyFileSync(a, b); carried.push(r);
    }
  }
}

function makeLink(source, target) {
  fs.symlinkSync(source, target, process.platform === 'win32' ? 'junction' : 'dir');
}

function run({ check = false, home = os.homedir(), root = ROOT } = {}) {
  const chome = claudeHome(home);
  const report = { home: chome, root, links: [], ok: true };
  if (!check) fs.mkdirSync(chome, { recursive: true });
  for (const l of LINKS) {
    const source = path.join(root, l.source);
    const target = path.join(chome, l.name);
    const row = { name: l.name, target, source, what: l.what, ...linkState(target, source), carried: [] };
    if (!fs.existsSync(source)) { row.state = 'no-source'; row.action = 'skipped'; report.ok = false; report.links.push(row); continue; }
    if (row.state === 'ok') { row.action = 'kept'; report.links.push(row); continue; }
    report.ok = false;
    if (check) { row.action = 'would-link'; report.links.push(row); continue; }
    if (row.state === 'directory') {
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
      const aside = path.join(chome, '.agnostic-migrated', `${l.name}-${stamp}`);
      fs.mkdirSync(path.dirname(aside), { recursive: true });
      copyMissing(target, source, row.carried);
      fs.renameSync(target, aside);
      row.movedAside = aside;
    } else if (row.state === 'wrong-target' || row.state === 'dangling' || row.state === 'file') {
      fs.rmSync(target, { force: true, recursive: false });
    }
    makeLink(source, target);
    row.action = 'linked';
    row.state = 'ok';
    report.links.push(row);
  }
  report.ok = report.links.every((r) => r.state === 'ok');
  return report;
}

function print(report) {
  console.log(`Claude home: ${report.home}`);
  for (const r of report.links) {
    const mark = r.state === 'ok' ? 'ok  ' : 'FAIL';
    console.log(`  ${mark} ${r.name.padEnd(10)} -> ${path.relative(report.root, r.source) || '.'}  [${r.action}]${r.movedAside ? `  (previous directory kept at ${r.movedAside})` : ''}`);
    if (r.carried.length) console.log(`       carried ${r.carried.length} untracked item(s) into the repository: ${r.carried.slice(0, 8).join(', ')}${r.carried.length > 8 ? ', ...' : ''}`);
    if (r.state === 'wrong-target') console.log(`       currently points at ${r.real}`);
  }
  console.log(report.ok ? 'links: all bound' : 'links: NOT bound (run without --check to repair)');
}

if (require.main === module) {
  const argv = process.argv.slice(2);
  const report = run({ check: argv.includes('--check') });
  if (argv.includes('--json')) console.log(JSON.stringify(report, null, 2));
  else print(report);
  process.exit(report.ok ? 0 : 1);
}

module.exports = { run, LINKS, claudeHome, linkState };
