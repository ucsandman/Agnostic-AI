#!/usr/bin/env node
/**
 * tools/sync/parity.cjs — Agnostic Harness Parity Monitor.
 *
 * Inspects all configured targets and checks their sync status against SSOT.
 *
 * Usage:
 *   node tools/sync/parity.cjs           # Print terminal status
 *   node tools/sync/parity.cjs --open    # Serve and open interactive web dashboard
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const { exec } = require('child_process');
const { compileTarget, loadSource, expandPath } = require('../../engine/sync/sync.cjs');

const ROOT = path.resolve(__dirname, '..', '..');
const TARGETS_CONFIG = path.join(ROOT, 'core', 'templates', 'targets.json');
const HTML_FILE = path.join(__dirname, 'parity.html');

const OPEN_FLAG = process.argv.includes('--open');
const PORT = process.env.PARITY_PORT || 7845;

// POST /api/sync rewrites 18 config files under the home directory. Loopback
// binding alone does not stop a page on any site from triggering it, so it
// needs the per-process token this server injects into parity.html.
const SESSION_TOKEN = crypto.randomBytes(24).toString('hex');
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);

function authorized(req) {
  const headers = (req && req.headers) || {};
  const supplied = Buffer.from(String(headers['x-parity-token'] || ''));
  const expected = Buffer.from(SESSION_TOKEN);
  if (supplied.length !== expected.length) return false;
  if (!crypto.timingSafeEqual(supplied, expected)) return false;
  const source = headers.origin || headers.referer;
  if (source) {
    try {
      if (!LOOPBACK_HOSTS.has(new URL(source).hostname.replace(/^\[|\]$/g, ''))) return false;
    } catch (_) {
      return false;
    }
  }
  return true;
}

function getParityStatus() {
  const source = loadSource();
  const rawConfig = JSON.parse(fs.readFileSync(TARGETS_CONFIG, 'utf8'));
  const targets = rawConfig.targets || [];

  const results = targets.map(target => {
    const targetPath = expandPath(target.rulesFile);
    let inSync = false;
    let exists = false;
    let lastModified = null;

    if (fs.existsSync(targetPath)) {
      exists = true;
      const existing = fs.readFileSync(targetPath, 'utf8');
      const compiled = compileTarget(target, source);
      inSync = existing === compiled;
      try {
        lastModified = fs.statSync(targetPath).mtime.toISOString();
      } catch (_) {}
    }

    let skillsLinked = false;
    if (target.skillsDir) {
      const sPath = expandPath(target.skillsDir);
      // Honest check: only a managed symlink/junction counts as linked. A plain
      // real directory is the target's own skills folder, NOT our synced catalog.
      try {
        skillsLinked = fs.lstatSync(sPath).isSymbolicLink();
      } catch (_) {
        skillsLinked = false;
      }
    }

    return {
      id: target.id,
      name: target.name,
      category: target.category || 'Agent',
      path: targetPath,
      skillsDir: target.skillsDir ? expandPath(target.skillsDir) : null,
      skillsLinked,
      hooksConfigFile: target.hooksConfigFile ? expandPath(target.hooksConfigFile) : null,
      exists,
      inSync,
      dialect: target.dialect,
      lastModified
    };
  });

  let dashclawConfig = null;
  try {
    const { getStoredDashClawConfig } = require('../../engine/hooks/dashclaw-setup.cjs');
    dashclawConfig = getStoredDashClawConfig();
  } catch (_) {}

  return {
    timestamp: new Date().toISOString(),
    targets: results,
    total: results.length,
    inSyncCount: results.filter(r => r.inSync).length,
    staleCount: results.filter(r => !r.inSync).length,
    allInSync: results.every(r => r.inSync),
    dashclaw: dashclawConfig || { configured: false }
  };
}

function serve() {
  const server = http.createServer((req, res) => {
    if (req.url === '/api/status') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify(getParityStatus()));
    }

    if (req.url === '/api/sync' && req.method === 'POST') {
      if (!authorized(req)) {
        res.writeHead(403, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'Forbidden' }));
      }
      try {
        const { run } = require('../../engine/sync/sync.cjs');
        const syncResult = run();
        res.writeHead(200, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ success: true, result: syncResult }));
      } catch (err) {
        // A half-written target must surface as a failed sync, not a dead server.
        console.error('[Parity] Sync failed:', err);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ success: false, error: err.message }));
      }
    }

    if (req.url === '/' || req.url === '/index.html') {
      if (fs.existsSync(HTML_FILE)) {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(fs.readFileSync(HTML_FILE, 'utf8').replace('__PARITY_TOKEN__', SESSION_TOKEN));
      }
    }

    res.writeHead(404);
    res.end('Not Found');
  });

  server.listen(PORT, '127.0.0.1', () => {
    const url = `http://127.0.0.1:${PORT}`;
    console.log(`[Parity] Dashboard live at ${url}`);
    if (OPEN_FLAG) {
      const openCmd = process.platform === 'win32' ? `start ${url}` : `open ${url}`;
      exec(openCmd);
    }
  });
}

if (require.main === module) {
  if (OPEN_FLAG || process.argv.includes('--serve')) {
    serve();
  } else {
    const status = getParityStatus();
    console.log('[Agnostic Parity Status]');
    for (const t of status.targets) {
      console.log(`  ${t.inSync ? '✓' : '✗'} ${t.name.padEnd(25)} [${t.inSync ? 'IN SYNC' : 'STALE'}] -> ${t.path}`);
    }
  }
}

module.exports = { getParityStatus, authorized, SESSION_TOKEN };
