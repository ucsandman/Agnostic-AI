#!/usr/bin/env node
/**
 * secret-guard.cjs — Agnostic Secret Scanning Hook.
 * Scans tool invocations (commands and file paths) across Claude, Codex, agy, etc.
 */

const fs = require('fs');
const path = require('path');
const { normalizePayload, formatDenial, formatApproval } = require('./universal-adapter.cjs');

const GUARDS_CONFIG = path.resolve(__dirname, '..', '..', 'core', 'safety', 'guards.json');

// Fail-closed fallback: if guards.json is missing or unreadable, these built-in
// secret-path regexes still block the non-negotiable cases. A missing policy
// file must never mean "allow everything".
const FALLBACK_SECRET_REGEXES = [
  '(?i)(^|[\\s="\'`/\\\\(@<>:,*&|;])\\.env(rc)?\\b',
  '(?i)\\.secrets(\\.env)?\\b',
  '(?i)\\bid_(rsa|ed25519|ecdsa|dsa)\\b',
  '(?i)\\.(pem|pfx|p12|key)\\b',
  '(?i)\\bcredentials\\.json\\b',
  '(?i)\\.aws[\\\\/]credentials\\b'
];

// A denial is anything a client renders as blocked — some clients express it as
// {allowed:false} with no `decision` field, so all three shapes must be checked.
function isDeny(output) {
  return Boolean(output) && (
    output.decision === 'deny' ||
    output.permissionDecision === 'deny' ||
    output.allowed === false
  );
}

// guards.json patterns carry an inline (?i) flag that JS RegExp does not support.
function matches(pattern, subject) {
  try {
    const regex = new RegExp(pattern.replace(/^\(\?i\)/, ''), pattern.startsWith('(?i)') ? 'i' : '');
    return regex.test(subject);
  } catch (_) {
    return false; // Skip invalid regex
  }
}

function checkSecrets(normalized, config) {
  const secretConfig = config.guards?.secretScan || {};
  // Only an explicit `enabled: false` disables scanning. Undefined (e.g. a
  // missing/empty policy) must NOT switch protection off — fail closed.
  if (secretConfig.enabled === false) return { blocked: false };

  // If the loaded policy carries no secret regexes/globs (missing or malformed
  // guards.json), fall back to the built-in non-negotiable set.
  const secretPathRegexes = (secretConfig.secretPathRegexes && secretConfig.secretPathRegexes.length)
    ? secretConfig.secretPathRegexes
    : FALLBACK_SECRET_REGEXES;
  secretConfig.secretPathRegexes = secretPathRegexes;

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

  // 2. Check secret paths referenced anywhere in a command string
  //    ('cat ~/.secrets.env', 'type ~/.ssh/id_rsa' never reach targetFile).
  if (normalized.command) {
    for (const pat of secretConfig.secretPathRegexes || []) {
      if (matches(pat, normalized.command)) {
        return {
          blocked: true,
          reason: `[Agnostic Security] Command references a protected secret path: ${normalized.command}`
        };
      }
    }
  }

  // 3. Check sensitive patterns in command strings
  if (normalized.command) {
    for (const pat of secretConfig.sensitivePatterns || []) {
      if (matches(pat, normalized.command)) {
        return {
          blocked: true,
          reason: `[Agnostic Security] Detected potential live secret / token in command execution.`
        };
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
      process.exit(isDeny(output) ? 2 : 0);
    } catch (err) {
      // Unparseable hook payload: still deny if the raw text references a secret path.
      const output = handlePayload({ tool: 'bash', args: { command: buffer } });
      process.stdout.write(JSON.stringify(output) + '\n');
      process.exit(isDeny(output) ? 2 : 0);
    }
  });
}

module.exports = { handlePayload, checkSecrets };
