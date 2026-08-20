#!/usr/bin/env node
/**
 * engine/setup/first-run.cjs — First-Run Onboarding & Default Harness Setup.
 *
 * Runs automatically when the user uses the Agnostic Harness for the first time
 * (or manually via `npm run setup:default` / `python launch.py`).
 *
 * Actions:
 *   1. Harvester: Scans existing agent logs (~/.claude, ~/.codex, etc.) so harness starts loaded.
 *   2. Consolidator: Ingests all skills from all agent runtimes into skills/definitions/.
 *   3. Polyglot Sync: Compiles Single Source of Truth to all 18 agent target agreement files.
 *   4. Hook Proxy: Registers Universal Hook & DashClaw Guard into Claude, Codex, Gemini settings.
 *   5. DashClaw Provisioner: Links agent identity & API key for governed autonomy.
 *   6. Persistence: Writes storage/harness-installed.json marking default installation.
 *
 * Usage:
 *   node engine/setup/first-run.cjs          # Run setup / verify default state
 *   node engine/setup/first-run.cjs --force  # Force re-installation
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const STORAGE = path.join(ROOT, 'storage');
const STATE_FILE = path.join(STORAGE, 'harness-installed.json');

const HOME = os.homedir();
const FORCE_FLAG = process.argv.includes('--force');

function isFirstRun(stateFile = STATE_FILE) {
  if (!fs.existsSync(stateFile)) return true;
  try {
    const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
    return !state.installed;
  } catch (_) {
    return true;
  }
}

// Returns null ONLY for a file that exists but cannot be parsed. Callers must
// check existence first: an absent file is a fresh install, an unparseable one
// is a user config we must never overwrite.
function readJsonSafe(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (_) {
    return null;
  }
}

function warnMalformed(file) {
  console.warn(`  ! ${file} is not valid JSON — left untouched; fix it by hand then re-run`);
}

function backup(file) {
  if (fs.existsSync(file)) {
    try {
      fs.copyFileSync(file, `${file}.bak`);
    } catch (_) {}
  }
}

/**
 * Registers the guard hooks into every agent runtime present under `home`.
 * Always read-merge-write: an existing user hook file is preserved, never clobbered.
 * Returns a per-target report of what was installed.
 */
function wireAgentHooks(home = HOME) {
  const hookCommand = (name) =>
    `node "${path.join(ROOT, 'engine', 'hooks', name).replace(/\\/g, '/')}"`;
  const report = {
    claude: { present: false, dashclawGuard: false, secretGuard: false, malformed: false },
    codex: { present: false, dashclawGuard: false, secretGuard: false, malformed: false },
    gemini: { present: false, dashclawGuard: false, secretGuard: false, malformed: false }
  };

  // Claude Code — PreToolUse takes {matcher, hooks[]} groups, so it can host both guards.
  const claudeSettings = path.join(home, '.claude', 'settings.json');
  const claudeCfg = fs.existsSync(claudeSettings) ? readJsonSafe(claudeSettings) : undefined;
  if (claudeCfg === null) {
    report.claude.present = true;
    report.claude.malformed = true;
    warnMalformed(claudeSettings);
  } else if (claudeCfg) {
    report.claude.present = true;
    try {
      const cfg = claudeCfg;
      if (!cfg.hooks) cfg.hooks = {};

      // Claude Code wants PreToolUse as an array of {matcher, hooks[]} groups,
      // not the flat string Codex/Antigravity take. A lowercase key is silently
      // ignored here and breaks PowerShell ConvertFrom-Json via case collision.
      delete cfg.hooks.preToolUse; // stale invalid key from older installs
      if (!Array.isArray(cfg.hooks.PreToolUse)) cfg.hooks.PreToolUse = [];

      const matcher = 'Bash|PowerShell|Edit|Write|MultiEdit';
      const installed = [];
      for (const [script, pattern, status] of [
        ['dashclaw-guard.cjs', /dashclaw-guard/i, 'DashClaw guard check...'],
        ['secret-guard.cjs', /secret-guard/i, 'Secret scan...']
      ]) {
        // Skip if this guard already gates tool calls (ours or a native one).
        const guarded = cfg.hooks.PreToolUse.some(g =>
          (g.hooks || []).some(h => pattern.test(h.command || '')));
        if (!guarded) {
          cfg.hooks.PreToolUse.push({
            matcher,
            hooks: [{ type: 'command', command: hookCommand(script), timeout: 10, statusMessage: status }]
          });
          installed.push(script);
        }
      }
      report.claude.dashclawGuard = true;
      report.claude.secretGuard = true;

      backup(claudeSettings);
      fs.writeFileSync(claudeSettings, JSON.stringify(cfg, null, 2), 'utf8');
      console.log(`  ✓ Claude Code PreToolUse hooks in ~/.claude/settings.json (dashclaw-guard + secret-guard${installed.length ? `; added ${installed.join(', ')}` : '; already present'})`);
    } catch (err) {
      report.claude.dashclawGuard = false;
      report.claude.secretGuard = false;
      console.warn(`  ! Could not wire Claude Code hooks in ${claudeSettings}: ${err.message}`);
    }
  }

  // Codex CLI and Antigravity (agy) take a single flat command string per event,
  // so they get the guard only; a foreign hook already there is left alone.
  const flatTargets = [
    { key: 'codex', dir: path.join(home, '.codex'), file: path.join(home, '.codex', 'hooks.json'), field: 'pre_tool_use', label: '~/.codex/hooks.json' },
    { key: 'gemini', dir: path.join(home, '.gemini', 'config'), file: path.join(home, '.gemini', 'config', 'hooks.json'), field: 'preToolUse', label: '~/.gemini/config/hooks.json' }
  ];

  for (const target of flatTargets) {
    if (!fs.existsSync(target.dir)) continue;
    report[target.key].present = true;
    const cfg = fs.existsSync(target.file) ? readJsonSafe(target.file) : {};
    if (cfg === null) {
      report[target.key].malformed = true;
      warnMalformed(target.file);
      continue;
    }
    try {
      const existing = cfg[target.field];
      if (existing && !/dashclaw-guard/i.test(existing)) {
        console.warn(`  ! Preserved existing ${target.field} hook in ${target.label}; guard NOT installed (only one command is supported there).`);
      } else {
        cfg[target.field] = hookCommand('dashclaw-guard.cjs');
        cfg.governance = 'agnostic-harness';
        report[target.key].dashclawGuard = true;
        // dashclaw-guard runs the secret-path check internally, so the single
        // flat-format hook covers secret scanning on these targets too.
        report[target.key].secretGuard = true;
      }
      backup(target.file);
      fs.writeFileSync(target.file, JSON.stringify(cfg, null, 2), 'utf8');
      if (report[target.key].dashclawGuard) {
        console.log(`  ✓ Guard hook registered in ${target.label}`);
      }
    } catch (err) {
      console.warn(`  ! Could not wire hook in ${target.label}: ${err.message}`);
    }
  }

  return report;
}

