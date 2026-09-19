#!/usr/bin/env node
// security-tier-check.cjs — PreToolUse [Bash|PowerShell]
// Multi-tier command safety check based on declarative security tiers (security-tiers.json).
// Fast fail-open on non-matches; emits standard PreToolUse block if matched.
'use strict';
const fs = require('fs');
const path = require('path');

let input = '';
try {
  input = fs.readFileSync(0, 'utf8');
} catch {
  process.exit(0);
}

if (!input.trim()) process.exit(0);

let evt;
try {
  evt = JSON.parse(input);
} catch {
  process.exit(0);
}

const tool = evt.tool_name || evt.toolName || '';
if (!['Bash', 'PowerShell', 'shell', 'shell_command'].includes(tool)) {
  process.exit(0);
}

const cmd = (evt.tool_input && (evt.tool_input.command || evt.tool_input.CommandLine)) || '';
if (!cmd || typeof cmd !== 'string') process.exit(0);

const specPath = path.join(__dirname, 'security-tiers.json');
if (!fs.existsSync(specPath)) process.exit(0);

let spec;
try {
  spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
} catch {
  process.exit(0);
}

const tiers = spec.tiers || {};
const tierKeys = Object.keys(tiers).sort((a, b) => Number(b) - Number(a));

for (const tierKey of tierKeys) {
  const tier = tiers[tierKey];
  if (!tier.patterns || !Array.isArray(tier.patterns)) continue;
  for (const patStr of tier.patterns) {
    try {
      const re = new RegExp(patStr, 'i');
      if (re.test(cmd)) {
        const reason = `[Security Tier ${tierKey}: ${tier.name}] ${tier.description}. Command matches blocked pattern: ${patStr}`;
        const output = {
          hookSpecificOutput: {
            hookEventName: 'PreToolUse',
            permissionDecision: 'deny',
            permissionDecisionReason: reason
          }
        };
        process.stdout.write(JSON.stringify(output) + '\n');
        process.exit(0);
      }
    } catch {
      // Ignore invalid regex
    }
  }
}

process.exit(0);
