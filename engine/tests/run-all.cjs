#!/usr/bin/env node
/**
 * engine/tests/run-all.cjs — Comprehensive Test Runner for Agnostic AI Harness.
 *
 * HERMETIC BY DESIGN:
 *   - Never asserts real machine state (candidate counts, skill counts, "am I
 *     in sync with my own home directory") — those numbers differ on every
 *     clone and every day. Assertions here check SHAPE (types, structure) or
 *     behavior against fixtures this file creates itself.
 *   - Any engine function that writes to real storage/ or ~ (home) files is
 *     wrapped so the suite leaves those files byte-for-byte as it found them,
 *     even if a test throws. Nothing here mutates the developer's real
 *     candidates.jsonl, skills/definitions/, or DashClaw config.
 *   - Must pass with exit 0 on a clean clone with an empty storage/.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const STORAGE = path.join(ROOT, 'storage');

console.log('=== Running Agnostic AI Test Suite ===\n');
let passed = 0;
let failed = 0;

async function test(name, fn) {
  try {
    await fn();
    console.log(`  \u2713 ${name}`);
    passed++;
  } catch (err) {
    console.error(`  \u2717 ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

// ── Hermetic helpers ─────────────────────────────────────────────────────────
// Snapshot real files a function under test may write to, then restore them
// exactly (including "did not exist before") once the test is done, whether
// it passed or threw. This is what keeps calls into the real engine modules
// (which hardcode paths under storage/ or ~) from leaving lasting mutations.

function snapshotFile(filePath) {
  const existed = fs.existsSync(filePath);
  const original = existed ? fs.readFileSync(filePath) : null;
  return function restore() {
    if (existed) {
      fs.mkdirSync(path.dirname(filePath), { recursive: true });
      fs.writeFileSync(filePath, original);
    } else if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
    }
  };
}

async function withRealFilesRestored(filePaths, fn) {
  const restores = filePaths.map(snapshotFile);
  try {
    return await fn();
  } finally {
    for (const restore of restores) restore();
  }
}

async function withEnvCleared(keys, fn) {
  const saved = {};
  for (const k of keys) {
    saved[k] = process.env[k];
    delete process.env[k];
  }
  try {
    return await fn();
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
}

function makeTmpDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

async function run() {
  // 1. Test Sync Engine (pure: compileTarget/loadSource only read repo-committed SSOT files)
  const { compileTarget, loadSource } = require('../sync/sync.cjs');
  await test('Sync: loads source rules and compiles target output', () => {
    const source = loadSource();
    assert(source.rules.includes('Non-Negotiables'), 'Rules should include Non-Negotiables');
    const target = { name: 'Test Target', preamble: '# Test Header\n', dialect: 'generic' };
    const compiled = compileTarget(target, source);
    assert(compiled.startsWith('# Test Header'), 'Compiled output should start with preamble');
    assert(compiled.includes('Simplicity first'), 'Compiled output should include core rules');
  });

  // 2. Test Universal Hook Adapter Across All Dialects (pure)
  const { normalizePayload, formatDenial, formatApproval, detectClient } = require('../hooks/universal-adapter.cjs');
  await test('Hooks: normalizes Claude payload', () => {
    const payload = {
      event: 'pre_tool',
      tool_name: 'bash',
      tool_input: { command: 'git status' }
    };
    const normalized = normalizePayload(payload);
    assert.strictEqual(normalized.client, 'claude');
    assert.strictEqual(normalized.command, 'git status');
    assert.strictEqual(normalized.isShell, true);
  });

  await test('Hooks: normalizes Antigravity (agy) payload', () => {
    const payload = {
      eventName: 'PreInvocation',
      toolCall: {
        name: 'run_command',
        args: { CommandLine: 'npm test' }
      }
    };
    const normalized = normalizePayload(payload);
    assert.strictEqual(normalized.client, 'agy');
    assert.strictEqual(normalized.command, 'npm test');
    assert.strictEqual(normalized.isShell, true);
  });

  await test('Hooks: normalizes Cursor & Windsurf & Cline payloads', () => {
    const cursorPayload = {
      cursorTool: true,
      name: 'execute_command',
      arguments: { command: 'pytest' }
    };
    const cursorNorm = normalizePayload(cursorPayload);
    assert.strictEqual(cursorNorm.client, 'cursor');
    assert.strictEqual(cursorNorm.command, 'pytest');
    assert.strictEqual(cursorNorm.isShell, true);

    const windsurfPayload = {
      cascadeTool: true,
      name: 'run_command',
      arguments: { CommandLine: 'cargo build' }
    };
    const windsurfNorm = normalizePayload(windsurfPayload);
    assert.strictEqual(windsurfNorm.client, 'windsurf');
    assert.strictEqual(windsurfNorm.command, 'cargo build');

    const clinePayload = {
      cline_action: true,
      tool: 'execute_command',
      parameters: { command: 'go test ./...' }
    };
    const clineNorm = normalizePayload(clinePayload);
    assert.strictEqual(clineNorm.client, 'cline');
    assert.strictEqual(clineNorm.command, 'go test ./...');
  });

  await test('Hooks: normalizes OpenHands, Goose, and Continue payloads', () => {
    const ohPayload = {
      source: 'openhands',
      action: 'run',
      args: { command: 'make test' }
    };
    const ohNorm = normalizePayload(ohPayload);
    assert.strictEqual(ohNorm.client, 'openhands');
    assert.strictEqual(ohNorm.command, 'make test');

    const goosePayload = {
      goose_extension: true,
      tool_call: 'shell',
      arguments: { command: 'ruff check' }
    };
    const gooseNorm = normalizePayload(goosePayload);
    assert.strictEqual(gooseNorm.client, 'goose');
    assert.strictEqual(gooseNorm.command, 'ruff check');

    const continuePayload = {
      slashCommand: true,
      name: 'exec',
      arguments: { command: 'node server.js' }
    };
    const contNorm = normalizePayload(continuePayload);
    assert.strictEqual(contNorm.client, 'continue');
    assert.strictEqual(contNorm.command, 'node server.js');
  });

  await test('Hooks: denial formatting per client dialect', () => {
    const agyDenial = formatDenial('agy', 'Access denied');
    assert.strictEqual(agyDenial.decision, 'deny');

    const claudeDenial = formatDenial('claude', 'Access denied');
    assert.strictEqual(claudeDenial.permissionDecision, 'deny');

    const cursorDenial = formatDenial('cursor', 'Blocked file');
    assert.strictEqual(cursorDenial.isError, true);
    assert.strictEqual(cursorDenial.allowed, false);

    const ohDenial = formatDenial('openhands', 'Security policy violation');
    assert.strictEqual(ohDenial.status, 'rejected');

    const gooseDenial = formatDenial('goose', 'Sensitive path');
    assert.strictEqual(gooseDenial.block, true);
  });

  // 3. Test Secret Guard (pure: mockConfig passed explicitly, no real config file touched)
  const { checkSecrets } = require('../hooks/secret-guard.cjs');
  await test('Security: blocks access to .secrets.env', () => {
    const mockConfig = {
      guards: {
        secretScan: {
          enabled: true,
          blockedFiles: ['**/.secrets.env'],
          sensitivePatterns: ['sk_live_[0-9a-zA-Z]{24,}']
        }
      }
    };

    const blockedRes = checkSecrets({ targetFile: '/workspace/.secrets.env' }, mockConfig);
    assert.strictEqual(blockedRes.blocked, true, 'Should block .secrets.env');

    const safeRes = checkSecrets({ targetFile: 'C:/Projects/agnostic-ai/README.md' }, mockConfig);
    assert.strictEqual(safeRes.blocked, false, 'Should allow safe files');
  });

  // 4. Test Distill Ladder Fingerprinting (pure). Deliberately NOT calling
  // runDistillation() here: it writes storage/candidates.jsonl,
  // distill-PROPOSAL.md, distill-digest.json, storage/prune-report.json, AND
  // migrates promoted items into dynamically-named core/examples/<hash>.json
  // files whose names can't be known ahead of time to back up — there is no
  // way to call it without leaving real, unpredictable production writes.
  const { hashFingerprint } = require('../distill/distill.cjs');
  await test('Distill: fingerprints candidate text deterministically', () => {
    const a = hashFingerprint('Always validate user input at the API boundary.');
    const b = hashFingerprint('  ALWAYS validate user input at the api boundary!!  ');
    assert.strictEqual(a, b, 'Fingerprint should normalize case/punctuation/whitespace');
    assert.strictEqual(typeof a, 'string');
    assert.strictEqual(a.length, 16, 'Fingerprint should be a 16-char hex slice');

    const c = hashFingerprint('A completely different observation.');
    assert.notStrictEqual(a, c, 'Different text should fingerprint differently');
  });

  // 5. Test Recall Engine (read-only against repo-committed core/rules/global-rules.md)
  const { searchMemory } = require('../../tools/recall/recall.cjs');
  await test('Recall: searches rules and facts', () => {
    const results = searchMemory('Simplicity');
    assert(Array.isArray(results), 'Results should be an array');
    assert(results.length > 0, 'Should find Simplicity rule in the repo SSOT');
    assert.strictEqual(results[0].type, 'rule');
  });

  // 6. Test Multi-Rule Merger Across Polyglot Formats (pure, given mock files)
  const { mergeRuleFiles } = require('../ingest/merge.cjs');
  await test('Merge: ingests and unifies CLAUDE.md, AGENTS.md, .cursorrules, and CONVENTIONS.md', () => {
    const mockFiles = [
      { name: 'CLAUDE.md', content: '## Core Rules\n\n- Rule A\n\n## Learned Rules\n\n- **L1 (2026-08-10)**: First lesson' },
      { name: 'AGENTS.md', content: '## Core Rules\n\n- Rule A\n- Rule B\n\n## Learned Rules\n\n- **L2 (2026-08-12)**: Second lesson' },
      { name: '.cursor/rules/global-rules.mdc', content: '---\ndescription: "Cursor rules"\n---\n\n## Core Rules\n\n- Rule C' },
      { name: 'CONVENTIONS.md', content: '## Core Rules\n\n- Rule D' }
    ];
    const merged = mergeRuleFiles(mockFiles);
    assert(merged.includes('Rule A'), 'Merged should contain Rule A');
    assert(merged.includes('Rule B'), 'Merged should contain Rule B');
    assert(merged.includes('Rule C'), 'Merged should contain Rule C');
    assert(merged.includes('Rule D'), 'Merged should contain Rule D');
    assert(merged.includes('L1 (2026-08-10)'), 'Merged should contain L1');
    assert(merged.includes('L2 (2026-08-12)'), 'Merged should contain L2');
  });

  // 7. Test Parity Engine — tracked-target shape from the repo SSOT config, plus a
  // fixture in-sync/drifted round-trip through the real compileTarget/loadSource
  // pipeline. No real home-directory rules files are read or compared here.
  await test('Parity: tracks 18 targets and detects in-sync vs. drifted fixtures', () => {
    const targetsConfig = JSON.parse(
      fs.readFileSync(path.join(ROOT, 'core', 'templates', 'targets.json'), 'utf8')
    );
    const targets = targetsConfig.targets || [];
    assert.strictEqual(targets.length, 18, 'Should track exactly 18 targets');
    for (const t of targets) {
      assert.strictEqual(typeof t.id, 'string', 'Each target needs a string id');
      assert.strictEqual(typeof t.name, 'string', 'Each target needs a string name');
      assert.strictEqual(typeof t.dialect, 'string', 'Each target needs a string dialect');
    }

    // Fixture round-trip: compile once, write it out, confirm it reads back in-sync;
    // then drift the file and confirm the same equality check now reports drift.
    const source = loadSource();
    const fixtureTarget = { id: 'fixture-target', name: 'Fixture Target', preamble: '# Fixture\n', dialect: 'generic' };
    const compiled = compileTarget(fixtureTarget, source);

    const tmpDir = makeTmpDir('agnostic-parity-fixture-');
    try {
      const fixtureFile = path.join(tmpDir, 'fixture-rules.md');

      fs.writeFileSync(fixtureFile, compiled, 'utf8');
      const inSyncExisting = fs.readFileSync(fixtureFile, 'utf8');
      assert.strictEqual(inSyncExisting === compiled, true, 'Freshly written fixture should report in-sync');

      fs.writeFileSync(fixtureFile, compiled + '\nSTALE DRIFT LINE\n', 'utf8');
      const driftedExisting = fs.readFileSync(fixtureFile, 'utf8');
      assert.strictEqual(driftedExisting === compiled, false, 'Manually drifted fixture should report out-of-sync');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  // 8. Test DashClaw Auto-Discovery (read-only paths only — never calls
  // autoConfigureDashClaw(), which writes storage/dashclaw-config.json and can
  // attempt a real network probe).
  const { discoverDashClawSources, getStoredDashClawConfig } = require('../hooks/dashclaw-setup.cjs');
  await test('DashClaw Setup: discovery and stored-config readers are well-shaped', () => {
    const sources = discoverDashClawSources();
    assert(Array.isArray(sources), 'Should return sources array');

    const stored = getStoredDashClawConfig();
    assert(stored === null || typeof stored === 'object', 'Stored config should be null or an object');
  });

  // 9. Test DashClaw Guard & Risk Scoring — every real config source
  // getDashClawConfig()/discoverDashClawSources() can find (repo-local
  // .dashclaw-local/state.json, ~/.dashclaw/config.json, ~/.dashclaw/instance.json,
  // storage/dashclaw-config.json) plus the DashClaw env vars are neutralized for
  // the duration, byte-for-byte restored after. This is not just "hermetic" —
  // without it, handleGuard() below resolves a real stored DashClaw API key and
  // fires an actual network request carrying it on every test run.
  const { calculateLocalRisk, handleGuard, getDashClawConfig } = require('../hooks/dashclaw-guard.cjs');
  const DASHCLAW_REAL_FILES = [
    path.join(STORAGE, 'dashclaw-config.json'),
    path.join(ROOT, '.dashclaw-local', 'state.json'),
    path.join(os.homedir(), '.dashclaw', 'config.json'),
    path.join(os.homedir(), '.dashclaw', 'instance.json')
  ];
  await test('DashClaw Guard: calculates risk score for destructive actions', async () => {
    await withRealFilesRestored(DASHCLAW_REAL_FILES, () =>
      withEnvCleared(['DASHCLAW_BASE_URL', 'DASHCLAW_API_KEY', 'DASHCLAW_AGENT_ID', 'DASHCLAW_AGENT_NAME'], async () => {
        for (const f of DASHCLAW_REAL_FILES) {
          if (fs.existsSync(f)) fs.unlinkSync(f);
        }

        const dcConfig = getDashClawConfig();
        assert.strictEqual(dcConfig.enabled, false, 'With no config/env, DashClaw should resolve disabled');

        const highRisk = calculateLocalRisk({ command: 'git push --force origin main' });
        assert.strictEqual(highRisk >= 80, true, 'git push --force should be high risk');

        const lowRisk = calculateLocalRisk({ command: 'npm test' });
        assert.strictEqual(lowRisk <= 20, true, 'npm test should be low risk');

        const agyPayload = {
          eventName: 'PreInvocation',
          toolCall: { name: 'run_command', args: { CommandLine: 'git push --force origin main' } }
        };
        const decision = await handleGuard(agyPayload);
        assert.strictEqual(decision.decision, 'deny', 'High risk command should be blocked without override');
      })
    );
  });

  // 10. Test Data Harvester — real function (exercises the actual harvest
  // pipeline), but storage/candidates.jsonl and distill-digest.json are
  // restored afterward. A seeded fixture makes the verdict carry volume: a
  // pass on an empty machine would prove nothing.
  const { runHarvest } = require('../harvest/harvest.cjs');
  let harvestTotal = null;
  await test('Harvester: produces a well-shaped result without corrupting storage', async () => {
    const candidatesFile = path.join(STORAGE, 'candidates.jsonl');
    await withRealFilesRestored(
      [candidatesFile, path.join(STORAGE, 'distill-digest.json')],
      () => {
        const fixture = {
          id: 'runallfixture01',
          text: 'run-all fixture candidate: harvest must carry this through the merge.',
          firstSeen: '2026-08-20',
          sightingDays: ['2026-08-20'],
          tier: 0,
          client: 'test-fixture',
          tags: ['fixture']
        };
        fs.mkdirSync(STORAGE, { recursive: true });
        const existing = fs.existsSync(candidatesFile) ? fs.readFileSync(candidatesFile, 'utf8').trim() : '';
        fs.writeFileSync(candidatesFile, (existing ? existing + '\n' : '') + JSON.stringify(fixture) + '\n', 'utf8');

        const res = runHarvest();
        assert(res !== null, 'Harvest result should not be null');
        assert.strictEqual(typeof res.stats.candidatesTotal, 'number', 'candidatesTotal should be a number');
        assert(res.stats.candidatesTotal >= 1, `candidatesTotal must count the seeded fixture, got ${res.stats.candidatesTotal}`);
        assert(res.allCandidates.some(c => c.id === fixture.id), 'the seeded fixture must survive the harvest merge');
        harvestTotal = res.stats.candidatesTotal;
      }
    );
  });
  console.log(`      candidatesTotal=${harvestTotal} (1 seeded fixture + whatever this machine holds)`);

  // 11. Test Skill Metadata Parsing — fixture SKILL.md in a tmp dir, never touches
  // ~/.claude/skills (or any other real agent skills dir) or skills/definitions/.
  const { parseSkillMetadata } = require('../skills/consolidate.cjs');
  await test('Skills: parses SKILL.md frontmatter into consolidated metadata', () => {
    const tmpDir = makeTmpDir('agnostic-skill-fixture-');
    try {
      fs.writeFileSync(
        path.join(tmpDir, 'SKILL.md'),
        '---\nname: "fixture-skill"\ndescription: "A fixture skill for hermetic testing"\n---\n\nBody text.\n',
        'utf8'
      );
      const metadata = parseSkillMetadata(tmpDir, 'fixture-skill');
      assert.strictEqual(metadata.name, 'fixture-skill');
      assert.strictEqual(metadata.description, 'A fixture skill for hermetic testing');
      assert.strictEqual(metadata.hasSkillMd, true);
      assert(Array.isArray(metadata.tags), 'tags should be an array');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  // 12. Test Project Tech-Stack Analyzer — fixture project dir with a package.json,
  // never reads/writes real storage/skills-config.json or scans C:\Projects.
  const { analyzeProjectTechStack } = require('../skills/recommend.cjs');
  await test('Recommender: analyzes project tech stack from a fixture package.json', () => {
    const tmpDir = makeTmpDir('agnostic-project-fixture-');
    try {
      fs.writeFileSync(
        path.join(tmpDir, 'package.json'),
        JSON.stringify({ name: 'fixture-project', dependencies: { three: '^0.160.0', react: '^18.0.0' } }),
        'utf8'
      );
      const tech = analyzeProjectTechStack(tmpDir);
      assert.strictEqual(tech.exists, true);
      assert(tech.languages.includes('JavaScript'), 'Should detect JavaScript from package.json');
      assert(tech.frameworks.includes('React'), 'Should detect React dependency');
      assert(tech.libraries.includes('Three.js'), 'Should detect Three.js dependency');
      assert(tech.traits.includes('3d-graphics'), 'Should tag 3d-graphics trait');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  // 13. Test First-Run Setup & Default State (read-only against real storage/harness-installed.json)
  const { isFirstRun } = require('../setup/first-run.cjs');
  await test('First-Run Setup: verifies installation state and default harness status', () => {
    const firstRun = isFirstRun();
    assert.strictEqual(typeof firstRun, 'boolean', 'isFirstRun should return boolean');
  });

  // 14. Test Candidate Update & Tombstoned Deletion — real storage/candidates.jsonl
  // and distill-digest.json are restored afterward regardless of outcome.
  const { getCandidate, updateCandidate, deleteCandidate, loadDeletedIds } = require('../harvest/harvest.cjs');
  await test('Candidates: supports editing message and permanent tombstone deletion', async () => {
    await withRealFilesRestored(
      [path.join(STORAGE, 'candidates.jsonl'), path.join(STORAGE, 'distill-digest.json')],
      () => {
        const { loadAllCandidatesMap } = require('../harvest/harvest.cjs');
        const testId = 'test-cand-001';
        const testText = 'Temporary testing observation for deletion verification';
        const map = loadAllCandidatesMap();
        map.set(testId, {
          id: testId,
          text: testText,
          tier: 0,
          kind: 'deviation',
          bucket: 'testing',
          firstSeen: '2026-08-18',
          sightingDays: ['2026-08-18'],
          tags: ['test']
        });
        const CANDIDATES_FILE = path.join(STORAGE, 'candidates.jsonl');
        fs.mkdirSync(STORAGE, { recursive: true });
        fs.writeFileSync(CANDIDATES_FILE, Array.from(map.values()).map(v => JSON.stringify(v)).join('\n') + '\n');

        const fetched = getCandidate(testId);
        assert(fetched !== null, 'Should find test candidate');
        const updated = updateCandidate(testId, { text: 'Updated test observation message', tier: 1 });
        assert.strictEqual(updated.text, 'Updated test observation message');
        assert.strictEqual(updated.tier, 1);

        const delRes = deleteCandidate(testId);
        assert.strictEqual(delRes.success, true);
        assert.strictEqual(getCandidate(testId), null, 'Candidate should be deleted from candidates.jsonl');
        const deletedIds = loadDeletedIds();
        assert(deletedIds.has(testId), 'Candidate ID should be in tombstone deleted-candidates set');
      }
    );
  });

  // 15. Test Bloat Audit Engine (read-only against real storage/*.json — no writes)
  const { auditHarnessBloat } = require('../audit/bloat-audit.cjs');
  await test('Bloat Audit: audits tool bloat, context tax, and calculates token savings', () => {
    const audit = auditHarnessBloat();
    assert.strictEqual(typeof audit.score, 'number', 'Audit score should be a number');
    assert.strictEqual(typeof audit.skills.total, 'number', 'skills.total should be a number');
    assert(audit.tokenTax.estimatedTokenSavings >= 0, 'Should calculate estimated token savings');
    assert(Array.isArray(audit.recommendations) && audit.recommendations.length > 0, 'Should produce actionable recommendations');
  });

  // 16-18. Dashboard server hardening. Requiring dashboard.cjs must not bind a
  // port — it only serves under require.main === module.
  const dashboard = require('../../tools/dashboard/dashboard.cjs');
  const fakeReq = (headers) => ({ headers });

  await test('Dashboard Auth: rejects missing/foreign-origin tokens, accepts loopback', () => {
    const token = dashboard.SESSION_TOKEN;
    assert(typeof token === 'string' && token.length === 48, 'SESSION_TOKEN should be a 24-byte hex string');
    assert.strictEqual(dashboard.authorized(fakeReq({})), false, 'No token should be rejected');
    assert.strictEqual(dashboard.authorized(fakeReq({ 'x-dashboard-token': 'nope' })), false, 'Wrong token should be rejected');
    assert.strictEqual(
      dashboard.authorized(fakeReq({ 'x-dashboard-token': token, origin: 'https://evil.example' })),
      false,
      'Correct token from a non-loopback origin should be rejected'
    );
    assert.strictEqual(
      dashboard.authorized(fakeReq({ 'x-dashboard-token': token, origin: 'http://127.0.0.1:7842' })),
      true,
      'Correct token from a loopback origin should be accepted'
    );
    assert.strictEqual(
      dashboard.authorized(fakeReq({ 'x-dashboard-token': token })),
      true,
      'Correct token with no Origin/Referer should be accepted'
    );
  });

  await test('Dashboard Guard Simulator: verdicts come from core/safety/guards.json', () => {
    const destructive = dashboard.simulateGuard('rm -rf /', 'run_command');
    assert.strictEqual(destructive.verdict, 'REQUIRE_APPROVAL', 'rm -rf / must require human approval');
    assert(/guards\.json/.test(destructive.reason), 'Reason should name the guard source');
    const safe = dashboard.simulateGuard('ls', 'run_command');
    assert.strictEqual(safe.verdict, 'APPROVED', 'ls should be approved');
    assert.strictEqual(typeof safe.riskScore, 'number', 'riskScore should be a number');
  });

  await test('Dashboard Decisions: audit stream carries no fabricated bootstrap events', () => {
    const decisions = dashboard.getDecisionsData();
    assert(Array.isArray(decisions.recentEvents), 'recentEvents should be an array');
    assert.strictEqual(decisions.eventCount, decisions.recentEvents.length, 'eventCount should match recentEvents');
    const fabricated = ['SAFETY_SCAN', 'ENDPOINT_SYNC', 'GOVERNANCE_ACTIVE'];
    for (const evt of decisions.recentEvents) {
      assert(!fabricated.includes(evt.type), `Event type ${evt.type} asserts work that never ran`);
    }
  });

  console.log(`\n=== Tests Complete: ${passed} passed / ${failed} failed ===`);
  if (failed > 0) process.exit(1);
}

run();
