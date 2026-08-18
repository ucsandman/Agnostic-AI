#!/usr/bin/env node
/**
 * distill.cjs — Automated Daily Reflection & Error Distillation Engine.
 *
 * Implements the 4-Tier Promotion Ladder:
 *   Tier 0 · Observation (Raw sighting)
 *   Tier 1 · Fact (Repo-specific quirk, prevents repeat blunder)
 *   Tier 2 · Rule (Universal constraint: 3+ sightings on 3+ separate days)
 *   Tier 3 · Trait (Guiding disposition when no rule covers the case)
 *
 * Enforces the Refusal-to-Promotion Ratio to prevent instruction bloat.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');

const ROOT = path.resolve(__dirname, '..', '..');
const STORAGE = path.join(ROOT, 'storage');
const CANDIDATES_FILE = path.join(STORAGE, 'candidates.jsonl');
const CORRECTIONS_FILE = path.join(STORAGE, 'corrections.jsonl');
const PROPOSAL_FILE = path.join(STORAGE, 'distill-PROPOSAL.md');
const DIGEST_FILE = path.join(STORAGE, 'distill-digest.json');

function hashFingerprint(text) {
  const normalized = text.toLowerCase().replace(/[^a-z0-9]/g, ' ').replace(/\s+/g, ' ').trim();
  return crypto.createHash('sha256').update(normalized).digest('hex').slice(0, 16);
}

function loadCandidates() {
  if (!fs.existsSync(CANDIDATES_FILE)) return new Map();
  const lines = fs.readFileSync(CANDIDATES_FILE, 'utf8').trim().split('\n').filter(Boolean);
  const map = new Map();
  for (const line of lines) {
    try {
      const item = JSON.parse(line);
      map.set(item.id, item);
    } catch (_) {}
  }
  return map;
}

function saveCandidates(map) {
  if (!fs.existsSync(STORAGE)) fs.mkdirSync(STORAGE, { recursive: true });
  const lines = Array.from(map.values()).map(v => JSON.stringify(v));
  fs.writeFileSync(CANDIDATES_FILE, lines.join('\n') + (lines.length ? '\n' : ''), 'utf8');
}

function harvestCorrections() {
  if (!fs.existsSync(CORRECTIONS_FILE)) return [];
  const lines = fs.readFileSync(CORRECTIONS_FILE, 'utf8').trim().split('\n').filter(Boolean);
  const events = [];
  for (const line of lines) {
    try {
      events.push(JSON.parse(line));
    } catch (_) {}
  }
  return events;
}

function harvestRepoErrors() {
  const errors = [];
  const errorsMd = path.join(ROOT, 'docs', 'ERRORS.md');
  if (fs.existsSync(errorsMd)) {
    const content = fs.readFileSync(errorsMd, 'utf8');
    const sections = content.split(/^###\s+/m).slice(1);
    for (const sec of sections) {
      const lines = sec.trim().split('\n');
      const title = lines[0];
      errors.push({
        type: 'documented_error',
        title,
        text: sec,
        date: new Date().toISOString().slice(0, 10)
      });
    }
  }
  return errors;
}

function runDistillation() {
  const today = new Date().toISOString().slice(0, 10);
  console.log(`[Distill] Starting daily self-maintenance run for ${today}...`);

  const candidates = loadCandidates();
  const corrections = harvestCorrections();
  const repoErrors = harvestRepoErrors();

  const observations = [];
  const promotedFacts = [];
  const candidateRules = [];
  const refusedItems = [];

  // 1. Process Corrections
  for (const cor of corrections) {
    const fp = hashFingerprint(cor.correction);
    const existing = candidates.get(fp) || {
      id: fp,
      text: cor.correction,
      firstSeen: today,
      sightingDays: [],
      tier: 0,
      client: cor.client,
      repo: cor.repo
    };

    if (!existing.sightingDays.includes(today)) {
      existing.sightingDays.push(today);
    }
    candidates.set(fp, existing);
    observations.push(existing);
  }

  // 2. Process Documented Errors
  for (const err of repoErrors) {
    const fp = hashFingerprint(err.title);
    const existing = candidates.get(fp) || {
      id: fp,
      text: err.title,
      firstSeen: today,
      sightingDays: [],
      tier: 0,
      client: 'all'
    };
    if (!existing.sightingDays.includes(today)) {
      existing.sightingDays.push(today);
    }
    candidates.set(fp, existing);
  }

  // 3. Evaluate Ladder Gates
  for (const [id, item] of candidates.entries()) {
    const count = item.sightingDays.length;

    // Gate 0 -> 1: Repo Fact (Single sighting with named repo context)
    if (item.tier === 0 && item.repo && count >= 1) {
      item.tier = 1;
      promotedFacts.push(item);
    }

    // Gate 1 -> 2: Universal Rule (3+ sightings on 3+ distinct days)
    if (item.tier <= 1 && count >= 3) {
      if (candidateRules.length < 2) { // Max 2 rule promotions per run ceiling
        item.tier = 2;
        candidateRules.push(item);
      } else {
        refusedItems.push({
          item,
          reason: 'Ceiling reached: maximum 2 rule promotions permitted per run to prevent context bloat'
        });
      }
    } else if (count === 2 && item.tier === 1) {
      refusedItems.push({
        item,
        reason: 'Sighted 2 days (requires 3 distinct sighting days for Rule promotion)'
      });
    }
  }

  saveCandidates(candidates);

  // 4. Generate distill-PROPOSAL.md
  let proposalMd = `# Daily Distillation Proposal — ${today}\n\n`;
  proposalMd += `> Generated by Agnostic AI Distillation Engine. Review below and approve promotions.\n\n`;

  proposalMd += `## Health Metrics\n`;
  proposalMd += `- **Total Active Candidates:** ${candidates.size}\n`;
  proposalMd += `- **New Observations (Tier 0):** ${observations.length}\n`;
  proposalMd += `- **Promoted to Repo Facts (Tier 1):** ${promotedFacts.length}\n`;
  proposalMd += `- **Candidates for Universal Rules (Tier 2):** ${candidateRules.length}\n`;
  proposalMd += `- **Refused / Withheld (Gating Healthy):** ${refusedItems.length}\n\n`;

  proposalMd += `## Recommended Rule Promotions (Tier 2)\n`;
  if (candidateRules.length === 0) {
    proposalMd += `*None today. (No candidate has met the 3-day multi-sighting gate)*\n\n`;
  } else {
    for (const r of candidateRules) {
      proposalMd += `### Proposed Rule: \`${r.text}\`\n`;
      proposalMd += `- **Sightings (${r.sightingDays.length} days):** ${r.sightingDays.join(', ')}\n`;
      proposalMd += `- **Client / Source:** ${r.client}\n`;
      proposalMd += `- **Proposed Action:** Append to \`core/rules/global-rules.md\` and run \`node engine/sync/sync.cjs\`\n\n`;
    }
  }

  proposalMd += `## Refused Candidates & Gated Checks\n`;
  if (refusedItems.length === 0) {
    proposalMd += `*No candidates currently pending gate review.*\n\n`;
  } else {
    for (const ref of refusedItems) {
      proposalMd += `- **${ref.item.text}**: REFUSED (${ref.reason})\n`;
    }
    proposalMd += `\n`;
  }

  fs.writeFileSync(PROPOSAL_FILE, proposalMd, 'utf8');

  // 5. Generate JSON digest for dashboard UI
  const digest = {
    date: today,
    stats: {
      candidatesTotal: candidates.size,
      observationsCount: observations.length,
      promotedFactsCount: promotedFacts.length,
      candidateRulesCount: candidateRules.length,
      refusedCount: refusedItems.length
    },
    candidateRules,
    promotedFacts,
    refusedItems,
    allCandidates: Array.from(candidates.values())
  };
  fs.writeFileSync(DIGEST_FILE, JSON.stringify(digest, null, 2), 'utf8');

  console.log(`[Distill] Complete.`);
  console.log(`  - Proposal written: ${PROPOSAL_FILE}`);
  console.log(`  - Digest written: ${DIGEST_FILE}`);

  return digest;
}

if (require.main === module) {
  runDistillation();
}

module.exports = { runDistillation, hashFingerprint };