async function runFirstRunSetup() {
  console.log('==================================================');
  console.log('   AGNOSTIC AI HARNESS — FIRST-RUN SETUP & WIRING');
  console.log('==================================================\n');

  const steps = [
    {
      title: '[1/5] Harvesting past errors, corrections, and meditation candidates...',
      run: async () => {
        const { runHarvest } = require('../harvest/harvest.cjs');
        return runHarvest();
      }
    },
    {
      title: '[2/5] Ingesting and consolidating all agent skills...',
      run: async () => {
        const { consolidateSkills } = require('../skills/consolidate.cjs');
        return consolidateSkills();
      }
    },
    {
      title: '[3/5] Synchronizing and compiling 18 agent targets...',
      run: async () => {
        const { run } = require('../sync/sync.cjs');
        return run();
      }
    },
    {
      title: '[4/5] Wiring Universal Hook proxies and DashClaw governance...',
      run: async () => {
        const { autoConfigureDashClaw } = require('../hooks/dashclaw-setup.cjs');
        const dashclawResult = await autoConfigureDashClaw();

        const hookReport = wireAgentHooks();
        const wired = Object.entries(hookReport)
          .filter(([, r]) => r.present)
          .map(([name, r]) => `${name}(${[r.dashclawGuard && 'dashclaw-guard', r.secretGuard && 'secret-guard'].filter(Boolean).join('+') || 'none'})`);
        console.log(`  ✓ Hook targets wired: ${wired.length ? wired.join(', ') : 'none detected'}`);

        return dashclawResult;
      }
    },
    {
      title: '[5/5] Finalizing default harness configuration & state...',
      run: async () => {
        if (!fs.existsSync(STORAGE)) fs.mkdirSync(STORAGE, { recursive: true });
        const installState = {
          installed: true,
          installedAt: new Date().toISOString(),
          root: ROOT,
          version: '1.2.0',
          defaultFor: ['claude', 'codex', 'agy', 'cursor', 'windsurf', 'cline', 'openhands', 'goose', 'continue', 'zed', 'trae', 'amazonq', 'cody', 'openclaw', 'hermes']
        };
        fs.writeFileSync(STATE_FILE, JSON.stringify(installState, null, 2), 'utf8');
        console.log(`  ✓ Default harness state persisted: ${STATE_FILE}`);
        return installState;
      }
    }
  ];

  for (const step of steps) {
    console.log(step.title);
    try {
      await step.run();
    } catch (err) {
      console.error(`  ✗ Error in step: ${err.message}`);
    }
    console.log('');
  }

  console.log('==================================================');
  console.log('  ✓ Agnostic AI Harness is now the default harness');
  console.log('    for Claude, Codex, agy, Cursor, and all agents.');
  console.log('==================================================\n');
}

if (require.main === module) {
  if (!FORCE_FLAG && !isFirstRun()) {
    const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    console.log(`✓ Agnostic AI Harness already installed (${state.installedAt || 'unknown date'}, v${state.version || '?'}).`);
    console.log('  Nothing to do. Re-run with --force to reinstall.');
  } else {
    runFirstRunSetup();
  }
}

module.exports = { isFirstRun, runFirstRunSetup, wireAgentHooks };
