#!/usr/bin/env node
/**
 * engine/sync/claude-md.cjs — assemble the Claude Code CLAUDE.md from its two sources.
 *
 * CLAUDE.md has ONE writer: this step of `npm run sync`. It is built from
 *   1. the @import of the compiled rules file (core/rules -> agnostic-rules.md),
 *   2. <claude home>/overlay/profile.md: the private profile (who the operator is,
 *      their ALWAYS/NEVER lines, machine notes). Optional; a public install has none.
 *   3. foreign marker blocks another tool owns and this step preserves verbatim
 *      (today: declick's `<!-- declick:start -->` ... `<!-- declick:end -->`).
 *
 *   node engine/sync/claude-md.cjs            # write when changed (backup kept)
 *   node engine/sync/claude-md.cjs --check    # exit 1 when CLAUDE.md is not what sync would write
 *
 * Anything else in CLAUDE.md is lost on the next sync, on purpose: hand edits go
 * in overlay/profile.md, rules go in core/rules/global-rules.md.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const PRESERVED = [['<!-- declick:start -->', '<!-- declick:end -->']];
const HEADER = '<!-- agnostic:generated — assembled by `npm run sync` (agnostic-ai engine/sync/claude-md.cjs) from core/rules (the @import) and overlay/profile.md. Edit those; this file is overwritten. -->';

function claudeHome(home = os.homedir()) {
  return process.env.CLAUDE_CONFIG_DIR ? path.resolve(process.env.CLAUDE_CONFIG_DIR) : path.join(home, '.claude');
}

function preservedBlocks(existing) {
  const out = [];
  for (const [start, end] of PRESERVED) {
    const i = existing.indexOf(start);
    const j = i >= 0 ? existing.indexOf(end, i) : -1;
    if (i >= 0 && j >= 0) out.push(existing.slice(i, j + end.length));
  }
  return out;
}

function assemble({ home = os.homedir(), rulesFile, existing = '' } = {}) {
  const chome = claudeHome(home);
  const rules = rulesFile || path.join(chome, 'agnostic-rules.md');
  const profilePath = path.join(chome, 'overlay', 'profile.md');
  const profile = fs.existsSync(profilePath) ? fs.readFileSync(profilePath, 'utf8').replace(/\r\n/g, '\n').trim() : '';
  const parts = [HEADER, '', `@${rules.replace(/\\/g, '/')}`, ''];
  if (profile) parts.push('<!-- agnostic:profile -->', profile, '<!-- /agnostic:profile -->', '');
  for (const b of preservedBlocks(existing)) parts.push(b, '');
  return parts.join('\n').replace(/\n{3,}/g, '\n\n');
}

function run({ home = os.homedir(), check = false } = {}) {
  const chome = claudeHome(home);
  const file = path.join(chome, 'CLAUDE.md');
  const existing = fs.existsSync(file) ? fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n') : '';
  const wanted = assemble({ home, existing });
  if (existing === wanted) return { file, status: 'unchanged' };
  if (check) return { file, status: 'stale' };
  if (existing) {
    const bak = path.join(chome, 'backups', `CLAUDE.md-${new Date().toISOString().replace(/[:.]/g, '-')}.bak`);
    fs.mkdirSync(path.dirname(bak), { recursive: true });
    fs.writeFileSync(bak, existing, 'utf8');
  }
  fs.writeFileSync(file, wanted, 'utf8');
  return { file, status: existing ? 'updated' : 'created' };
}

if (require.main === module) {
  const r = run({ check: process.argv.includes('--check') });
  console.log(`CLAUDE.md: ${r.status}  (${r.file})`);
  process.exit(r.status === 'stale' ? 1 : 0);
}

module.exports = { run, assemble, claudeHome, PRESERVED };
