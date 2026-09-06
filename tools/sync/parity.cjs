#!/usr/bin/env node
/**
 * tools/sync/parity.cjs — the human surface of the harness port.
 *
 * Serves the component matrix produced by engine/harness/status.cjs: for every
 * installed client, whether its rules, hooks, skills, agents, commands, MCP
 * servers and permissions match the captured source harness, plus everything
 * that could not be ported and why. Two buttons: check, and port now.
 *
 * Usage:
 *   node tools/sync/parity.cjs           # print the matrix in the terminal
 *   node tools/sync/parity.cjs --open    # serve the page and open a browser
 *   node tools/sync/parity.cjs --serve   # serve only
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const { exec } = require('child_process');

const { capture, loadRegistry, loadPort } = require('../../engine/harness/capture.cjs');
const { apply, selectTargets, formatTable } = require('../../engine/harness/apply.cjs');
const { status: harnessStatus, formatDropped, NO_BUNDLE } = require('../../engine/harness/status.cjs');

const HTML_FILE = path.join(__dirname, 'parity.html');

const OPEN_FLAG = process.argv.includes('--open');
let PORT = parseInt(process.env.PARITY_PORT || '7845', 10);

// POST /api/port rewrites config files under the home directory. Loopback
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

/** A target is "in parity" when every component the adapter supports is synced. */
function targetInSync(target) {
  if (target.status === 'source') return true;
  const supported = Object.values(target.components || {}).filter((r) => r.status !== 'unsupported');
  return supported.length > 0 && supported.every((r) => r.status === 'synced');
}

function summarise(report) {
  const targets = Object.values(report.targets || {});
  const inSyncCount = targets.filter(targetInSync).length;
  return {
    total: targets.length,
    inSyncCount,
    staleCount: targets.length - inSyncCount,
    allInSync: targets.length > 0 && inSyncCount === targets.length,
  };
}

function dashclaw() {
  try {
    const { getStoredDashClawConfig } = require('../../engine/hooks/dashclaw-setup.cjs');
    return getStoredDashClawConfig() || { configured: false };
  } catch (_) {
    return { configured: false };
  }
}

/**
 * The live report: an apply run in check mode, so nothing is written to any
 * client. Also the shape tools/dashboard/dashboard.cjs reads
 * ({ total, inSyncCount, staleCount, allInSync }).
 */
function getParityStatus() {
  const result = harnessStatus({ quiet: true });
  if (!result.report) {
    // Nothing captured yet: every selected client is out of parity, and we say
    // how many that is rather than reporting a meaningless zero.
    const selected = selectTargets(loadRegistry(os.homedir()), { port: loadPort() });
    return {
      timestamp: new Date().toISOString(),
      message: NO_BUNDLE,
      report: null,
      targets: [],
      total: selected.length,
      inSyncCount: 0,
      staleCount: selected.length,
      allInSync: false,
      dashclaw: dashclaw(),
    };
  }
  const report = result.report;
  return Object.assign({
    timestamp: report.appliedAt,
    message: null,
    report,
    targets: Object.values(report.targets),
    dashclaw: dashclaw(),
  }, summarise(report));
}

/** The "Port now" button: capture the source client, then write every target. */
function runPort() {
  const { bundle, warnings } = capture({});
  const report = apply({ bundle, quiet: true });
  return Object.assign({
    timestamp: report.appliedAt,
    message: null,
    report,
    warnings,
    targets: Object.values(report.targets),
    dashclaw: dashclaw(),
  }, summarise(report));
}

// parity.html and SESSION_TOKEN are both fixed for the life of the process:
// read and inject once, not on every request. Lazily, so requiring this module
// still touches no disk.
let cachedPage;
function renderPage() {
  if (cachedPage === undefined) {
    cachedPage = fs.existsSync(HTML_FILE)
      ? fs.readFileSync(HTML_FILE, 'utf8').replace('__PARITY_TOKEN__', SESSION_TOKEN)
      : null;
  }
  return cachedPage;
}

function serve({ port = PORT, open = OPEN_FLAG } = {}) {
  const json = (res, code, body) => {
    res.writeHead(code, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(body));
  };

  const server = http.createServer((req, res) => {
    const url = (req.url || '').split('?')[0];

    if (url === '/api/status') {
      try {
        return json(res, 200, getParityStatus());
      } catch (err) {
        console.error('[Parity] status failed:', err.message);
        return json(res, 500, { error: err.message });
      }
    }

    if (url === '/api/port' && req.method === 'POST') {
      if (!authorized(req)) return json(res, 403, { error: 'Forbidden' });
      try {
        return json(res, 200, Object.assign({ success: true }, runPort()));
      } catch (err) {
        // A half-written target must surface as a failed port, not a dead server.
        console.error('[Parity] port failed:', err.message);
        return json(res, 500, { success: false, error: err.message });
      }
    }

    if (url === '/' || url === '/index.html') {
      const page = renderPage();
      if (page !== null) {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(page);
      }
    }

    res.writeHead(404);
    res.end('Not Found');
  });

  // Another app on 7845 must not stop the monitor from coming up; walk the port
  // up and print the URL we actually got. (The dashboard does the same.)
  const firstPort = port;
  let current = port;
  server.on('error', (err) => {
    if (err.code !== 'EADDRINUSE') {
      console.error('[Parity] server error:', err.message);
      process.exit(1);
    }
    if (current - firstPort >= 10) {
      console.error(`[Parity] ports ${firstPort}-${current} are all taken by other apps.`);
      process.exit(1);
    }
    console.log(`[Parity] port ${current} belongs to another app; trying ${current + 1}.`);
    current += 1;
    server.listen(current, '127.0.0.1');
  });

  server.listen(current, '127.0.0.1', () => {
    const url = `http://127.0.0.1:${server.address().port}`;
    console.log(`[Parity] Harness port monitor live at ${url}`);
    if (open) exec(process.platform === 'win32' ? `start ${url}` : `open ${url}`);
  });

  return server;
}

if (require.main === module) {
  if (OPEN_FLAG || process.argv.includes('--serve')) {
    serve();
  } else {
    const result = getParityStatus();
    if (!result.report) {
      console.log(`[Agnostic Parity] ${result.message} (${result.total} clients waiting)`);
      process.exitCode = 1;
    } else {
      console.log(formatTable(result.report));
      console.log('');
      console.log(formatDropped(result.report));
      console.log(`\n${result.inSyncCount} of ${result.total} clients in full parity with ${result.report.source}.`);
    }
  }
}

module.exports = { getParityStatus, runPort, summarise, targetInSync, authorized, serve, SESSION_TOKEN };
