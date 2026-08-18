#!/usr/bin/env node
/**
 * engine/ingest/merge.cjs — Universal Rule & Lesson Merger.
 *
 * Automatically discovers, parses, and merges rules, lessons, and facts from:
 *   - CLAUDE.md
 *   - AGENTS.md
 *   - GEMINI.md
 *   - SYSTEM.md
 *
 * Ensures no lessons or past coding corrections from any agent session are lost,
 * regardless of whether the user used Claude Code, Codex, Antigravity (agy), or OpenClaw.
 *
 * Usage:
 *   node engine/ingest/merge.cjs                  # Merge rules in current working directory
 *   node engine/ingest/merge.cjs --global         # Merge global rules across ~/.claude, ~/.codex, ~/.gemini
 *   node engine/ingest/merge.cjs --dir <path>     # Merge rules in specific project directory
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const HOME = os.homedir();
const ROOT = path.resolve(__dirname, '..', '..');

const RULE_FILENAMES = ['CLAUDE.md', 'AGENTS.md', 'GEMINI.md', 'SYSTEM.md'];

function normalizeText(str) {
  return str.toLowerCase().replace(/[^a-z0-9]/g, ' ').replace(/\s+/g, ' ').trim();
}

function hashBullet(str) {
  return crypto.createHash('sha256').update(normalizeText(str)).digest('hex').slice(0, 16);
}

function discoverRuleFiles(targetDir) {
  const found = [];
  for (const name of RULE_FILENAMES) {
    const p = path.join(targetDir, name);
    if (fs.existsSync(p)) {
      found.push({ name, path: p, content: fs.readFileSync(p, 'utf8') });
    }
  }
  return found;
}

function discoverGlobalRuleFiles() {
  const globalPaths = [
    { name: 'CLAUDE.md', path: path.join(HOME, '.claude', 'CLAUDE.md') },
    { name: 'AGENTS.md', path: path.join(HOME, '.codex', 'AGENTS.md') },
    { name: 'GEMINI.md', path: path.join(HOME, '.gemini', 'GEMINI.md') },
    { name: 'SYSTEM.md', path: path.join(HOME, '.openclaw', 'SYSTEM.md') }
  ];

  return globalPaths.filter(g => fs.existsSync(g.path)).map(g => ({
    name: g.name,
    path: g.path,
    content: fs.readFileSync(g.path, 'utf8')
  }));
}

function parseSections(markdown) {
  const sections = new Map();
  const rawSections = markdown.split(/^##\s+/m);
  
  // Preamble or Title
  const titlePart = rawSections[0].trim();
  sections.set('__preamble__', titlePart);

  for (let i = 1; i < rawSections.length; i++) {
    const raw = rawSections[i];
    const firstLineEnd = raw.indexOf('\n');
    const title = (firstLineEnd !== -1 ? raw.slice(0, firstLineEnd) : raw).trim();
    const body = firstLineEnd !== -1 ? raw.slice(firstLineEnd + 1).trim() : '';
    sections.set(title, body);
  }

  return sections;
}

function mergeBulletList(bodyA = '', bodyB = '') {
  const bulletsA = bodyA.split('\n').map(l => l.trim()).filter(Boolean);
  const bulletsB = bodyB.split('\n').map(l => l.trim()).filter(Boolean);

  const seen = new Set();
  const merged = [];

  for (const b of [...bulletsA, ...bulletsB]) {
    // Treat sub-bullets or prose lines
    const hash = hashBullet(b);
    if (!seen.has(hash)) {
      seen.add(hash);
      merged.push(b);
    }
  }

  return merged.join('\n');
}

function mergeRuleFiles(files) {
  if (!files || files.length === 0) return null;
  if (files.length === 1) return files[0].content;

  console.log(`[Merge] Ingesting and unifying rules from ${files.length} sources: ${files.map(f => f.name).join(', ')}`);

  const masterSections = new Map();
  const learnedRulesMap = new Map();

  for (const file of files) {
    const parsed = parseSections(file.content);
    for (const [title, body] of parsed.entries()) {
      if (title === '__preamble__') continue;

      if (title.toLowerCase().includes('learned rule')) {
        // Special handling for learned rules
        const lines = body.split('\n').filter(l => l.trim().startsWith('-'));
        for (const l of lines) {
          const fp = hashBullet(l);
          if (!learnedRulesMap.has(fp)) {
            learnedRulesMap.set(fp, l);
          }
        }
        continue;
      }

      if (!masterSections.has(title)) {
        masterSections.set(title, body);
      } else {
        // Merge bodies by deduplicating bullets/paragraphs
        const existing = masterSections.get(title);
        masterSections.set(title, mergeBulletList(existing, body));
      }
    }
  }

  // Rebuild unified markdown
  const parts = [];
  parts.push(`# Universal Working Agreement (Unified Across All Agents)\n\n> Automatically merged from: ${files.map(f => f.name).join(', ')}\n`);

  for (const [title, body] of masterSections.entries()) {
    parts.push(`## ${title}\n\n${body}`);
  }

  if (learnedRulesMap.size > 0) {
    const learnedRulesBody = Array.from(learnedRulesMap.values()).join('\n\n');
    parts.push(`## Learned Rules (Self-Promoted via Distillation Ladder)\n\n${learnedRulesBody}`);
  }

  return parts.join('\n\n---\n\n') + '\n';
}

function syncProjectDirectory(targetDir) {
  const files = discoverRuleFiles(targetDir);
  if (files.length === 0) {
    console.log(`[Merge] No CLAUDE.md, AGENTS.md, or GEMINI.md found in ${targetDir}`);
    return null;
  }

  const merged = mergeRuleFiles(files);
  for (const name of ['CLAUDE.md', 'AGENTS.md', 'GEMINI.md']) {
    const p = path.join(targetDir, name);
    fs.writeFileSync(p, merged, 'utf8');
    console.log(`  ✓ Synced merged rules to: ${name}`);
  }

  return merged;
}

if (require.main === module) {
  const isGlobal = process.argv.includes('--global');
  const dirArg = process.argv.find((_, i, arr) => arr[i - 1] === '--dir') || process.cwd();

  if (isGlobal) {
    const globalFiles = discoverGlobalRuleFiles();
    const merged = mergeRuleFiles(globalFiles);
    if (merged) {
      const ssotPath = path.join(ROOT, 'core', 'rules', 'global-rules.md');
      fs.writeFileSync(ssotPath, merged, 'utf8');
      console.log(`[Merge] Global SSOT updated: ${ssotPath}`);
      // Re-trigger sync
      const { run } = require('../sync/sync.cjs');
      run();
    }
  } else {
    syncProjectDirectory(dirArg);
  }
}

module.exports = {
  discoverRuleFiles,
  discoverGlobalRuleFiles,
  parseSections,
  mergeRuleFiles,
  syncProjectDirectory
};
