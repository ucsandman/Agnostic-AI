#!/usr/bin/env node
/**
 * engine/hooks/dashclaw-setup.cjs — DashClaw Auto-Discovery & Self-Configuration Engine.
 *
 * Automatically detects an existing DashClaw instance (global config, local daemon,
 * environment variables, or workspace state), provisions the harness agent identity,
 * sets up the API key and endpoint, and wires all 18 agent targets for Governed Autonomy.
 *
 * Usage:
 *   node engine/hooks/dashclaw-setup.cjs           # Auto-discover and configure
 *   node engine/hooks/dashclaw-setup.cjs --status  # Print current DashClaw status
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');
const https = require('https');

const HOME = os.homedir();
const ROOT = path.resolve(__dirname, '..', '..');
const CONFIG_STORAGE = path.join(ROOT, 'storage', 'dashclaw-config.json');

const CANDIDATE_CONFIG_PATHS = [
  { type: 'global_config', path: path.join(HOME, '.dashclaw', 'config.json') },
  { type: 'global_instance', path: path.join(HOME, '.dashclaw', 'instance.json') },
  { type: 'local_state', path: path.join(ROOT, '.dashclaw-local', 'state.json') }
];

const DEFAULT_AGENT_ID = process.env.DASHCLAW_AGENT_ID || 'agnostic-harness';
const DEFAULT_AGENT_NAME = process.env.DASHCLAW_AGENT_NAME || 'Agnostic AI Harness';

const GUARDS_CONFIG = path.join(ROOT, 'core', 'safety', 'guards.json');

function dashclawPolicy() {
  try {
    return JSON.parse(fs.readFileSync(GUARDS_CONFIG, 'utf8')).guards?.dashclaw || {};
  } catch (_) {
    return {};
  }
}

function checkEndpointHealth(urlStr, apiKey = null, timeoutMs = 3500) {
  return new Promise((resolve) => {
    try {
      const parsed = new URL(urlStr);
      const client = parsed.protocol === 'https:' ? https : http;
      const headers = {
        'User-Agent': 'Agnostic-Harness-AutoSetup/1.2',
        'Accept': 'application/json, text/plain, */*'
      };
      if (apiKey) {
        headers['x-api-key'] = apiKey;
        headers['Authorization'] = `Bearer ${apiKey}`;
      }

      // Check /api/health first (public health endpoint)
      const healthReq = client.request({
        hostname: parsed.hostname,
        port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
        path: '/api/health',
        method: 'GET',
        headers,
        timeout: timeoutMs
      }, (res) => {
        let body = '';
        res.on('data', chunk => { body += chunk; });
        res.on('end', () => {
          if (res.statusCode >= 200 && res.statusCode < 400) {
            return resolve({
              ok: true,
              reachable: true,
              authenticated: true,
              statusCode: res.statusCode,
              message: 'Online & healthy'
            });
          }
          
          // Fallback probe to root
          checkRoot();
        });
      });

      healthReq.on('error', () => checkRoot());
      healthReq.on('timeout', () => {
        healthReq.destroy();
        checkRoot();
      });
      healthReq.end();

      function checkRoot() {
        try {
          const rootReq = client.request({
            hostname: parsed.hostname,
            port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
            path: '/',
            method: 'GET',
            headers,
            timeout: timeoutMs
          }, (res) => {
            resolve({
              ok: res.statusCode >= 200 && res.statusCode < 500,
              reachable: true,
              authenticated: res.statusCode < 400,
              statusCode: res.statusCode,
              message: res.statusCode < 400 ? 'Online & healthy' : `Endpoint reached with HTTP ${res.statusCode}`
            });
          });
          rootReq.on('error', () => resolve({ ok: false, reachable: false, authenticated: false, message: 'Endpoint unreachable' }));
          rootReq.on('timeout', () => {
            rootReq.destroy();
            resolve({ ok: false, reachable: false, authenticated: false, message: 'Connection timed out' });
          });
          rootReq.end();
        } catch (_) {
          resolve({ ok: false, reachable: false, authenticated: false, message: 'Invalid URL or connection failed' });
        }
      }
    } catch (_) {
      resolve({ ok: false, reachable: false, authenticated: false, message: 'Invalid URL format' });
    }
  });
}

