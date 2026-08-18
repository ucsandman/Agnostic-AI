#!/usr/bin/env node
/**
 * engine/skills/consolidate.cjs — Cross-Agent Skill Consolidation Engine.
 *
 * Scans all AI agent skill directories (~/.claude/skills, ~/.codex/skills,
 * ~/.gemini/config/skills, ~/.agents/skills, ~/.openhands/skills, etc.)
 * and consolidates unique, well-formed skills into the Agnostic Harness
 * repository under skills/definitions/<skill-name>/.
 *
 * Generates:
 *   - storage/skills-manifest.json  (full metadata catalog)
 *   - storage/skills-config.json    (global & per-project enable/disable state)
 *
 * Usage:
 *   node engine/skills/consolidate.cjs            # Consolidate and sync
 *   node engine/skills/consolidate.cjs --dry-run  # Preview only
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT = path.resolve(__dirname, '..', '..');
const SKILLS_DIR = path.join(ROOT, 'skills', 'definitions');
const STORAGE = path.join(ROOT, 'storage');
const MANIFEST_FILE = path.join(STORAGE, 'skills-manifest.json');
const CONFIG_FILE = path.join(STORAGE, 'skills-config.json');

const HOME = os.homedir();
const DRY_RUN = process.argv.includes('--dry-run');

// Known locations where AI agents store skills
const SOURCE_DIRS = [
  { name: 'claude', path: path.join(HOME, '.claude', 'skills') },
  { name: 'codex', path: path.join(HOME, '.codex', 'skills') },
  { name: 'gemini', path: path.join(HOME, '.gemini', 'config', 'skills') },
  { name: 'antigravity-builtin', path: path.join(HOME, '.gemini', 'antigravity-cli', 'builtin', 'skills') },
  { name: 'agents', path: path.join(HOME, '.agents', 'skills') },
  { name: 'openhands', path: path.join(HOME, '.openhands', 'skills') }
];

const IGNORED_NAMES = new Set([
  '.git', '.github', '.gitignore', '.dashclaw-local', '.offlocal',
  '.claude-plugin', '.system', 'archive', 'cache', 'node_modules'
]);

function copyDirRecursive(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function parseSkillMetadata(skillDir, skillName) {
  const skillMdPath = path.join(skillDir, 'SKILL.md');
  let name = skillName;
  let description = 'Custom AI agent skill';
  let category = 'General & Workflow';
  let tags = [];
  let rawContent = '';

  if (fs.existsSync(skillMdPath)) {
    try {
      rawContent = fs.readFileSync(skillMdPath, 'utf8');
      
      // Extract YAML frontmatter
      const fmMatch = rawContent.match(/^---\r?\n([\s\S]*?)\r?\n---/);
      if (fmMatch) {
        const fm = fmMatch[1];
        const nameMatch = fm.match(/^name:\s*(.+)$/m);
        const descMatch = fm.match(/^description:\s*(.+)$/m);
        if (nameMatch) name = nameMatch[1].trim().replace(/^["']|["']$/g, '');
        if (descMatch) description = descMatch[1].trim().replace(/^["']|["']$/g, '');
      } else {
        // Fallback: extract heading & first paragraph
        const headingMatch = rawContent.match(/^#\s+(.+)$/m);
        if (headingMatch) name = headingMatch[1].trim();
        const paraMatch = rawContent.match(/^#.+?\n+([^#\n].+)/m);
        if (paraMatch) description = paraMatch[1].trim();
      }
    } catch (_) {}
  }

  // Infer category based on name & description
  const lower = (name + ' ' + description).toLowerCase();
  if (lower.includes('design') || lower.includes('ui') || lower.includes('tailwind') || lower.includes('css') || lower.includes('color') || lower.includes('typeset')) {
    category = 'UI & Design';
  } else if (lower.includes('review') || lower.includes('audit') || lower.includes('critique') || lower.includes('verify') || lower.includes('test') || lower.includes('blindspot') || lower.includes('harden')) {
    category = 'Quality & Review';
  } else if (lower.includes('video') || lower.includes('animate') || lower.includes('animation') || lower.includes('threejs') || lower.includes('media') || lower.includes('audio')) {
    category = 'Media & Animation';
  } else if (lower.includes('dashclaw') || lower.includes('security') || lower.includes('secret') || lower.includes('auth') || lower.includes('guard')) {
    category = 'Safety & Governance';
  } else if (lower.includes('distill') || lower.includes('meditat') || lower.includes('habit') || lower.includes('soul') || lower.includes('voice')) {
    category = 'Reflection & Persona';
  } else if (lower.includes('plan') || lower.includes('lateral') || lower.includes('inversion') || lower.includes('six-hats') || lower.includes('bolder') || lower.includes('quieter')) {
    category = 'Thinking & Ideation';
  } else if (lower.includes('zustand') || lower.includes('react') || lower.includes('claude-api') || lower.includes('browser') || lower.includes('flow')) {
    category = 'Engineering & Stacks';
  }

  // Extract tags
  const words = lower.split(/[^a-z0-9_-]+/).filter(w => w.length > 3);
  tags = Array.from(new Set(words)).slice(0, 8);

  return { name, description, category, tags, hasSkillMd: fs.existsSync(skillMdPath) };
}

function consolidateSkills() {
  console.log('[Skills] Starting Cross-Agent Skill Consolidation...\n');

  if (!fs.existsSync(SKILLS_DIR)) {
    fs.mkdirSync(SKILLS_DIR, { recursive: true });
  }
  if (!fs.existsSync(STORAGE)) {
    fs.mkdirSync(STORAGE, { recursive: true });
  }

  const manifest = {};
  let existingConfig = { globalEnabled: {}, projectOverrides: {} };

  if (fs.existsSync(CONFIG_FILE)) {
    try {
      existingConfig = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
    } catch (_) {}
  }

  // Track discovered skills
  const discovered = new Map(); // id -> { name, sourcePaths: [], primarySource }

  for (const src of SOURCE_DIRS) {
    if (!fs.existsSync(src.path)) continue;
    try {
      const items = fs.readdirSync(src.path, { withFileTypes: true });
      for (const item of items) {
        if (!item.isDirectory()) continue;
        if (IGNORED_NAMES.has(item.name)) continue;

        const skillId = item.name.toLowerCase();
        const fullPath = path.join(src.path, item.name);

        if (!discovered.has(skillId)) {
          discovered.set(skillId, {
            id: skillId,
            rawName: item.name,
            sourcePaths: [fullPath],
            sourceClients: [src.name]
          });
        } else {
          const entry = discovered.get(skillId);
          entry.sourcePaths.push(fullPath);
          if (!entry.sourceClients.includes(src.name)) {
            entry.sourceClients.push(src.name);
          }
        }
      }
    } catch (err) {
      console.warn(`  [Warning] Could not scan ${src.path}: ${err.message}`);
    }
  }

  console.log(`[Skills] Discovered ${discovered.size} unique skills across all agent locations.`);

  let copiedCount = 0;
  for (const [id, info] of discovered.entries()) {
    const destDir = path.join(SKILLS_DIR, id);
    const primarySource = info.sourcePaths[0];

    if (!DRY_RUN) {
      if (!fs.existsSync(destDir)) {
        copyDirRecursive(primarySource, destDir);
        copiedCount++;
      } else {
        // If dest exists but is empty or missing SKILL.md, copy over
        if (!fs.existsSync(path.join(destDir, 'SKILL.md')) && fs.existsSync(path.join(primarySource, 'SKILL.md'))) {
          copyDirRecursive(primarySource, destDir);
          copiedCount++;
        }
      }
    }

    const metadata = parseSkillMetadata(fs.existsSync(destDir) ? destDir : primarySource, info.rawName);

    manifest[id] = {
      id,
      name: metadata.name,
      description: metadata.description,
      category: metadata.category,
      tags: metadata.tags,
      sources: info.sourceClients,
      installedPath: path.relative(ROOT, destDir).replace(/\\/g, '/'),
      enabled: existingConfig.globalEnabled[id] !== false // default true
    };

    if (existingConfig.globalEnabled[id] === undefined) {
      existingConfig.globalEnabled[id] = true;
    }
  }

  if (!DRY_RUN) {
    fs.writeFileSync(MANIFEST_FILE, JSON.stringify(manifest, null, 2), 'utf8');
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(existingConfig, null, 2), 'utf8');
  }

  console.log(`[Skills] Consolidated ${Object.keys(manifest).length} skills into ${SKILLS_DIR}`);
  console.log(`[Skills] Manifest updated: ${MANIFEST_FILE}`);
  console.log(`[Skills] Config updated: ${CONFIG_FILE}`);

  // Summary by category
  const catCounts = {};
  for (const skill of Object.values(manifest)) {
    catCounts[skill.category] = (catCounts[skill.category] || 0) + 1;
  }
  console.log('\n[Skills] Category Breakdown:');
  for (const [cat, count] of Object.entries(catCounts).sort((a, b) => b[1] - a[1])) {
    console.log(`  - ${cat}: ${count} skills`);
  }

  return { manifest, config: existingConfig };
}

if (require.main === module) {
  consolidateSkills();
}

module.exports = { consolidateSkills, parseSkillMetadata };
