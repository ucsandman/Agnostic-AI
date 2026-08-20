#!/usr/bin/env node
/**
 * agnostic-sync — Compiles universal rules, traits, and safety policies into
 * target configurations (Claude Code, Codex CLI, Antigravity agy, OpenClaw, Hermes).
 *
 * Usage:
 *   node engine/sync/sync.cjs            # Compile and apply to all targets
 *   node engine/sync/sync.cjs --check    # Check if targets are in sync (exit 1 if stale)
 *   node engine/sync/sync.cjs --target <id> # Sync specific target
 *   node engine/sync/sync.cjs --force    # Overwrite targets that drifted (hand-edited)
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { execSync } = require('child_process');

const HOME = os.homedir();
const ROOT = path.resolve(__dirname, '..', '..');

const RULES_SOURCE = path.join(ROOT, 'core', 'rules', 'global-rules.md');
const TRAITS_SOURCE = path.join(ROOT, 'core', 'traits', 'traits.md');
const TARGETS_CONFIG = path.join(ROOT, 'core', 'templates', 'targets.json');

const CHECK_ONLY = process.argv.includes('--check');
const FORCE = process.argv.includes('--force');
const TARGET_FILTER = process.argv.find((_, i, arr) => arr[i - 1] === '--target');

function sha(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

// Records the hash of what sync itself last wrote to each target, so a later
// run can tell "stale because the source changed" from "a human edited this".
function loadSyncState(stateFile) {
  if (!fs.existsSync(stateFile)) return {};
  try {
    return JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  } catch (_) {
    return {};
  }
}

function saveSyncState(stateFile, state) {
  const dir = path.dirname(stateFile);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(stateFile, JSON.stringify(state, null, 2), 'utf8');
}

function backupTarget(backupsDir, targetId, targetPath) {
  if (!fs.existsSync(backupsDir)) fs.mkdirSync(backupsDir, { recursive: true });
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const backupPath = path.join(backupsDir, `${targetId}-${path.basename(targetPath)}-${timestamp}.bak`);
  fs.copyFileSync(targetPath, backupPath);
  return backupPath;
}

function expandPath(p) {
  if (!p) return '';
  let resolved = p;
  // Replace Windows %VAR% patterns
  resolved = resolved.replace(/%([^%]+)%/g, (_, n) => process.env[n] || '');
  if (resolved.startsWith('~/') || resolved.startsWith('~\\')) {
    return path.join(HOME, resolved.slice(2));
  }
  if (!path.isAbsolute(resolved)) {
    return path.join(ROOT, resolved);
  }
  return resolved;
}

function loadSource() {
  if (!fs.existsSync(RULES_SOURCE)) {
    throw new Error(`Missing source rules file: ${RULES_SOURCE}`);
  }
  const rules = fs.readFileSync(RULES_SOURCE, 'utf8').trim();
  const traits = fs.existsSync(TRAITS_SOURCE) ? fs.readFileSync(TRAITS_SOURCE, 'utf8').trim() : '';
  return { rules, traits };
}

const DROP_SECTIONS_FOR_NON_CLAUDE = ['Delegation and Model Routing'];

function stripSections(markdown, sectionTitles) {
  let result = markdown;
  for (const title of sectionTitles) {
    // `$(?![\s\S])` is end-of-input; a bare `$` under /m would stop at the first newline.
    const regex = new RegExp(`(^##\\s+${title}\\b[\\s\\S]*?)(?=^##\\s|$(?![\\s\\S]))`, 'm');
    result = result.replace(regex, '');
  }
  return result.replace(/\n{3,}/g, '\n\n').trim();
}

function compileTarget(target, source) {
  const parts = [];
  if (target.preamble) {
    parts.push(target.preamble.trim());
  }

  let rules = source.rules;
  if (target.id !== 'claude') {
    rules = stripSections(rules, DROP_SECTIONS_FOR_NON_CLAUDE);
  }

  parts.push(rules);
  if (source.traits && !target.traitsFile) {
    parts.push('\n---\n\n' + source.traits);
  }
  return parts.join('\n\n') + '\n';
}

function linkSkillsDirectory(target) {
  if (!target.skillsDir) return { linked: false, reason: 'no skills dir' };
  const targetDir = expandPath(target.skillsDir);
  const sourceDir = path.join(ROOT, 'skills', 'definitions');

  if (!fs.existsSync(sourceDir)) {
    fs.mkdirSync(sourceDir, { recursive: true });
  }

  // Windows junction creation
  try {
    if (fs.existsSync(targetDir)) {
      // Only a link that actually resolves to our consolidated skills counts as linked.
      // A real directory belonging to the user is reported honestly and left untouched.
      const stat = fs.lstatSync(targetDir);
      if (stat.isSymbolicLink()) {
        let resolved = null;
        try { resolved = fs.realpathSync(targetDir); } catch (_) {}
        if (resolved && path.resolve(resolved) === path.resolve(fs.realpathSync(sourceDir))) {
          return { linked: true, path: targetDir, existing: true };
        }
        return { linked: false, path: targetDir, reason: 'exists-unmanaged', target: resolved };
      }
      return { linked: false, path: targetDir, reason: 'exists-unmanaged' };
    }
    const parent = path.dirname(targetDir);
    if (!fs.existsSync(parent)) fs.mkdirSync(parent, { recursive: true });
    
    if (process.platform === 'win32') {
      execSync(`cmd /c mklink /J "${targetDir}" "${sourceDir}"`, { stdio: 'pipe' });
    } else {
      fs.symlinkSync(sourceDir, targetDir, 'junction');
    }
    return { linked: true, path: targetDir, created: true };
  } catch (err) {
    return { linked: false, error: err.message };
  }
}

/**
 * Writes one compiled file, refusing to destroy a hand edit.
 * A target is "drifted" only when sync HAS recorded a hash for it and the file
 * no longer matches that hash — i.e. a human edited what sync wrote. Drifted
 * targets are backed up and skipped unless --force is given. A target sync has
 * never recorded (no key in sync-state) is not drifted: it is backed up and
 * written, so the first sync of an install actually installs.
 */
