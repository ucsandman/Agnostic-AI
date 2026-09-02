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
const fableGuard = require('../hooks/fable-delegate-guard.cjs');
const graphGuard = require('../hooks/capability-graph-guard.cjs');
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

  // --- 8. fable-delegate-guard: a Fable main loop must delegate the hands-on work ---
  const FABLE = 'claude-fable-5-1';

  // Each case gets an isolated home. tmpdir is redirected inside that home so
  // the real os.tmpdir() (which contains the fake home) cannot allow everything.
  function fableEnv() {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-fable-'));
    return {
      home,
      opts: {
        home,
        stateDir: path.join(home, 'state'),
        logPath: path.join(home, 'guard.jsonl'),
        tmpdir: path.join(home, 'tmp'),
        env: {}
      }
    };
  }

  function logKinds(opts) {
    if (!fs.existsSync(opts.logPath)) return [];
    return fs.readFileSync(opts.logPath, 'utf8').trim().split('\n').filter(Boolean)
      .map(l => JSON.parse(l).kind);
  }

  const body = (n) => Array.from({ length: n }, (_, i) => `line ${i}`).join('\n');

  await test('FableGuard: Fable main loop cannot Write a large file into the repo', () => {
    const { opts } = fableEnv();
    const result = fableGuard.decide({
      hook_event_name: 'PreToolUse', session_id: 's-edit', prompt_id: 'p1', cwd: 'C:/repo',
      tool_name: 'Write', tool_input: { file_path: 'C:/repo/x.py', content: body(200) }
    }, { ...opts, model: FABLE });
    assert.strictEqual(result.action, 'deny', JSON.stringify(result));
    assert.strictEqual(result.kind, 'deny-edit');
    assert(result.reason.includes('[fable-delegate-guard]'), `reason: ${result.reason}`);
    assert(result.reason.includes('used 0 of 3'), `reason must report the budget: ${result.reason}`);
    assert.deepStrictEqual(logKinds(opts), ['deny-edit'], 'the denial must be logged');
  });

  await test('FableGuard: 3 small direct edits per prompt are allowed, the 4th is denied', () => {
    const { opts } = fableEnv();
    const small = (promptId) => ({
      session_id: 's-budget', prompt_id: promptId, cwd: 'C:/repo',
      tool_name: 'Write', tool_input: { file_path: 'C:/repo/x.py', content: body(10) }
    });
    for (let i = 1; i <= 3; i++) {
      const r = fableGuard.decide(small('p1'), { ...opts, model: FABLE });
      assert.strictEqual(r.kind, 'allowed-small', `edit ${i}: ${JSON.stringify(r)}`);
      assert.strictEqual(r.reason, `${i} of 3`);
    }
    const fourth = fableGuard.decide(small('p1'), { ...opts, model: FABLE });
    assert.strictEqual(fourth.kind, 'deny-edit', JSON.stringify(fourth));
    assert(fourth.reason.includes('used 3 of 3'), `reason: ${fourth.reason}`);

    const nextPrompt = fableGuard.decide(small('p2'), { ...opts, model: FABLE });
    assert.strictEqual(nextPrompt.kind, 'allowed-small', 'a new prompt resets the budget');
    assert.strictEqual(nextPrompt.reason, '1 of 3');
  });

  await test('FableGuard: writes under the scratchpad and ~/.claude are allowed', () => {
    const { home, opts } = fableEnv();
    const scratch = path.join(home, 'scratch');
    const inScratch = fableGuard.decide({
      session_id: 's-ok', cwd: 'C:/repo', scratchpad_dir: scratch,
      tool_name: 'Write', tool_input: { file_path: path.join(scratch, 'note.md') }
    }, { ...opts, model: FABLE });
    assert.strictEqual(inScratch.kind, 'allowed-path', JSON.stringify(inScratch));

    const inClaude = fableGuard.decide({
      session_id: 's-ok', cwd: 'C:/repo',
      tool_name: 'Edit', tool_input: { file_path: path.join(home, '.claude', 'projects', 'p', 'memory', 'a.md') }
    }, { ...opts, model: FABLE });
    assert.strictEqual(inClaude.kind, 'allowed-path', JSON.stringify(inClaude));
  });

  await test('FableGuard: a subagent (agent_id present) may write anywhere', () => {
    const { opts } = fableEnv();
    const result = fableGuard.decide({
      session_id: 's-sub', agent_id: 'agent_123', agent_type: 'sonnet-implementer', cwd: 'C:/repo',
      tool_name: 'Write', tool_input: { file_path: 'C:/repo/x.py', content: body(200) }
    }, { ...opts, model: FABLE });
    assert.strictEqual(result.kind, 'subagent', JSON.stringify(result));
    assert.strictEqual(result.action, 'allow');
  });

  await test('FableGuard: an Opus main loop is untouched', () => {
    const { home, opts } = fableEnv();
    const transcript = path.join(home, 'opus.jsonl');
    fs.writeFileSync(transcript, JSON.stringify({ type: 'assistant', message: { model: 'claude-opus-5' } }) + '\n', 'utf8');
    const result = fableGuard.decide({
      session_id: 's-opus', cwd: 'C:/repo', transcript_path: transcript,
      tool_name: 'Write', tool_input: { file_path: 'C:/repo/x.py', content: body(200) }
    }, opts);
    assert.strictEqual(result.kind, 'not-fable', JSON.stringify(result));
    assert.strictEqual(result.model, 'claude-opus-5');
  });

  const SHELL_CASES = [
    ['git status && python -m pytest tests/ -q', 'allowed-shell'],
    ['git commit -m x', 'allowed-shell'],
    ["python - <<'EOF'", 'deny-shell'],
    ['echo hi > C:/repo/out.txt', 'deny-shell'],
    ['npm install left-pad', 'allowed-shell'],
    ['python -c "open(\'a\',\'w\').write(1)"', 'deny-shell'],
    ['ruff check . 2>&1', 'allowed-shell'],
    ['Set-Content -Path a -Value b', 'deny-shell']
  ];
  for (const [command, kind] of SHELL_CASES) {
    await test(`FableGuard: shell '${command}' => ${kind}`, () => {
      const { opts } = fableEnv();
      const result = fableGuard.decide({
        session_id: 's-shell', cwd: 'C:/repo',
        tool_name: /Set-Content/.test(command) ? 'PowerShell' : 'Bash',
        tool_input: { command }
      }, { ...opts, model: FABLE });
      assert.strictEqual(result.kind, kind, JSON.stringify(result));
    });
  }

  await test('FableGuard: redirection into the tmpdir is allowed', () => {
    const { opts } = fableEnv();
    const result = fableGuard.decide({
      session_id: 's-tmp', cwd: 'C:/repo', tool_name: 'Bash',
      tool_input: { command: `echo hi > ${opts.tmpdir.replace(/\\/g, '/')}/out.txt` }
    }, { ...opts, model: FABLE });
    assert.strictEqual(result.kind, 'allowed-shell', JSON.stringify(result));
  });

  await test('FableGuard: "# FABLE_OK:" overrides one shell command and is logged', () => {
    const { opts } = fableEnv();
    const result = fableGuard.decide({
      session_id: 's-ovr', cwd: 'C:/repo', tool_name: 'Bash',
      tool_input: { command: 'rm -rf build # FABLE_OK: stale artefacts' }
    }, { ...opts, model: FABLE });
    assert.strictEqual(result.kind, 'override', JSON.stringify(result));
    assert.strictEqual(result.action, 'allow');
    assert(logKinds(opts).includes('override'), 'the override must be logged');
  });

  await test('FableGuard: FABLE_DELEGATE_GUARD=off disables the guard', () => {
    const { opts } = fableEnv();
    const result = fableGuard.decide({
      session_id: 's-off', cwd: 'C:/repo', tool_name: 'Write',
      tool_input: { file_path: 'C:/repo/x.py', content: body(200) }
    }, { ...opts, model: FABLE, env: { FABLE_DELEGATE_GUARD: 'off' } });
    assert.strictEqual(result.kind, 'disabled', JSON.stringify(result));
    assert.strictEqual(result.action, 'allow');
  });

  await test('FableGuard: sessionModel reads the transcript tail, caches it, falls back to settings', () => {
    const { home, opts } = fableEnv();
    const transcript = path.join(home, 't.jsonl');
    fs.writeFileSync(transcript, [
      JSON.stringify({ type: 'assistant', message: { model: 'claude-opus-5' } }),
      JSON.stringify({ type: 'user', message: { content: 'hi' } }),
      JSON.stringify({ type: 'assistant', message: { model: FABLE } })
    ].join('\n') + '\n', 'utf8');

    assert.strictEqual(fableGuard.sessionModel({ session_id: 'sm1', transcript_path: transcript }, opts), FABLE);
    assert.strictEqual(fs.readFileSync(path.join(opts.stateDir, 'sm1.model'), 'utf8'), FABLE, 'model must be cached per session');

    fs.unlinkSync(transcript);
    assert.strictEqual(fableGuard.sessionModel({ session_id: 'sm1', transcript_path: transcript }, opts), FABLE, 'cache must survive a missing transcript');

    fs.mkdirSync(path.join(home, '.claude'), { recursive: true });
    fs.writeFileSync(path.join(home, '.claude', 'settings.json'), JSON.stringify({ model: 'claude-opus-5' }), 'utf8');
    assert.strictEqual(fableGuard.sessionModel({ session_id: 'sm2' }, opts), 'claude-opus-5', 'settings.json is the last fallback');
    assert.strictEqual(fableGuard.sessionModel({ session_id: 'sm3' }, { ...opts, home: path.join(home, 'nope') }), null);
  });

  await test('FableGuard: the delegate-first briefing is injected once per session', () => {
    const { opts } = fableEnv();
    const payload = { hook_event_name: 'UserPromptSubmit', session_id: 'up1', cwd: 'C:/repo', prompt: 'go' };
    const first = fableGuard.main(payload, { ...opts, model: FABLE });
    assert(first, 'first UserPromptSubmit must inject');
    const parsed = JSON.parse(first);
    assert.strictEqual(parsed.hookSpecificOutput.hookEventName, 'UserPromptSubmit');
    assert(parsed.hookSpecificOutput.additionalContext.includes('Delegate-first is ENFORCED'), first);
    assert.strictEqual(fableGuard.main(payload, { ...opts, model: FABLE }), '', 'second call must stay silent');
    assert(fableGuard.injectionText().includes('Delegate-first is ENFORCED'));
  });

  await test('FirstRun: wires fable-delegate-guard into PreToolUse, UserPromptSubmit and SessionStart', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-claude-fable-'));
    fs.mkdirSync(path.join(home, '.claude'), { recursive: true });
    const settings = path.join(home, '.claude', 'settings.json');
    fs.writeFileSync(settings, JSON.stringify({ model: 'opus' }, null, 2), 'utf8');

    firstRun.wireAgentHooks(home);
    const report = firstRun.wireAgentHooks(home); // idempotent

    const after = JSON.parse(fs.readFileSync(settings, 'utf8'));
    const count = (event) => (after.hooks[event] || [])
      .flatMap(g => (g.hooks || []).map(h => h.command || ''))
      .filter(c => /fable-delegate-guard/.test(c)).length;
    for (const event of ['PreToolUse', 'UserPromptSubmit', 'SessionStart']) {
      assert.strictEqual(count(event), 1, `${event} must hold exactly one delegate-guard entry`);
    }
    const pre = after.hooks.PreToolUse.find(g => (g.hooks || []).some(h => /fable-delegate-guard/.test(h.command || '')));
    assert.strictEqual(pre.matcher, 'Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell');
    assert.strictEqual(report.claude.delegateGuard, true, 'report must state the delegate guard was installed');
  });

  // --- 9. capability-graph-guard: delegation flows downward only ---------------

  function graphEnv() {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-graph-'));
    return {
      home,
      opts: {
        home,
        stateDir: path.join(home, 'state'),
        logPath: path.join(home, 'graph.jsonl'),
        env: {}
      }
    };
  }

  // Registers one subagent and returns a PreToolUse payload factory for it.
  function callerOf(opts, sid, agentId, model) {
    graphGuard.recordSubagent({
      hook_event_name: 'SubagentStart', session_id: sid, agent_id: agentId,
      agent_type: 'worker', subagent_config: { agent_type: 'worker', agent_id: agentId, model }
    }, opts);
    return (toolInput, tool = 'Agent') => ({
      hook_event_name: 'PreToolUse', session_id: sid, agent_id: agentId,
      cwd: 'C:/repo', tool_name: tool, tool_input: toolInput
    });
  }

  function graphEvents(opts) {
    if (!fs.existsSync(opts.logPath)) return [];
    return fs.readFileSync(opts.logPath, 'utf8').trim().split('\n').filter(Boolean)
      .map(l => JSON.parse(l));
  }

  function graphKinds(opts) {
    return graphEvents(opts).map(e => e.kind);
  }

  // The REAL SubagentStart payload (measured 2026-09-02): subagent_config is
  // null, so the model only exists in the sidecar files Claude Code writes
  // under <transcript_path minus .jsonl>/subagents/.
  function nullConfigCaller(home, opts, sid, agentId, agentType) {
    const sessionDir = path.join(home, 'projects', 'proj', sid);
    fs.mkdirSync(path.join(sessionDir, 'subagents'), { recursive: true });
    const transcript = `${sessionDir}.jsonl`;
    const base = path.join(sessionDir, 'subagents', `agent-${agentId}`);
    const common = {
      session_id: sid, agent_id: agentId, agent_type: agentType,
      transcript_path: transcript, cwd: 'C:/repo'
    };
    return {
      sessionDir,
      writeMeta: (obj) => fs.writeFileSync(`${base}.meta.json`, JSON.stringify(obj), 'utf8'),
      writeTranscript: (lines) => fs.writeFileSync(`${base}.jsonl`, lines.map(l => JSON.stringify(l)).join('\n') + '\n', 'utf8'),
      start: () => graphGuard.recordSubagent({
        ...common, hook_event_name: 'SubagentStart', subagent_config: null
      }, opts),
      registry: () => JSON.parse(fs.readFileSync(path.join(opts.stateDir, 'graph', `${sid}.json`), 'utf8'))[agentId],
      call: (toolInput, tool = 'Agent') => ({
        ...common, hook_event_name: 'PreToolUse', tool_name: tool, tool_input: toolInput
      })
    };
  }

  await test('GraphGuard: rankOf maps real model ids to the capability ladder', () => {
    assert.strictEqual(graphGuard.rankOf('claude-fable-5-1'), 3);
    assert.strictEqual(graphGuard.rankOf('opus'), 2);
    assert.strictEqual(graphGuard.rankOf('claude-sonnet-5'), 1);
    assert.strictEqual(graphGuard.rankOf('haiku'), 0);
    assert.strictEqual(graphGuard.rankOf('gpt-5.6'), null);
    assert.strictEqual(graphGuard.rankOf(''), null);
    assert.strictEqual(graphGuard.rankOf(undefined), null);
  });

  await test('GraphGuard: a Sonnet subagent may spawn Haiku, never Sonnet or Opus', () => {
    const { opts } = graphEnv();
    const call = callerOf(opts, 's-son', 'agent_son', 'claude-sonnet-5');

    const reg = JSON.parse(fs.readFileSync(path.join(opts.stateDir, 'graph', 's-son.json'), 'utf8'));
    assert.strictEqual(reg.agent_son.model, 'claude-sonnet-5', JSON.stringify(reg));
    assert.strictEqual(reg.agent_son.agent_type, 'worker');

    const down = graphGuard.decide(call({ subagent_type: 'haiku-scout', model: 'haiku' }), opts);
    assert.strictEqual(down.kind, 'downward', JSON.stringify(down));
    assert.strictEqual(down.action, 'allow');

    const peer = graphGuard.decide(call({ subagent_type: 'sonnet-implementer', model: 'claude-sonnet-5' }), opts);
    assert.strictEqual(peer.action, 'deny', JSON.stringify(peer));
    assert.strictEqual(peer.kind, 'upward-or-peer');
    assert(peer.reason.startsWith(graphGuard.REASON_TEXT), `reason must carry the graph: ${peer.reason}`);

    const up = graphGuard.decide(call({ subagent_type: 'big', model: 'claude-opus-5' }), opts);
    assert.strictEqual(up.action, 'deny', JSON.stringify(up));
    assert.strictEqual(up.kind, 'upward-or-peer');

    const advisor = graphGuard.decide(call({ subagent_type: 'advisor' }), opts);
    assert.strictEqual(advisor.kind, 'advisor', JSON.stringify(advisor));
    assert.strictEqual(advisor.action, 'allow');

    assert.deepStrictEqual(graphKinds(opts), ['upward-or-peer', 'upward-or-peer', 'advisor'],
      'denials and advisor allows are logged, plain downward allows are not');
  });

  await test('GraphGuard: a Haiku subagent spawns nobody and consults nobody', () => {
    const { opts } = graphEnv();
    const call = callerOf(opts, 's-hai', 'agent_hai', 'claude-haiku-4.5');

    const leaf = graphGuard.decide(call({ subagent_type: 'haiku-scout', model: 'haiku' }), opts);
    assert.strictEqual(leaf.action, 'deny', JSON.stringify(leaf));
    assert.strictEqual(leaf.kind, 'haiku-leaf');
    assert(/Haiku spawns nobody/.test(leaf.reason), leaf.reason);

    const advisor = graphGuard.decide(call({ subagent_type: 'advisor' }), opts);
    assert.strictEqual(advisor.action, 'deny', JSON.stringify(advisor));
    assert.strictEqual(advisor.kind, 'advisor-haiku');
  });

  await test('GraphGuard: an Opus subagent may spawn Sonnet but not Fable', () => {
    const { opts } = graphEnv();
    const call = callerOf(opts, 's-opu', 'agent_opu', 'claude-opus-5');

    const down = graphGuard.decide(call({ subagent_type: 'sonnet-implementer', model: 'sonnet' }), opts);
    assert.strictEqual(down.kind, 'downward', JSON.stringify(down));

    const up = graphGuard.decide(call({ subagent_type: 'judge', model: 'claude-fable-5-1' }), opts);
    assert.strictEqual(up.action, 'deny', JSON.stringify(up));
    assert.strictEqual(up.kind, 'upward-or-peer');
  });

  await test('GraphGuard: the main loop delegates by its own session model', () => {
    const { opts } = graphEnv();
    const mainCall = (toolInput) => ({
      hook_event_name: 'PreToolUse', session_id: 's-main', cwd: 'C:/repo',
      tool_name: 'Agent', tool_input: toolInput
    });
    const fableOpts = { ...opts, sessionModelOverride: 'claude-fable-5-1' };
    for (const model of ['claude-opus-5', 'claude-sonnet-5', 'haiku']) {
      const r = graphGuard.decide(mainCall({ subagent_type: 'w', model }), fableOpts);
      assert.strictEqual(r.kind, 'downward', `${model}: ${JSON.stringify(r)}`);
    }
    const peer = graphGuard.decide(mainCall({ subagent_type: 'w', model: 'fable' }), fableOpts);
    assert.strictEqual(peer.kind, 'upward-or-peer', JSON.stringify(peer));

    const opusMain = graphGuard.decide(mainCall({ subagent_type: 'advisor' }), { ...opts, sessionModelOverride: 'claude-opus-5' });
    assert.strictEqual(opusMain.kind, 'advisor', JSON.stringify(opusMain));
    assert.strictEqual(opusMain.action, 'allow');
  });

  await test('GraphGuard: advisor consultations are capped at 2 per agent and 3 per session', () => {
    const { opts } = graphEnv();
    const a = callerOf(opts, 's-adv', 'agent_a', 'claude-sonnet-5');
    const b = callerOf(opts, 's-adv', 'agent_b', 'claude-opus-5');

    for (let i = 1; i <= 2; i++) {
      const r = graphGuard.decide(a({ subagent_type: 'advisor' }), opts);
      assert.strictEqual(r.kind, 'advisor', `advisor ${i}: ${JSON.stringify(r)}`);
    }
    const third = graphGuard.decide(a({ subagent_type: 'advisor' }), opts);
    assert.strictEqual(third.action, 'deny', JSON.stringify(third));
    assert.strictEqual(third.kind, 'advisor-cap');
    assert(/2 advisor consultations/.test(third.reason), third.reason);

    const otherFirst = graphGuard.decide(b({ subagent_type: 'advisor' }), opts);
    assert.strictEqual(otherFirst.kind, 'advisor', `session cap not yet reached: ${JSON.stringify(otherFirst)}`);
    const fourth = graphGuard.decide(b({ subagent_type: 'advisor' }), opts);
    assert.strictEqual(fourth.action, 'deny', JSON.stringify(fourth));
    assert.strictEqual(fourth.kind, 'advisor-cap');
    assert(/3 advisor consultations/.test(fourth.reason), fourth.reason);
  });

  await test('GraphGuard: unknown caller and unknown callee fail open, a pinned agent file is enforced', () => {
    const { home, opts } = graphEnv();

    const ghost = graphGuard.decide({
      hook_event_name: 'PreToolUse', session_id: 's-ghost', agent_id: 'never_recorded',
      cwd: 'C:/repo', tool_name: 'Agent', tool_input: { subagent_type: 'w', model: 'claude-opus-5' }
    }, opts);
    assert.strictEqual(ghost.action, 'allow', JSON.stringify(ghost));
    assert.strictEqual(ghost.kind, 'unknown-caller');
    assert.deepStrictEqual(graphKinds(opts), ['unknown-caller'], 'the unknown caller is logged once');
    graphGuard.decide({
      hook_event_name: 'PreToolUse', session_id: 's-ghost', agent_id: 'never_recorded',
      cwd: 'C:/repo', tool_name: 'Agent', tool_input: { subagent_type: 'w', model: 'claude-opus-5' }
    }, opts);
    assert.deepStrictEqual(graphKinds(opts), ['unknown-caller'], 'and only once per agent_id');

    const call = callerOf(opts, 's-unk', 'agent_unk', 'claude-sonnet-5');
    const blind = graphGuard.decide(call({ subagent_type: 'mystery' }), opts);
    assert.strictEqual(blind.kind, 'unknown-callee', JSON.stringify(blind));

    fs.mkdirSync(path.join(home, '.claude', 'agents'), { recursive: true });
    fs.writeFileSync(path.join(home, '.claude', 'agents', 'mystery.md'),
      '---\nname: mystery\nmodel: opus\n---\nbody\n', 'utf8');
    const pinned = graphGuard.decide(call({ subagent_type: 'mystery' }), opts);
    assert.strictEqual(pinned.action, 'deny', JSON.stringify(pinned));
    assert.strictEqual(pinned.kind, 'upward-or-peer');
    assert.strictEqual(graphGuard.calleeModel({ subagent_type: 'mystery' }, opts), 'opus');
  });

  await test('GraphGuard: subagent_config null resolves the caller from the sidecar meta.json', () => {
    const { home, opts } = graphEnv();
    const a = nullConfigCaller(home, opts, 's-meta', 'aid_meta', 'general-purpose');

    a.start();
    assert.strictEqual(a.registry().model, null, 'the real SubagentStart carries no model');
    assert.strictEqual(a.registry().agent_type, 'general-purpose');

    // meta.json lands after the start event, so resolution has to be lazy.
    a.writeMeta({ model: 'sonnet', spawnDepth: 1 });

    const peer = graphGuard.decide(a.call({ subagent_type: 'sonnet-implementer', model: 'claude-sonnet-5' }), opts);
    assert.strictEqual(peer.action, 'deny', JSON.stringify(peer));
    assert.strictEqual(peer.kind, 'upward-or-peer');

    const down = graphGuard.decide(a.call({ subagent_type: 'haiku-scout', model: 'haiku' }), opts);
    assert.strictEqual(down.kind, 'downward', JSON.stringify(down));

    const denyEvent = graphEvents(opts).find(e => e.kind === 'upward-or-peer');
    assert.strictEqual(denyEvent.caller.model, 'sonnet', JSON.stringify(denyEvent));
    assert.strictEqual(denyEvent.caller.source, 'meta');
    assert.strictEqual(denyEvent.caller.spawn_depth, 1);
  });

  await test('GraphGuard: with no meta.json the caller comes off its own transcript', () => {
    const { home, opts } = graphEnv();
    const a = nullConfigCaller(home, opts, 's-tr', 'aid_tr', 'general-purpose');

    a.start();
    a.writeTranscript([
      { type: 'user', message: { role: 'user' } },
      { type: 'assistant', message: { model: 'claude-opus-5' } }
    ]);

    const down = graphGuard.decide(a.call({ subagent_type: 'w', model: 'claude-sonnet-5' }), opts);
    assert.strictEqual(down.kind, 'downward', JSON.stringify(down));

    const peer = graphGuard.decide(a.call({ subagent_type: 'w', model: 'claude-opus-5' }), opts);
    assert.strictEqual(peer.action, 'deny', JSON.stringify(peer));
    assert.strictEqual(peer.kind, 'upward-or-peer');

    const denyEvent = graphEvents(opts).find(e => e.kind === 'upward-or-peer');
    assert.strictEqual(denyEvent.caller.model, 'claude-opus-5', JSON.stringify(denyEvent));
    // The first decide already cached it, so the deny logs source 'registry';
    // the transcript is what put it there.
    assert.strictEqual(a.registry().model_source, 'subagent-transcript', JSON.stringify(a.registry()));
  });

  await test('GraphGuard: with no sidecar files the caller comes off its agent file', () => {
    const { home, opts } = graphEnv();
    fs.mkdirSync(path.join(home, '.claude', 'agents'), { recursive: true });
    fs.writeFileSync(path.join(home, '.claude', 'agents', 'haiku-scout.md'),
      '---\nname: haiku-scout\nmodel: haiku\n---\nbody\n', 'utf8');
    const a = nullConfigCaller(home, opts, 's-fm', 'aid_fm', 'haiku-scout');

    a.start();
    assert.strictEqual(a.registry().model, 'haiku', 'the agent file resolves at SubagentStart already');

    for (const model of ['haiku', 'claude-sonnet-5', 'claude-opus-5']) {
      const r = graphGuard.decide(a.call({ subagent_type: 'w', model }), opts);
      assert.strictEqual(r.action, 'deny', `${model}: ${JSON.stringify(r)}`);
      assert.strictEqual(r.kind, 'haiku-leaf', `${model}: ${JSON.stringify(r)}`);
    }
  });

  await test('GraphGuard: an unresolvable caller still fails open and logs source "none"', () => {
    const { home, opts } = graphEnv();
    const a = nullConfigCaller(home, opts, 's-none', 'aid_none', 'ghost-worker');

    a.start();
    assert.strictEqual(a.registry().model, null);

    const r = graphGuard.decide(a.call({ subagent_type: 'w', model: 'claude-fable-5-1' }), opts);
    assert.strictEqual(r.action, 'allow', JSON.stringify(r));
    assert.strictEqual(r.kind, 'unknown-caller');

    const events = graphEvents(opts);
    assert.deepStrictEqual(events.map(e => e.kind), ['unknown-caller']);
    assert.strictEqual(events[0].caller.model, null, JSON.stringify(events[0]));
    assert.strictEqual(events[0].caller.source, 'none');
  });

  await test('GraphGuard: a resolved caller model is back-filled into the registry', () => {
    const { home, opts } = graphEnv();
    const a = nullConfigCaller(home, opts, 's-fill', 'aid_fill', 'general-purpose');

    a.start();
    assert.strictEqual(a.registry().model, null);

    a.writeMeta({ model: 'sonnet', spawnDepth: 2 });
    graphGuard.decide(a.call({ subagent_type: 'haiku-scout', model: 'haiku' }), opts);

    const entry = a.registry();
    assert.strictEqual(entry.model, 'sonnet', JSON.stringify(entry));
    assert.strictEqual(entry.model_source, 'meta', JSON.stringify(entry));
    assert.strictEqual(entry.spawn_depth, 2, JSON.stringify(entry));
    assert.strictEqual(entry.agent_type, 'general-purpose', JSON.stringify(entry));

    // The cached entry is now authoritative: deleting the sidecar changes nothing.
    fs.rmSync(path.join(a.sessionDir, 'subagents'), { recursive: true, force: true });
    assert.deepStrictEqual(
      graphGuard.callerModelFor(a.call({}), opts),
      { model: 'sonnet', source: 'registry', spawn_depth: 2 });
  });

  await test('GraphGuard: only Opus subagents run Workflows, and only downward ones', () => {
    const { opts } = graphEnv();
    const sonnet = callerOf(opts, 's-wf', 'agent_wf_s', 'claude-sonnet-5');
    const opus = callerOf(opts, 's-wf', 'agent_wf_o', 'claude-opus-5');
    const downScript = "await parallel([agent('a', {model: 'sonnet'}), agent('b', {model: 'haiku'})]);";
    const upScript = "await agent('a', {model: 'opus'});";

    const blocked = graphGuard.decide(sonnet({ script: downScript }, 'Workflow'), opts);
    assert.strictEqual(blocked.action, 'deny', JSON.stringify(blocked));
    assert.strictEqual(blocked.kind, 'workflow-rank');

    const ok = graphGuard.decide(opus({ script: downScript }, 'Workflow'), opts);
    assert.strictEqual(ok.kind, 'workflow-downward', JSON.stringify(ok));

    const upward = graphGuard.decide(opus({ script: upScript }, 'Workflow'), opts);
    assert.strictEqual(upward.action, 'deny', JSON.stringify(upward));
    assert.strictEqual(upward.kind, 'workflow-upward');

    const named = graphGuard.decide(opus({ name: 'tournament' }, 'Workflow'), opts);
    assert.strictEqual(named.kind, 'workflow-named', JSON.stringify(named));

    const fromMain = graphGuard.decide({
      hook_event_name: 'PreToolUse', session_id: 's-wf', cwd: 'C:/repo',
      tool_name: 'Workflow', tool_input: { script: upScript }
    }, { ...opts, sessionModelOverride: 'claude-fable-5-1' });
    assert.strictEqual(fromMain.kind, 'main-workflow', JSON.stringify(fromMain));
  });

  await test('GraphGuard: CAPABILITY_GRAPH_GUARD=off disables the guard', () => {
    const { opts } = graphEnv();
    const call = callerOf(opts, 's-off', 'agent_off', 'claude-haiku-4.5');
    const result = graphGuard.decide(call({ subagent_type: 'w', model: 'claude-fable-5-1' }),
      { ...opts, env: { CAPABILITY_GRAPH_GUARD: 'off' } });
    assert.strictEqual(result.action, 'allow', JSON.stringify(result));
    assert.strictEqual(result.kind, 'disabled');
  });

  await test('GraphGuard: main() emits the deny envelope and records SubagentStart silently', () => {
    const { opts } = graphEnv();
    assert.strictEqual(graphGuard.main({
      hook_event_name: 'SubagentStart', session_id: 's-main2', agent_id: 'agent_m',
      agent_type: 'worker', subagent_config: { model: 'claude-haiku-4.5' }
    }, opts), '', 'SubagentStart writes state and stays silent');
    assert.strictEqual(graphGuard.main({
      hook_event_name: 'SubagentStop', session_id: 's-main2', agent_id: 'agent_m'
    }, opts), '', 'SubagentStop never blocks');

    const out = graphGuard.main({
      hook_event_name: 'PreToolUse', session_id: 's-main2', agent_id: 'agent_m',
      tool_name: 'Agent', tool_input: { subagent_type: 'w', model: 'haiku' }
    }, opts);
    const parsed = JSON.parse(out);
    assert.strictEqual(parsed.hookSpecificOutput.permissionDecision, 'deny', out);
    assert.strictEqual(parsed.hookSpecificOutput.hookEventName, 'PreToolUse');
    assert(parsed.hookSpecificOutput.permissionDecisionReason.startsWith(graphGuard.REASON_TEXT), out);
  });

  await test('FirstRun: wires capability-graph-guard and installs the advisor agent', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-claude-graph-'));
    fs.mkdirSync(path.join(home, '.claude'), { recursive: true });
    const settings = path.join(home, '.claude', 'settings.json');
    fs.writeFileSync(settings, JSON.stringify({ model: 'opus' }, null, 2), 'utf8');

    firstRun.wireAgentHooks(home);
    const report = firstRun.wireAgentHooks(home); // idempotent

    const after = JSON.parse(fs.readFileSync(settings, 'utf8'));
    const count = (event) => (after.hooks[event] || [])
      .flatMap(g => (g.hooks || []).map(h => h.command || ''))
      .filter(c => /capability-graph-guard/.test(c)).length;
    for (const event of ['PreToolUse', 'SubagentStart', 'SubagentStop']) {
      assert.strictEqual(count(event), 1, `${event} must hold exactly one capability-graph-guard entry`);
    }
    const pre = after.hooks.PreToolUse.find(g => (g.hooks || []).some(h => /capability-graph-guard/.test(h.command || '')));
    assert.strictEqual(pre.matcher, 'Agent|Task|Workflow');
    assert.strictEqual(report.claude.graphGuard, true, 'report must state the graph guard was installed');

    const source = path.join(ROOT, 'engine', 'setup', 'agents', 'advisor.md');
    const dest = path.join(home, '.claude', 'agents', 'advisor.md');
    assert.strictEqual(fs.readFileSync(dest, 'utf8'), fs.readFileSync(source, 'utf8'), 'advisor.md must be installed verbatim');
    assert.strictEqual(report.claude.advisorAgent, 'kept', 'the second run must keep the file it already installed');
  });

  await test('FirstRun: an existing advisor.md is kept byte-identical', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-claude-advisor-'));
    fs.mkdirSync(path.join(home, '.claude', 'agents'), { recursive: true });
    fs.writeFileSync(path.join(home, '.claude', 'settings.json'), JSON.stringify({ model: 'opus' }), 'utf8');
    const mine = '---\nname: advisor\nmodel: opus\n---\nmy own advisor\n';
    const dest = path.join(home, '.claude', 'agents', 'advisor.md');
    fs.writeFileSync(dest, mine, 'utf8');

    const report = firstRun.wireAgentHooks(home);

    assert.strictEqual(fs.readFileSync(dest, 'utf8'), mine, 'an operator-owned advisor must never be overwritten');
    assert.strictEqual(report.claude.advisorAgent, 'kept');
  });

  console.log(`\n=== Hook Regression Tests Complete: ${passed} passed, ${failed} failed (${passed + failed} total) ===`);
  if (failed > 0) process.exit(1);
}

run();
