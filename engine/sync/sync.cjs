#!/usr/bin/env node
/**
 * agnostic-sync — Compiles universal rules, traits, and safety policies into
 * target configurations (Claude Code, Codex CLI, Antigravity agy, OpenClaw, Hermes).
 *
 * Usage:
 *   node engine/sync/sync.cjs            # Compile and apply to all targets
 *   node engine/sync/sync.cjs --check    # Check if targets are in sync (exit 1 if stale)
 *   node engine/sync/sync.cjs --target <id> # Sync specific target
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

const HOME = os.homedir();
const ROOT = path.resolve(__dirname, '..', '..');

const RULES_SOURCE = path.join(ROOT, 'core', 'rules', 'global-rules.md');
const TRAITS_SOURCE = path.join(ROOT, 'core', 'traits', 'traits.md');
const TARGETS_CONFIG = path.join(ROOT, 'core', 'templates', 'targets.json');

const CHECK_ONLY = process.argv.includes('--check');
const TARGET_FILTER = process.argv.find((_, i, arr) => arr[i - 1] === '--target');

function expandPath(p) {
  if (p.startsWith('~/') || p.startsWith('~\\')) {
    return path.join(HOME, p.slice(2));
  }
  if (!path.isAbsolute(p)) {
    return path.join(ROOT, p);
  }
  return p;
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
    const regex = new RegExp(`(^##\\s+${title}\\b[\\s\\S]*?)(?=^##\\s|\\Z)`, 'm');
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
      const stat = fs.lstatSync(targetDir);
      if (stat.isSymbolicLink() || stat.isDirectory()) {
        return { linked: true, path: targetDir, existing: true };
      }
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

function run() {
  const source = loadSource();
  const rawConfig = JSON.parse(fs.readFileSync(TARGETS_CONFIG, 'utf8'));
  const targets = rawConfig.targets.filter(t => !TARGET_FILTER || t.id === TARGET_FILTER);

  let outOfSyncCount = 0;
  const results = [];

  console.log(`[Agnostic-Sync] Evaluating ${targets.length} target(s)...`);

  for (const target of targets) {
    const compiled = compileTarget(target, source);
    const targetPath = expandPath(target.rulesFile);

    let isStale = true;
    if (fs.existsSync(targetPath)) {
      const existing = fs.readFileSync(targetPath, 'utf8');
      isStale = existing !== compiled;
    }

    if (isStale) {
      outOfSyncCount++;
      if (!CHECK_ONLY) {
        const targetDir = path.dirname(targetPath);
        if (!fs.existsSync(targetDir)) {
          fs.mkdirSync(targetDir, { recursive: true });
        }
        fs.writeFileSync(targetPath, compiled, 'utf8');
        console.log(`  ✓ Synced: ${target.name} -> ${targetPath}`);
      } else {
        console.log(`  ✗ Out of sync: ${target.name} (${targetPath})`);
      }
    } else {
      console.log(`  - Up to date: ${target.name}`);
    }

    const skillResult = !CHECK_ONLY ? linkSkillsDirectory(target) : { checkOnly: true };
    results.push({ id: target.id, name: target.name, path: targetPath, stale: isStale, skills: skillResult });
  }

  // Also compile generic compiled files to storage/compiled/
  const compiledDir = path.join(ROOT, 'storage', 'compiled');
  if (!fs.existsSync(compiledDir)) fs.mkdirSync(compiledDir, { recursive: true });
  fs.writeFileSync(path.join(compiledDir, 'rules.md'), source.rules, 'utf8');
  fs.writeFileSync(path.join(compiledDir, 'traits.md'), source.traits, 'utf8');

  console.log(`\n[Agnostic-Sync] Result: ${outOfSyncCount} target(s) ${CHECK_ONLY ? 'stale' : 'updated'}.`);

  if (CHECK_ONLY && outOfSyncCount > 0) {
    process.exit(1);
  }
  return results;
}

if (require.main === module) {
  run();
}

module.exports = { run, compileTarget, loadSource, expandPath };
