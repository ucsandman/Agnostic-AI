#!/usr/bin/env node
/**
 * correction-tracker.cjs — Intercepts and logs user corrections & rejections
 * into storage/corrections.jsonl across any client.
 */

const fs = require('fs');
const path = require('path');
const { normalizePayload } = require('./universal-adapter.cjs');

const STORAGE_DIR = path.resolve(__dirname, '..', '..', 'storage');
const CORRECTIONS_FILE = path.join(STORAGE_DIR, 'corrections.jsonl');

function logCorrection(entry) {
  if (!fs.existsSync(STORAGE_DIR)) {
    fs.mkdirSync(STORAGE_DIR, { recursive: true });
  }

  const record = {
    timestamp: new Date().toISOString(),
    client: entry.client || 'unknown',
    repo: entry.repo || process.cwd(),
    correction: entry.correction || entry.text || '',
    toolName: entry.toolName || null,
    command: entry.command || null,
    resolved: false
  };

  fs.appendFileSync(CORRECTIONS_FILE, JSON.stringify(record) + '\n', 'utf8');
  return record;
}

if (require.main === module) {
  let buffer = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { buffer += chunk; });
  process.stdin.on('end', () => {
    try {
      const payload = buffer.trim() ? JSON.parse(buffer) : {};
      const normalized = normalizePayload(payload);
      if (normalized.raw.correction || normalized.raw.user_correction) {
        logCorrection({
          client: normalized.client,
          correction: normalized.raw.correction || normalized.raw.user_correction,
          toolName: normalized.toolName,
          command: normalized.command
        });
      }
    } catch (_) {}
    process.exit(0);
  });
}

module.exports = { logCorrection };
