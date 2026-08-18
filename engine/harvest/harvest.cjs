#!/usr/bin/env node
/**
 * harvest.cjs — Cross-Agent Data Harvester.
 *
 * Scans all known AI agent directories for errors, corrections, lessons,
 * meditation candidates, and learned rules. Converts them into the
 * unified candidates.jsonl format consumed by the distillation engine
 * and the dashboard.
 *
 * Sources:
 *   ~/.claude/error-log/claude.jsonl     (864+ structured error entries)
 *   ~/.claude/corrections.jsonl          (user corrections to agent behavior)
 *   ~/.claude/meditations/CANDIDATES.md  (4-tier promotion ladder candidates)
 *   ~/.claude/error-log/wes.jsonl        (human-side error tracking)
 *   core/rules/global-rules.md           (learned rules section)
 *
 * Usage:
 *   node engine/harvest/harvest.cjs             # Harvest and populate
 *   node engine/harvest/harvest.cjs --dry-run   # Preview counts only
 *   node engine/harvest/harvest.cjs --stats     # Show source statistics
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..', '..');
const STORAGE = path.join(ROOT, 'storage');
const CANDIDATES_FILE = path.join(STORAGE, 'candidates.jsonl');
const DIGEST_FILE = path.join(STORAGE, 'distill-digest.json');

const HOME = os.homedir();
const DRY_RUN = process.argv.includes('--dry-run');
const STATS_ONLY = process.argv.includes('--stats');

function hashFingerprint(text) {
  const normalized = text.toLowerCase().replace(/[^a-z0-9]/g, ' ').replace(/\s+/g, ' ').trim();
  return crypto.createHash('sha256').update(normalized).digest('hex').slice(0, 16);
}

// ── Source 1: Claude error-log JSONL ──────────────────────────────────────────

function harvestClaudeErrorLog() {
  const file = path.join(HOME, '.claude', 'error-log', 'claude.jsonl');
  if (!fs.existsSync(file)) return [];

  const lines = fs.readFileSync(file, 'utf8').trim().split('\n').filter(Boolean);
  const items = [];

  for (const line of lines) {
    try {
      const entry = JSON.parse(line);
      const text = (entry.text || '').trim();
      if (!text || text.length < 10) continue;

      const fp = hashFingerprint(text);
      const day = entry.day || entry.ts?.slice(0, 10) || new Date().toISOString().slice(0, 10);

      // Map error-log kinds to tiers
      let tier = 0;
      if (entry.kind === 'deviation') tier = 0;
      if (entry.kind === 'assumption') tier = 0;
      if (entry.kind === 'correction') tier = 0;

      // Map buckets to more descriptive tags
      const bucket = entry.bucket || 'unclassified';
      const tags = [entry.kind || 'unknown', bucket].filter(Boolean);
      if (entry.repo) tags.push(entry.repo);

      items.push({
        id: fp,
        text,
        firstSeen: day,
        sightingDays: [day],
        tier,
        client: 'claude-code',
        source: 'error-log',
        kind: entry.kind || 'unknown',
        bucket,
        repo: entry.repo || null,
        tags
      });
    } catch (_) {}
  }

  return items;
}

// ── Source 2: Claude corrections JSONL ────────────────────────────────────────

function harvestClaudeCorrections() {
  const file = path.join(HOME, '.claude', 'corrections.jsonl');
  if (!fs.existsSync(file)) return [];

  const lines = fs.readFileSync(file, 'utf8').trim().split('\n').filter(Boolean);
  const items = [];

  for (const line of lines) {
    try {
      const entry = JSON.parse(line);
      const text = (entry.snippet || entry.correction || '').trim();
      if (!text || text.length < 5) continue;

      const fp = hashFingerprint(text);
      const day = entry.ts?.slice(0, 10) || new Date().toISOString().slice(0, 10);

      items.push({
        id: fp,
        text,
        firstSeen: day,
        sightingDays: [day],
        tier: 0,
        client: 'claude-code',
        source: 'corrections',
        kind: 'correction',
        bucket: entry.bucket || 'user-correction',
        repo: entry.cwd ? path.basename(entry.cwd) : null,
        tags: ['correction', entry.bucket || 'user-correction']
      });
    } catch (_) {}
  }

  return items;
}

// ── Source 3: Meditation candidates (structured markdown) ────────────────────

function harvestMeditationCandidates() {
  const file = path.join(HOME, '.claude', 'meditations', 'CANDIDATES.md');
  if (!fs.existsSync(file)) return [];

  const content = fs.readFileSync(file, 'utf8');
  const items = [];

  // Parse ### blocks into candidates
  const blocks = content.split(/^### /m).slice(1);

  for (const block of blocks) {
    const lines = block.trim().split('\n');
    const slug = lines[0].trim();

    // Extract claim
    const claimMatch = block.match(/\*\*Claim(?:\s*\([^)]*\))?:\*\*\s*(.+)/);
    const claim = claimMatch ? claimMatch[1].trim() : slug;

    // Extract tier
    const tierMatch = block.match(/\*\*Tier:\*\*\s*(\d)/);
    const tier = tierMatch ? parseInt(tierMatch[1], 10) : 0;

    // Extract status
    const statusMatch = block.match(/\*\*Status:\*\*\s*(\w+)/);
    const status = statusMatch ? statusMatch[1].trim() : 'watching';

    // Extract sighting days
    const sightingDays = [];
    const dateRegex = /(\d{4}-\d{2}-\d{2})/g;
    const sightingsSection = block.match(/\*\*Sightings:\*\*\s*([\s\S]*?)(?=\n- \*\*(?:Next gate|Tier|What)|$)/);
    if (sightingsSection) {
      let match;
      while ((match = dateRegex.exec(sightingsSection[1])) !== null) {
        if (!sightingDays.includes(match[1])) {
          sightingDays.push(match[1]);
        }
      }
    }
    // Also pull dates from RECORDED/WITHHELD entries
    const allDates = [];
    const allDateRegex = /\*\*(\d{4}-\d{2}-\d{2})/g;
    let dm;
    while ((dm = allDateRegex.exec(block)) !== null) {
      if (!allDates.includes(dm[1])) allDates.push(dm[1]);
    }
    const finalDays = allDates.length > sightingDays.length ? allDates : sightingDays;

    const fp = hashFingerprint(claim);

    items.push({
      id: fp,
      text: claim,
      slug,
      firstSeen: finalDays[0] || new Date().toISOString().slice(0, 10),
      sightingDays: finalDays,
      tier,
      status,
      client: 'all',
      source: 'meditations',
      kind: 'meditation-candidate',
      bucket: `tier-${tier}`,
      tags: ['meditation', `tier-${tier}`, status]
    });
  }

  return items;
}

// ── Source 4: Learned rules from global-rules.md ─────────────────────────────

function harvestLearnedRules() {
  const file = path.join(ROOT, 'core', 'rules', 'global-rules.md');
  if (!fs.existsSync(file)) return [];

  const content = fs.readFileSync(file, 'utf8');
  const items = [];

  // Extract learned rules section
  const learnedMatch = content.match(/## Learned Rules[\s\S]*$/m);
  if (!learnedMatch) return [];

  const ruleRegex = /- \*\*(\w+)\s*\((\d{4}-\d{2}-\d{2})\)\s*[—–-]\s*(.*?)\*\*/g;
  let match;
  while ((match = ruleRegex.exec(learnedMatch[0])) !== null) {
    const ruleId = match[1];
    const date = match[2];
    const text = match[3].trim();
    const fp = hashFingerprint(text);

    items.push({
      id: fp,
      text,
      ruleId,
      firstSeen: date,
      sightingDays: [date],
      tier: 2,
      status: 'promoted',
      client: 'all',
      source: 'learned-rules',
      kind: 'learned-rule',
      bucket: 'promoted-rule',
      tags: ['rule', 'tier-2', 'promoted', ruleId]
    });
  }

  return items;
}

