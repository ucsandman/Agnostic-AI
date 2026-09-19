#!/usr/bin/env node
/**
 * task-contract — validate a TASK_CONTRACT.md, and optionally discharge it.
 *
 *   node task-contract.mjs <path>            validate shape only
 *   node task-contract.mjs <path> --run      also run every test-tier check
 *   node task-contract.mjs <path> --json     machine-readable result
 *
 * Exit codes are the verdict, so CI can branch on them:
 *   0  pass
 *   1  fail                (a test-tier check failed, or could not be run)
 *   2  insufficient_spec   (unresolved non_inferable item, or unconfirmable judgment item)
 *   3  malformed contract
 *
 * Note which way 2 points. insufficient_spec is not a softer 1 — it means the
 * artifact does not contain the answer, so no amount of re-reading produces one.
 * It routes to a human. A caller that treats it as success has reintroduced the
 * exact failure the contract exists to prevent.
 */

import { readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { extractYamlBlock, parseContract } from './parse.mjs';

const EDGE_CATEGORIES = new Set([
  'boundaries', 'adjacency', 'empty', 'encoding',
  'ordering', 'precision', 'idempotency', 'concurrency', 'none',
]);
const SHAPES = new Set(['numeric-range', 'collection', 'text', 'stateful', 'io']);
const DISPOSITIONS = new Set(['specify', 'backstop', 'dismiss', 'defer']);
const TIERS = new Set(['test', 'judgment']);

function asList(v) {
  if (v == null) return [];
  return Array.isArray(v) ? v : [v];
}

export function validate(doc) {
  const errors = [];
  const seen = new Set();

  if (doc.contract_version !== 1) errors.push('contract_version must be 1');
  if (!doc.subject) errors.push('subject is required');

  const musts = asList(doc.must_haves);
  if (musts.length === 0) {
    errors.push('must_haves is empty — a contract with no obligations verifies nothing');
  }

  for (const it of musts) {
    const id = it.id || '(no id)';
    if (!/^MH-\d+$/.test(String(it.id || ''))) errors.push(`${id}: id must match MH-<n>`);
    if (seen.has(it.id)) errors.push(`${id}: duplicate id`);
    seen.add(it.id);

    if (!it.requirement) errors.push(`${id}: requirement is required`);
    const shapes = asList(it.shape);
    if (shapes.length === 0) errors.push(`${id}: shape is required`);
    for (const s of shapes) {
      if (!SHAPES.has(s)) errors.push(`${id}: unknown shape "${s}"`);
    }
    if (!EDGE_CATEGORIES.has(it.edge_category)) errors.push(`${id}: unknown edge_category "${it.edge_category}"`);
    if (!DISPOSITIONS.has(it.disposition)) errors.push(`${id}: unknown disposition "${it.disposition}"`);
    if (!TIERS.has(it.tier)) errors.push(`${id}: unknown tier "${it.tier}"`);
    if (typeof it.non_inferable !== 'boolean') errors.push(`${id}: non_inferable must be true or false`);

    if (it.tier === 'test' && !it.check) {
      errors.push(`${id}: tier "test" requires a runnable check`);
    }
    if ((it.disposition === 'dismiss' || it.disposition === 'defer') && !it.reason) {
      errors.push(`${id}: disposition "${it.disposition}" requires a reason`);
    }
    // A backstop exists precisely because prose could not carry the edge.
    if (it.disposition === 'backstop' && it.non_inferable !== true) {
      errors.push(`${id}: disposition "backstop" implies non_inferable: true`);
    }
  }

  for (const p of asList(doc.prohibitions)) {
    const id = p.id || '(no id)';
    if (!/^PR-\d+$/.test(String(p.id || ''))) errors.push(`${id}: id must match PR-<n>`);
    if (seen.has(p.id)) errors.push(`${id}: duplicate id`);
    seen.add(p.id);
    if (!p.must_not) errors.push(`${id}: must_not is required`);
    if (!TIERS.has(p.tier)) errors.push(`${id}: unknown tier "${p.tier}"`);
    // Scope, not negation, is what makes a prohibition hard: it quantifies over
    // the repository while any one review samples it. So a test-tier prohibition
    // owes a repo-wide rule, and a judgment-tier one owes an explanation of why
    // no such rule exists.
    if (p.tier === 'test' && !p.repo_check) {
      errors.push(`${id}: tier "test" requires a repo_check (repo-wide rule, not a sampled review)`);
    }
    if (p.tier === 'judgment' && !p.reason) {
      errors.push(`${id}: tier "judgment" requires a reason naming why no repo_check exists`);
    }
  }

  for (const q of asList(doc.open_questions)) {
    const id = q.id || '(no id)';
    if (!/^OQ-\d+$/.test(String(q.id || ''))) errors.push(`${id}: id must match OQ-<n>`);
    if (!q.question) errors.push(`${id}: question is required`);
    for (const ref of asList(q.blocks)) {
      if (!seen.has(ref)) errors.push(`${id}: blocks unknown item "${ref}"`);
    }
  }

  return errors;
}

/**
 * Items that cannot be discharged by any check, and so must abstain.
 *
 * One line per item, not per reason. An item that is both non-inferable and
 * deferred is one thing a person has to decide, and listing it twice makes a
 * contract look worse than it is — which is its own way of training people to
 * skim past the abstentions.
 */
export function abstentions(doc) {
  const out = [];
  const seen = new Set();
  const add = (id, why) => {
    if (seen.has(id)) return;
    seen.add(id);
    out.push({ id, why });
  };
  for (const it of asList(doc.must_haves)) {
    // The exogenous tag. Anything non-inferable that was not resolved into an
    // explicit criterion is, by construction, something the verifier has no
    // basis to judge.
    if (it.non_inferable === true && it.disposition !== 'specify') {
      add(it.id, `non_inferable and dispositioned "${it.disposition}", not specified`);
    }
    if (it.tier === 'judgment' && it.disposition === 'defer') {
      add(it.id, 'judgment-tier item deferred — no mechanical check can settle it');
    }
  }
  for (const p of asList(doc.prohibitions)) {
    if (p.tier === 'judgment') {
      add(p.id, 'judgment-tier prohibition — no repo-wide rule, needs a human');
    }
  }
  return out;
}

function runOne(id, command, cwd, results) {
  try {
    execSync(command, { cwd, stdio: 'pipe', timeout: 10 * 60 * 1000 });
    results.push({ id, check: command, ok: true });
  } catch (err) {
    // Fail closed. A check that could not be RUN is indistinguishable from a
    // check that ran and failed, as far as what we know about the code.
    const ran = typeof err.status === 'number';
    results.push({
      id,
      check: command,
      ok: false,
      ran,
      detail: ran ? `exit ${err.status}` : `could not run: ${String(err.message).split('\n')[0]}`,
    });
  }
}

function runChecks(doc, cwd) {
  const results = [];
  for (const it of asList(doc.must_haves)) {
    if (it.tier === 'test' && it.check) runOne(it.id, it.check, cwd, results);
  }
  for (const p of asList(doc.prohibitions)) {
    if (p.tier === 'test' && p.repo_check) runOne(p.id, p.repo_check, cwd, results);
  }
  return results;
}

function main() {
  const args = process.argv.slice(2);
  const path = args.find((a) => !a.startsWith('--'));
  const doRun = args.includes('--run');
  const asJson = args.includes('--json');

  if (!path) {
    console.error('usage: task-contract <TASK_CONTRACT.md> [--run] [--json]');
    process.exit(3);
  }

  let doc;
  try {
    doc = parseContract(extractYamlBlock(readFileSync(path, 'utf8')));
  } catch (err) {
    if (asJson) console.log(JSON.stringify({ verdict: 'malformed', error: err.message }, null, 2));
    else console.error(`MALFORMED  ${path}\n  ${err.message}`);
    process.exit(3);
  }

  const errors = validate(doc);
  if (errors.length) {
    if (asJson) {
      console.log(JSON.stringify({ verdict: 'malformed', errors }, null, 2));
    } else {
      console.error(`MALFORMED  ${path}  (${errors.length} schema error${errors.length === 1 ? '' : 's'})`);
      for (const e of errors) console.error(`  - ${e}`);
    }
    process.exit(3);
  }

  const abstain = abstentions(doc);
  const checks = doRun ? runChecks(doc, dirname(resolve(path))) : [];
  const failed = checks.filter((c) => !c.ok);

  // Order matters. A hard failure outranks an abstention: we know something is
  // wrong, which is more actionable than knowing we cannot tell.
  let verdict = 'pass';
  if (failed.length) verdict = 'fail';
  else if (abstain.length) verdict = 'insufficient_spec';

  const testTier = asList(doc.must_haves).filter((i) => i.tier === 'test').length
    + asList(doc.prohibitions).filter((p) => p.tier === 'test').length;

  if (asJson) {
    console.log(JSON.stringify({
      verdict,
      subject: doc.subject,
      checks,
      abstentions: abstain,
      counts: {
        must_haves: asList(doc.must_haves).length,
        prohibitions: asList(doc.prohibitions).length,
        test_tier: testTier,
        ran: checks.length,
      },
    }, null, 2));
  } else {
    // Every verdict carries the volume it processed — an OK from an instrument
    // that touched nothing reads identically to a clean run otherwise.
    console.log(`${verdict.toUpperCase()}  ${doc.subject}`);
    console.log(`  must_haves=${asList(doc.must_haves).length} prohibitions=${asList(doc.prohibitions).length} test_tier=${testTier} checks_run=${checks.length}`);
    for (const c of failed) console.log(`  FAIL  ${c.id}: ${c.detail}  [${c.check}]`);
    for (const a of abstain) console.log(`  ABSTAIN  ${a.id}: ${a.why}`);
    if (verdict === 'insufficient_spec') {
      console.log('  -> human_needed. This is not a pass. The artifact does not contain the answer.');
    }
    if (doRun && testTier > 0 && checks.length === 0) {
      console.log('  note: test-tier items exist but no check ran.');
    }
  }

  process.exit(verdict === 'pass' ? 0 : verdict === 'fail' ? 1 : 2);
}

// Only run as a CLI. The validator and the abstention rule are imported by the
// test suite, and by any repo that wants to enforce the contract in-process.
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  main();
}
