#!/usr/bin/env node
/**
 * reg-harness.cjs — Regression tests for the engine/harness port engine.
 *
 * Contract: engine/harness/README.md. Covers bundle round-trip + validation,
 * toml.cjs parsing, capture (claude + codex as source), apply (codex, gemini,
 * cursor, generic/windsurf, claude as reverse target), idempotence/--check,
 * prune, the hook dialect shim, and the CLI.
 *
 * Other workers are landing engine/harness/sources/*.cjs, targets/*.cjs,
 * apply.cjs, status.cjs, cli.cjs and engine/hooks/shim.cjs in parallel. A test
 * group whose module(s) do not exist yet prints SKIPPED and the run still
 * exits 0, so this file is meaningful before every worker lands. Once every
 * module exists there must be zero skips.
 *
 * Every test runs against temp homes and a temp storage dir. Nothing here
 * touches the real home directory or the repo's own harness/ or storage/.
 */

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const bundleMod = require('../harness/bundle.cjs');
const tomlMod = require('../harness/toml.cjs');
const common = require('../harness/common.cjs');
const { buildClaudeHome, buildCodexHome, CLAUDE_HOOK_HANDLER_TOTAL, fakeToken } = require('./fixtures/harness/build-home.cjs');

const ROOT = common.ROOT;

