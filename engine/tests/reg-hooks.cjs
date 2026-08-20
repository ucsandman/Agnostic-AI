#!/usr/bin/env node
/**
 * engine/tests/reg-hooks.cjs — Regression tests for the engine security hooks.
 *
 * Covers the fail-open / bypass defects in dashclaw-guard, secret-guard,
 * dashclaw-setup and first-run. Policy comes from core/safety/guards.json.
 */

const os = require('os');
const fs = require('fs');
const path = require('path');
const http = require('http');
const assert = require('assert');

// Isolate HOME before any hook module is loaded (they cache os.homedir() at require time).
const TMP_HOME = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-home-'));
process.env.USERPROFILE = TMP_HOME;
process.env.HOME = TMP_HOME;

const ROOT = path.resolve(__dirname, '..', '..');
const GUARDS = JSON.parse(fs.readFileSync(path.join(ROOT, 'core', 'safety', 'guards.json'), 'utf8')).guards;
const HARD_BLOCK = GUARDS.dashclaw.hardBlockRiskThreshold;
const DC_CONFIG_STORAGE = path.join(ROOT, 'storage', 'dashclaw-config.json');

const guard = require('../hooks/dashclaw-guard.cjs');
const secretGuard = require('../hooks/secret-guard.cjs');
const dashclawSetup = require('../hooks/dashclaw-setup.cjs');
const firstRun = require('../setup/first-run.cjs');

console.log('=== Running Engine Hook Security Regression Tests ===\n');
let passed = 0;
let failed = 0;