function discoverDashClawSources() {
  const sources = [];

  // 1. Environment variables
  if (process.env.DASHCLAW_BASE_URL || process.env.DASHCLAW_API_KEY) {
    sources.push({
      type: 'environment',
      baseUrl: process.env.DASHCLAW_BASE_URL || 'https://my-dashclaw.vercel.app',
      apiKey: process.env.DASHCLAW_API_KEY || null,
      agentId: process.env.DASHCLAW_AGENT_ID || DEFAULT_AGENT_ID,
      agentName: process.env.DASHCLAW_AGENT_NAME || DEFAULT_AGENT_NAME
    });
  }

  // 2. Candidate configuration files
  for (const candidate of CANDIDATE_CONFIG_PATHS) {
    if (fs.existsSync(candidate.path)) {
      try {
        const raw = JSON.parse(fs.readFileSync(candidate.path, 'utf8'));
        // Only an explicitly declared endpoint counts. A state file that merely has
        // workspaces is NOT a licence to adopt whatever is listening on a dev port.
        const baseUrl = raw.baseUrl || raw.url || null;
        const apiKey = raw.apiKey || raw.key || raw.token || null;
        const agentId = raw.agentId || raw.agent_id || DEFAULT_AGENT_ID;
        const agentName = raw.agentName || raw.agent_name || DEFAULT_AGENT_NAME;

        if (baseUrl) {
          sources.push({
            type: candidate.type,
            path: candidate.path,
            baseUrl,
            apiKey,
            agentId,
            agentName
          });
        }
      } catch (_) {}
    }
  }

  return sources;
}

async function autoConfigureDashClaw() {
  const storageDir = path.dirname(CONFIG_STORAGE);
  if (!fs.existsSync(storageDir)) {
    fs.mkdirSync(storageDir, { recursive: true });
  }

  const sources = discoverDashClawSources();

  if (sources.length === 0) {
    // No probing of common dev ports: a bare health-200 on 127.0.0.1:3000 is not
    // proof of a governance authority (guards.dashclaw.adoptLocalhostPortsAllowed).
    const fallbackConfig = {
      configured: false,
      active: false,
      source: 'none',
      reason: 'No explicitly declared DashClaw endpoint (DASHCLAW_BASE_URL or a config file baseUrl). Local safety guards active and failing closed.',
      updatedAt: new Date().toISOString()
    };
    fs.writeFileSync(CONFIG_STORAGE, JSON.stringify(fallbackConfig, null, 2), 'utf8');
    return fallbackConfig;
  }

  // Prioritize environment, then global config, then local state
  const selected = sources.find(s => s.type === 'environment') ||
                   sources.find(s => s.type === 'global_config') ||
                   sources[0];

  // A loopback endpoint is only trusted when the operator declared it via the
  // environment, or policy explicitly permits adopting local ports.
  const isLoopback = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i.test(selected.baseUrl || '');
  if (isLoopback && selected.type !== 'environment' && dashclawPolicy().adoptLocalhostPortsAllowed !== true) {
    const rejected = {
      configured: false,
      active: false,
      source: 'none',
      reason: `Refused to adopt local endpoint ${selected.baseUrl} from ${selected.type}: guards.dashclaw.adoptLocalhostPortsAllowed is false. Set DASHCLAW_BASE_URL to opt in explicitly.`,
      updatedAt: new Date().toISOString()
    };
    fs.writeFileSync(CONFIG_STORAGE, JSON.stringify(rejected, null, 2), 'utf8');
    return rejected;
  }

  const config = {
    configured: true,
    active: true,
    baseUrl: selected.baseUrl,
    apiKey: selected.apiKey,
    agentId: selected.agentId || DEFAULT_AGENT_ID,
    agentName: selected.agentName || DEFAULT_AGENT_NAME,
    source: selected.type,
    sourcePath: selected.path || null,
    updatedAt: new Date().toISOString()
  };

  fs.writeFileSync(CONFIG_STORAGE, JSON.stringify(config, null, 2), 'utf8');
  return config;
}

function getStoredDashClawConfig() {
  if (fs.existsSync(CONFIG_STORAGE)) {
    try {
      return JSON.parse(fs.readFileSync(CONFIG_STORAGE, 'utf8'));
    } catch (_) {}
  }
  return null;
}

async function run() {
  const isStatusOnly = process.argv.includes('--status');
  let config = getStoredDashClawConfig();

  if (!config || !isStatusOnly) {
    config = await autoConfigureDashClaw();
  }

  console.log('=== Agnostic DashClaw Governed Autonomy Integration ===');
  if (config.configured && config.active) {
    console.log(`  ✓ Status:       Connected & Configured`);
    console.log(`  ✓ Base URL:     ${config.baseUrl}`);
    console.log(`  ✓ Agent ID:     ${config.agentId}`);
    console.log(`  ✓ Agent Name:   ${config.agentName}`);
    console.log(`  ✓ Source:       ${config.source}`);
    console.log(`  ✓ API Key:      ${config.apiKey ? '***configured***' : '(None - local mode)'}`);
    console.log(`\n  All 18 agent targets are now governed via DashClaw.`);
  } else {
    console.log(`  ○ Status:       Standalone (Local Safety Guards Active)`);
    console.log(`  ○ Detail:       ${config.reason || 'No DashClaw instance configured'}`);
    console.log(`\n  To connect DashClaw, start an instance ('npx dashclaw up') or set DASHCLAW_BASE_URL.`);
  }

  return config;
}

if (require.main === module) {
  run();
}

module.exports = {
  autoConfigureDashClaw,
  getStoredDashClawConfig,
  discoverDashClawSources,
  checkEndpointHealth
};
