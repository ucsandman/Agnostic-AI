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

function isFirstRun() {
  if (FORCE_FLAG) return true;
  if (!fs.existsSync(STATE_FILE)) return true;
  try {
    const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    return !state.installed;
  } catch (_) {
    return true;
  }
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

        // Wire Claude settings.json hook if available
        const claudeSettings = path.join(HOME, '.claude', 'settings.json');
        if (fs.existsSync(claudeSettings)) {
          try {
            const raw = fs.readFileSync(claudeSettings, 'utf8');
            const cfg = JSON.parse(raw);
            if (!cfg.hooks) cfg.hooks = {};
            
            // Claude Code wants PreToolUse as an array of {matcher, hooks[]} groups,
            // not the flat string Codex/Antigravity take. A lowercase key is silently
            // ignored here and breaks PowerShell ConvertFrom-Json via case collision.
            const hookScript = path.join(ROOT, 'engine', 'hooks', 'dashclaw-guard.cjs').replace(/\\/g, '/');
            const command = `node "${hookScript}"`;

            delete cfg.hooks.preToolUse; // stale invalid key from older installs
            if (!Array.isArray(cfg.hooks.PreToolUse)) cfg.hooks.PreToolUse = [];

            // Skip if a DashClaw guard already gates tool calls (ours or a native one).
            const guarded = cfg.hooks.PreToolUse.some(g =>
              (g.hooks || []).some(h => /dashclaw/i.test(h.command || '')));
            if (!guarded) {
              cfg.hooks.PreToolUse.push({
                matcher: 'Bash|PowerShell|Edit|Write|MultiEdit',
                hooks: [{ type: 'command', command, timeout: 10, statusMessage: 'DashClaw guard check...' }]
              });
            }

            fs.writeFileSync(claudeSettings, JSON.stringify(cfg, null, 2), 'utf8');
            console.log(`  ✓ Claude Code PreToolUse hook ${guarded ? 'already present' : 'registered'} in ~/.claude/settings.json`);
          } catch (err) {
            console.warn(`  ! Could not wire Claude Code hook in ${claudeSettings}: ${err.message}`);
          }
        }

        // Wire Codex hooks.json if directory exists
        const codexDir = path.join(HOME, '.codex');
        if (fs.existsSync(codexDir)) {
          const codexHooks = path.join(codexDir, 'hooks.json');
          const hookScript = path.join(ROOT, 'engine', 'hooks', 'dashclaw-guard.cjs').replace(/\\/g, '/');
          const hookConfig = {
            pre_tool_use: `node "${hookScript}"`,
            governance: 'agnostic-harness'
          };
          fs.writeFileSync(codexHooks, JSON.stringify(hookConfig, null, 2), 'utf8');
          console.log(`  ✓ Codex CLI hook registered in ~/.codex/hooks.json`);
        }

        // Wire Antigravity (agy) config/hooks.json if directory exists
        const geminiConfigDir = path.join(HOME, '.gemini', 'config');
        if (fs.existsSync(geminiConfigDir)) {
          const geminiHooks = path.join(geminiConfigDir, 'hooks.json');
          const hookScript = path.join(ROOT, 'engine', 'hooks', 'dashclaw-guard.cjs').replace(/\\/g, '/');
          const hookConfig = {
            preToolUse: `node "${hookScript}"`,
            governance: 'agnostic-harness'
          };
          fs.writeFileSync(geminiHooks, JSON.stringify(hookConfig, null, 2), 'utf8');
          console.log(`  ✓ Antigravity CLI (agy) hook registered in ~/.gemini/config/hooks.json`);
        }

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
  runFirstRunSetup();
}

module.exports = { isFirstRun, runFirstRunSetup };