function writeGuarded(targetPath, content, ctx) {
  const exists = fs.existsSync(targetPath);
  const existing = exists ? fs.readFileSync(targetPath, 'utf8') : null;
  const stale = !exists || existing !== content;
  const recorded = Object.prototype.hasOwnProperty.call(ctx.state, targetPath);
  const drifted = Boolean(exists && stale && recorded && ctx.state[targetPath] !== sha(existing));
  const result = { stale, drifted, written: false, backup: null };

  if (!stale) {
    // Already identical to what we would write — record it as known-good so the
    // first run after an upgrade does not read every target as hand-edited.
    ctx.state[targetPath] = sha(content);
    return result;
  }
  if (ctx.checkOnly) return result;

  if (drifted) {
    // Back up once per distinct hand-edited content, not once per run.
    const driftKey = `drift:${targetPath}`;
    if (ctx.state[driftKey] !== sha(existing)) {
      result.backup = backupTarget(ctx.backupsDir, ctx.targetId, targetPath);
      ctx.state[driftKey] = sha(existing);
    }
    if (!ctx.force) return result;
  } else if (exists) {
    result.backup = backupTarget(ctx.backupsDir, ctx.targetId, targetPath);
  }

  const dir = path.dirname(targetPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(targetPath, content, 'utf8');
  ctx.state[targetPath] = sha(content);
  delete ctx.state[`drift:${targetPath}`];
  result.written = true;
  return result;
}

function run(opts = {}) {
  const source = loadSource();
  const targetsConfig = opts.targetsConfig || TARGETS_CONFIG;
  const storageDir = opts.storageDir || path.join(ROOT, 'storage');
  const checkOnly = opts.check !== undefined ? opts.check : CHECK_ONLY;
  const force = opts.force !== undefined ? opts.force : FORCE;
  const stateFile = path.join(storageDir, 'sync-state.json');
  const backupsDir = path.join(storageDir, 'backups');
  const state = loadSyncState(stateFile);

  const rawConfig = JSON.parse(fs.readFileSync(targetsConfig, 'utf8'));
  const targets = rawConfig.targets.filter(t => !TARGET_FILTER || t.id === TARGET_FILTER);

  let outOfSyncCount = 0;
  let driftedCount = 0;
  const results = [];

  console.log(`[Agnostic-Sync] Evaluating ${targets.length} target(s)...`);

  for (const target of targets) {
    const compiled = compileTarget(target, source);
    const targetPath = expandPath(target.rulesFile);
    const ctx = { state, backupsDir, force, checkOnly, targetId: target.id || 'general' };

    const res = writeGuarded(targetPath, compiled, ctx);

    if (res.stale) {
      outOfSyncCount++;
      if (checkOnly) {
        console.log(`  ✗ Out of sync: ${target.name} (${targetPath})`);
      } else if (res.written) {
        console.log(`  ✓ Synced: ${target.name} -> ${targetPath}${res.backup ? ' (backup saved)' : ''}`);
      } else {
        driftedCount++;
        console.log(`  ! SKIPPED (hand-edited): ${target.name} -> ${targetPath}`);
        console.log(`      Local edits differ from what sync last wrote. Backup: ${res.backup || 'already saved'}`);
        console.log(`      Re-run with --force to overwrite, or fold the edits into core/rules/global-rules.md.`);
      }
    } else {
      console.log(`  - Up to date: ${target.name}`);
    }

    // Sync traits file if target defines a separate one
    let traitsRes = null;
    if (target.traitsFile && source.traits) {
      traitsRes = writeGuarded(expandPath(target.traitsFile), source.traits, ctx);
      if (traitsRes.drifted && !traitsRes.written && !checkOnly) {
        driftedCount++;
        console.log(`  ! SKIPPED (hand-edited): ${target.name} traits -> ${expandPath(target.traitsFile)}`);
      }
    }

    const skillResult = !checkOnly ? linkSkillsDirectory(target) : { checkOnly: true };
    if (skillResult.error) {
      console.log(`  ! Skills link failed: ${target.name} -> ${skillResult.error}`);
    }
    results.push({
      id: target.id,
      name: target.name,
      path: targetPath,
      stale: res.stale,
      drifted: res.drifted,
      written: res.written,
      backup: res.backup,
      traits: traitsRes,
      skills: skillResult
    });
  }

  if (!checkOnly) saveSyncState(stateFile, state);

  // Also compile generic compiled files to storage/compiled/
  const compiledDir = path.join(storageDir, 'compiled');
  if (!fs.existsSync(compiledDir)) fs.mkdirSync(compiledDir, { recursive: true });
  fs.writeFileSync(path.join(compiledDir, 'rules.md'), source.rules, 'utf8');
  fs.writeFileSync(path.join(compiledDir, 'traits.md'), source.traits, 'utf8');

  // Auto-configure DashClaw if present
  try {
    const { autoConfigureDashClaw } = require('../hooks/dashclaw-setup.cjs');
    const dc = autoConfigureDashClaw();
    if (dc && dc.configured && dc.active) {
      console.log(`  ✓ DashClaw: Governed Autonomy enabled (${dc.agentId} @ ${dc.baseUrl})`);
    }
  } catch (_) {}

  const updated = results.filter(r => r.written).length;
  const skillsLinked = results.filter(r => r.skills && r.skills.linked).length;
  const skillsFailed = results.filter(r => r.skills && r.skills.error).length;
  console.log(`\n[Agnostic-Sync] Result: ${targets.length} evaluated, ${checkOnly ? `${outOfSyncCount} stale` : `${updated} updated`}, ${driftedCount} skipped as hand-edited, skills ${skillsLinked} linked / ${skillsFailed} failed.`);

  if (checkOnly && outOfSyncCount > 0) {
    process.exit(1);
  }
  return results;
}

if (require.main === module) {
  run();
}

module.exports = { run, compileTarget, loadSource, expandPath, linkSkillsDirectory };
