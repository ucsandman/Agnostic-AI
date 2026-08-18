#!/usr/bin/env node
/**
 * engine/distill/prune.cjs — Rule Pruning, Eviction & Conflict Detection Engine.
 *
 * Implements lessons learned from high-volume production agent deployments:
 *   1. Hard Rule Ceiling: Caps top-level principles at 5 core dispositions.
 *   2. Contradiction & Conflict Matrix: Checks candidate rules against active rules
 *      for direct oppositions (e.g. bold vs cautious, append vs replace).
 *   3. Few-Shot Migration: Rather than appending endless edge-case rules,
 *      converts nuanced operational failures into few-shot example fixtures.
 *   4. Least-Recently-Sighted Eviction: Suggests eviction or consolidation of
 *      stale/dormant rules when ceiling is reached.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const CORE_RULES_FILE = path.join(ROOT, 'core', 'rules', 'global-rules.md');
const CORE_TRAITS_FILE = path.join(ROOT, 'core', 'traits', 'traits.md');
const EXAMPLES_DIR = path.join(ROOT, 'core', 'examples');
const PRUNE_REPORT_FILE = path.join(ROOT, 'storage', 'prune-report.json');

const MAX_CORE_PRINCIPLES = 5; // Production-tested cap to prevent prompt soup

// Semantic conflict pair signatures for rule contradiction detection
const CONFLICT_HEURISTICS = [
  {
    topic: 'Autonomy vs Confirmation',
    positive: /\b(ask|confirm|prompt the user|wait for approval|stop and ask)\b/i,
    negative: /\b(autonomous|default to action|never ask|proceed without asking|bias toward action)\b/i
  },
  {
    topic: 'File Modification Strategy',
    positive: /\b(rewrite the whole file|overwrite|replace entire content)\b/i,
    negative: /\b(surgical|touch only what is needed|single contiguous block|never overwrite)\b/i
  },
  {
    topic: 'Output Verbosity',
    positive: /\b(detailed explanation|comprehensive walkthrough|deep dive)\b/i,
    negative: /\b(concise|direct|no filler|zero fluff|short plain sentences)\b/i
  },
  {
    topic: 'Dependency Addition',
    positive: /\b(install any package|add dependencies freely)\b/i,
    negative: /\b(no extra dependencies|prefer maintained dependencies|do not add frameworks)\b/i
  }
];

function ensureExamplesDir() {
  if (!fs.existsSync(EXAMPLES_DIR)) {
    fs.mkdirSync(EXAMPLES_DIR, { recursive: true });
  }
}

/**
 * Parses active principles/rules from core files.
 */