async function test(name, fn) {
  try {
    await fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

function denied(result) {
  return result.allowed === false || result.decision === 'deny' || result.permissionDecision === 'deny';
}

function shellPayload(command) {
  return { tool: 'bash', args: { command } };
}

const FAKE_CONFIG = {
  enabled: true,
  baseUrl: 'http://127.0.0.1:65535',
  apiKey: null,
  agentId: 'reg-test',
  agentName: 'Reg Test'
};

async function run() {
  // --- 1. Risk scoring uses guards.json patterns, not hardcoded includes() ---
  const HIGH_RISK_COMMANDS = [
    'git push origin main --force',
    'git push -f origin main',
    'rm -rf ~/Projects',
    'git reset --hard HEAD~5',
    'npm publish'
  ];
  for (const cmd of HIGH_RISK_COMMANDS) {
    await test(`Risk: '${cmd}' scores >= ${HARD_BLOCK}`, () => {
      const risk = guard.calculateLocalRisk({ command: cmd, targetFile: null });
      assert(risk >= HARD_BLOCK, `expected >= ${HARD_BLOCK}, got ${risk}`);
    });
  }

  await test('Risk: benign command stays low', () => {
    const risk = guard.calculateLocalRisk({ command: 'git status', targetFile: null });
    assert(risk < GUARDS.dashclaw.defaultRiskThreshold, `expected low risk, got ${risk}`);
  });

  // --- 2. Fail CLOSED on remote failure / exception ---
  await test('FailClosed: high risk + remote throws => BLOCK', async () => {
    process.env.ALLOW_HIGH_RISK = '1';
    const result = await guard.handleGuard(shellPayload('git push origin main --force'), {
      getDashClawConfig: () => FAKE_CONFIG,
      queryDashClawGuard: () => { throw new Error('remote exploded'); }
    });
    delete process.env.ALLOW_HIGH_RISK;
    assert(denied(result), `expected denial, got ${JSON.stringify(result)}`);
  });

  await test('FailClosed: high risk + remote resolves null (timeout) => BLOCK', async () => {
    const result = await guard.handleGuard(shellPayload('rm -rf ~/Projects'), {
      getDashClawConfig: () => FAKE_CONFIG,
      queryDashClawGuard: async () => null
    });
    assert(denied(result), `expected denial, got ${JSON.stringify(result)}`);
  });

  await test('FailClosed: ALLOW_HIGH_RISK env no longer bypasses the hard block', async () => {
    process.env.ALLOW_HIGH_RISK = '1';
    const result = await guard.handleGuard(shellPayload('git push -f origin main'), {
      getDashClawConfig: () => ({ ...FAKE_CONFIG, enabled: false })
    });
    delete process.env.ALLOW_HIGH_RISK;
    assert(denied(result), `expected denial, got ${JSON.stringify(result)}`);
  });

  await test('FailClosed: low risk + remote null still allowed', async () => {
    const result = await guard.handleGuard(shellPayload('git status'), {
      getDashClawConfig: () => FAKE_CONFIG,
      queryDashClawGuard: async () => null
    });
    assert(!denied(result), `expected approval, got ${JSON.stringify(result)}`);
  });

  // --- 3. secret-guard scans secret PATHS inside command strings ---
  const SECRET_COMMANDS = [
    'cat ~/.secrets.env',
    'type ~/.ssh/id_rsa',
    'cat .env',
    'Get-Content C:/Users/me/.aws/credentials',
    // Bypasses found by adversarial review (git rev-spec, glob, direnv, bare .aws):
    'git show HEAD:.env',
    'git show :.env',
    'git cat-file -p HEAD:.env',
    'cat *.env',
    'cat .envrc',
    'cat .aws/credentials',
    'cat .env | head -5',
    'sed -n 1p .env'
  ];
  for (const cmd of SECRET_COMMANDS) {
    await test(`SecretGuard: blocks '${cmd}'`, () => {
      const result = secretGuard.handlePayload(shellPayload(cmd));
      assert(denied(result), `expected denial, got ${JSON.stringify(result)}`);
    });
  }

  // Must NOT false-positive on benign commands that merely contain "env".
  for (const cmd of ['cat README.md', 'ls -la', 'cat .environment', 'npm run env-check', 'git commit -m env']) {
    await test(`SecretGuard: allows benign '${cmd}'`, () => {
      const result = secretGuard.handlePayload(shellPayload(cmd));
      assert(!denied(result), `expected approval, got ${JSON.stringify(result)}`);
    });
  }

  // --- 4. dashclaw-setup does not adopt a bare healthy localhost:3000 ---
  await test('Setup: does NOT adopt a healthy 127.0.0.1 dev server when adoptLocalhostPortsAllowed=false', async () => {
    assert.strictEqual(GUARDS.dashclaw.adoptLocalhostPortsAllowed, false, 'guards.json must forbid localhost adoption');
    const backup = fs.existsSync(DC_CONFIG_STORAGE) ? fs.readFileSync(DC_CONFIG_STORAGE, 'utf8') : null;
    const savedEnv = { url: process.env.DASHCLAW_BASE_URL, key: process.env.DASHCLAW_API_KEY };
    delete process.env.DASHCLAW_BASE_URL;
    delete process.env.DASHCLAW_API_KEY;

    const server = http.createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok' }));
    });
    // Port 0: a listen() failure is an 'error' EVENT, not a rejection, so a fixed
    // port that some other dev server already holds would crash the whole suite.
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));

    try {
      const config = await dashclawSetup.autoConfigureDashClaw();
      assert.strictEqual(config.configured, false, `must not configure from a bare local probe on port ${server.address().port}: ${JSON.stringify(config)}`);
      assert.strictEqual(config.active, false, 'must not activate from a bare local probe');
    } finally {
      await new Promise((resolve) => server.close(resolve));
      if (backup !== null) fs.writeFileSync(DC_CONFIG_STORAGE, backup, 'utf8');
      else if (fs.existsSync(DC_CONFIG_STORAGE)) fs.unlinkSync(DC_CONFIG_STORAGE);
      if (savedEnv.url) process.env.DASHCLAW_BASE_URL = savedEnv.url;
      if (savedEnv.key) process.env.DASHCLAW_API_KEY = savedEnv.key;
    }
  });

  // --- 5. first-run merges hook files instead of clobbering them ---
  await test('FirstRun: merges existing ~/.codex/hooks.json instead of clobbering', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-codex-'));
    fs.mkdirSync(path.join(home, '.codex'), { recursive: true });
    const hooksFile = path.join(home, '.codex', 'hooks.json');
    fs.writeFileSync(hooksFile, JSON.stringify({ pre_tool_use: 'node "C:/mine.js"', custom: 'keep-me' }, null, 2), 'utf8');

    firstRun.wireAgentHooks(home);

    const after = JSON.parse(fs.readFileSync(hooksFile, 'utf8'));
    assert.strictEqual(after.custom, 'keep-me', 'existing user key must survive');
    assert.strictEqual(after.pre_tool_use, 'node "C:/mine.js"', 'existing user hook must not be overwritten');
  });

  await test('FirstRun: installs codex hook when none exists, preserving other keys', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-codex2-'));
    fs.mkdirSync(path.join(home, '.codex'), { recursive: true });
    const hooksFile = path.join(home, '.codex', 'hooks.json');
    fs.writeFileSync(hooksFile, JSON.stringify({ custom: 'keep-me' }, null, 2), 'utf8');

    firstRun.wireAgentHooks(home);

    const after = JSON.parse(fs.readFileSync(hooksFile, 'utf8'));
    assert.strictEqual(after.custom, 'keep-me', 'existing user key must survive');
    assert(/dashclaw-guard/.test(after.pre_tool_use || ''), 'guard hook must be installed');
  });

  await test('FirstRun: merges existing ~/.gemini/config/hooks.json instead of clobbering', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-gemini-'));
    fs.mkdirSync(path.join(home, '.gemini', 'config'), { recursive: true });
    const hooksFile = path.join(home, '.gemini', 'config', 'hooks.json');
    fs.writeFileSync(hooksFile, JSON.stringify({ custom: 'keep-me' }, null, 2), 'utf8');

    firstRun.wireAgentHooks(home);

    const after = JSON.parse(fs.readFileSync(hooksFile, 'utf8'));
    assert.strictEqual(after.custom, 'keep-me', 'existing user key must survive');
    assert(/dashclaw-guard/.test(after.preToolUse || ''), 'guard hook must be installed');
  });

  // --- 6. secret-guard is actually wired into Claude Code ---
  await test('FirstRun: wires secret-guard AND dashclaw-guard into Claude PreToolUse', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-claude-'));
    fs.mkdirSync(path.join(home, '.claude'), { recursive: true });
    const settings = path.join(home, '.claude', 'settings.json');
    fs.writeFileSync(settings, JSON.stringify({ model: 'opus', hooks: {} }, null, 2), 'utf8');

    const report = firstRun.wireAgentHooks(home);

    const after = JSON.parse(fs.readFileSync(settings, 'utf8'));
    assert.strictEqual(after.model, 'opus', 'existing settings must survive');
    const commands = (after.hooks.PreToolUse || []).flatMap(g => (g.hooks || []).map(h => h.command || ''));
    assert(commands.some(c => /dashclaw-guard/.test(c)), `dashclaw-guard not wired: ${JSON.stringify(commands)}`);
    assert(commands.some(c => /secret-guard/.test(c)), `secret-guard not wired: ${JSON.stringify(commands)}`);
    assert(report.claude.secretGuard === true, 'report must state secret-guard was installed for claude');
  });

  // --- 6b. a malformed settings file is never replaced by a hooks-only file ---
  await test('FirstRun: leaves a malformed ~/.claude/settings.json byte-identical', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-claude-bad-'));
    fs.mkdirSync(path.join(home, '.claude'), { recursive: true });
    const settings = path.join(home, '.claude', 'settings.json');
    const malformed = '{"permissions":{"allow":["Bash(git:*)"]},"model":"opus",}';
    fs.writeFileSync(settings, malformed, 'utf8');

    const logs = [];
    const realLog = console.log;
    console.log = (...args) => logs.push(args.join(' '));
    let report;
    try {
      report = firstRun.wireAgentHooks(home);
    } finally {
      console.log = realLog;
    }

    assert.strictEqual(fs.readFileSync(settings, 'utf8'), malformed, 'malformed settings must be left byte-identical');
    assert.strictEqual(report.claude.malformed, true, 'report must flag the target as malformed');
    assert.strictEqual(report.claude.dashclawGuard, false, 'nothing may be reported as wired');
    assert(!logs.some(l => l.includes('\u2713') && /settings\.json/.test(l)), `no success line may be printed: ${JSON.stringify(logs)}`);
  });

  await test('FirstRun: leaves a malformed ~/.codex/hooks.json byte-identical', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-codex-bad-'));
    fs.mkdirSync(path.join(home, '.codex'), { recursive: true });
    const hooksFile = path.join(home, '.codex', 'hooks.json');
    const malformed = '{"pre_tool_use":"node \\"C:/mine.js\\"",}';
    fs.writeFileSync(hooksFile, malformed, 'utf8');

    const report = firstRun.wireAgentHooks(home);

    assert.strictEqual(fs.readFileSync(hooksFile, 'utf8'), malformed, 'malformed hooks file must be left byte-identical');
    assert.strictEqual(report.codex.malformed, true, 'report must flag the target as malformed');
    assert.strictEqual(report.codex.dashclawGuard, false, 'nothing may be reported as wired');
  });

  // --- 7. first-run actually detects a prior run ---
  await test('FirstRun: isFirstRun() is false once a prior install is recorded', () => {
    const stateFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-state-')), 'harness-installed.json');
    assert.strictEqual(firstRun.isFirstRun(stateFile), true, 'missing state file means first run');
    fs.writeFileSync(stateFile, JSON.stringify({ installed: true }), 'utf8');
    assert.strictEqual(firstRun.isFirstRun(stateFile), false, 'recorded install must suppress re-setup');
  });

  console.log(`\n=== Hook Regression Tests Complete: ${passed} passed, ${failed} failed (${passed + failed} total) ===`);
  if (failed > 0) process.exit(1);
}

run();
