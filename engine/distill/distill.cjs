#!/usr/bin/env node
/**
 * distill.cjs — Automated Daily Reflection & Error Distillation Engine.
 *
 * Implements the 4-Tier Promotion Ladder & Anti-Bloat Pruning:
 *   Tier 0 · Observation (Raw sighting)
 *   Tier 1 · Fact (Repo-specific quirk, prevents repeat blunder)
 *   Tier 2 · Rule (Universal constraint: 3+ sightings on 3+ separate days, max 5 core)
 *   Tier 3 · Trait (Guiding disposition when no rule covers the case)
 *   Tier E · Few-Shot Example (Converted failure fixtures to prevent prompt soup)
 *
 * Enforces the Refusal-to-Promotion Ratio & Conflict Matrix.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');
const { auditRuleBudget, pushToExamples, MAX_CORE_PRINCIPLES } = require('./prune.cjs');

const ROOT = path.resolve(__dirname, '..', '..');
const STORAGE = process.env.AGNOSTIC_STORAGE || path.join(ROOT, 'storage');
const CANDIDATES_FILE = path.join(STORAGE, 'candidates.jsonl');
const CORRECTIONS_FILE = path.join(STORAGE, 'corrections.jsonl');
const PROPOSAL_FILE = path.join(STORAGE, 'distill-PROPOSAL.md');
const DIGEST_FILE = path.join(STORAGE, 'distill-digest.json');
const CORE_RULES_FILE = path.join(ROOT, 'core', 'rules', 'global-rules.md');
const LEARNED_HEADING = '## Learned Rules (Self-Promoted via Distillation Ladder)';

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
  const examplesMigrated = [];
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

  // 3. Collect Tier 2 Candidates
  const rawRuleCandidates = [];
  for (const [id, item] of candidates.entries()) {
    const count = item.sightingDays.length;

    // Gate 0 -> 1: Repo Fact (Single sighting with named repo context)
    if (item.tier === 0 && item.repo && count >= 1) {
      item.tier = 1;
      promotedFacts.push(item);
    }

    // Gate 1 -> 2: Universal Rule check (3+ sightings on 3+ distinct days)
    if (item.tier <= 1 && count >= 3) {
      rawRuleCandidates.push(item);
    } else if (count === 2 && item.tier === 1) {
      refusedItems.push({
        item,
        reason: 'Sighted 2 days (requires 3 distinct sighting days for Rule promotion)'
      });
    }
  }

  // 4. Run Rule Budget, Ceiling & Conflict Audit (The Pruning Step)
  const pruneAudit = auditRuleBudget(rawRuleCandidates);

  for (const analysis of pruneAudit.candidateAnalyses) {
    const item = candidates.get(analysis.id);
    if (!item) continue;

    if (analysis.recommendation === 'promote_rule') {
      if (candidateRules.length < 2) {
        item.tier = 2;
        candidateRules.push(item);
      } else {
        refusedItems.push({
          item,
          reason: 'Ceiling reached: maximum 2 rule promotions permitted per run to prevent context bloat'
        });
      }
    } else if (analysis.recommendation === 'push_to_examples') {
      const exRes = pushToExamples(item);
      examplesMigrated.push({
        item,
        path: exRes.path,
        reason: analysis.rationale
      });
    }
  }

  saveCandidates(candidates);

  // 5. Generate distill-PROPOSAL.md
  let proposalMd = `# Daily Distillation Proposal — ${today}\n\n`;
  proposalMd += `> Generated by Agnostic AI Distillation Engine. Review below and approve promotions.\n\n`;

  proposalMd += `## Health Metrics\n`;
  proposalMd += `- **Total Active Candidates:** ${candidates.size}\n`;
  proposalMd += `- **Active Core Principles:** ${pruneAudit.activeCount} / ${pruneAudit.ceiling}\n`;
  proposalMd += `- **New Observations (Tier 0):** ${observations.length}\n`;
  proposalMd += `- **Promoted to Repo Facts (Tier 1):** ${promotedFacts.length}\n`;
  proposalMd += `- **Candidates for Universal Rules (Tier 2):** ${candidateRules.length}\n`;
  proposalMd += `- **Migrated to Few-Shot Examples (Tier E):** ${examplesMigrated.length}\n`;
  proposalMd += `- **Refused / Withheld (Gating Healthy):** ${refusedItems.length}\n\n`;

  proposalMd += `## Recommended Rule Promotions (Tier 2)\n`;
  if (candidateRules.length === 0) {
    proposalMd += `*None today. (No candidate met the 3-day multi-sighting and rule ceiling gates)*\n\n`;
  } else {
    for (const r of candidateRules) {
      proposalMd += `### Proposed Rule: \`${r.text}\`\n`;
      proposalMd += `- **Sightings (${r.sightingDays.length} days):** ${r.sightingDays.join(', ')}\n`;
      proposalMd += `- **Client / Source:** ${r.client}\n`;
      proposalMd += `- **Proposed Action:** Append to \`core/rules/global-rules.md\` and run \`node engine/sync/sync.cjs\`\n\n`;
    }
  }

  proposalMd += `## Migrated to Few-Shot Examples (Anti-Bloat & Conflict Prevention)\n`;
  if (examplesMigrated.length === 0) {
    proposalMd += `*No rules converted to examples in this run.*\n\n`;
  } else {
    for (const ex of examplesMigrated) {
      proposalMd += `- **${ex.item.text}**\n  - *Reason:* ${ex.reason}\n  - *Example Fixture:* \`${path.basename(ex.path)}\`\n`;
    }
    proposalMd += `\n`;
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

  // 6. Generate JSON digest for dashboard UI
  const digest = {
    date: today,
    stats: {
      candidatesTotal: candidates.size,
      activeCorePrinciples: pruneAudit.activeCount,
      principlesCeiling: pruneAudit.ceiling,
      observationsCount: observations.length,
      promotedFactsCount: promotedFacts.length,
      candidateRulesCount: candidateRules.length,
      examplesMigratedCount: examplesMigrated.length,
      refusedCount: refusedItems.length
    },
    candidateRules,
    examplesMigrated,
    promotedFacts,
    refusedItems,
    allCandidates: Array.from(candidates.values())
  };
  fs.writeFileSync(DIGEST_FILE, JSON.stringify(digest, null, 2), 'utf8');

  console.log(`[Distill] Complete.`);
  console.log(`  - Active Principles: ${pruneAudit.activeCount} / ${pruneAudit.ceiling}`);
  console.log(`  - Migrated to Examples: ${examplesMigrated.length}`);
  console.log(`  - Proposal written: ${PROPOSAL_FILE}`);
  console.log(`  - Digest written: ${DIGEST_FILE}`);

  return digest;
}

/**
 * Closes the promotion loop: writes an approved candidate into the SSOT
 * (core/rules/global-rules.md) so `node engine/sync/sync.cjs` can fan it out.
 * Idempotent — a rule whose text is already present is never appended twice.
 */