function extractActivePrinciples() {
  const principles = [];

  if (fs.existsSync(CORE_TRAITS_FILE)) {
    const text = fs.readFileSync(CORE_TRAITS_FILE, 'utf8');
    const traitBlocks = text.split(/^###\s+/m).slice(1);
    for (const b of traitBlocks) {
      const lines = b.trim().split('\n');
      const title = lines[0].replace(/^Trait\s+\d+:\s*/i, '').trim();
      principles.push({
        id: `trait-${title.toLowerCase().replace(/[^a-z0-9]/g, '-')}`,
        type: 'trait',
        title,
        text: b.trim(),
        sourceFile: 'core/traits/traits.md'
      });
    }
  }

  if (fs.existsSync(CORE_RULES_FILE)) {
    const text = fs.readFileSync(CORE_RULES_FILE, 'utf8');
    const learnedMatch = text.match(/## Learned Rules[\s\S]*$/i);
    if (learnedMatch) {
      const lines = learnedMatch[0].split('\n').filter(l => l.startsWith('- **L'));
      for (const l of lines) {
        principles.push({
          id: `learned-${principles.length + 1}`,
          type: 'learned_rule',
          title: l.slice(0, 40),
          text: l.trim(),
          sourceFile: 'core/rules/global-rules.md'
        });
      }
    }
  }

  return principles;
}

/**
 * Checks a candidate rule for direct contradiction with existing principles.
 */
function checkRuleConflicts(candidateText, activePrinciples) {
  const conflicts = [];

  for (const heuristic of CONFLICT_HEURISTICS) {
    const candidateMatchesPos = heuristic.positive.test(candidateText);
    const candidateMatchesNeg = heuristic.negative.test(candidateText);

    if (candidateMatchesPos || candidateMatchesNeg) {
      for (const p of activePrinciples) {
        const pMatchesPos = heuristic.positive.test(p.text);
        const pMatchesNeg = heuristic.negative.test(p.text);

        if ((candidateMatchesPos && pMatchesNeg) || (candidateMatchesNeg && pMatchesPos)) {
          conflicts.push({
            heuristic: heuristic.topic,
            conflictingWith: p.title,
            ruleText: p.text,
            reason: `Candidate expresses '${candidateMatchesPos ? 'positive' : 'negative'}' disposition while '${p.title}' enforces the opposing pattern.`
          });
        }
      }
    }
  }

  return conflicts;
}

/**
 * Converts a specific incident candidate into a few-shot example markdown file
 * instead of polluting the top-level global rule prompt.
 */
function pushToExamples(candidate, options = {}) {
  ensureExamplesDir();
  const filename = `${candidate.id || 'example-' + Date.now()}.json`;
  const targetPath = path.join(EXAMPLES_DIR, filename);

  const examplePayload = {
    id: candidate.id,
    title: options.title || candidate.text.slice(0, 60),
    incidentDate: candidate.firstSeen || new Date().toISOString().slice(0, 10),
    sightingDays: candidate.sightingDays || [],
    failureContext: candidate.text,
    correctPrinciple: options.suggestedPrinciple || 'Demonstrate compliance with surgical changes and deterministic verification.',
    exampleInput: options.exampleInput || `Task requiring action related to: ${candidate.text.slice(0, 50)}`,
    badBehavior: options.badBehavior || 'Agent applied rule inconsistently or introduced speculative edits.',
    expectedBehavior: options.expectedBehavior || candidate.text,
    created: new Date().toISOString()
  };

  fs.writeFileSync(targetPath, JSON.stringify(examplePayload, null, 2), 'utf8');
  return { success: true, path: targetPath, example: examplePayload };
}

/**
 * Runs rule pruning and budget audit.
 */
function auditRuleBudget(candidates = []) {
  const activePrinciples = extractActivePrinciples();
  const overCeilingCount = Math.max(0, activePrinciples.length - MAX_CORE_PRINCIPLES);

  const candidateAnalyses = [];

  for (const c of candidates) {
    const conflicts = checkRuleConflicts(c.text, activePrinciples);
    const wouldExceedCeiling = (activePrinciples.length + candidateAnalyses.filter(a => a.action === 'promote_rule').length) >= MAX_CORE_PRINCIPLES;

    let recommendation = 'promote_rule';
    let rationale = 'Healthy candidate under ceiling.';

    if (conflicts.length > 0) {
      recommendation = 'push_to_examples';
      rationale = `Detected ${conflicts.length} direct conflict(s) with existing principles: ${conflicts.map(cf => cf.conflictingWith).join(', ')}. Converted to few-shot example to avoid prompt contradiction.`;
    } else if (wouldExceedCeiling) {
      recommendation = 'push_to_examples';
      rationale = `Core principle ceiling reached (${activePrinciples.length}/${MAX_CORE_PRINCIPLES}). Converted to few-shot example fixture.`;
    } else if (c.text.length > 180) {
      recommendation = 'push_to_examples';
      rationale = 'Rule contains high specific situational detail; better served as a few-shot example than a global rule.';
    }

    candidateAnalyses.push({
      id: c.id,
      text: c.text,
      sightings: (c.sightingDays || []).length,
      conflicts,
      recommendation,
      rationale
    });
  }

  const report = {
    timestamp: new Date().toISOString(),
    activeCount: activePrinciples.length,
    ceiling: MAX_CORE_PRINCIPLES,
    status: overCeilingCount > 0 ? 'OVER_CEILING' : 'HEALTHY',
    activePrinciples,
    candidateAnalyses
  };

  if (!fs.existsSync(path.dirname(PRUNE_REPORT_FILE))) {
    fs.mkdirSync(path.dirname(PRUNE_REPORT_FILE), { recursive: true });
  }
  fs.writeFileSync(PRUNE_REPORT_FILE, JSON.stringify(report, null, 2), 'utf8');

  return report;
}

module.exports = {
  MAX_CORE_PRINCIPLES,
  extractActivePrinciples,
  checkRuleConflicts,
  pushToExamples,
  auditRuleBudget
};

if (require.main === module) {
  console.log('[Rule Pruner] Running Rule Budget & Conflict Analysis...');
  const res = auditRuleBudget();
  console.log(`Active Principles: ${res.activeCount} / ${res.ceiling}`);
}