// ── Source 5: Wes's error log ────────────────────────────────────────────────

function harvestWesErrorLog() {
  const file = path.join(HOME, '.claude', 'error-log', 'wes.jsonl');
  if (!fs.existsSync(file)) return [];

  const lines = fs.readFileSync(file, 'utf8').trim().split('\n').filter(Boolean);
  const items = [];

  for (const line of lines) {
    try {
      const entry = JSON.parse(line);
      if (entry.skipped) continue;

      // Extract predictions that were wrong
      if (entry.wrong && typeof entry.wrong === 'object') {
        const text = `Prediction was wrong: believed "${entry.wrong.believed}", predicted "${entry.wrong.predicted}". Wasted: ${entry.wrong.wasted}`;
        if (text.length < 20 || text.includes('test')) continue; // Skip test entries
        const fp = hashFingerprint(text);
        items.push({
          id: fp,
          text,
          firstSeen: entry.date || entry.ts?.slice(0, 10),
          sightingDays: [entry.date || entry.ts?.slice(0, 10)],
          tier: 0,
          client: 'human',
          source: 'wes-error-log',
          kind: 'human-prediction',
          bucket: 'wrong-prediction',
          tags: ['human', 'prediction', 'wrong']
        });
      }
    } catch (_) {}
  }

  return items;
}

