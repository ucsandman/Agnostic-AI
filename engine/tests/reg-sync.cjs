#!/usr/bin/env node
/**
 * reg-sync.cjs — Regression tests for the promotion + sync loop.
 *
 * Covers:
 *   1. distill --approve appends a rule to global-rules.md and is idempotent.
 *   2. sync run() backs up a hand-edited (drifted) target instead of destroying it.
 *   3. harvest merge preserves an existing tier-2 promotion across a re-harvest.
 *   4. linkSkillsDirectory reports the honest state for an unmanaged skills dir.
 *
 * Every test runs against temp paths. Nothing here touches the real
 * core/rules/global-rules.md, storage/, or any home-directory target.
 */

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-'));
const TMP_STORAGE = path.join(TMP, 'storage');
fs.mkdirSync(TMP_STORAGE, { recursive: true });

// Redirect engine storage before anything is required.
process.env.AGNOSTIC_STORAGE = TMP_STORAGE;
process.env.AGNOSTIC_EXAMPLES_DIR = path.join(TMP, 'examples');

const { approveCandidate } = require('../distill/distill.cjs');
const { run, linkSkillsDirectory, compileTarget } = require('../sync/sync.cjs');
const { deduplicateAndMerge } = require('../harvest/harvest.cjs');
const { pushToExamples } = require('../distill/prune.cjs');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  ✓ ${name}`);
  } catch (err) {
    failed++;
    console.log(`  ✗ ${name}`);
    console.log(`      ${err && err.message}`);
  }
}

function writeCandidates(items) {
  fs.writeFileSync(
    path.join(TMP_STORAGE, 'candidates.jsonl'),
    items.map(i => JSON.stringify(i)).join('\n') + '\n',
    'utf8'
  );
}

function readCandidates() {
  const raw = fs.readFileSync(path.join(TMP_STORAGE, 'candidates.jsonl'), 'utf8').trim();
  return raw.split('\n').filter(Boolean).map(l => JSON.parse(l));
}

console.log('[reg-sync] Promotion + sync loop regressions\n');

// ── 1. Promotion loop closes: --approve writes into the SSOT ─────────────────

test('approve: appends the rule under Learned Rules in a TEMP global-rules.md', () => {
  const rulesFile = path.join(TMP, 'global-rules-approve.md');
  fs.writeFileSync(
    rulesFile,
    '# Global Working Agreement\n\n## How to Work\n\n- Do the thing.\n\n' +
    '## Learned Rules (Self-Promoted via Distillation Ladder)\n\n' +
    '- **L1 (2026-08-13) — An existing learned rule.**\n',
    'utf8'
  );
  writeCandidates([{
    id: 'regcand01',
    text: 'Always read the exit code, never the summary.',
    firstSeen: '2026-08-18',
    sightingDays: ['2026-08-18', '2026-08-19', '2026-08-20'],
    tier: 2,
    client: 'claude'
  }]);

  const res = approveCandidate('regcand01', rulesFile);
  assert.strictEqual(res.ok, true, `approve should succeed, got ${JSON.stringify(res)}`);

  const md = fs.readFileSync(rulesFile, 'utf8');
  assert(md.includes('Always read the exit code, never the summary.'), 'rule text must land in the rules file');
  assert(md.includes('L1 (2026-08-13)'), 'existing learned rules must survive');
  assert(md.includes('## Learned Rules'), 'section heading must survive');

  const promoted = readCandidates().find(c => c.id === 'regcand01');
  assert.strictEqual(promoted.promoted, true, 'candidate must be marked promoted in candidates.jsonl');
});

test('approve: is idempotent on a second run (no duplicate bullet)', () => {
  const rulesFile = path.join(TMP, 'global-rules-approve.md');
  const res = approveCandidate('regcand01', rulesFile);
  assert.strictEqual(res.ok, true, 'second approve should still report ok');
  const md = fs.readFileSync(rulesFile, 'utf8');
  const occurrences = md.split('Always read the exit code, never the summary.').length - 1;
  assert.strictEqual(occurrences, 1, `rule must appear exactly once, found ${occurrences}`);
});

test('approve: prose above the Learned Rules section does not count as promoted', () => {
  const rulesFile = path.join(TMP, 'global-rules-prose.md');
  fs.writeFileSync(
    rulesFile,
    '# Global Working Agreement\n\n## Core Philosophy\n\n- Prefer the boring, obvious solution.\n\n' +
    '## Learned Rules (Self-Promoted via Distillation Ladder)\n\n' +
    '- **L1 (2026-08-13) — An existing learned rule.**\n',
    'utf8'
  );
  writeCandidates([{
    id: 'regprose01',
    text: 'Prefer the boring, obvious solution.',
    firstSeen: '2026-08-18',
    sightingDays: ['2026-08-18', '2026-08-19', '2026-08-20'],
    tier: 1,
    client: 'claude'
  }]);

  const res = approveCandidate('regprose01', rulesFile);
  assert.strictEqual(res.ok, true, `approve should succeed, got ${JSON.stringify(res)}`);
  assert.notStrictEqual(res.alreadyPresent, true, 'text found only in prose must not be reported as already present');

  const md = fs.readFileSync(rulesFile, 'utf8');
  const learned = md.slice(md.indexOf('## Learned Rules'));
  assert(learned.includes('Prefer the boring, obvious solution.'), 'the rule must be appended under Learned Rules');
});

test('approve: refreshes distill-digest.json so the dashboard is not stale', () => {
  const digestFile = path.join(TMP_STORAGE, 'distill-digest.json');
  if (fs.existsSync(digestFile)) fs.unlinkSync(digestFile);

  const rulesFile = path.join(TMP, 'global-rules-digest.md');
  fs.writeFileSync(
    rulesFile,
    '# Global Working Agreement\n\n## Learned Rules (Self-Promoted via Distillation Ladder)\n\n',
    'utf8'
  );
  writeCandidates([{
    id: 'regdigest01',
    text: 'The digest must refresh the moment a candidate is approved.',
    firstSeen: '2026-08-18',
    sightingDays: ['2026-08-18', '2026-08-19', '2026-08-20'],
    tier: 1,
    client: 'claude'
  }]);

  const res = approveCandidate('regdigest01', rulesFile);
  assert.strictEqual(res.ok, true, `approve should succeed, got ${JSON.stringify(res)}`);
  assert(fs.existsSync(digestFile), 'approve must (re)write distill-digest.json');

  const digest = JSON.parse(fs.readFileSync(digestFile, 'utf8'));
  const entry = (digest.allCandidates || []).find(c => c.id === 'regdigest01');
  assert(entry, 'the approved candidate must appear in the refreshed digest');
  assert.strictEqual(entry.promoted, true, 'the digest must show the candidate as promoted');
});

// ── 2. Sync must never silently destroy a hand edit ──────────────────────────

test('sync: writes a pre-existing target sync has never recorded (first install)', () => {
  const targetFile = path.join(TMP, 'targets', 'HANDEDIT.md');
  fs.mkdirSync(path.dirname(targetFile), { recursive: true });
  const preexisting = '# CLAUDE.md\n\n- Content that predates the harness install.\n';
  fs.writeFileSync(targetFile, preexisting, 'utf8');

  const targetsConfig = path.join(TMP, 'targets.json');
  fs.writeFileSync(targetsConfig, JSON.stringify({
    version: 'test',
    targets: [{ id: 'regtarget', name: 'Reg Target', rulesFile: targetFile, preamble: '# Reg Header\n' }]
  }), 'utf8');

  const storageDir = path.join(TMP, 'sync-storage');
  const results = run({ targetsConfig, storageDir });
  const result = results.find(r => r.id === 'regtarget');

  assert.strictEqual(result.written, true, 'a never-recorded target must be written on the first sync');
  assert.strictEqual(result.drifted, false, 'never recorded is not the same as hand-edited');
  assert(fs.readFileSync(targetFile, 'utf8').startsWith('# Reg Header'), 'compiled output must land in the target');

  const baks = fs.readdirSync(path.join(storageDir, 'backups')).filter(f => f.endsWith('.bak'));
  const backedUp = baks.map(f => fs.readFileSync(path.join(storageDir, 'backups', f), 'utf8'));
  assert(backedUp.includes(preexisting), 'the pre-existing content must be backed up before the first write');
});

test('sync: backs up a hand-edited target instead of overwriting it', () => {
  const targetFile = path.join(TMP, 'targets', 'HANDEDIT.md');
  const targetsConfig = path.join(TMP, 'targets.json');
  const storageDir = path.join(TMP, 'sync-storage');

  const handEdited = '# CLAUDE.md\n\n- **L2 (2026-08-20) — A rule a human added by hand.**\n';
  fs.writeFileSync(targetFile, handEdited, 'utf8');

  const results = run({ targetsConfig, storageDir });

  const after = fs.readFileSync(targetFile, 'utf8');
  assert.strictEqual(after, handEdited, 'hand-edited target must NOT be overwritten without --force');

  const backupsDir = path.join(storageDir, 'backups');
  assert(fs.existsSync(backupsDir), 'storage/backups must be created');
  const baks = fs.readdirSync(backupsDir).filter(f => f.endsWith('.bak'));
  assert(baks.length > 0, 'a .bak must exist for the drifted target');
  const backedUp = baks.map(f => fs.readFileSync(path.join(backupsDir, f), 'utf8'));
  assert(backedUp.includes(handEdited), 'a backup must hold the exact hand-edited content');

  const result = results.find(r => r.id === 'regtarget');
  assert.strictEqual(result.drifted, true, 'result must report the target as drifted');
  assert.strictEqual(result.written, false, 'result must report that nothing was written');
});

test('sync: --force writes the drifted target and records state so the next run is clean', () => {
  const targetFile = path.join(TMP, 'targets', 'HANDEDIT.md');
  const targetsConfig = path.join(TMP, 'targets.json');
  const storageDir = path.join(TMP, 'sync-storage');

  const forced = run({ targetsConfig, storageDir, force: true });
  assert.strictEqual(forced.find(r => r.id === 'regtarget').written, true, 'force must write');
  assert(fs.readFileSync(targetFile, 'utf8').startsWith('# Reg Header'), 'target must now hold compiled output');

  const again = run({ targetsConfig, storageDir });
  const r = again.find(r => r.id === 'regtarget');
  assert.strictEqual(r.stale, false, 'target should be up to date on the following run');
  assert.strictEqual(r.drifted, false, 'a sync-written target must not read as drifted');
});

// run(--check) signals staleness by exiting 1; capture that instead of dying.
function checkExitCode(targetsConfig, storageDir) {
  const realExit = process.exit;
  let code = null;
  process.exit = (c) => { code = c; throw new Error('__exit__'); };
  try {
    run({ targetsConfig, storageDir, check: true });
  } catch (err) {
    if (err.message !== '__exit__') throw err;
  } finally {
    process.exit = realExit;
  }
  return code;
}

test('sync: --check reports stale when only the traits file drifted', () => {
  const dir = path.join(TMP, 'traits-target');
  fs.mkdirSync(dir, { recursive: true });
  const rulesFile = path.join(dir, 'RULES.md');
  const traitsFile = path.join(dir, 'SOUL.md');
  const targetsConfig = path.join(TMP, 'targets-traits.json');
  fs.writeFileSync(targetsConfig, JSON.stringify({
    version: 'test',
    targets: [{ id: 'regtraits', name: 'Reg Traits', rulesFile, traitsFile, preamble: '# Reg Traits\n' }]
  }), 'utf8');
  const storageDir = path.join(TMP, 'traits-storage');

  run({ targetsConfig, storageDir });
  assert.strictEqual(checkExitCode(targetsConfig, storageDir), null, 'a freshly synced target must check clean');

  fs.writeFileSync(traitsFile, '# traits content changed\n', 'utf8');
  assert.strictEqual(
    checkExitCode(targetsConfig, storageDir),
    1,
    '--check must exit 1 when the traits file no longer matches core/traits/traits.md'
  );
});

test('sync: check/target come from run() options, never from process.argv', () => {
  const dir = path.join(TMP, 'opts-target');
  fs.mkdirSync(dir, { recursive: true });
  const rulesFile = path.join(dir, 'RULES.md');
  const targetsConfig = path.join(TMP, 'targets-opts.json');
  fs.writeFileSync(targetsConfig, JSON.stringify({
    version: 'test',
    targets: [
      { id: 'regopts', name: 'Reg Opts', rulesFile, preamble: '# Reg Opts\n' },
      { id: 'regopts2', name: 'Reg Opts 2', rulesFile: path.join(dir, 'RULES2.md'), preamble: '# Reg Opts 2\n' }
    ]
  }), 'utf8');
  const storageDir = path.join(TMP, 'opts-storage');

  const argvBefore = process.argv.join(' ');
  assert.strictEqual(
    checkExitCode(targetsConfig, storageDir),
    1,
    'run({check:true}) must report stale targets even though process.argv carries no --check'
  );
  assert.strictEqual(process.argv.join(' '), argvBefore, 'run() must not read or mutate process.argv');
  assert(!fs.existsSync(rulesFile), 'a --check run must not write the target');

  const only = run({ targetsConfig, storageDir, target: 'regopts' });
  assert.strictEqual(only.length, 1, `target option must filter to one target, got ${only.length}`);
  assert.strictEqual(only[0].id, 'regopts', 'the filtered target must be the requested one');
  assert(!fs.existsSync(path.join(dir, 'RULES2.md')), 'the filtered-out target must not be written');
});

// ── 3. Harvest must not clobber tier promotions ──────────────────────────────

test('harvest: merge preserves an existing tier-2 candidate across a re-harvest', () => {
  writeCandidates([{
    id: 'regtier02',
    text: 'Verify a green check by making it fail on purpose.',
    firstSeen: '2026-08-10',
    sightingDays: ['2026-08-10', '2026-08-12'],
    tier: 2,
    status: 'promoted',
    client: 'claude',
    tags: ['rule', 'tier-2'],
    dashboardNote: 'edited in the dashboard'
  }]);

  const freshFromSource = [{
    id: 'regtier02',
    text: 'Verify a green check by making it fail on purpose.',
    firstSeen: '2026-08-10',
    sightingDays: ['2026-08-20'],
    tier: 0,
    client: 'claude',
    tags: ['observation'],
    kind: 'correction',
    bucket: 'verification'
  }];

  const merged = deduplicateAndMerge(freshFromSource);
  const item = merged.get('regtier02');
  assert(item, 'merged map must still contain the seeded candidate');
  assert.strictEqual(item.tier, 2, `tier must stay 2, got ${item.tier}`);
  assert.strictEqual(item.dashboardNote, 'edited in the dashboard', 'dashboard edits must survive');
  assert(item.sightingDays.includes('2026-08-10'), 'existing sighting days must survive');
  assert(item.sightingDays.includes('2026-08-20'), 'new sighting day must be merged in');
});

// ── 4. Skills link must report the real state ────────────────────────────────

test('skills: linkSkillsDirectory reports linked:false for an unmanaged existing dir', () => {
  const skillsDir = path.join(TMP, 'unmanaged-skills');
  fs.mkdirSync(skillsDir, { recursive: true });
  fs.writeFileSync(path.join(skillsDir, 'my-own-skill.md'), '# mine\n', 'utf8');

  const res = linkSkillsDirectory({ id: 'regtarget', skillsDir });
  assert.strictEqual(res.linked, false, 'an unmanaged real dir must never report linked:true');
  assert.strictEqual(res.reason, 'exists-unmanaged', `reason must be exists-unmanaged, got ${res.reason}`);
  assert(fs.existsSync(path.join(skillsDir, 'my-own-skill.md')), 'user skills must be left alone');
});

// ── 5. Prune must not churn git on a no-op run ───────────────────────────────

test('prune: pushToExamples is idempotent (no rewrite on a second run)', () => {
  const candidate = { id: 'regexample1', text: 'A candidate that belongs in examples.', firstSeen: '2026-08-01', sightingDays: ['2026-08-01'] };
  const first = pushToExamples(candidate);
  const firstContent = fs.readFileSync(first.path, 'utf8');

  const second = pushToExamples(candidate);
  assert.strictEqual(second.skipped, true, 'second push must report skipped');
  assert.strictEqual(fs.readFileSync(second.path, 'utf8'), firstContent, 'fixture must be byte-identical on a no-op run');
});

// ── 6. stripSections must reach end-of-input ─────────────────────────────────

test('sync: compileTarget strips a dropped section that runs to end of file', () => {
  const source = {
    rules: '# Rules\n\n## Keep Me\n\n- keep\n\n## Delegation and Model Routing\n\n- drop this\n',
    traits: ''
  };
  const compiled = compileTarget({ id: 'codex', name: 'Codex' }, source);
  assert(compiled.includes('## Keep Me'), 'other sections must survive');
  assert(!compiled.includes('Delegation and Model Routing'), 'trailing dropped section must be stripped');
  assert(!compiled.includes('drop this'), 'trailing dropped section body must be stripped');
});

console.log(`\n[reg-sync] ${passed} passed / ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
