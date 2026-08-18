#!/usr/bin/env node
/**
 * engine/tests/run-all.cjs — Comprehensive Test Runner for Agnostic AI Harness.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log('=== Running Agnostic AI Test Suite ===\n');
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

async function run() {
  // 1. Test Sync Engine
  const { compileTarget, loadSource } = require('../sync/sync.cjs');
  await test('Sync: loads source rules and compiles target output', () => {
    const source = loadSource();
    assert(source.rules.includes('Non-Negotiables'), 'Rules should include Non-Negotiables');
    const target = { name: 'Test Target', preamble: '# Test Header\n', dialect: 'generic' };
    const compiled = compileTarget(target, source);
    assert(compiled.startsWith('# Test Header'), 'Compiled output should start with preamble');
    assert(compiled.includes('Simplicity first'), 'Compiled output should include core rules');
  });

  // 2. Test Universal Hook Adapter Across All Dialects
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

  // 3. Test Secret Guard
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

  // 4. Test Distill Ladder Evaluation
  const { runDistillation } = require('../distill/distill.cjs');
  await test('Distill: executes reflection pass and generates proposal', () => {
    const digest = runDistillation();
    assert(digest !== null, 'Digest should not be null');
    assert(digest.stats.candidatesTotal !== undefined, 'Digest stats should be present');
  });

  // 5. Test Recall Engine
  const { searchMemory } = require('../../tools/recall/recall.cjs');
  await test('Recall: searches rules and facts', () => {
    const results = searchMemory('Simplicity');
    assert(results.length > 0, 'Should find Simplicity rule');
    assert.strictEqual(results[0].type, 'rule');
  });

  // 6. Test Multi-Rule Merger Across Polyglot Formats
  const { mergeRuleFiles, parseSections } = require('../ingest/merge.cjs');
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

  // 7. Test Parity Status Across All 18 Targets
  const { getParityStatus } = require('../../tools/sync/parity.cjs');
  await test('Parity: validates that all 18 configured runtimes are tracked and in sync', () => {
    const status = getParityStatus();
    assert.strictEqual(status.targets.length, 18, 'Should track exactly 18 targets');
    const targetIds = status.targets.map(t => t.id);
    const expectedIds = ['claude', 'codex', 'agy', 'cursor', 'windsurf', 'copilot', 'cline', 'aider', 'openhands', 'goose', 'continue', 'zed', 'trae', 'amazonq', 'cody', 'openclaw', 'hermes', 'generic'];
    for (const eid of expectedIds) {
      assert(targetIds.includes(eid), `Target ${eid} should be present in status`);
    }
    assert.strictEqual(status.allInSync, true, 'All targets should be in sync');
  });

  // 8. Test DashClaw Auto-Discovery & Self-Configuration
  const { discoverDashClawSources, autoConfigureDashClaw, getStoredDashClawConfig } = require('../hooks/dashclaw-setup.cjs');
  await test('DashClaw Setup: discovers instance and configures agent identity', async () => {
    const sources = discoverDashClawSources();
    assert(Array.isArray(sources), 'Should return sources array');

    const config = await autoConfigureDashClaw();
    assert(config !== null, 'Config should not be null');
    assert(config.agentId === 'agnostic-harness' || typeof config.agentId === 'string', 'Agent ID should be configured');

    const stored = getStoredDashClawConfig();
    assert(stored !== null, 'Stored config should exist after configuration');
  });

  // 9. Test DashClaw Guard & Risk Scoring
  const { calculateLocalRisk, handleGuard, getDashClawConfig } = require('../hooks/dashclaw-guard.cjs');
  await test('DashClaw Guard: calculates risk score for destructive actions', async () => {
    const dcConfig = getDashClawConfig();
    assert(dcConfig.agentId !== undefined, 'Guard config should have agentId');

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
  });

  // 10. Test Data Harvester
  const { runHarvest } = require('../harvest/harvest.cjs');
  await test('Harvester: ingests error-log, corrections, and candidates from existing agents', () => {
    const res = runHarvest();
    assert(res !== null, 'Harvest result should not be null');
    assert(res.stats.candidatesTotal >= 800, 'Should harvest 800+ candidates from agent history');
  });

  // 11. Test Skill Consolidation & Manifest
  const { consolidateSkills } = require('../skills/consolidate.cjs');
  await test('Skills: consolidates unique skills across agent dirs into harness definitions', () => {
    const { manifest } = consolidateSkills();
    const count = Object.keys(manifest).length;
    assert(count >= 50, 'Should consolidate at least 50+ unique skills');
    assert(manifest['blindspot'] !== undefined, 'Should include blindspot skill');
    assert(manifest['install-anti-slop'] !== undefined, 'Should include install-anti-slop skill');
  });

  // 12. Test Project Analyzer & Skill Recommender
  const { recommendSkillsForProject, toggleSkill, applyProjectRecommendations } = require('../skills/recommend.cjs');
  await test('Recommender: analyzes project tech stack and recommends optimal skills', () => {
    const rec = recommendSkillsForProject('C:\\Projects\\agnostic-ai');
    assert(rec.project !== null, 'Project info should exist');
    assert(rec.recommendations.length > 0, 'Should have recommendations');
    assert(rec.recommendedCount > 0, 'Should have recommended skills');

    // Test toggle
    const toggled = toggleSkill('blindspot', false, 'C:\\Projects\\agnostic-ai');
    assert.strictEqual(toggled.projectOverrides['C:\\Projects\\agnostic-ai']['blindspot'], false);
    toggleSkill('blindspot', true, 'C:\\Projects\\agnostic-ai'); // revert
  });

  // 13. Test First-Run Setup & Default State
  const { isFirstRun } = require('../setup/first-run.cjs');
  await test('First-Run Setup: verifies installation state and default harness status', () => {
    const firstRun = isFirstRun();
    assert.strictEqual(typeof firstRun, 'boolean', 'isFirstRun should return boolean');
  });

  // 14. Test Candidate Update & Tombstoned Deletion
  const { getCandidate, updateCandidate, deleteCandidate, loadDeletedIds, loadAllCandidatesMap } = require('../harvest/harvest.cjs');
  await test('Candidates: supports editing message and permanent tombstone deletion', () => {
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
    const CANDIDATES_FILE = path.join(__dirname, '..', '..', 'storage', 'candidates.jsonl');
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
  });

  // 15. Test Bloat Audit Engine
  const { auditHarnessBloat } = require('../audit/bloat-audit.cjs');
  await test('Bloat Audit: audits tool bloat, context tax, and calculates token savings', () => {
    const audit = auditHarnessBloat();
    assert(typeof audit.score === 'number', 'Audit score should be a number');
    assert(audit.skills.total >= 50, 'Should detect consolidated skills');
    assert(audit.tokenTax.estimatedTokenSavings >= 0, 'Should calculate estimated token savings');
    assert(audit.recommendations.length > 0, 'Should produce actionable recommendations');
  });

  console.log(`\n=== Tests Complete: ${passed} passed, ${failed} failed ===`);
  if (failed > 0) process.exit(1);
}

run();
