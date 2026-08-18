#!/usr/bin/env node
/**
 * secret-guard.cjs — Agnostic Secret Scanning Hook.
 * Scans tool invocations (commands and file paths) across Claude, Codex, agy, etc.
 */

const fs = require('fs');
const path = require('path');
const { normalizePayload, formatDenial, formatApproval } = require('./universal-adapter.cjs');

const GUARDS_CONFIG = path.resolve(__dirname, '..', '..', 'core', 'safety', 'guards.json');

function checkSecrets(normalized, config) {
  const secretConfig = config.guards?.secretScan || {};
  if (!secretConfig.enabled) return { blocked: false };

  // 1. Check blocked files
  if (normalized.targetFile) {
    const target = normalized.targetFile.toLowerCase().replace(/\\/g, '/');
    for (const pattern of secretConfig.blockedFiles || []) {
      const cleanPattern = pattern.toLowerCase().replace(/\*\*\//g, '').replace(/\*/g, '');
      if (target.includes(cleanPattern)) {
        return {
          blocked: true,
          reason: `[Agnostic Security] Access to protected secret file blocked: ${normalized.targetFile}`
        };
      }
    }
  }

  // 2. Check sensitive patterns in command strings
  if (normalized.command) {
    for (const pat of secretConfig.sensitivePatterns || []) {
      try {
        const regex = new RegExp(pat.replace(/^\(\?i\)/, ''), pat.startsWith('(?i)') ? 'i' : '');
        if (regex.test(normalized.command)) {
          return {
            blocked: true,
            reason: `[Agnostic Security] Detected potential live secret / token in command execution.`
          };
        }
      } catch (err) {
        // Skip invalid regex
      }
    }
  }

  return { blocked: false };
}

function handlePayload(rawPayload) {
  let config = {};
  if (fs.existsSync(GUARDS_CONFIG)) {
    try {
      config = JSON.parse(fs.readFileSync(GUARDS_CONFIG, 'utf8'));
    } catch (_) {}
  }

  const normalized = normalizePayload(rawPayload);
  const result = checkSecrets(normalized, config);

  if (result.blocked) {
    return formatDenial(normalized.client, result.reason);
  }
  return formatApproval(normalized.client);
}

// CLI / Stdin runner
if (require.main === module) {
  let buffer = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { buffer += chunk; });
  process.stdin.on('end', () => {
    try {
      const payload = buffer.trim() ? JSON.parse(buffer) : {};
      const output = handlePayload(payload);
      process.stdout.write(JSON.stringify(output) + '\n');
      if (output.decision === 'deny' || output.permissionDecision === 'deny') {
        process.exit(2);
      }
      process.exit(0);
    } catch (err) {
      // Fail open on unparseable hook payload
      process.stdout.write(JSON.stringify({ decision: 'allow' }) + '\n');
      process.exit(0);
    }
  });
}

module.exports = { handlePayload, checkSecrets };
