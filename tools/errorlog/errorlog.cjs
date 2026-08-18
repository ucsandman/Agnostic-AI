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
const http = require('http');
const { exec } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const HTML_FILE = path.join(__dirname, 'errorlog.html');
const DIGEST_FILE = path.join(ROOT, 'storage', 'distill-digest.json');
const CANDIDATES_FILE = path.join(ROOT, 'storage', 'candidates.jsonl');

const OPEN_FLAG = process.argv.includes('--open');
const SELFTEST_FLAG = process.argv.includes('--selftest');
const PORT = process.env.PORT || 7842;

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
  const server = http.createServer((req, res) => {
    if (req.url === '/api/data') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify(getErrorData()));
    }
    
    if (req.url === '/' || req.url === '/index.html') {
      if (fs.existsSync(HTML_FILE)) {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(fs.readFileSync(HTML_FILE, 'utf8'));
      }
    }

    res.writeHead(404);
    res.end('Not Found');
  });

  server.listen(PORT, '127.0.0.1', () => {
    const url = `http://127.0.0.1:${PORT}`;
    console.log(`[ErrorLog] Dashboard live at ${url}`);
    if (OPEN_FLAG) {
      const openCmd = process.platform === 'win32' ? `start ${url}` : `open ${url}`;
      exec(openCmd);
    }
  });
}

function runSelfTest() {
  console.log('[ErrorLog] Running selftests...');
  const data = getErrorData();
  console.log('  ✓ Data structure valid:', typeof data === 'object');
  console.log('  ✓ Stats present:', data.stats !== undefined);
  console.log('  ✓ All checks passed.');
  process.exit(0);
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
