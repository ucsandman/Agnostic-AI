#!/usr/bin/env node
/**
 * engine/audit/bloat-audit.cjs — Harness Bloat Audit & Context Optimizer.
 *
 * Implements the Subtraction Principle and Tool-Cliff Prevention:
 *   - Audits global skill context tax vs JIT per-project scoping
 *   - Identifies stale single-sighting T0 observations for archiving
 *   - Computes live token savings & bloat health score
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const STORAGE = path.join(ROOT, 'storage');
const SKILLS_CONFIG_FILE = path.join(STORAGE, 'skills-config.json');
const SKILLS_MANIFEST_FILE = path.join(STORAGE, 'skills-manifest.json');
const CANDIDATES_FILE = path.join(STORAGE, 'candidates.jsonl');
const DIGEST_FILE = path.join(STORAGE, 'distill-digest.json');
const DELETED_FILE = path.join(STORAGE, 'deleted-candidates.json');

// Universal Core Skills that are safe/recommended to keep globally enabled
const UNIVERSAL_CORE_SKILLS = new Set([
  'blindspot',
  'harden',
  'wes-voice',
  'dashclaw-governance',
  'preflight',
  'secrets',
  'install-anti-slop',
  'dashclaw-platform-intelligence'
]);

function loadJsonSafe(filePath, fallback = {}) {
  if (!fs.existsSync(filePath)) return fallback;
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (_) {
    return fallback;
  }
}

function auditHarnessBloat() {
  const manifest = loadJsonSafe(SKILLS_MANIFEST_FILE, {});
  const config = loadJsonSafe(SKILLS_CONFIG_FILE, { globalEnabled: {}, projectOverrides: {} });
  const digest = loadJsonSafe(DIGEST_FILE, {});

  const totalSkills = Object.keys(manifest).length || 99;
  const globalEnabledSkills = Object.entries(config.globalEnabled || {})
    .filter(([_, enabled]) => Boolean(enabled))
    .map(([id]) => id);

  const nonUniversalGlobalSkills = globalEnabledSkills.filter(id => !UNIVERSAL_CORE_SKILLS.has(id));

  // Load candidates
  let candidates = [];
  if (fs.existsSync(CANDIDATES_FILE)) {
    const lines = fs.readFileSync(CANDIDATES_FILE, 'utf8').trim().split('\n').filter(Boolean);
    candidates = lines.map(l => {
      try { return JSON.parse(l); } catch (_) { return null; }
    }).filter(Boolean);
  }

  // T0 Observations analysis
  const t0Candidates = candidates.filter(c => c.tier === 0);
  const t1Facts = candidates.filter(c => c.tier === 1);
  const t2Rules = candidates.filter(c => c.tier === 2);
  const t3Traits = candidates.filter(c => c.tier === 3);

  const now = Date.now();
  const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

  const staleSingleSightingT0 = t0Candidates.filter(c => {
    const sightings = (c.sightingDays || []).length;
    if (sightings > 1) return false;
    const firstSeenDate = c.firstSeen ? new Date(c.firstSeen).getTime() : 0;
    return !firstSeenDate || (now - firstSeenDate > SEVEN_DAYS_MS);
  });

  // Calculate Token Context Tax
  // Average skill prompt schema/description ~ 180 tokens
  // Core rules & system prompt ~ 2,500 tokens
  const currentSkillTokens = globalEnabledSkills.length * 180;
  const optimizedSkillTokens = Math.min(globalEnabledSkills.length, UNIVERSAL_CORE_SKILLS.size) * 180;
  const currentTotalTokens = 2500 + currentSkillTokens;
  const optimizedTotalTokens = 2500 + optimizedSkillTokens;
  const estimatedTokenSavings = Math.max(0, currentSkillTokens - optimizedSkillTokens);
  const percentageSavings = currentTotalTokens > 0 ? Math.round((estimatedTokenSavings / currentTotalTokens) * 100) : 0;

  // Calculate Bloat Index Score (100 = perfectly lean, 0 = severe bloat)
  let bloatPenalty = 0;
  if (globalEnabledSkills.length > 20) bloatPenalty += 45;
  else if (globalEnabledSkills.length > 10) bloatPenalty += 25;

  if (staleSingleSightingT0.length > 500) bloatPenalty += 30;
  else if (staleSingleSightingT0.length > 100) bloatPenalty += 15;

  const healthScore = Math.max(10, 100 - bloatPenalty);
  const healthStatus = healthScore >= 80 ? 'Lean & Optimized' : healthScore >= 50 ? 'Moderate Context Tax' : 'High Tool & Memory Bloat';

  return {
    score: healthScore,
    status: healthStatus,
    skills: {
      total: totalSkills,
      globalEnabledCount: globalEnabledSkills.length,
      universalCoreCount: UNIVERSAL_CORE_SKILLS.size,
      nonUniversalGlobalCount: nonUniversalGlobalSkills.length,
      nonUniversalSkills: nonUniversalGlobalSkills
    },
    observations: {
      totalCandidates: candidates.length,
      t0Count: t0Candidates.length,
      t1Count: t1Facts.length,
      t2Count: t2Rules.length,
      t3Count: t3Traits.length,
      staleT0Count: staleSingleSightingT0.length,
      staleT0Ids: staleSingleSightingT0.map(c => c.id)
    },
    tokenTax: {
      currentSkillTokens,
      optimizedSkillTokens,
      currentTotalTokens,
      optimizedTotalTokens,
      estimatedTokenSavings,
      percentageSavings
    },
    recommendations: [
      {
        id: 'scope_skills_jit',
        title: 'Switch Global Skills to Just-in-Time Project Scoping',
        description: `Deactivate ${nonUniversalGlobalSkills.length} domain-specific skills from global loading. Retain only ${UNIVERSAL_CORE_SKILLS.size} universal safety/voice skills globally, and activate others via per-project recommendations.`,
        impact: `Saves ~${estimatedTokenSavings.toLocaleString()} tokens per interaction (${percentageSavings}% reduction)`,
        recommended: nonUniversalGlobalSkills.length > 0,
        defaultChecked: true
      },
      {
        id: 'purge_stale_t0',
        title: 'Archive Stale Single-Sighting T0 Observations',
        description: `Permanently tombstone ${staleSingleSightingT0.length} raw observations that occurred only once and never graduated to T1/T2 over 7+ days.`,
        impact: `Removes ${staleSingleSightingT0.length} unpromoted candidate records from memory`,
        recommended: staleSingleSightingT0.length > 0,
        defaultChecked: true
      }
    ]
  };
}

function applyBloatOptimizations(options = {}) {
  const audit = auditHarnessBloat();
  const results = {
    scopedSkillsCount: 0,
    purgedT0Count: 0,
    tokensSaved: 0,
    newHealthScore: 100
  };

  // 1. Optimize Global Skills to JIT Project Scoping
  if (options.scopeSkills !== false && audit.skills.nonUniversalGlobalCount !== 0) {
    const config = loadJsonSafe(SKILLS_CONFIG_FILE, { globalEnabled: {}, projectOverrides: {} });
    for (const skillId of Object.keys(config.globalEnabled || {})) {
      if (!UNIVERSAL_CORE_SKILLS.has(skillId)) {
        config.globalEnabled[skillId] = false;
        results.scopedSkillsCount++;
      } else {
        config.globalEnabled[skillId] = true;
      }
    }
    fs.writeFileSync(SKILLS_CONFIG_FILE, JSON.stringify(config, null, 2), 'utf8');
    results.tokensSaved += audit.tokenTax.estimatedTokenSavings;
  }

  // 2. Purge Stale T0 Observations
  if (options.purgeStaleT0 !== false && audit.observations.staleT0Ids.length > 0) {
    const { loadDeletedIds, saveDeletedId } = require('../harvest/harvest.cjs');
    const staleIdSet = new Set(audit.observations.staleT0Ids);

    let candidates = [];
    if (fs.existsSync(CANDIDATES_FILE)) {
      const lines = fs.readFileSync(CANDIDATES_FILE, 'utf8').trim().split('\n').filter(Boolean);
      candidates = lines.map(l => {
        try { return JSON.parse(l); } catch (_) { return null; }
      }).filter(Boolean);
    }

    const remaining = [];
    for (const c of candidates) {
      if (staleIdSet.has(c.id)) {
        saveDeletedId(c.id, c.text);
        results.purgedT0Count++;
      } else {
        remaining.push(c);
      }
    }

    const lines = remaining.map(v => JSON.stringify(v));
    fs.writeFileSync(CANDIDATES_FILE, lines.join('\n') + (lines.length ? '\n' : ''), 'utf8');

    // Update digest
    const observations = remaining.filter(c => c.tier === 0);
    const facts = remaining.filter(c => c.tier === 1);
    const rules = remaining.filter(c => c.tier === 2);

    const digest = {
      date: new Date().toISOString().slice(0, 10),
      stats: {
        candidatesTotal: remaining.length,
        observationsCount: observations.length,
        promotedFactsCount: facts.length,
        candidateRulesCount: rules.length,
        refusedCount: 0
      },
      candidateRules: rules,
      promotedFacts: facts,
      refusedItems: [],
      allCandidates: remaining
    };
    fs.writeFileSync(DIGEST_FILE, JSON.stringify(digest, null, 2), 'utf8');
  }

  // Re-run audit to get new score
  const newAudit = auditHarnessBloat();
  results.newHealthScore = newAudit.score;
  results.newHealthStatus = newAudit.status;

  return results;
}

if (require.main === module) {
  const applyFlag = process.argv.includes('--apply');
  if (applyFlag) {
    const res = applyBloatOptimizations();
    console.log(`[Bloat Audit] Optimization applied successfully!`);
    console.log(`  - Deactivated ${res.scopedSkillsCount} non-universal global skills (JIT scoping)`);
    console.log(`  - Purged and tombstoned ${res.purgedT0Count} stale T0 observations`);
    console.log(`  - Estimated prompt savings: ~${res.tokensSaved.toLocaleString()} tokens/request`);
    console.log(`  - New Harness Health Score: ${res.newHealthScore} / 100 (${res.newHealthStatus})`);
  } else {
    const res = auditHarnessBloat();
    console.log(`=== Agnostic AI Harness Bloat & Health Audit ===\n`);
    console.log(`Health Score:  ${res.score} / 100 [${res.status}]`);
    console.log(`Skills:        ${res.skills.globalEnabledCount} global enabled (${res.skills.nonUniversalGlobalCount} non-universal)`);
    console.log(`Observations:  ${res.observations.totalCandidates} total (${res.observations.staleT0Count} stale T0 candidates)`);
    console.log(`Token Load:    ~${res.tokenTax.currentTotalTokens.toLocaleString()} tokens/request (Optimal: ~${res.tokenTax.optimizedTotalTokens.toLocaleString()})`);
    console.log(`Potential:     Save ~${res.tokenTax.estimatedTokenSavings.toLocaleString()} tokens/request (${res.tokenTax.percentageSavings}% reduction)\n`);
    console.log(`Recommendations:`);
    for (const r of res.recommendations) {
      console.log(`  ⚡ ${r.title}`);
      console.log(`     ${r.description}`);
      console.log(`     Impact: ${r.impact}\n`);
    }
  }
}

module.exports = {
  auditHarnessBloat,
  applyBloatOptimizations,
  UNIVERSAL_CORE_SKILLS
};