function approveCandidate(id, rulesFile = CORE_RULES_FILE) {
  const candidates = loadCandidates();
  const item = candidates.get(id);
  if (!item) return { ok: false, reason: 'unknown-candidate', id };
  if (!fs.existsSync(rulesFile)) return { ok: false, reason: 'missing-rules-file', path: rulesFile };

  const text = String(item.text || '').trim();
  if (!text) return { ok: false, reason: 'empty-candidate-text', id };

  const md = fs.readFileSync(rulesFile, 'utf8');
  const headIdx = md.indexOf(LEARNED_HEADING);
  if (headIdx === -1) return { ok: false, reason: 'missing-learned-section', path: rulesFile };

  const today = new Date().toISOString().slice(0, 10);
  const markPromoted = () => {
    item.tier = Math.max(item.tier || 0, 2);
    item.promoted = true;
    item.promotedAt = item.promotedAt || today;
    candidates.set(id, item);
    // harvest owns the candidates+digest write path; reuse it so the dashboard
    // overview is not stale until the next harvest run.
    require('../harvest/harvest.cjs').saveCandidatesMap(candidates);
  };

  // Only the Learned Rules section counts as "already promoted" \u2014 the same words
  // appearing in the prose above it are not a promotion.
  const rest = md.slice(headIdx + LEARNED_HEADING.length);
  const nextHeadRel = rest.search(/\n##\s/);
  const insertAt = nextHeadRel === -1 ? md.length : headIdx + LEARNED_HEADING.length + nextHeadRel;

  if (md.slice(headIdx, insertAt).includes(text)) {
    markPromoted();
    return { ok: true, id, alreadyPresent: true, path: rulesFile };
  }

  const labels = md.match(/^- \*\*L(\d+)\b/gm) || [];
  const nextNumber = labels.reduce((max, l) => Math.max(max, parseInt(l.replace(/\D/g, ''), 10) || 0), 0) + 1;
  const label = `L${nextNumber}`;
  const bullet = `- **${label} (${today}) \u2014 ${text}**\n`;

  const before = md.slice(0, insertAt).replace(/\s*$/, '\n');
  const after = md.slice(insertAt).replace(/^\n+/, '');

  fs.writeFileSync(rulesFile, `${before}\n${bullet}${after ? '\n' + after : ''}`, 'utf8');
  markPromoted();
  return { ok: true, id, label, path: rulesFile, appended: bullet.trim() };
}

if (require.main === module) {
  const approveIdx = process.argv.indexOf('--approve');
  if (approveIdx !== -1) {
    const id = process.argv[approveIdx + 1];
    const rulesIdx = process.argv.indexOf('--rules-file');
    const rulesFile = rulesIdx !== -1 ? process.argv[rulesIdx + 1] : CORE_RULES_FILE;
    const res = approveCandidate(id, rulesFile);
    if (res.ok) {
      console.log(`[Distill] Approved ${id}${res.alreadyPresent ? ' (already present — no change)' : ` as ${res.label}`} -> ${res.path}`);
      console.log('  Next: node engine/sync/sync.cjs');
    } else {
      console.error(`[Distill] Approve failed for ${id}: ${res.reason}`);
    }
    process.exit(res.ok ? 0 : 1);
  }
  runDistillation();
}

module.exports = { runDistillation, hashFingerprint, approveCandidate, CORE_RULES_FILE };