const TMP_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'agnostic-reg-harness-'));
let tmpCounter = 0;
function mkTmp(prefix) {
  const dir = path.join(TMP_ROOT, `${String(++tmpCounter).padStart(3, '0')}-${prefix}`);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

// The shipped policy's exclusion list is part of the contract under test; the
// operator-specific parts (target-only extra hooks, addenda, skill and MCP
// exclusions by name, Codex skill disables) are not, so the fixtures see a
// policy with those emptied and the expectations stay stable as the operator edits them.
const portPolicy = () => {
  const p = JSON.parse(fs.readFileSync(path.join(ROOT, 'core', 'port.json'), 'utf8'));
  p.hooks.extra = {};
  p.rules.addenda = {};
  p.skills.exclude = {};
  p.skills.codexDisable = [];
  p.mcp.exclude = {};
  return p;
};

let passed = 0;
let failed = 0;
let skipped = 0;

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

function exists(rel) {
  return fs.existsSync(path.join(ROOT, rel));
}

function req(rel) {
  return require(path.join(ROOT, rel));
}

/** Run a numbered test group; skip it (without failing the run) if a required module is missing. */
function section(num, label, deps, fn) {
  const missing = deps.filter((d) => !exists(d));
  if (missing.length) {
    skipped++;
    console.log(`\n${num}. ${label}`);
    console.log(`  ○ SKIPPED (missing: ${missing.join(', ')})`);
    return;
  }
  console.log(`\n${num}. ${label}`);
  try {
    fn();
  } catch (err) {
    failed++;
    console.log(`  ✗ ${label} (setup threw before its tests could run)`);
    console.log(`      ${err && err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Small helpers shared by several sections
// ---------------------------------------------------------------------------

function flattenFiles(targetReport) {
  const out = [];
  if (!targetReport || !targetReport.components) return out;
  for (const comp of Object.values(targetReport.components)) if (Array.isArray(comp.files)) out.push(...comp.files);
  return out;
}

function flattenDropped(targetReport) {
  const out = [];
  if (!targetReport || !targetReport.components) return out;
  for (const comp of Object.values(targetReport.components)) if (Array.isArray(comp.dropped)) out.push(...comp.dropped);
  return out;
}

/** Strip every known managed region so what remains is the user's own, untouched text. */
function stripKnownRegions(text) {
  let out = text;
  for (const c of bundleMod.COMPONENTS) out = common.replaceRegion(out, common.regionMarkers(c), '');
  return out;
}

/** Normalise whitespace noise (trailing spaces, blank-line runs) before an "identical" compare. */
function normalizeWhitespace(text) {
  return String(text)
    .replace(/\r\n/g, '\n')
    .split('\n').map((l) => l.replace(/[ \t]+$/, '')).join('\n')
    .replace(/\n{2,}/g, '\n\n')
    .trim();
}

console.log('[reg-harness] Harness port engine regressions\n');

// ── 1. bundle round trip + validate + toml.parse ─────────────────────────────

section(1, 'bundle round trip + validate + toml.parse', [], () => {
  test('bundle: createBundle -> save -> load equals (counts, agent meta, commands)', () => {
    // An OS-absolute fake home: `C:/...` is not absolute on POSIX and validate() checks skill paths.
    const fakeHome = mkTmp('fake-home');
    const b = bundleMod.createBundle('claude', fakeHome);
    b.rules = '# Global Working Agreement\n\n## How to Work\n\n- Do the thing.\n';
    b.identity = '# SOUL\n\nBe helpful.\n';
    b.hooks = {
      dialect: 'claude',
      events: {
        PreToolUse: [{ matcher: 'Bash', hooks: [{ type: 'command', command: 'node hook.cjs' }] }],
        Stop: [{ hooks: [{ type: 'command', command: 'node stop.cjs' }] }],
      },
    };
    b.mcp = { servers: { docs: { transport: 'stdio', command: 'npx', args: ['-y', 'x'], env: { CONTEXT7_API_KEY: '${CONTEXT7_API_KEY}' } } } };
    b.agents = [{ name: 'opus-owner', meta: { name: 'opus-owner', description: 'Owns review.', model: 'opus', tools: 'Read, Edit, Bash', readonly: 'false' }, body: 'Own the plan.' }];
    b.commands = [{ name: 'wrap', meta: { description: 'Wrap up.', 'argument-hint': '[note]' }, body: 'Summarize.' }];
    b.skills = { sourceDir: path.join(fakeHome, '.claude', 'skills'), skills: [{ name: 'alpha', path: path.join(fakeHome, '.claude', 'skills', 'alpha') }] };
    b.permissions = { allow: ['Bash(git *)'], deny: ['Bash(rm -rf *)'], ask: [] };

    const dir = bundleMod.save(b, mkTmp('bundle-roundtrip'));
    const loaded = bundleMod.load(dir);

    assert.deepStrictEqual(bundleMod.counts(loaded), bundleMod.counts(b), `counts must round-trip, got ${JSON.stringify(bundleMod.counts(loaded))} vs ${JSON.stringify(bundleMod.counts(b))}`);
    assert.strictEqual(loaded.agents.length, 1, `expected 1 agent after load, got ${loaded.agents.length}`);
    assert.deepStrictEqual(loaded.agents[0].meta, b.agents[0].meta);
    assert.strictEqual(loaded.agents[0].body.trim(), b.agents[0].body.trim());
    assert.strictEqual(loaded.commands.length, 1, `expected 1 command after load, got ${loaded.commands.length}`);
    assert.deepStrictEqual(loaded.commands[0].meta, b.commands[0].meta);
    assert.strictEqual(loaded.commands[0].body.trim(), b.commands[0].body.trim());
  });

  test('bundle: validate rejects a secret-looking mcp env value', () => {
    const b = bundleMod.createBundle('claude');
    b.rules = '# Rules\n\nSomething.\n';
    b.mcp = { servers: { docs: { transport: 'stdio', command: 'npx', env: { CONTEXT7_API_KEY: fakeToken() } } } };
    const problems = bundleMod.validate(b);
    assert(problems.length > 0, 'expected at least 1 validation problem, got 0');
    assert(problems.some((p) => /secret/i.test(p)), `expected a secret-shaped problem, got ${JSON.stringify(problems)}`);
    assert.throws(() => bundleMod.save(b, mkTmp('bundle-secret-reject')), /refusing to save an invalid bundle/);
  });

  test('bundle: validate rejects a non-kebab-case agent name', () => {
    const b = bundleMod.createBundle('claude');
    b.rules = '# Rules\n\nSomething.\n';
    b.agents = [{ name: 'Bad_Name', meta: { description: 'x' }, body: 'y' }];
    const problems = bundleMod.validate(b);
    assert(problems.some((p) => /kebab-case/.test(p)), `expected a kebab-case problem, got ${JSON.stringify(problems)}`);
  });

  test('toml.parse: escapes, multi-line arrays, inline tables, triple-quoted strings, [[arr]] then [arr.sub] on the last element', () => {
    const text = [
      'str1 = "line1\\nline2 \\"quoted\\""',
      'multi_arr = [',
      '  "a",',
      '  "b",',
      '  "c",',
      ']',
      'inline = { x = 1, y = "two", z = true }',
      'block = """',
      'first',
      'second"""',
      '',
      '[[arr]]',
      'name = "first"',
      '[arr.sub]',
      'value = 1',
      '',
      '[[arr]]',
      'name = "second"',
      '[arr.sub]',
      'value = 2',
      '',
    ].join('\n');
    const { data, warnings } = tomlMod.parse(text);
    assert.deepStrictEqual(warnings, [], `expected zero warnings, got ${JSON.stringify(warnings)}`);
    assert.strictEqual(data.str1, 'line1\nline2 "quoted"');
    assert.deepStrictEqual(data.multi_arr, ['a', 'b', 'c']);
    assert.deepStrictEqual(data.inline, { x: 1, y: 'two', z: true });
    assert.strictEqual(data.block, 'first\nsecond');
    assert.strictEqual(data.arr.length, 2, `expected 2 array-of-table entries, got ${data.arr.length}`);
    assert.strictEqual(data.arr[0].sub.value, 1);
    assert.strictEqual(data.arr[1].sub.value, 2, 'the second [arr.sub] must land on arr[1], the last element');
  });
});

// ── 2. capture claude ─────────────────────────────────────────────────────────

section(2, 'capture claude', ['engine/harness/capture.cjs', 'engine/harness/sources/claude.cjs'], () => {
  const capture = req('engine/harness/capture.cjs');
  const home = mkTmp('capture-claude-home');
  buildClaudeHome(home);
  const outDir = mkTmp('capture-claude-bundle');

  test('capture claude: component counts, rules content, mcp secret handling, agent readonly, skill path', () => {
    const { bundle: b, warnings } = capture.capture({ from: 'claude', home, outDir });
    const c = bundleMod.counts(b);
    assert.strictEqual(c.hooks, CLAUDE_HOOK_HANDLER_TOTAL, `hooks handler total: expected ${CLAUDE_HOOK_HANDLER_TOTAL}, got ${c.hooks}`);
    assert.strictEqual(c.agents, 2, `agents: expected 2, got ${c.agents}`);
    assert.strictEqual(c.commands, 1, `commands: expected 1 (README.md ignored), got ${c.commands}`);
    assert.strictEqual(c.skills, 3, `skills: expected 3, got ${c.skills}`);
    assert.strictEqual(c.mcp, 3, `mcp: expected 3, got ${c.mcp}`);
    assert.strictEqual(c.permissions, 5, `permissions: expected 5, got ${c.permissions}`);

    assert(b.rules.includes('Batch tool calls; one call per turn is the slow path.'), 'rules must contain the agnostic-rules content');
    assert(!b.rules.includes('@~/.claude/agnostic-rules.md'), 'rules must not contain the import line');
    assert(!b.rules.includes('@RTK.md'), 'rules must not contain the relative import line');
    assert(!b.rules.includes('GENERATED FILE'), 'rules must not contain the source header');

    assert.strictEqual(b.mcp.servers.docs.env.CONTEXT7_API_KEY, '${CONTEXT7_API_KEY}', 'the secret env value must be replaced with a reference');
    assert.strictEqual(b.mcp.servers.docs.env.PORT, '8080', 'a non-secret env value must survive unchanged');
    assert(warnings.some((w) => w.includes('CONTEXT7_API_KEY')), `expected a warning naming CONTEXT7_API_KEY, got ${JSON.stringify(warnings)}`);

    const advisor = b.agents.find((a) => a.name === 'advisor');
    const owner = b.agents.find((a) => a.name === 'opus-owner');
    assert(advisor, 'advisor agent must be captured');
    assert(owner, 'opus-owner agent must be captured');
    assert.strictEqual(String(advisor.meta.readonly), 'true', 'advisor must be readonly');
    assert(!owner.meta.readonly || String(owner.meta.readonly) === 'false', `opus-owner must not be readonly, got ${JSON.stringify(owner.meta.readonly)}`);

    const gamma = b.skills.skills.find((s) => s.name === 'gamma');
    assert(gamma && path.isAbsolute(gamma.path), 'gamma skill path must resolve to an absolute path');
  });
});

// ── 3-5. apply to codex: apply / idempotence + check / prune ────────────────

section(
  '3-5',
  'apply to codex: apply, idempotence + check, prune',
  ['engine/harness/capture.cjs', 'engine/harness/apply.cjs', 'engine/harness/sources/claude.cjs', 'engine/harness/targets/codex.cjs'],
  () => {
    const capture = req('engine/harness/capture.cjs');
    const apply = req('engine/harness/apply.cjs');

    const sourceHome = mkTmp('codex-src-claude');
    buildClaudeHome(sourceHome);
    const bundleDir = mkTmp('codex-apply-bundle');
    const { bundle: b } = capture.capture({ from: 'claude', home: sourceHome, outDir: bundleDir });

    const targetHome = mkTmp('codex-target-home');
    buildCodexHome(targetHome);
    const configPath = path.join(targetHome, '.codex', 'config.toml');
    const originalConfigText = fs.readFileSync(configPath, 'utf8');
    const betaSkillPath = path.join(targetHome, '.codex', 'skills', 'beta', 'SKILL.md');
    const originalBetaSkillText = fs.readFileSync(betaSkillPath, 'utf8');
    const storageDir = mkTmp('codex-target-storage');
    const port = portPolicy();

    let firstReport;
    test('3. apply to codex: AGENTS.md, config.toml regions/hooks/mcp, agents, prompts, skills, rules', () => {
      firstReport = apply.apply({ bundle: b, home: targetHome, port, to: ['codex'], storageDir });
      const codexReport = firstReport.targets.codex;
      assert(codexReport, 'report.targets.codex must exist');

      const agentsMd = fs.readFileSync(path.join(targetHome, '.codex', 'AGENTS.md'), 'utf8');
      assert(agentsMd.split(/\r?\n/, 6).slice(0, 5).some((l) => l.includes('GENERATED by agnostic-ai')), 'AGENTS.md preamble (first five lines) must carry the GENERATED mark');
      assert(agentsMd.includes('Batch tool calls; one call per turn is the slow path.'), 'AGENTS.md must contain the agnostic-rules content');
      assert(agentsMd.includes('Traits and identity notes for the agent.'), 'AGENTS.md must contain the SOUL content');
      assert(!agentsMd.includes('Delegation and Model Routing'), 'AGENTS.md must not contain the dropped section');

      const configText = fs.readFileSync(configPath, 'utf8');
      assert.strictEqual(
        normalizeWhitespace(stripKnownRegions(configText)),
        normalizeWhitespace(stripKnownRegions(originalConfigText)),
        'outside-region config.toml text must be untouched'
      );

      const { data: configData, warnings: configWarnings } = tomlMod.parse(configText);
      assert.deepStrictEqual(configWarnings, [], `toml.parse(config) must yield zero warnings, got ${JSON.stringify(configWarnings)}`);

      const preGroups = (configData.hooks && configData.hooks.PreToolUse) || [];
      const FOREIGN_MATCHER = 'apply_patch|Bash';
      assert(preGroups.some((g) => g.matcher === FOREIGN_MATCHER), 'the foreign apply_patch|Bash PreToolUse group must survive');
      const portedGroups = preGroups.filter((g) => g.matcher !== FOREIGN_MATCHER);
      assert.strictEqual(portedGroups.length, 2, `ported [[hooks.PreToolUse]] groups: expected 2, got ${portedGroups.length}`);
      assert(
        portedGroups.some((g) => /Edit/.test(g.matcher || '') && /Bash/.test(g.matcher || '')),
        `expected a translated matcher containing Edit and Bash, got ${JSON.stringify(portedGroups.map((g) => g.matcher))}`
      );
      assert(!configText.includes('capability-graph-guard'), 'capability-graph-guard must be excluded per core/port.json');
      assert(!configText.includes('MessageDisplay'), 'MessageDisplay must not appear (Claude-only event)');
      assert(!/Read\|Glob\|Grep/.test(configText), 'Read|Glob|Grep group must be dropped (no Codex hook surface)');

      const hookState = (configData.hooks && configData.hooks.state) || {};
      const foreignKey = 'C:\\other\\hooks.json:pre_tool_use:0:0';
      assert(hookState[foreignKey], 'the foreign hooks.state block must survive');
      const trustEntries = Object.keys(hookState).filter((k) => k !== foreignKey);
      // One trust entry per ported handler across EVERY event: PreToolUse 3, PostToolUse 1,
      // Stop 1, SessionStart 1, UserPromptSubmit 1 = 7 (MessageDisplay and the excluded
      // guard never reach config.toml). Counted from the config itself, not asserted from memory.
      const portedHandlers = Object.entries(configData.hooks || {})
        .filter(([event]) => event !== 'state')
        .reduce((n, [, groups]) => n + groups.reduce((m, g) => m + (g.hooks || []).length, 0), 0);
      // The fixture config.toml already carried ONE user hook ([[hooks.PreToolUse]] apply_patch|Bash);
      // it is preserved outside the region and gets no trust entry from us: 7 ported + 1 user = 8.
      assert.strictEqual(portedHandlers, 8, `handlers across all events: expected 8 (7 ported + 1 pre-existing user hook), got ${portedHandlers}`);
      assert.strictEqual(trustEntries.length, 7, `trust entries: expected 7 (one per ported handler), got ${trustEntries.length}`);
      const hasSha256 = (entry) => Object.values(entry || {}).some((v) => typeof v === 'string' && v.startsWith('sha256:'));
      for (const k of trustEntries) assert(hasSha256(hookState[k]), `trust entry ${k} must carry a sha256: hash, got ${JSON.stringify(hookState[k])}`);

      assert(configData.mcp_servers.docs, '[mcp_servers.docs] must exist');
      assert.deepStrictEqual(configData.mcp_servers.docs.env_vars, ['CONTEXT7_API_KEY']);
      assert.deepStrictEqual(configData.mcp_servers.docs.env, { PORT: '8080' });
      assert(configData.mcp_servers.remote && configData.mcp_servers.remote.url, '[mcp_servers.remote] must exist with a url');
      assert(!configData.mcp_servers.events, '[mcp_servers.events] (sse) must be dropped');
      assert.strictEqual((configText.match(/\[mcp_servers\.existing\]/g) || []).length, 1, 'no second [mcp_servers.existing]');

      const agentsDir = path.join(targetHome, '.codex', 'agents');
      const ownerToml = tomlMod.parse(fs.readFileSync(path.join(agentsDir, 'opus-owner.toml'), 'utf8')).data;
      assert.strictEqual(ownerToml.model, 'gpt-5.6-sol', `opus-owner.toml model: got ${ownerToml.model}`);
      assert.strictEqual(ownerToml.sandbox_mode, undefined, 'opus-owner (not readonly) must not carry sandbox_mode');
      const advisorToml = tomlMod.parse(fs.readFileSync(path.join(agentsDir, 'advisor.toml'), 'utf8')).data;
      assert.strictEqual(advisorToml.model, 'gpt-6-astra', `advisor.toml model: got ${advisorToml.model}`);
      assert.strictEqual(advisorToml.sandbox_mode, 'read-only');

      assert(fs.existsSync(path.join(targetHome, '.codex', 'prompts', 'wrap.md')), 'prompts/wrap.md must exist');
      assert(!fs.existsSync(path.join(targetHome, '.codex', 'prompts', 'README.md')), 'no README.md prompt');

      const skillsDir = path.join(targetHome, '.codex', 'skills');
      assert(common.readLinkTarget(path.join(skillsDir, 'alpha')) !== null, 'alpha must be a link into the Claude skills dir');
      assert(
        common.readLinkTarget(path.join(skillsDir, 'beta')) === null,
        'the Codex-native real beta dir must not be replaced by a link'
      );
      assert.strictEqual(
        fs.readFileSync(betaSkillPath, 'utf8'),
        originalBetaSkillText,
        'the Codex-native beta SKILL.md content must be untouched'
      );
      assert(!fs.existsSync(path.join(skillsDir, 'gamma')), 'gamma is not linked (already reachable via the shared skills dir)');

      const droppedItems = flattenDropped(codexReport);
      const droppedGamma = droppedItems.find((d) => /gamma/i.test(d.item));
      assert(droppedGamma && /shared/i.test(droppedGamma.reason), `gamma drop reason must mention it is shared, got ${JSON.stringify(droppedGamma)}`);

      const skillsConfigCandidates = ['skills.config', 'config.toml'].map((f) => path.join(targetHome, '.codex', f)).filter(fs.existsSync);
      // TOML basic strings escape backslashes, so a Windows path shows up as skills\\beta\\SKILL.md.
      const disablesBeta = skillsConfigCandidates.some((f) => /skills[\\/]+beta[\\/]+SKILL\.md/.test(fs.readFileSync(f, 'utf8')));
      assert(disablesBeta, 'a skills.config region must disable the duplicate Codex-native beta skill');

      const rulesText = fs.readFileSync(path.join(targetHome, '.codex', 'rules', 'agnostic.rules'), 'utf8');
      assert(rulesText.includes('["git"]'), `rules must carry the git allow rule, got:\n${rulesText}`);
      assert(rulesText.includes('["npm", "run", "build"]'), `rules must carry the npm run build allow rule, got:\n${rulesText}`);
      assert(/forbidden/i.test(rulesText) && /rm/.test(rulesText), 'a forbidden rule for rm must exist');

      const dropped = flattenDropped(codexReport);
      // `Bash(npm run test:*)` is Claude's whole-string prefix operator, which IS a Codex prefix rule.
      assert(rulesText.includes('["npm", "run", "test"]'), `test:* must become the prefix rule ["npm", "run", "test"], got:\n${rulesText}`);
      assert(!dropped.some((d) => /test:\*/.test(d.item)), 'test:* must not be dropped');
      assert(dropped.some((d) => /Read\(/.test(d.item)), `dropped list must mention the Read( permission, got ${JSON.stringify(dropped)}`);
      for (const d of dropped) assert(d.reason && d.reason.length > 0, `dropped item ${d.item} must carry a reason`);
    });

    test('4a. second apply is a no-op: every file action unchanged (or a steady real-directory skip), config.toml bytes identical', () => {
      const configBefore = fs.readFileSync(configPath, 'utf8');
      const report2 = apply.apply({ bundle: b, home: targetHome, port, to: ['codex'], storageDir });
      const files = flattenFiles(report2.targets.codex);
      assert(files.length > 0, `expected at least 1 file entry, got ${files.length}`);
      // 'skipped-real-directory' is the Codex-native beta dir the harness deliberately
      // never touches (never destroy user content); that is a steady no-op too, not drift.
      const NO_OP_ACTIONS = new Set(['unchanged', 'skipped-real-directory']);
      for (const f of files) assert(NO_OP_ACTIONS.has(f.action), `${f.path} action must be a no-op, got ${f.action}`);
      assert.strictEqual(fs.readFileSync(configPath, 'utf8'), configBefore, 'config.toml bytes must be identical on the second apply');
    });

    test('4b. --check reports not stale and writes nothing', () => {
      const before = fs.readFileSync(path.join(targetHome, '.codex', 'AGENTS.md'), 'utf8');
      const report3 = apply.apply({ bundle: b, home: targetHome, port, to: ['codex'], storageDir, check: true });
      assert.strictEqual(report3.stale, false, `report.stale must be false, got ${report3.stale}`);
      assert.strictEqual(fs.readFileSync(path.join(targetHome, '.codex', 'AGENTS.md'), 'utf8'), before, 'a --check run must not write');
    });

    test('4c. appending a line (header intact) reads as stale under --check', () => {
      const agentsMdPath = path.join(targetHome, '.codex', 'AGENTS.md');
      fs.appendFileSync(agentsMdPath, '\nA hand-added line.\n');
      const report4 = apply.apply({ bundle: b, home: targetHome, port, to: ['codex'], storageDir, check: true });
      assert.strictEqual(report4.stale, true, `report.stale must be true after a hand edit, got ${report4.stale}`);
    });

    test('4d. deleting the GENERATED mark (the ownership claim): skipped without force (with backup), written with force', () => {
      const agentsMdPath = path.join(targetHome, '.codex', 'AGENTS.md');
      const withHeaderRemoved = fs.readFileSync(agentsMdPath, 'utf8').split(/\r?\n/).filter((l) => !l.includes('GENERATED by agnostic-ai')).join('\n');
      fs.writeFileSync(agentsMdPath, withHeaderRemoved, 'utf8');
      const beforeForce = fs.readFileSync(agentsMdPath, 'utf8');

      const report5 = apply.apply({ bundle: b, home: targetHome, port, to: ['codex'], storageDir });
      const agentsFile5 = flattenFiles(report5.targets.codex).find((f) => /AGENTS\.md$/.test(f.path));
      assert(agentsFile5, 'AGENTS.md must be in the files list');
      assert.strictEqual(agentsFile5.action, 'skipped-hand-edited', `expected skipped-hand-edited, got ${agentsFile5.action}`);
      assert.strictEqual(fs.readFileSync(agentsMdPath, 'utf8'), beforeForce, 'a hand-edited file must not be overwritten without --force');
      const backupsDir = path.join(storageDir, 'backups');
      assert(fs.existsSync(backupsDir) && fs.readdirSync(backupsDir).some((f) => f.includes('AGENTS')), 'a backup of the hand-edited AGENTS.md must exist');

      const report6 = apply.apply({ bundle: b, home: targetHome, port, to: ['codex'], storageDir, force: true });
      const agentsFile6 = flattenFiles(report6.targets.codex).find((f) => /AGENTS\.md$/.test(f.path));
      assert.strictEqual(agentsFile6.action, 'written', `expected written with force, got ${agentsFile6.action}`);
      assert(fs.readFileSync(agentsMdPath, 'utf8').includes('GENERATED by agnostic-ai'), 'force must restore the generated header');
    });

    test('5. prune: removing advisor and skill alpha from the bundle removes them; beta stays untouched', () => {
      const pruned = JSON.parse(JSON.stringify(b));
      pruned.agents = pruned.agents.filter((a) => a.name !== 'advisor');
      pruned.skills.skills = pruned.skills.skills.filter((s) => s.name !== 'alpha');

      apply.apply({ bundle: pruned, home: targetHome, port, to: ['codex'], storageDir });
      assert(!fs.existsSync(path.join(targetHome, '.codex', 'agents', 'advisor.toml')), 'advisor.toml must be removed after prune');
      assert(
        common.readLinkTarget(path.join(targetHome, '.codex', 'skills', 'alpha')) === null,
        'the alpha link must be removed after prune'
      );
      assert(
        fs.existsSync(path.join(targetHome, '.codex', 'skills', 'beta', 'SKILL.md')),
        "the user's real beta dir must survive pruning untouched"
      );
    });
  }
);

// ── 6. apply to gemini, cursor, generic (windsurf) ───────────────────────────

section(
  6,
  'apply to gemini, cursor, generic (windsurf)',
  ['engine/harness/apply.cjs', 'engine/harness/capture.cjs', 'engine/harness/sources/claude.cjs', 'engine/harness/targets/gemini.cjs', 'engine/harness/targets/cursor.cjs', 'engine/harness/targets/generic.cjs'],
  () => {
    const capture = req('engine/harness/capture.cjs');
    const apply = req('engine/harness/apply.cjs');
    const home = mkTmp('multi-target-home');
    buildClaudeHome(home);

    const geminiSettingsPath = path.join(home, '.gemini', 'settings.json');
    fs.mkdirSync(path.dirname(geminiSettingsPath), { recursive: true });
    fs.writeFileSync(geminiSettingsPath, JSON.stringify({
      hooks: { BeforeTool: [{ matcher: 'foreign_tool', hooks: [{ type: 'command', command: 'node foreign-gemini-hook.cjs' }] }] },
    }, null, 2) + '\n');

    const cursorHooksPath = path.join(home, '.cursor', 'hooks.json');
    fs.mkdirSync(path.dirname(cursorHooksPath), { recursive: true });
    fs.writeFileSync(cursorHooksPath, JSON.stringify({
      version: 1,
      hooks: { preToolUse: [{ command: 'node foreign-cursor-hook.cjs' }] },
    }, null, 2) + '\n');

    fs.mkdirSync(path.join(home, '.windsurf'), { recursive: true });

    const bundleDir = mkTmp('multi-target-bundle');
    const { bundle: b } = capture.capture({ from: 'claude', home, outDir: bundleDir });
    const port = portPolicy();
    const storageDir = mkTmp('multi-target-storage');

    test('6a. apply to gemini/cursor/windsurf: rules, gemini hooks + commands, cursor hooks + agents, windsurf mcp', () => {
      apply.apply({ bundle: b, home, port, to: ['gemini', 'cursor', 'windsurf'], storageDir });

      const geminiRules = fs.readFileSync(path.join(home, '.gemini', 'GEMINI.md'), 'utf8');
      assert(geminiRules.split(/\r?\n/, 6).slice(0, 5).some((l) => l.includes('GENERATED by agnostic-ai')));
      const cursorRules = fs.readFileSync(path.join(home, '.cursor', 'rules', 'global-rules.mdc'), 'utf8');
      assert(cursorRules.includes('GENERATED by agnostic-ai'));
      const windsurfRules = fs.readFileSync(path.join(home, '.windsurf', 'rules', 'global-rules.md'), 'utf8');
      assert(windsurfRules.split(/\r?\n/, 6).slice(0, 5).some((l) => l.includes('GENERATED by agnostic-ai')));

      const geminiSettings = JSON.parse(fs.readFileSync(geminiSettingsPath, 'utf8'));
      const beforeTool = geminiSettings.hooks.BeforeTool || [];
      assert(
        // docs/porting.md's event map: Claude PreToolUse -> Gemini's own native event name "BeforeTool".
        beforeTool.some((g) => (g.hooks || []).some((h) => h.command && h.command.includes('shim.cjs') && h.command.includes('--client gemini') && h.command.includes('--event BeforeTool'))),
        `gemini BeforeTool must shim through PreToolUse, got ${JSON.stringify(beforeTool)}`
      );
      assert(
        beforeTool.some((g) => (g.hooks || []).some((h) => h.command && h.command.includes(' ++ '))),
        'gemini must chain multiple guards for one event with ++'
      );
      assert(geminiSettings.hooks.AfterAgent, 'gemini AfterAgent (Stop) must exist');
      assert(!geminiSettings.hooks.MessageDisplay, 'gemini must not carry MessageDisplay');
      assert(beforeTool.some((g) => g.matcher === 'foreign_tool'), 'the foreign gemini BeforeTool group must survive');

      const geminiWrap = fs.readFileSync(path.join(home, '.gemini', 'commands', 'wrap.toml'), 'utf8');
      const { data: wrapData } = tomlMod.parse(geminiWrap);
      assert(wrapData.description, 'gemini commands/wrap.toml must have a description');
      assert(wrapData.prompt, 'gemini commands/wrap.toml must have a prompt');

      const cursorHooks = JSON.parse(fs.readFileSync(cursorHooksPath, 'utf8'));
      assert.strictEqual(cursorHooks.version, 1, `cursor hooks.json version: got ${cursorHooks.version}`);
      assert(
        cursorHooks.hooks.preToolUse.some((h) => h.command && h.command.includes('--client cursor')),
        'cursor preToolUse must shim with --client cursor'
      );
      assert(
        cursorHooks.hooks.preToolUse.some((h) => h.command === 'node foreign-cursor-hook.cjs'),
        'the foreign cursor preToolUse entry must survive'
      );

      const cursorAdvisor = fs.readFileSync(path.join(home, '.cursor', 'agents', 'advisor.md'), 'utf8');
      assert(/readonly:\s*true/.test(cursorAdvisor), 'cursor advisor.md must carry readonly: true');

      const windsurfMcp = JSON.parse(fs.readFileSync(path.join(home, '.codeium', 'windsurf', 'mcp_config.json'), 'utf8'));
      assert(windsurfMcp.mcpServers.docs, 'windsurf mcp_config.json must have docs');
      assert.strictEqual(windsurfMcp.mcpServers.docs.env.CONTEXT7_API_KEY, '${CONTEXT7_API_KEY}', 'the literal ${VAR} reference must be preserved');
      assert(windsurfMcp.mcpServers.remote, 'windsurf mcp_config.json must have remote');
    });

    test('6b. second apply to gemini/cursor/windsurf is unchanged', () => {
      const geminiBefore = fs.readFileSync(path.join(home, '.gemini', 'GEMINI.md'), 'utf8');
      const report2 = apply.apply({ bundle: b, home, port, to: ['gemini', 'cursor', 'windsurf'], storageDir });
      for (const id of ['gemini', 'cursor', 'windsurf']) {
        for (const f of flattenFiles(report2.targets[id])) assert.strictEqual(f.action, 'unchanged', `${id} ${f.path} must be unchanged on second apply, got ${f.action}`);
      }
      assert.strictEqual(fs.readFileSync(path.join(home, '.gemini', 'GEMINI.md'), 'utf8'), geminiBefore);
    });
  }
);

// ── 7. reverse: codex as source, claude as target ────────────────────────────

section(
  7,
  'reverse: codex as source, claude as target',
  ['engine/harness/capture.cjs', 'engine/harness/sources/codex.cjs', 'engine/harness/apply.cjs', 'engine/harness/targets/claude.cjs'],
  () => {
    const capture = req('engine/harness/capture.cjs');
    const apply = req('engine/harness/apply.cjs');

    const codexSourceHome = mkTmp('reverse-codex-source');
    buildCodexHome(codexSourceHome);
    const bundleDir = mkTmp('reverse-bundle');

    let b;
    test('7a. capture from codex: rules, hooks, agent ladder reverse lookup, command, skills, mcp, permissions', () => {
      ({ bundle: b } = capture.capture({ from: 'codex', home: codexSourceHome, outDir: bundleDir }));
      assert(b.rules && b.rules.includes('Keep diffs minimal and reversible.'), 'rules must be captured from AGENTS.md');

      const preToolUse = b.hooks.events.PreToolUse || [];
      const handlerCount = preToolUse.reduce((n, g) => n + (g.hooks || []).length, 0);
      assert.strictEqual(handlerCount, 1, `expected 1 hook handler, got ${handlerCount}`);
      const matcher = (preToolUse[0] || {}).matcher || '';
      assert(matcher.includes('Edit|Write') || (matcher.includes('Edit') && matcher.includes('Write')), `matcher must translate apply_patch to Edit|Write, got "${matcher}"`);
      assert(matcher.includes('Bash'), `matcher must include Bash, got "${matcher}"`);

      assert.strictEqual(b.agents.length, 1, `expected 1 agent, got ${b.agents.length}`);
      assert.strictEqual(String(b.agents[0].meta.readonly), 'true', 'the read-only sandbox_mode must map to readonly true');
      assert.strictEqual(b.agents[0].meta.model, 'sonnet', `gpt-5.6-terra must reverse-map to the sonnet tier, got ${b.agents[0].meta.model}`);

      assert.strictEqual(b.commands.length, 1, `expected 1 command, got ${b.commands.length}`);

      assert.strictEqual(b.skills.skills.length, 1, `expected 1 skill (.system excluded), got ${b.skills.skills.length}`);
      assert.strictEqual(b.skills.skills[0].name, 'beta');

      assert.strictEqual(Object.keys(b.mcp.servers).length, 1, `expected 1 mcp server, got ${Object.keys(b.mcp.servers).length}`);
      assert(b.mcp.servers.existing, 'the existing mcp server must be captured');

      assert.deepStrictEqual(b.permissions.allow, ['Bash(ls *)'], `expected the allow prefix_rule translated, got ${JSON.stringify(b.permissions.allow)}`);
      assert.deepStrictEqual(b.permissions.deny, ['Bash(rm -rf *)'], `expected the forbidden prefix_rule translated, got ${JSON.stringify(b.permissions.deny)}`);
    });

    const claudeHome = mkTmp('reverse-claude-target');
    const claudeMdPath = path.join(claudeHome, '.claude', 'CLAUDE.md');
    fs.mkdirSync(path.dirname(claudeMdPath), { recursive: true });
    fs.writeFileSync(claudeMdPath, '# CLAUDE.md\n\nExisting hand-written instructions.\n', 'utf8');
    const settingsPath = path.join(claudeHome, '.claude', 'settings.json');
    fs.writeFileSync(settingsPath, JSON.stringify({ hooks: { PreToolUse: [{ matcher: 'foreign', hooks: [{ type: 'command', command: 'node foreign.cjs' }] }] } }, null, 2) + '\n');
    const storageDir = mkTmp('reverse-storage');
    const port = portPolicy();

    test('7b. apply to claude: CLAUDE.md gains exactly one import line and keeps its content; foreign settings survive', () => {
      apply.apply({ bundle: b, home: claudeHome, port, to: ['claude'], storageDir });
      const claudeMd = fs.readFileSync(claudeMdPath, 'utf8');
      const importOccurrences = claudeMd.split('@~/.claude/agnostic-rules.md').length - 1;
      assert.strictEqual(importOccurrences, 1, `expected exactly one import line, found ${importOccurrences}`);
      assert(claudeMd.includes('Existing hand-written instructions.'), 'the pre-existing CLAUDE.md content must survive');

      assert(fs.existsSync(path.join(claudeHome, '.claude', 'agnostic-rules.md')), 'agnostic-rules.md must be written');

      const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
      const preGroups = settings.hooks.PreToolUse || [];
      assert(preGroups.some((g) => g.matcher === 'foreign'), 'the foreign hook group must survive');
      assert(preGroups.length > 1, 'our ported hook group must be added alongside the foreign one');

      const claudeJson = JSON.parse(fs.readFileSync(path.join(claudeHome, '.claude.json'), 'utf8'));
      assert(claudeJson.mcpServers.existing, 'the mcp server must be ported into .claude.json');

      assert(fs.existsSync(path.join(claudeHome, '.claude', 'agents', 'one.md')), 'agents/one.md must exist');
      const oneMd = fs.readFileSync(path.join(claudeHome, '.claude', 'agents', 'one.md'), 'utf8');
      assert(/readonly:\s*true/.test(oneMd) || /tools:\s*Read/.test(oneMd), 'agents/one.md must carry a readonly-derived tools list or a readonly marker');
    });

    test('7c. second apply to claude is unchanged', () => {
      const before = fs.readFileSync(claudeMdPath, 'utf8');
      const report2 = apply.apply({ bundle: b, home: claudeHome, port, to: ['claude'], storageDir });
      for (const f of flattenFiles(report2.targets.claude)) assert.strictEqual(f.action, 'unchanged', `${f.path} must be unchanged on second apply, got ${f.action}`);
      assert.strictEqual(fs.readFileSync(claudeMdPath, 'utf8'), before);
    });
  }
);

// ── 8. shim wire tests ────────────────────────────────────────────────────────

section(8, 'shim wire tests', ['engine/hooks/shim.cjs'], () => {
  const shimPath = path.join(ROOT, 'engine', 'hooks', 'shim.cjs');
  const secretGuardPath = path.join(ROOT, 'engine', 'hooks', 'secret-guard.cjs');

  function runShim(client, event, cmdTokens, payload, input) {
    const args = ['--client', client, '--event', event, '--', ...cmdTokens];
    return spawnSync(process.execPath, [shimPath, ...args], {
      input: input !== undefined ? input : JSON.stringify(payload),
      encoding: 'utf8', windowsHide: true, timeout: 10000,
    });
  }

  test('8a. cursor beforeShellExecution: cat .env denies with a non-empty agent_message', () => {
    const res = runShim('cursor', 'beforeShellExecution', ['node', secretGuardPath], { command: 'cat .env', cwd: ROOT });
    const out = JSON.parse(res.stdout || '{}');
    assert.strictEqual(out.permission, 'deny', `expected permission deny, got ${JSON.stringify(out)}`);
    assert(out.agent_message && out.agent_message.length > 0, 'agent_message must be non-empty');
  });

  test('8b. cursor beforeShellExecution: git status allows or gives no opinion', () => {
    const res = runShim('cursor', 'beforeShellExecution', ['node', secretGuardPath], { command: 'git status' });
    const out = JSON.parse(res.stdout || '{}');
    assert(out.permission === 'allow' || Object.keys(out).length === 0, `expected allow or {}, got ${JSON.stringify(out)}`);
  });

  test('8c. gemini BeforeTool: cat .env denies with exit code 2', () => {
    const res = runShim('gemini', 'BeforeTool', ['node', secretGuardPath], { tool_name: 'run_shell_command', tool_input: { command: 'cat .env' } });
    const out = JSON.parse(res.stdout || '{}');
    assert.strictEqual(out.decision, 'deny', `expected decision deny, got ${JSON.stringify(out)}`);
    assert.strictEqual(res.status, 2, `expected exit code 2, got ${res.status}`);
  });

  test('8d. agy PreToolUse: cat .env denies', () => {
    const res = runShim('agy', 'PreToolUse', ['node', secretGuardPath], { toolCall: { name: 'run_command', args: { CommandLine: 'cat .env' } } });
    const out = JSON.parse(res.stdout || '{}');
    assert.strictEqual(out.decision, 'deny', `expected decision deny, got ${JSON.stringify(out)}`);
  });

  test('8e. a chain of a no-op guard then secret-guard still denies', () => {
    const noopDir = mkTmp('shim-noop');
    const noopPath = path.join(noopDir, 'noop.cjs');
    fs.writeFileSync(noopPath, 'process.stdin.resume(); process.stdout.write("{}"); process.exit(0);\n', 'utf8');
    const res = runShim('cursor', 'beforeShellExecution', ['node', noopPath, '++', 'node', secretGuardPath], { command: 'cat .env' });
    const out = JSON.parse(res.stdout || '{}');
    assert.strictEqual(out.permission, 'deny', `expected deny after chaining (first deny wins), got ${JSON.stringify(out)}`);
  });

  test('8f. unparseable stdin fails open: {} and exit 0', () => {
    const res = runShim('cursor', 'beforeShellExecution', ['node', secretGuardPath], null, 'not json{{{');
    assert.strictEqual(res.status, 0, `expected exit 0 on unparseable stdin, got ${res.status}`);
    const out = JSON.parse(res.stdout || '{}');
    assert.deepStrictEqual(out, {}, `expected {}, got ${JSON.stringify(out)}`);
  });
});

// ── 9. CLI ─────────────────────────────────────────────────────────────────────

section(9, 'CLI', ['engine/harness/cli.cjs', 'engine/harness/sources/claude.cjs', 'engine/harness/targets/codex.cjs'], () => {
  const cliPath = path.join(ROOT, 'engine', 'harness', 'cli.cjs');
  const home = mkTmp('cli-home');
  buildClaudeHome(home);
  buildCodexHome(home);
  const storageDir = mkTmp('cli-storage');

  function runCli(args) {
    return spawnSync(process.execPath, [cliPath, ...args], { cwd: ROOT, encoding: 'utf8', windowsHide: true, timeout: 20000 });
  }

  test('9a. port applies and exits 0, printing a table line per applied target', () => {
    const res = runCli(['port', '--home', home, '--storage', storageDir]);
    assert.strictEqual(res.status, 0, `expected exit 0, got ${res.status}; stderr: ${res.stderr}`);
    const lines = (res.stdout || '').split(/\r?\n/).filter((l) => /codex/i.test(l));
    assert(lines.length > 0, `expected at least 1 table line naming codex, got 0. stdout:\n${res.stdout}`);
  });

  test('9b. port --check exits 0 immediately after a clean apply', () => {
    const res = runCli(['port', '--home', home, '--storage', storageDir, '--check']);
    assert.strictEqual(res.status, 0, `expected exit 0, got ${res.status}; stderr: ${res.stderr}`);
  });

  test('9c. drifting AGENTS.md makes port --check exit 1 (L1 proof)', () => {
    const agentsMdPath = path.join(home, '.codex', 'AGENTS.md');
    fs.appendFileSync(agentsMdPath, '\nhand edit\n');
    const res = runCli(['port', '--home', home, '--storage', storageDir, '--check']);
    assert.strictEqual(res.status, 1, `expected exit 1 on drift, got ${res.status}; stdout: ${res.stdout}`);
  });

  test('9d. explain prints the sse drop reason', () => {
    const res = runCli(['explain', '--home', home, '--storage', storageDir]);
    assert.strictEqual(res.status, 0, `expected exit 0, got ${res.status}; stderr: ${res.stderr}`);
    assert(/sse/i.test(res.stdout) && /events/i.test(res.stdout), `expected the sse/events drop reason in stdout:\n${res.stdout}`);
  });
});

console.log(`\n[reg-harness] ${passed} passed / ${failed} failed / ${skipped} skipped`);
process.exit(failed > 0 ? 1 : 0);
