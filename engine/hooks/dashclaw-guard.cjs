#!/usr/bin/env node
/**
 * engine/hooks/dashclaw-guard.cjs — Agnostic DashClaw Governed Autonomy Hook.
 *
 * Integrates DashClaw's remote approval and risk scoring layer with any AI agent.
 * Catches destructive or high-risk tool calls (git force push, db drops, deletions)
 * before execution and holds for remote approval via DashClaw (web/phone/Telegram).
 *
 * Falls back gracefully to local guard rules if DashClaw is not running.
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const os = require('os');
const { normalizePayload, formatDenial, formatApproval } = require('./universal-adapter.cjs');

const { getStoredDashClawConfig, discoverDashClawSources } = require('./dashclaw-setup.cjs');

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

function calculateLocalRisk(normalized) {
  const cmd = (normalized.command || '').toLowerCase();
  const file = (normalized.targetFile || '').toLowerCase();

  // High risk triggers (80-100)
  if (cmd.includes('drop table') || cmd.includes('rmdir /s') || cmd.includes('rm -rf /') || cmd.includes('git push --force') || cmd.includes('git reset --hard')) {
    return 90;
  }
  // Medium risk triggers (50-79)
  if (cmd.includes('npm publish') || cmd.includes('vercel --prod') || cmd.includes('stripe') || file.includes('.env')) {
    return 65;
  }
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

async function handleGuard(rawPayload) {
  const normalized = normalizePayload(rawPayload);
  const dcConfig = getDashClawConfig();

  // Local risk check
  const risk = calculateLocalRisk(normalized);

  // If DashClaw is active, query DashClaw
  if (dcConfig.enabled && risk >= 50) {
    const dcResponse = await queryDashClawGuard(dcConfig, normalized);
    if (dcResponse && dcResponse.decision === 'block') {
      return formatDenial(
        normalized.client,
        `[DashClaw Guard] Blocked action (Risk: ${dcResponse.risk || risk}). Reason: ${dcResponse.reason || 'High risk policy violation'}`
      );
    }
  }

  // Fallback to local hard-stop rules
  if (risk >= 90 && !process.env.ALLOW_HIGH_RISK) {
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
      process.stdout.write(JSON.stringify(result) + '\n');
      if (result.decision === 'deny' || result.permissionDecision === 'deny' || result.allowed === false) {
        process.exit(2);
      }
      process.exit(0);
    } catch (err) {
      process.stdout.write(JSON.stringify({ decision: 'allow' }) + '\n');
      process.exit(0);
    }
  });
}

module.exports = { handleGuard, calculateLocalRisk, getDashClawConfig };
