/**
 * engine/tests/fixtures/harness/build-home.cjs — fake client homes for reg-harness.cjs.
 *
 * buildClaudeHome(dir) / buildCodexHome(dir) populate a temp directory that
 * stands in for a user's real $HOME, with a realistic Claude Code / Codex CLI
 * install: rules, hooks, agents, commands, skills, mcp servers, permissions.
 *
 * Any token-looking value is built at runtime (never a literal here) so a
 * pre-commit secret scan never trips on this file.
 */

const fs = require('fs');
const path = require('path');

const fakeToken = () => 'sk-' + 'x'.repeat(24);

function writeFile(p, content) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content, 'utf8');
}

/** A tiny CommonJS hook script: reads stdin (if any), prints `{}`, exits 0. */
function noopHookSource() {
  return [
    '#!/usr/bin/env node',
    'let buf = "";',
    'process.stdin.on("data", (d) => { buf += d; });',
    'process.stdin.on("end", () => { process.stdout.write("{}"); process.exit(0); });',
    'process.stdin.resume();',
    '',
  ].join('\n');
}

// ---------------------------------------------------------------------------
// Claude Code
// ---------------------------------------------------------------------------

// Total command handlers wired into settings.json hooks below (asserted by
// reg-harness.cjs against manifest.components.hooks after capture).
const CLAUDE_HOOK_HANDLER_TOTAL = 10;

function buildClaudeHome(dir) {
  const claude = path.join(dir, '.claude');

  writeFile(path.join(claude, 'CLAUDE.md'), [
    '# CLAUDE.md',
    '',
    'This is the operating guide for the assistant working in this repository; follow it for every task.',
    '',
    '@~/.claude/agnostic-rules.md',
    '@RTK.md',
    '',
    '## How to Work',
    '',
    '- Batch tool calls before editing files.',
    '',
    '## Delegation and Model Routing',
    '',
    '- Route heavy synthesis to Opus, mechanical edits to Haiku.',
    '',
  ].join('\n'));

  writeFile(path.join(claude, 'agnostic-rules.md'), [
    '# Agnostic Rules',
    'GENERATED FILE. Source of truth is agnostic-ai/core/.',
    '',
    '## How to Work',
    '',
    '- Batch tool calls; one call per turn is the slow path.',
    '- declick first: before an MCP tool, WebFetch, a browser read, a screenshot or raw curl.',
    '',
  ].join('\n'));

  writeFile(path.join(claude, 'RTK.md'), [
    '# RTK Reference',
    '',
    'Local reference notes specific to this machine.',
    '',
  ].join('\n'));

  writeFile(path.join(claude, 'SOUL.md'), [
    '# SOUL',
    '',
    'Traits and identity notes for the agent.',
    '',
  ].join('\n'));

  // -- hooks: settings.json -------------------------------------------------
  const hooksDir = path.join(claude, 'hooks');
  const hookNames = [
    'secret-guard', 'rm-guard', 'scope-lock', 'capability-graph-guard', 'read-audit',
    'post-log', 'stop-notify', 'session-start', 'prompt-submit', 'message-display',
  ];
  for (const name of hookNames) writeFile(path.join(hooksDir, `${name}.cjs`), noopHookSource());

  const cmd = (name) => `node "${path.join(hooksDir, `${name}.cjs`)}"`;
  const handler = (name) => ({ type: 'command', command: cmd(name) });

  const settings = {
    permissions: {
      allow: ['Bash(git *)', 'Bash(npm run build)', 'Bash(npm run test:*)', 'Read(~/.zshrc)'],
      deny: ['Bash(rm -rf *)'],
    },
    hooks: {
      PreToolUse: [
        { matcher: 'Write|Edit|MultiEdit|Bash|PowerShell', hooks: [handler('secret-guard')] },
        { matcher: 'Bash', hooks: [handler('rm-guard'), handler('scope-lock')] },
        { matcher: 'Agent|Task|Workflow', hooks: [handler('capability-graph-guard')] },
        { matcher: 'Read|Glob|Grep', hooks: [handler('read-audit')] },
      ],
      PostToolUse: [{ matcher: '*', hooks: [handler('post-log')] }],
      Stop: [{ hooks: [handler('stop-notify')] }],
      SessionStart: [{ hooks: [handler('session-start')] }],
      UserPromptSubmit: [{ hooks: [handler('prompt-submit')] }],
      MessageDisplay: [{ hooks: [handler('message-display')] }],
    },
  };
  writeFile(path.join(claude, 'settings.json'), JSON.stringify(settings, null, 2) + '\n');

  // -- agents ----------------------------------------------------------------
  writeFile(path.join(claude, 'agents', 'opus-owner.md'), [
    '---',
    'name: opus-owner',
    'description: Owns architecture decisions and final review.',
    'model: opus',
    'tools: Read, Edit, Bash',
    '---',
    '',
    "Own the plan, review the diff, ship the change.",
    '',
  ].join('\n'));

  writeFile(path.join(claude, 'agents', 'advisor.md'), [
    '---',
    'name: advisor',
    'description: Read-only architecture and security advisor.',
    'model: fable',
    'tools: Read, Grep, Glob',
    '---',
    '',
    'Advise only; never edit a file.',
    '',
  ].join('\n'));

  // -- commands ----------------------------------------------------------------
  writeFile(path.join(claude, 'commands', 'wrap.md'), [
    '---',
    'description: Wrap up the session with a retro.',
    'argument-hint: [note]',
    '---',
    '',
    'Summarize what changed and the one lesson to carry forward.',
    '',
  ].join('\n'));

  writeFile(path.join(claude, 'commands', 'README.md'), [
    '# Commands',
    '',
    'Slash commands for this project. See wrap.md for an example.',
    '',
  ].join('\n'));

  // -- skills ------------------------------------------------------------------
  for (const name of ['alpha', 'beta', 'gamma']) {
    writeFile(path.join(claude, 'skills', name, 'SKILL.md'), [
      '---',
      `name: ${name}`,
      `description: ${name} skill.`,
      '---',
      '',
      `Do ${name} things.`,
      '',
    ].join('\n'));
  }
  // gamma also lives in the shared skills dir Codex reads natively.
  writeFile(path.join(dir, '.agents', 'skills', 'gamma', 'SKILL.md'), [
    '---',
    'name: gamma',
    'description: gamma skill (shared).',
    '---',
    '',
    'Do gamma things.',
    '',
  ].join('\n'));

  // -- .claude.json (mcp servers) ------------------------------------------------
  const claudeJson = {
    mcpServers: {
      docs: {
        command: 'npx',
        args: ['-y', '@upstash/context7-mcp'],
        env: { CONTEXT7_API_KEY: fakeToken(), PORT: '8080' },
      },
      remote: {
        type: 'http',
        url: 'https://example.com/mcp',
        headers: { Authorization: 'Bearer ' + fakeToken() },
      },
      events: {
        type: 'sse',
        url: 'https://example.com/events',
      },
    },
  };
  writeFile(path.join(dir, '.claude.json'), JSON.stringify(claudeJson, null, 2) + '\n');

  return dir;
}

