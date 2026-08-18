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

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

// 1. Test Sync Engine
const { compileTarget, loadSource } = require('../sync/sync.cjs');
test('Sync: loads source rules and compiles target output', () => {
  const source = loadSource();
  assert(source.rules.includes('Non-Negotiables'), 'Rules should include Non-Negotiables');
  const target = { name: 'Test Target', preamble: '# Test Header\n', dialect: 'generic' };
  const compiled = compileTarget(target, source);
  assert(compiled.startsWith('# Test Header'), 'Compiled output should start with preamble');
  assert(compiled.includes('Simplicity first'), 'Compiled output should include core rules');
});

// 2. Test Universal Hook Adapter
const { normalizePayload, formatDenial, formatApproval } = require('../hooks/universal-adapter.cjs');
test('Hooks: normalizes Claude payload', () => {
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

test('Hooks: normalizes Antigravity (agy) payload', () => {
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

test('Hooks: denial formatting per client dialect', () => {
  const agyDenial = formatDenial('agy', 'Access denied');
  assert.strictEqual(agyDenial.decision, 'deny');

  const claudeDenial = formatDenial('claude', 'Access denied');
  assert.strictEqual(claudeDenial.permissionDecision, 'deny');
});

// 3. Test Secret Guard
const { checkSecrets } = require('../hooks/secret-guard.cjs');
test('Security: blocks access to .secrets.env', () => {
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
const { runDistillation, hashFingerprint } = require('../distill/distill.cjs');
test('Distill: executes reflection pass and generates proposal', () => {
  const digest = runDistillation();
  assert(digest !== null, 'Digest should not be null');
  assert(digest.stats.candidatesTotal !== undefined, 'Digest stats should be present');
});

// 5. Test Recall Engine
const { searchMemory } = require('../../tools/recall/recall.cjs');
test('Recall: searches rules and facts', () => {
  const results = searchMemory('Simplicity');
  assert(results.length > 0, 'Should find Simplicity rule');
  assert.strictEqual(results[0].type, 'rule');
});

// 6. Test Multi-Rule Merger
const { mergeRuleFiles } = require('../ingest/merge.cjs');
test('Merge: ingests and unifies CLAUDE.md, AGENTS.md, and GEMINI.md', () => {
  const mockFiles = [
    { name: 'CLAUDE.md', content: '## Core Rules\n\n- Rule A\n\n## Learned Rules\n\n- **L1 (2026-08-10)**: First lesson' },
    { name: 'AGENTS.md', content: '## Core Rules\n\n- Rule A\n- Rule B\n\n## Learned Rules\n\n- **L2 (2026-08-12)**: Second lesson' }
  ];
  const merged = mergeRuleFiles(mockFiles);
  assert(merged.includes('Rule A'), 'Merged should contain Rule A');
  assert(merged.includes('Rule B'), 'Merged should contain Rule B');
  assert(merged.includes('L1 (2026-08-10)'), 'Merged should contain L1');
  assert(merged.includes('L2 (2026-08-12)'), 'Merged should contain L2');
});

console.log(`\n=== Tests Complete: ${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