// ── Deduplication & Merge ────────────────────────────────────────────────────

function deduplicateAndMerge(allItems) {
  const map = new Map();

  for (const item of allItems) {
    const existing = map.get(item.id);
    if (existing) {
      // Merge sighting days
      for (const day of item.sightingDays) {
        if (!existing.sightingDays.includes(day)) {
          existing.sightingDays.push(day);
        }
      }
      existing.sightingDays.sort();
      // Keep the higher tier
      if (item.tier > existing.tier) {
        existing.tier = item.tier;
        existing.status = item.status;
      }
      // Merge tags
      for (const tag of (item.tags || [])) {
        if (!existing.tags.includes(tag)) {
          existing.tags.push(tag);
        }
      }
    } else {
      map.set(item.id, { ...item });
    }
  }

  return map;
}

// ── Main ─────────────────────────────────────────────────────────────────────

function runHarvest() {
  console.log('[Harvest] Scanning agent directories for errors, lessons, and candidates...\n');

  const sources = [
    { name: 'Claude Error Log', fn: harvestClaudeErrorLog },
    { name: 'Claude Corrections', fn: harvestClaudeCorrections },
    { name: 'Meditation Candidates', fn: harvestMeditationCandidates },
    { name: 'Learned Rules', fn: harvestLearnedRules },
    { name: 'Wes Error Log', fn: harvestWesErrorLog }
  ];

  const allItems = [];

  for (const src of sources) {
    const items = src.fn();
    console.log(`  ${src.name}: ${items.length} entries`);
    allItems.push(...items);
  }

  console.log(`\n[Harvest] Total raw entries: ${allItems.length}`);

  const merged = deduplicateAndMerge(allItems);
  console.log(`[Harvest] After deduplication: ${merged.size} unique candidates`);

  // Stats by tier
  const tierCounts = [0, 0, 0, 0];
  const kindCounts = {};
  const bucketCounts = {};
  for (const item of merged.values()) {
    tierCounts[item.tier] = (tierCounts[item.tier] || 0) + 1;
    kindCounts[item.kind] = (kindCounts[item.kind] || 0) + 1;
    bucketCounts[item.bucket] = (bucketCounts[item.bucket] || 0) + 1;
  }

  console.log(`\n  By tier:`);
  console.log(`    T0 (Observations):  ${tierCounts[0]}`);
  console.log(`    T1 (Repo Facts):    ${tierCounts[1]}`);
  console.log(`    T2 (Rules):         ${tierCounts[2]}`);
  console.log(`    T3 (Traits):        ${tierCounts[3]}`);

  console.log(`\n  By kind:`);
  for (const [k, v] of Object.entries(kindCounts).sort((a, b) => b[1] - a[1])) {
    console.log(`    ${k}: ${v}`);
  }

  console.log(`\n  By bucket (top 10):`);
  const topBuckets = Object.entries(bucketCounts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  for (const [k, v] of topBuckets) {
    console.log(`    ${k}: ${v}`);
  }

  if (STATS_ONLY) {
    process.exit(0);
  }

  if (DRY_RUN) {
    console.log('\n[Harvest] Dry run — no files written.');
    process.exit(0);
  }

  // Write candidates.jsonl
  if (!fs.existsSync(STORAGE)) fs.mkdirSync(STORAGE, { recursive: true });
  const lines = Array.from(merged.values()).map(v => JSON.stringify(v));
  fs.writeFileSync(CANDIDATES_FILE, lines.join('\n') + (lines.length ? '\n' : ''), 'utf8');
  console.log(`\n[Harvest] Written: ${CANDIDATES_FILE} (${merged.size} candidates)`);

  // Update digest
  const observations = Array.from(merged.values()).filter(c => c.tier === 0);
  const facts = Array.from(merged.values()).filter(c => c.tier === 1);
  const rules = Array.from(merged.values()).filter(c => c.tier === 2);

  const digest = {
    date: new Date().toISOString().slice(0, 10),
    stats: {
      candidatesTotal: merged.size,
      observationsCount: observations.length,
      promotedFactsCount: facts.length,
      candidateRulesCount: rules.length,
      refusedCount: 0
    },
    candidateRules: rules,
    promotedFacts: facts,
    refusedItems: [],
    allCandidates: Array.from(merged.values())
  };
  fs.writeFileSync(DIGEST_FILE, JSON.stringify(digest, null, 2), 'utf8');
  console.log(`[Harvest] Written: ${DIGEST_FILE}`);

  return digest;
}

if (require.main === module) {
  runHarvest();
}

module.exports = { runHarvest, harvestClaudeErrorLog, harvestMeditationCandidates };
