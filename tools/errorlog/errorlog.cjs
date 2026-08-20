#!/usr/bin/env node
/**
 * tools/errorlog/errorlog.cjs — Agnostic Error & Lesson Harvester.
 *
 * Deterministically harvests errors, deviations, corrections, and pattern clusters
 * across all AI agent sessions.
 *
 * Usage:
 *   node tools/errorlog/errorlog.cjs             # Aggregate recent logs and render HTML
 *   node tools/errorlog/errorlog.cjs --open      # Serve and open browser UI
 *   node tools/errorlog/errorlog.cjs --selftest  # Run built-in test suite
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const DIGEST_FILE = path.join(ROOT, 'storage', 'distill-digest.json');
const CANDIDATES_FILE = path.join(ROOT, 'storage', 'candidates.jsonl');

const OPEN_FLAG = process.argv.includes('--open');
const SELFTEST_FLAG = process.argv.includes('--selftest');

function getErrorData() {
  let digest = {
    date: new Date().toISOString().slice(0, 10),
    stats: { candidatesTotal: 0, observationsCount: 0, promotedFactsCount: 0, candidateRulesCount: 0, refusedCount: 0 },
    candidateRules: [],
    promotedFacts: [],
    refusedItems: [],
    allCandidates: []
  };

  if (fs.existsSync(DIGEST_FILE)) {
    try {
      digest = JSON.parse(fs.readFileSync(DIGEST_FILE, 'utf8'));
    } catch (_) {}
  } else if (fs.existsSync(CANDIDATES_FILE)) {
    const lines = fs.readFileSync(CANDIDATES_FILE, 'utf8').trim().split('\n').filter(Boolean);
    digest.allCandidates = lines.map(l => {
      try { return JSON.parse(l); } catch (_) { return null; }
    }).filter(Boolean);
    digest.stats.candidatesTotal = digest.allCandidates.length;
  }

  return digest;
}

function serveDashboard() {
  const { serveDashboard: runUnifiedDashboard } = require('../dashboard/dashboard.cjs');
  runUnifiedDashboard();
}

function runSelfTest() {
  console.log('[ErrorLog] Running selftests...');
  const data = getErrorData();
  // assert, not console.log: a printed "✓ false" is a pass that reports a failure.
  assert(data && typeof data === 'object', 'getErrorData should return an object');
  assert(data.stats !== undefined, 'digest should carry a stats block');
  assert(typeof data.stats.candidatesTotal === 'number', 'stats.candidatesTotal should be a number');
  const loaded = Array.isArray(data.allCandidates) ? data.allCandidates.length : 0;
  console.log(`[ErrorLog] selftest OK: 3 checks, ${loaded} candidates loaded`);
}

if (SELFTEST_FLAG) {
  runSelfTest();
} else if (OPEN_FLAG || process.argv.includes('--serve')) {
  serveDashboard();
} else {
  console.log('[ErrorLog] Aggregated data snapshot:');
  console.log(JSON.stringify(getErrorData().stats, null, 2));
}

module.exports = { getErrorData };