// ---------------------------------------------------------------------------
// Codex CLI
// ---------------------------------------------------------------------------

function fwd(p) {
  return p.replace(/\\/g, '/');
}

function buildCodexHome(dir) {
  const codex = path.join(dir, '.codex');
  const codexGuard = path.join(codex, 'hooks', 'codex-guard.cjs');
  writeFile(codexGuard, noopHookSource());

  // Codex reads ~/.agents/skills natively; a skill living there must not be linked again.
  writeFile(path.join(dir, '.agents', 'skills', 'gamma', 'SKILL.md'), [
    '---', 'name: gamma', 'description: Shared skill read natively by Codex', '---', '', '# Gamma', '',
  ].join('\n'));

  writeFile(path.join(codex, 'config.toml'), [
    'model = "gpt-6-astra"',
    'model_reasoning_effort = "low"',
    '',
    '[projects."C:\\\\x"]',
    'trust_level = "trusted"',
    '',
    '[mcp_servers.existing]',
    'command = "npx"',
    'args = ["existing-server"]',
    '',
    "[hooks.state.'C:\\other\\hooks.json:pre_tool_use:0:0']",
    'hash = "deadbeef"',
    '',
    '[[hooks.PreToolUse]]',
    'matcher = "apply_patch|Bash"',
    `hooks = [{ type = "command", command = "node ${fwd(codexGuard)}" }]`,
    '',
  ].join('\n'));

  writeFile(path.join(codex, 'AGENTS.md'), [
    '# AGENTS.md',
    '',
    'Operating rules for Codex CLI in this environment.',
    '',
    '## How to Work',
    '',
    '- Keep diffs minimal and reversible.',
    '',
    '## Delegation and Model Routing',
    '',
    '- Route heavy synthesis to the strongest available model.',
    '',
  ].join('\n'));

  writeFile(path.join(codex, 'agents', 'one.toml'), [
    'name = "one"',
    'description = "A general worker agent ported from Claude."',
    'model = "gpt-5.6-terra"',
    'model_reasoning_effort = "medium"',
    'sandbox_mode = "read-only"',
    'developer_instructions = """',
    'Follow the ported instructions exactly.',
    '"""',
    '',
  ].join('\n'));

  writeFile(path.join(codex, 'prompts', 'p1.md'), [
    'Summarize the current diff and suggest a commit message.',
    '',
  ].join('\n'));

  // must be ignored: dot-prefixed system dir
  writeFile(path.join(codex, 'skills', '.system', 'x', 'SKILL.md'), [
    '---',
    'name: x',
    'description: internal system skill.',
    '---',
    '',
    'Not a real skill.',
    '',
  ].join('\n'));

  // a real (non-linked) dir that duplicates the Claude skill "beta"
  writeFile(path.join(codex, 'skills', 'beta', 'SKILL.md'), [
    '---',
    'name: beta',
    'description: Codex-native beta skill (duplicate of Claude\'s beta).',
    '---',
    '',
    'Do beta things, the Codex way.',
    '',
  ].join('\n'));

  writeFile(path.join(codex, 'rules', 'default.rules'), [
    'prefix_rule(pattern=["ls"], decision="allow")',
    'prefix_rule(pattern=["rm", "-rf"], decision="forbidden")',
    '',
  ].join('\n'));

  writeFile(path.join(codex, 'models_cache.json'), JSON.stringify({
    models: ['gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'],
  }, null, 2) + '\n');

  return dir;
}

module.exports = { buildClaudeHome, buildCodexHome, CLAUDE_HOOK_HANDLER_TOTAL, fakeToken };
