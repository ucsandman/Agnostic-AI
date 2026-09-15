import { test } from 'node:test';
import assert from 'node:assert/strict';
import { extractYamlBlock, parseContract } from './parse.mjs';
import { validate, abstentions } from './task-contract.mjs';

/** A contract that should be clean: every edge dispositioned, every tier honored. */
const CLEAN = `# Contract

\`\`\`yaml
contract_version: 1
subject: "merge_intervals(list) -> list"
generated: "2026-09-15"

must_haves:
  - id: MH-01
    requirement: "Overlapping intervals merge into one."
    shape: [collection]
    edge_category: none
    disposition: specify
    tier: test
    non_inferable: false
    check: "node -e 0"
  - id: MH-02
    requirement: "[1,2] and [2,3] touch at a point. They MERGE into [1,3]."
    shape: [collection, numeric-range]
    edge_category: adjacency
    disposition: specify
    tier: test
    non_inferable: true
    check: "node -e 0"
  - id: MH-03
    requirement: "Concurrency out of scope; the function is pure."
    shape: [collection]
    edge_category: concurrency
    disposition: dismiss
    tier: judgment
    non_inferable: false
    reason: "No shared state."

prohibitions:
  - id: PR-01
    must_not: "Mutate the caller's input array."
    tier: test
    repo_check: "node -e 0"

open_questions:
  - id: OQ-01
    question: "Are half-open intervals ever passed?"
    blocks: [MH-02]
\`\`\`
`;

function docOf(md) {
  return parseContract(extractYamlBlock(md));
}

test('parses the restricted subset', () => {
  const doc = docOf(CLEAN);
  assert.equal(doc.contract_version, 1);
  assert.equal(doc.subject, 'merge_intervals(list) -> list');
  assert.equal(doc.must_haves.length, 3);
  assert.deepEqual(doc.must_haves[1].shape, ['collection', 'numeric-range']);
  assert.equal(doc.must_haves[1].non_inferable, true);
  assert.equal(doc.must_haves[0].non_inferable, false);
  assert.deepEqual(doc.open_questions[0].blocks, ['MH-02']);
});

test('a well-formed contract validates clean', () => {
  assert.deepEqual(validate(docOf(CLEAN)), []);
});

test('a resolved non_inferable item does not abstain', () => {
  // MH-02 is non_inferable but dispositioned `specify` — the edge was written
  // into the spec, which is exactly the case that converts to a catch.
  const abstain = abstentions(docOf(CLEAN)).map((a) => a.id);
  assert.deepEqual(abstain, []);
});

test('an UNresolved non_inferable item abstains', () => {
  const md = CLEAN.replace('    disposition: specify\n    tier: test\n    non_inferable: true', '    disposition: backstop\n    tier: test\n    non_inferable: true');
  const abstain = abstentions(docOf(md));
  assert.equal(abstain.length, 1);
  assert.equal(abstain[0].id, 'MH-02');
  assert.match(abstain[0].why, /non_inferable/);
});

test('a judgment-tier prohibition abstains', () => {
  const md = CLEAN.replace('    tier: test\n    repo_check: "node -e 0"', '    tier: judgment\n    reason: "no repo-wide rule expressible"');
  const abstain = abstentions(docOf(md)).map((a) => a.id);
  assert.deepEqual(abstain, ['PR-01']);
});

// --- deliberate breakage: each of these must be REJECTED ---------------------
// L1: a validator never observed failing has been run, not verified.

test('rejects a test-tier item with no check', () => {
  const md = CLEAN.replace('    non_inferable: false\n    check: "node -e 0"', '    non_inferable: false');
  assert.match(validate(docOf(md)).join('\n'), /requires a runnable check/);
});

test('rejects a dismissed item with no reason', () => {
  const md = CLEAN.replace('    reason: "No shared state."', '');
  assert.match(validate(docOf(md)).join('\n'), /requires a reason/);
});

