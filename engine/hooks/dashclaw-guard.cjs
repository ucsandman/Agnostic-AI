#!/usr/bin/env node
/**
 * engine/hooks/dashclaw-guard.cjs — Agnostic DashClaw Governed Autonomy Hook.
 *
 * Integrates DashClaw's remote approval and risk scoring layer with any AI agent.
 * Catches destructive or high-risk tool calls (git force push, db drops, deletions)
 * before execution and holds for remote approval via DashClaw (web/phone/Telegram).
 *
 * Falls back to local guard rules (core/safety/guards.json) if DashClaw is not
 * running. That fallback fails CLOSED: an unreachable, timed-out or crashed
 * governance layer never turns a hard-stop command into an approval.
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const os = require('os');
const { normalizePayload, formatDenial, formatApproval, formatHookOutput } = require('./universal-adapter.cjs');

const { getStoredDashClawConfig, discoverDashClawSources } = require('./dashclaw-setup.cjs');
const { checkSecrets } = require('./secret-guard.cjs');

const GUARDS_CONFIG = path.resolve(__dirname, '..', '..', 'core', 'safety', 'guards.json');
const HOME = os.homedir();
const INSTANCE_FILE = path.join(HOME, '.dashclaw', 'instance.json');

function getDashClawConfig() {
  // Check stored/cached configuration first
  const stored = getStoredDashClawConfig();
  if (stored && stored.configured && stored.active) {
    return {
      enabled: true,
      baseUrl: stored.baseUrl,
      apiKey: stored.apiKey,
      agentId: stored.agentId || 'agnostic-harness',
      agentName: stored.agentName || 'Agnostic AI Harness',
      source: stored.source
    };
  }

  // Fallback discovery
  const sources = discoverDashClawSources();
  if (sources.length > 0) {
    const selected = sources[0];
    return {
      enabled: true,
      baseUrl: selected.baseUrl,
      apiKey: selected.apiKey,
      agentId: selected.agentId || 'agnostic-harness',
      agentName: selected.agentName || 'Agnostic AI Harness',
      source: selected.type
    };
  }

  return {
    enabled: false,
    baseUrl: 'https://my-dashclaw.vercel.app',
    apiKey: null,
    agentId: 'agnostic-harness',
    agentName: 'Agnostic AI Harness'
  };
}

let guardsCache = null;
function loadGuards() {
  if (guardsCache) return guardsCache;
  try {
    guardsCache = JSON.parse(fs.readFileSync(GUARDS_CONFIG, 'utf8')).guards || {};
  } catch (_) {
    guardsCache = {};
  }
  return guardsCache;
}

// guards.json patterns carry an inline (?i) flag that JS RegExp does not support.
function matchesAny(patterns, subject) {
  for (const pat of patterns || []) {
    try {
      const re = new RegExp(pat.replace(/^\(\?i\)/, ''), pat.startsWith('(?i)') ? 'i' : '');
      if (re.test(subject)) return true;
    } catch (_) {
      // Skip invalid regex
    }
  }
  return false;
}

function riskThresholds() {
  const dc = loadGuards().dashclaw || {};
  return {
    hardBlock: typeof dc.hardBlockRiskThreshold === 'number' ? dc.hardBlockRiskThreshold : 90,
    query: typeof dc.defaultRiskThreshold === 'number' ? dc.defaultRiskThreshold : 50,
    failClosed: dc.failClosed !== false
  };
}

function calculateLocalRisk(normalized) {
  const subject = `${normalized.command || ''} ${normalized.targetFile || ''}`;
  const guards = loadGuards();
  const { hardBlock, query } = riskThresholds();

  // Hard stops — anything needing explicit human approval, plus blocked process control.
  if (matchesAny(guards.hardStops?.requireApprovalPatterns, subject)) return hardBlock;
  if (matchesAny(guards.processControl?.blockedCommands, subject)) return hardBlock;

  // Secret paths anywhere in the command or target are governance-worthy, not hard stops.
  if (matchesAny(guards.secretScan?.secretPathRegexes, subject)) return query;

  return 10;
}

async function queryDashClawGuard(config, actionPayload) {
  if (!config.apiKey && !config.baseUrl.includes('localhost') && !config.baseUrl.includes('127.0.0.1')) {
    return null; // External DashClaw needs API key
  }

  return new Promise((resolve) => {
    try {
      const url = new URL('/api/guard', config.baseUrl);
      const postData = JSON.stringify({
        action: actionPayload.command || actionPayload.toolName,
        target: actionPayload.targetFile || actionPayload.repo,
        agentId: config.agentId || actionPayload.client || 'agnostic-harness',
        agentName: config.agentName || 'Agnostic AI Harness',
        clientType: actionPayload.client || 'unknown',
        risk: calculateLocalRisk(actionPayload)
      });

      const client = url.protocol === 'https:' ? https : http;
      const req = client.request(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(postData),
          ...(config.apiKey ? { 'Authorization': `Bearer ${config.apiKey}` } : {})
        },
        timeout: 3000
      }, (res) => {
        let data = '';
        res.on('data', chunk => { data += chunk; });
        res.on('end', () => {
          try {
            resolve(JSON.parse(data));
          } catch (_) {
            resolve(null);
          }
        });
      });

      req.on('error', () => resolve(null)); // Fail open/graceful on connection failure
      req.on('timeout', () => {
        req.destroy();
        resolve(null);
      });

      req.write(postData);
      req.end();
    } catch (_) {
      resolve(null);
    }
  });
}

async function handleGuard(rawPayload, deps = {}) {
  const normalized = normalizePayload(rawPayload);

  // Secret-path block first: on the flat-format targets (Codex, Gemini) this is
  // the only hook installed, so it must also enforce the never-read-secrets rule.
  try {
    let guardsConfig = {};
    if (fs.existsSync(GUARDS_CONFIG)) {
      guardsConfig = JSON.parse(fs.readFileSync(GUARDS_CONFIG, 'utf8'));
    }
    const secretResult = checkSecrets(normalized, guardsConfig);
    if (secretResult.blocked) {
      return formatDenial(normalized.client, secretResult.reason);
    }
  } catch (_) {
    // checkSecrets fails closed internally; a config read error here is non-fatal.
  }

  const { hardBlock, query, failClosed } = riskThresholds();
  const getConfig = deps.getDashClawConfig || getDashClawConfig;
  const askDashClaw = deps.queryDashClawGuard || queryDashClawGuard;

  // Unknown risk is treated as maximum risk: scoring must never fail open.
  let risk = hardBlock;
  try {
    risk = calculateLocalRisk(normalized);
  } catch (_) {}

  if (risk >= query) {
    try {
      const dcConfig = getConfig();
      if (dcConfig.enabled) {
        const dcResponse = await askDashClaw(dcConfig, normalized);
        if (dcResponse && (dcResponse.decision === 'block' || dcResponse.decision === 'require_approval')) {
          return formatDenial(
            normalized.client,
            `[DashClaw Guard] Blocked action (Risk: ${dcResponse.risk || risk}). Reason: ${dcResponse.reason || 'High risk policy violation'}`
          );
        }
        // No usable decision (unreachable, timeout, bad JSON): fail closed on hard stops.
        if (!dcResponse && failClosed && risk >= hardBlock) {
          return formatDenial(
            normalized.client,
            `[DashClaw Guard] Governance returned no decision and local risk ${risk} >= ${hardBlock}. Failing closed: ${normalized.command}`
          );
        }
      }
    } catch (err) {
      if (failClosed && risk >= hardBlock) {
        return formatDenial(
          normalized.client,
          `[DashClaw Guard] Governance check failed (${err.message}) and local risk ${risk} >= ${hardBlock}. Failing closed: ${normalized.command}`
        );
      }
    }
  }

  // Local hard-stop rules. No environment variable may disable this.
  if (risk >= hardBlock) {
    return formatDenial(
      normalized.client,
      `[Safety Guard] High-risk command requires explicit human confirmation: ${normalized.command}`
    );
  }

  return formatApproval(normalized.client);
}

if (require.main === module) {
  let buffer = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { buffer += chunk; });
  process.stdin.on('end', async () => {
    try {
      const payload = buffer.trim() ? JSON.parse(buffer) : {};
      const result = await handleGuard(payload);
      process.stdout.write(JSON.stringify(formatHookOutput(normalizePayload(payload).client, result)) + '\n');
      if (result.decision === 'deny' || result.permissionDecision === 'deny' || result.allowed === false) {
        process.stderr.write((result.reason || 'Action denied by safety policy.') + '\n');
        process.exit(2);
      }
      process.exit(0);
    } catch (err) {
      // Fail closed: an unparseable payload still gets scored as raw text.
      const { hardBlock } = riskThresholds();
      let risk = hardBlock;
      try {
        risk = calculateLocalRisk({ command: buffer });
      } catch (_) {}
      if (risk >= hardBlock) {
        const reason = `[Safety Guard] Guard hook error (${err.message}) on a high-risk payload. Failing closed.`;
        process.stdout.write(JSON.stringify({
          decision: 'deny',
          permissionDecision: 'deny',
          allowed: false,
          reason
        }) + '\n');
        process.stderr.write(reason + '\n');
        process.exit(2);
      }
      process.stdout.write('{}\n');
      process.exit(0);
    }
  });
}

module.exports = { handleGuard, calculateLocalRisk, getDashClawConfig, riskThresholds };