test('rejects a backstop that is not tagged non_inferable', () => {
  const md = CLEAN.replace(
    '    disposition: specify\n    tier: test\n    non_inferable: true',
    '    disposition: backstop\n    tier: test\n    non_inferable: false',
  );
  assert.match(validate(docOf(md)).join('\n'), /implies non_inferable/);
});

test('rejects a test-tier prohibition with no repo_check', () => {
  const md = CLEAN.replace('    tier: test\n    repo_check: "node -e 0"', '    tier: test');
  assert.match(validate(docOf(md)).join('\n'), /requires a repo_check/);
});

test('rejects a judgment-tier prohibition with no reason', () => {
  const md = CLEAN.replace('    tier: test\n    repo_check: "node -e 0"', '    tier: judgment');
  assert.match(validate(docOf(md)).join('\n'), /requires a reason/);
});

test('rejects an open question blocking an unknown item', () => {
  const md = CLEAN.replace('blocks: [MH-02]', 'blocks: [MH-99]');
  assert.match(validate(docOf(md)).join('\n'), /blocks unknown item "MH-99"/);
});

test('rejects an unknown edge_category', () => {
  const md = CLEAN.replace('edge_category: adjacency', 'edge_category: vibes');
  assert.match(validate(docOf(md)).join('\n'), /unknown edge_category "vibes"/);
});

test('rejects an empty must_haves list', () => {
  const md = '```yaml\ncontract_version: 1\nsubject: "x"\nmust_haves:\n```\n';
  assert.match(validate(docOf(md)).join('\n'), /must_haves is empty/);
});

test('rejects a duplicate id', () => {
  const md = CLEAN.replace('id: MH-03', 'id: MH-01');
  assert.match(validate(docOf(md)).join('\n'), /duplicate id/);
});

test('throws rather than half-parsing a document with no yaml block', () => {
  assert.throws(() => extractYamlBlock('# just prose\n'), /no ```yaml block/);
});

test('throws on nesting outside the accepted subset', () => {
  const md = '```yaml\ncontract_version: 1\nsubject: "x"\nmust_haves:\n  - id: MH-01\n    nested:\n      deeper: 1\n```\n';
  assert.throws(() => docOf(md), /expected "key: value"|value outside/);
});

// --- quoted scalars ---------------------------------------------------------
// A `check` is a shell command, so it contains quotes. Handing the backslashes
// through unchanged ran a corrupted command that failed for an invisible
// reason — found by the td-parlay contract, whose PR-01 uses a pytest -k
// expression. Half-parsing is the failure this reader exists to prevent.

test('unescapes quotes inside a double-quoted check', () => {
  const md = '```yaml\ncontract_version: 1\nsubject: "x"\nmust_haves:\n  - id: MH-01\n'
    + '    requirement: "r"\n    shape: [text]\n    edge_category: none\n'
    + '    disposition: specify\n    tier: test\n    non_inferable: false\n'
    + '    check: "pytest -q -k \\"not slow and not db\\""\n```\n';
  assert.equal(docOf(md).must_haves[0].check, 'pytest -q -k "not slow and not db"');
});

test('handles the other double-quoted escapes', () => {
  // The YAML source contains the two characters backslash-t, not a tab.
  const md = [
    '```yaml',
    'contract_version: 1',
    String.raw`subject: "a\tb and a \\ backslash"`,
    'must_haves:',
    '```',
    '',
  ].join('\n');
  assert.equal(docOf(md).subject, 'a\tb and a \\ backslash');
});

test('single-quoted scalars take no escapes but collapse a doubled quote', () => {
  // A Windows path in single quotes keeps both backslashes; '' is the only escape.
  const md = [
    '```yaml',
    'contract_version: 1',
    String.raw`subject: 'it''s C:\Projects\x'`,
    'must_haves:',
    '```',
    '',
  ].join('\n');
  assert.equal(docOf(md).subject, String.raw`it's C:\Projects\x`);
});

test('an unquoted value is left exactly as written', () => {
  const md = '```yaml\ncontract_version: 1\nsubject: plain value here\nmust_haves:\n```\n';
  assert.equal(docOf(md).subject, 'plain value here');
});
