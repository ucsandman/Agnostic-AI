/**
 * engine/harness/targets/codex.cjs — render the bundle into the Codex CLI.
 *
 * Codex adopted a near-clone of Claude Code's hook dialect, so most of the work
 * is a rename (Claude tool tokens -> Codex tool tokens) plus one thing no other
 * target needs: Codex refuses to run a hook it has not been shown in `/hooks`,
 * unless config.toml already carries a `[hooks.state]` entry whose `trusted_hash`
 * matches Codex's own hash of that hook's identity. Reproducing that hash is what
 * makes a ported harness live on the next run instead of after a manual review;
 * `selfTestTrustHash()` keeps a value Codex itself wrote as the proof that the
 * scheme has not changed under us.
 *
 * config.toml is the user's file. Every write here happens inside a marked region
 * (hooks, skills, mcp); everything outside is preserved.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const common = require('../common.cjs');
const toml = require('../toml.cjs');
const { stripSections } = common;

const ID = 'codex';
const COMPONENTS = ['rules', 'identity', 'hooks', 'skills', 'agents', 'commands', 'mcp', 'permissions'];

// Events Codex 0.153 exposes (developers.openai.com/codex/hooks, read 2026-09-05).
const CODEX_EVENTS = new Set([
  'SessionStart', 'SessionEnd', 'UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'PostToolUse',
  'PreCompact', 'PostCompact', 'SubagentStart', 'SubagentStop', 'Stop', 'Interrupt',
]);

// Claude tool names -> Codex matcher tokens. `null` drops the token; a token that
// is not listed passes through untouched (Codex-native names, `mcp__.*`, regexes).
const TOOL_MAP = {
  Bash: 'Bash', PowerShell: 'Bash',
  Edit: 'Edit', Write: 'Write', MultiEdit: 'Edit', NotebookEdit: 'Edit',
  Agent: 'Agent', Task: 'Agent', Workflow: 'Agent',
  Read: null, Glob: null, Grep: null, TaskStop: null, WebFetch: null, WebSearch: null,
};

const HANDLER_KEYS = ['type', 'command', 'timeout', 'statusMessage', 'async', 'additionalContextLimit'];

// The personal predecessor of this adapter (a retired per-machine sync script)
// wrote its own regions into the same file. Remove them so the two do not fight.
const LEGACY_HOOK_REGION = /\n*# >>> harness-sync hook trust start[\s\S]*?# <<< harness-sync hook trust end\n?/g; // old-ref-ok: markers still present in installed configs
const LEGACY_SKILL_REGION = /\n*# >>> harness-sync skills start[\s\S]*?# <<< harness-sync skills end\n?/g; // old-ref-ok: markers still present in installed configs

// ---------------------------------------------------------------------------
// Small shared helpers
// ---------------------------------------------------------------------------
const readText = common.readText;
const isTrue = (v) => v === true || v === 'true'; // frontmatter round-trips booleans as strings
const tildeOf = (p, ctx) => common.tildePath(p, ctx.home);
/** Both --check and --dry-run mean "touch nothing"; ctx.write already knows, direct fs calls do not. */
const readOnly = (ctx) => Boolean(ctx.check || ctx.dryRun);

function statusOf(files, extra = []) {
  const actions = files.map((f) => f.action).concat(extra);
  // A real directory we refuse to replace is a steady state (reported in
  // `dropped`), not a hand edit: only a hand-edited file makes the component "skipped".
  if (actions.some((a) => a === 'skipped-hand-edited')) return 'skipped';
  if (actions.some((a) => a === 'would-write' || a === 'would-link' || a === 'would-prune' || a === 'would-remove')) return 'stale';
  if (actions.some((a) => a === 'written' || a === 'linked' || a === 'pruned' || a === 'removed')) return 'written';
  return 'synced';
}

/** A user-supplied exclusion regex must not crash the port; treat a bad one as a literal. */
function matcherFor(pattern) {
  try { return new RegExp(pattern); } catch (_) { return { test: (s) => String(s).includes(pattern) }; }
}

/** The script a hook command runs, for the human-readable list in AGENTS.md. */
function scriptName(command) {
  const m = String(command).match(/([A-Za-z0-9_-]+)\.(?:cjs|mjs|js|ps1|py|sh)\b/);
  return m ? m[1] : String(command).trim().split(/\s+/)[0];
}

function readdirSafe(dir) {
  try { return fs.readdirSync(dir, { withFileTypes: true }); } catch (_) { return []; }
}

/** `ctx.state.owned.codex.<kind>`, created on demand. */
function ownedList(ctx, kind) {
  ctx.state.owned = ctx.state.owned || {};
  ctx.state.owned[ID] = ctx.state.owned[ID] || {};
  const current = ctx.state.owned[ID][kind];
  return Array.isArray(current) ? current : [];
}
function setOwned(ctx, kind, names) {
  ctx.state.owned = ctx.state.owned || {};
  ctx.state.owned[ID] = ctx.state.owned[ID] || {};
  ctx.state.owned[ID][kind] = names.slice().sort();
}

/**
 * Put `body` in the marked region of `text`, cleaning what `clean` names outside it.
 *
 * common.replaceRegion always appends, and three components (hooks, skills, mcp)
 * share config.toml: re-appending an unchanged region would reorder the file on
 * every run and the port would never report "synced". So a region that already
 * holds exactly what we would write, in a file that needs no cleaning, is left
 * where it is.
 */
function upsertRegion(text, markers, body, clean) {
  const strip = (t) => common.replaceRegion(t, markers, '');
  const stripped = strip(text);
  const base = clean ? clean(stripped) : stripped;
  const existing = common.readRegion(text, markers);
  const desired = String(body).trimEnd();
  const current = existing === null ? '' : existing.trimEnd();
  if (current === desired && base === stripped) return text;
  return common.replaceRegion(base, markers, body);
}

// ---------------------------------------------------------------------------
// Hook translation (shared by rules() and hooks(): AGENTS.md lists exactly the
// hooks config.toml will carry, so the two can never disagree)
// ---------------------------------------------------------------------------
function translateMatcher(matcher) {
  if (matcher == null || matcher === '' || matcher === '*') return undefined; // omit = match all
  const out = [];
  for (const token of String(matcher).split('|')) {
    const mapped = Object.prototype.hasOwnProperty.call(TOOL_MAP, token) ? TOOL_MAP[token] : token;
    if (mapped && !out.includes(mapped)) out.push(mapped);
  }
  return out.length ? out.join('|') : null; // null = every token dropped, drop the group
}

function translateHooks(ctx) {
  const events = {};
  const dropped = [];
  const kept = [];
  const excludes = ((ctx.port && ctx.port.hooks && ctx.port.hooks.exclude) || [])
    .filter((e) => e && e.match)
    .map((e) => ({ re: matcherFor(e.match), reason: e.reason || `excluded by core/port.json (${e.match})` }));

  for (const [event, groups] of Object.entries((ctx.bundle.hooks && ctx.bundle.hooks.events) || {})) {
    if (!CODEX_EVENTS.has(event)) {
      dropped.push({ item: `hook event ${event}`, reason: 'no such Codex event' });
      continue;
    }
    for (const group of groups || []) {
      const matcher = translateMatcher(group.matcher);
      if (matcher === null) {
        dropped.push({ item: `${event} [${group.matcher}]`, reason: 'no Codex tool behind this matcher' });
        continue;
      }
      const handlers = [];
      for (const h of (group && group.hooks) || []) {
        if (!h || h.type !== 'command' || !h.command) continue;
        const ex = excludes.find((e) => e.re.test(h.command));
        if (ex) {
          dropped.push({ item: `${event}: ${scriptName(h.command)}`, reason: ex.reason });
          continue;
        }
        const out = {};
        for (const key of HANDLER_KEYS) if (h[key] !== undefined && h[key] !== null) out[key] = h[key];
        // A `~/` inside a hook command is expanded here (port.json stays
        // machine-neutral; Codex does not expand it on Windows).
        if (typeof out.command === 'string') out.command = out.command.replace(/(^|["'\s])~\//g, `$1${String(ctx.home).replace(/\\/g, '/')}/`);
        out.type = 'command';
        handlers.push(out);
        kept.push(h.command);
      }
      if (!handlers.length) continue;
      (events[event] = events[event] || []).push(matcher === undefined ? { hooks: handlers } : { matcher, hooks: handlers });
    }
  }

  // Target-only hooks from core/port.json, already in the Codex dialect.
  const extra = (ctx.port && ctx.port.hooks && ctx.port.hooks.extra && ctx.port.hooks.extra[ID]) || {};
  for (const [event, groups] of Object.entries(extra)) {
    if (!CODEX_EVENTS.has(event)) {
      dropped.push({ item: `port.json hooks.extra.${ID}.${event}`, reason: 'no such Codex event' });
      continue;
    }
    for (const group of groups || []) {
      const handlers = [];
      for (const h of (group && group.hooks) || []) {
        if (!h || h.type !== 'command' || !h.command) continue;
        const out = {};
        for (const key of HANDLER_KEYS) if (h[key] !== undefined && h[key] !== null) out[key] = h[key];
        // A `~/` inside a hook command is expanded here (port.json stays
        // machine-neutral; Codex does not expand it on Windows).
        if (typeof out.command === 'string') out.command = out.command.replace(/(^|["'\s])~\//g, `$1${String(ctx.home).replace(/\\/g, '/')}/`);
        out.type = 'command';
        handlers.push(out);
        kept.push(h.command);
      }
      if (!handlers.length) continue;
      (events[event] = events[event] || []).push(group.matcher != null && group.matcher !== ''
        ? { matcher: group.matcher, hooks: handlers }
        : { hooks: handlers });
    }
  }

  return { events, dropped, names: [...new Set(kept.map(scriptName))].sort() };
}

// ---------------------------------------------------------------------------
// Trust hashes
//
// Codex records trust per hook as sha256 over a normalized identity
// (codex-rs/hooks/src/engine/discovery.rs::hook_hash, tag rust-v0.153.4):
//   identity = { event_name: <snake label>, matcher?, hooks: [normalized handler] }
//   normalized handler = { type:"command", command, async, timeout (default 600),
//                          statusMessage?, additionalContextLimit? (omitted when 2500) }
//   hash = sha256( canonical JSON: keys sorted recursively, compact )
// ---------------------------------------------------------------------------
const EVENT_LABEL = {
  PreToolUse: 'pre_tool_use', PermissionRequest: 'permission_request', PostToolUse: 'post_tool_use',
  PreCompact: 'pre_compact', PostCompact: 'post_compact', SessionStart: 'session_start', SessionEnd: 'session_end',
  UserPromptSubmit: 'user_prompt_submit', SubagentStart: 'subagent_start', SubagentStop: 'subagent_stop',
  Stop: 'stop', Interrupt: 'interrupt',
};
const NO_MATCHER_EVENTS = new Set(['UserPromptSubmit', 'Stop', 'Interrupt']);
const CONTEXT_EVENTS = new Set(['PreToolUse', 'PostToolUse', 'SessionStart', 'UserPromptSubmit', 'SubagentStart']);

function canonical(v) {
  if (Array.isArray(v)) return v.map(canonical);
  if (v && typeof v === 'object') {
    const o = {};
    for (const k of Object.keys(v).sort()) o[k] = canonical(v[k]);
    return o;
  }
  return v;
}

function hookHash(event, matcher, h) {
  let timeout = h.timeout == null ? 600 : Number(h.timeout);
  if (event === 'SessionEnd' || event === 'Interrupt') timeout = Math.min(Math.max(h.timeout == null ? 1 : Number(h.timeout), 1), 3);
  else timeout = Math.max(timeout, 1);
  const handler = { type: 'command', command: h.command, async: !!h.async, timeout };
  if (h.statusMessage) handler.statusMessage = h.statusMessage;
  if (CONTEXT_EVENTS.has(event) && h.additionalContextLimit != null && h.additionalContextLimit !== 2500) {
    handler.additionalContextLimit = h.additionalContextLimit;
  }
  const identity = { event_name: EVENT_LABEL[event], hooks: [handler] };
  if (!NO_MATCHER_EVENTS.has(event) && matcher != null) identity.matcher = matcher;
  return 'sha256:' + crypto.createHash('sha256').update(JSON.stringify(canonical(identity))).digest('hex');
}

/**
 * The proof that the scheme above still matches Codex's. The constant is a hash
 * Codex itself wrote into config.toml on 2026-09-05 for the hook described here;
 * it is a test vector, not configuration. When this fails, the hooks are still
 * written but the trust entries are withheld, because a wrong hash is worse than
 * no hash: Codex would silently never run them.
 */
function selfTestTrustHash() {
  const known = hookHash('PreToolUse', 'Bash|Edit|Write|MultiEdit|apply_patch|mcp__.*', {
    command: 'node "C:/Projects/agnostic-ai/engine/hooks/dashclaw-guard.cjs"',
    timeout: 60,
  });
  return known === 'sha256:ada757977119bf80c0f1c6fecb2e0ce58394b725fe690d40dcd2a4fbc41f4f9c';
}

// ---------------------------------------------------------------------------
// rules
// ---------------------------------------------------------------------------
const TOOL_TABLE = [
  '| Rule says | In Codex |',
  '|---|---|',
  '| Bash / PowerShell | `shell` (`Bash` at the hook layer, `shell_command` in transcripts) |',
  '| Edit / Write / MultiEdit | `apply_patch` |',
  '| Read / Grep / Glob | `shell` (`cat`, `rg`, `ls`) |',
  '| Agent / Task | `spawn_agent` with `agent_type` |',
  '| Workflow | no equivalent; fan out with `spawn_agent` and collect with `wait_agent` |',
  '| Artifact | no equivalent; write a file and say where it is |',
];

/** Codex's own model line, read from config.toml so nothing is asserted from memory. */
function codexModelLine(configFile) {
  const text = readText(configFile);
  if (text == null) return { model: '(unset)', effort: '(unset)' };
  const { data } = toml.parse(text);
  return {
    model: typeof data.model === 'string' && data.model ? data.model : '(unset)',
    effort: typeof data.model_reasoning_effort === 'string' && data.model_reasoning_effort ? data.model_reasoning_effort : '(unset)',
  };
}

function differencesSection(ctx) {
  const configFile = ctx.target.hooksConfigFile || path.join(ctx.target.home, 'config.toml');
  const { model, effort } = codexModelLine(configFile);
  const hooks = translateHooks(ctx).names;
  const agents = (ctx.bundle.agents || []).map((a) => `\`${a.name}\``);
  const prompts = (ctx.bundle.commands || []).map((c) => `\`/prompts:${c.name}\``);
  const list = (items) => (items.length ? items.join(', ') : '(none)');
  const skillsLine = ctx.target.skillsDir && ctx.bundle.skills && ctx.bundle.skills.sourceDir
    ? `Skills are not copied: each one is linked from \`${tildeOf(ctx.bundle.skills.sourceDir, ctx)}\` into \`${tildeOf(ctx.target.skillsDir, ctx)}\`, so an edit at the source is live here immediately.`
    : 'Skills are not ported to this client.';
  return [
    '## How this harness differs from the source',
    '',
    'The safety layer is shared, not reimplemented: the hook scripts below are the',
    'same files the source client runs, generated into',
    `\`${tildeOf(configFile, ctx)}\` and pre-trusted, so a fix lands in both at once.`,
    '',
    'Tool-name mapping when a rule below names a source tool:',
    '',
    ...TOOL_TABLE,
    '',
    `Model: Codex runs \`${model}\` at \`${effort}\` per \`${tildeOf(configFile, ctx)}\` (read at`,
    'generation time, never asserted from memory). Verify a model id resolves before',
    'writing it anywhere; a wrong id crashes the run.',
    '',
    `Hooks active in this harness: ${list(hooks.map((n) => `\`${n}\``))}.`,
    '',
    `Subagents (\`spawn_agent\` with \`agent_type\`): ${list(agents)}.`,
    '',
    `Slash commands: ${list(prompts)}.`,
    '',
    skillsLine,
  ].join('\n');
}

function rules(ctx) {
  try {
    const target = ctx.target;
    if (!target.rulesFile) return { status: 'unsupported', files: [], dropped: [], note: 'no rulesFile in the target registry' };
    const preamble = String(target.preamble || '').trimEnd();
    const header = preamble.split(/\r?\n/, 1)[0].trim();
    const dropSections = (ctx.port && ctx.port.rules && ctx.port.rules.dropSectionsForTargets) || [];
    const body = stripSections(ctx.bundle.rules || '', dropSections);
    const source = (ctx.bundle.manifest && ctx.bundle.manifest.source) || 'source';

    const parts = [preamble, '', differencesSection(ctx), '', '---', '', '# The agreement', '', body];
    // A target-specific addendum (core/port.json rules.addenda.<id> -> a markdown
    // file in the repo) carries guidance that only makes sense in this client.
    const addendumRel = ctx.port && ctx.port.rules && ctx.port.rules.addenda && ctx.port.rules.addenda[ID];
    const addendum = addendumRel ? readText(path.resolve((ctx.port && ctx.port.baseDir) || common.ROOT, addendumRel)) : null;
    if (addendum && addendum.trim()) parts.push('', '---', '', addendum.trim());
    if (ctx.bundle.identity) parts.push('', '---', '', '# Identity', '', String(ctx.bundle.identity).trim());
    parts.push('', `<!-- ${common.GENERATED_MARK} from the ${source} harness -->`, '');
    const content = parts.join('\n');

    const res = ctx.write(target.rulesFile, content, { header });
    const dropped = dropSections.map((s) => ({ item: `rules section "${s}"`, reason: 'core/port.json rules.dropSectionsForTargets' }));
    return {
      status: statusOf([{ path: target.rulesFile, action: res.action }]),
      files: [{ path: target.rulesFile, action: res.action }],
      dropped,
      note: `identity ${ctx.bundle.identity ? 'inlined' : 'absent'}, ${dropSections.length} section(s) dropped`,
    };
  } catch (err) {
    return { status: 'error', files: [], dropped: [], error: err.message };
  }
}

// ---------------------------------------------------------------------------
// identity — Codex has no separate identity file
// ---------------------------------------------------------------------------
function identity() {
  return { status: 'synced', files: [], dropped: [], note: 'inlined in AGENTS.md' };
}

// ---------------------------------------------------------------------------
// hooks
// ---------------------------------------------------------------------------
function renderHookTables(events) {
  const lines = [];
  for (const [event, groups] of Object.entries(events)) {
    for (const group of groups) {
      lines.push(`[[hooks.${event}]]`);
      if (group.matcher != null) lines.push(`matcher = ${common.tomlStr(group.matcher)}`);
      for (const h of group.hooks) {
        lines.push(`[[hooks.${event}.hooks]]`);
        for (const key of HANDLER_KEYS) {
          const v = h[key];
          if (v === undefined || v === null) continue;
          lines.push(`${key} = ${typeof v === 'string' ? common.tomlStr(v) : String(v)}`);
        }
      }
      lines.push('');
    }
  }
  return lines;
}

/** Codex writes the state key as a literal path; quote it the way TOML allows. */
function stateKey(configFile, event, gi, hi) {
  const key = `${configFile}:${EVENT_LABEL[event]}:${gi}:${hi}`;
  return key.includes("'") ? common.tomlStr(key) : `'${key}'`;
}

/**
 * Strip `[hooks.state.'<this config file>:...']` blocks that live outside our
 * region — left by Codex itself or by an older sync. A block is its header plus
 * the non-blank, non-table lines under it, so neighbouring tables survive.
 * Codex writes the path double-quoted with escaped separators, the predecessor
 * wrote it single-quoted and literal; both forms are matched.
 */
function strayStateRegex(configFile) {
  const forms = [...new Set([configFile, configFile.replace(/\\/g, '\\\\')])].map(common.escapeRe);
  return new RegExp(`\\[hooks\\.state\\.(?:'|")(?:${forms.join('|')}):[^'"]*(?:'|")\\]\\r?\\n(?:[^\\n\\[][^\\n]*\\r?\\n?)*`, 'g');
}

function hooks(ctx) {
  try {
    const configFile = ctx.target.hooksConfigFile;
    if (!configFile) return { status: 'unsupported', files: [], dropped: [], note: 'no hooksConfigFile in the target registry' };
    const { events, dropped, names } = translateHooks(ctx);
    const notes = [];

    const trusted = selfTestTrustHash();
    if (!trusted) {
      notes.push('trust-hash self-test failed: Codex changed its hook identity scheme; open /hooks in Codex to trust them');
    }

    const entries = [];
    if (trusted) {
      for (const [event, groups] of Object.entries(events)) {
        groups.forEach((group, gi) => group.hooks.forEach((h, hi) => {
          entries.push(`[hooks.state.${stateKey(configFile, event, gi, hi)}]\nenabled = true\ntrusted_hash = "${hookHash(event, group.matcher, h)}"`);
        }));
      }
    }

    const body = [...renderHookTables(events), ...(entries.length ? [entries.join('\n\n')] : [])].join('\n').trimEnd();
    const text = readText(configFile) || '';
    const stray = strayStateRegex(configFile);
    if (LEGACY_HOOK_REGION.test(text)) {
      LEGACY_HOOK_REGION.lastIndex = 0;
      dropped.push({ item: 'legacy hook trust region', reason: 'replaced legacy region' });
    }
    LEGACY_HOOK_REGION.lastIndex = 0;
    const clean = (t) => t.replace(LEGACY_HOOK_REGION, '\n').replace(stray, '');
    const next = upsertRegion(text, common.regionMarkers('hooks'), body, clean);

    const res = ctx.write(configFile, next, { region: true });
    const files = [{ path: configFile, action: res.action }];

    // Codex warns when hooks are configured in two places. Archiving is the
    // operator's call: a rename here could disable a hook they still rely on.
    const legacyJson = path.join(ctx.target.home, 'hooks.json');
    const legacy = common.readJSON(legacyJson);
    if (legacy && typeof legacy === 'object' && legacy.hooks && typeof legacy.hooks === 'object') {
      dropped.push({ item: tildeOf(legacyJson, ctx), reason: 'legacy hooks.json present: Codex warns when hooks live in both files; archive it by hand' });
      files.push({ path: legacyJson, action: 'inspected' });
    }

    const count = Object.values(events).reduce((n, g) => n + g.reduce((m, x) => m + x.hooks.length, 0), 0);
    notes.push(`${count} hook(s) in ${Object.keys(events).length} event(s): ${names.join(', ') || '(none)'}${trusted ? `, ${entries.length} pre-trusted` : ''}`);
    return { status: statusOf(files), files, dropped, note: notes.join(' | ') };
  } catch (err) {
    return { status: 'error', files: [], dropped: [], error: err.message };
  }
}

// ---------------------------------------------------------------------------
// skills
// ---------------------------------------------------------------------------
/**
 * Real (non-link) skill directories under the Codex skills dir that duplicate a
 * skill Codex already reads elsewhere, plus anything core/port.json names in
 * skills.codexDisable. Codex re-sends its whole skill catalog every turn, so a
 * skill listed twice is paid for twice.
 */
function duplicateSkillPaths(ctx) {
  const found = [];
  const skillsDir = ctx.target.skillsDir;
  const roots = [ctx.bundle.skills && ctx.bundle.skills.sourceDir, ...(ctx.target.sharedSkillDirs || [])].filter(Boolean);
  for (const e of readdirSafe(skillsDir)) {
    if (e.name.startsWith('.') || e.isSymbolicLink() || !e.isDirectory()) continue;
    const own = path.join(skillsDir, e.name, 'SKILL.md');
    if (!fs.existsSync(own)) continue;
    if (roots.some((r) => fs.existsSync(path.join(r, e.name, 'SKILL.md')))) found.push(own);
  }
  for (const pattern of (ctx.port && ctx.port.skills && ctx.port.skills.codexDisable) || []) {
    let candidates = [ctx.target.home];
    for (const part of String(pattern).split('/')) {
      candidates = candidates.flatMap((base) => (part === '*'
        ? readdirSafe(base).map((e) => path.join(base, e.name))
        : [path.join(base, part)]));
    }
    for (const c of candidates) if (fs.existsSync(c)) found.push(c);
  }
  return [...new Set(found)].sort();
}

function skills(ctx) {
  try {
    const skillsDir = ctx.target.skillsDir;
    if (!skillsDir) return { status: 'unsupported', files: [], dropped: [], note: 'no skillsDir in the target registry' };
    // A whole-directory junction (what the legacy sync created) would send every
    // per-skill link into someone else's directory. Refuse and say so.
    const dirLink = common.readLinkTarget(skillsDir);
    if (dirLink !== null) {
      return {
        status: 'skipped',
        files: [{ path: skillsDir, action: 'skipped-real-directory' }],
        dropped: [{ item: `skills dir ${tildeOf(skillsDir, ctx)}`, reason: `it is a link to ${dirLink}; per-skill links would land there` }],
        note: `skills dir is a link to ${dirLink}; remove that link to get per-skill links`,
      };
    }
    const dropped = [];
    const files = [];
    const exclude = (ctx.port && ctx.port.skills && ctx.port.skills.exclude) || {};
    const shared = ctx.target.sharedSkillDirs || [];

    const wanted = [];
    for (const skill of (ctx.bundle.skills && ctx.bundle.skills.skills) || []) {
      if (exclude[skill.name]) { dropped.push({ item: `skill ${skill.name}`, reason: exclude[skill.name] }); continue; }
      const nativeDir = shared.find((d) => fs.existsSync(path.join(d, skill.name, 'SKILL.md')));
      if (nativeDir) {
        dropped.push({ item: `skill ${skill.name}`, reason: `already in the shared skills dir ${tildeOf(nativeDir, ctx)}, which Codex reads natively; linking it again would list it twice` });
        continue;
      }
      wanted.push(skill);
    }

    const dry = readOnly(ctx);
    if (!dry) fs.mkdirSync(skillsDir, { recursive: true });
    const linked = [];
    for (const skill of wanted) {
      const dest = path.join(skillsDir, skill.name);
      const res = common.link(skill.path, dest, { check: dry });
      files.push({ path: dest, action: res.action });
      if (res.action === 'skipped-real-directory') {
        dropped.push({ item: `skill ${skill.name}`, reason: `a real directory already lives at ${tildeOf(dest, ctx)}; it was left alone` });
        continue;
      }
      linked.push(skill.name);
    }

    // Prune only links this adapter created: a real directory or someone else's
    // link is never touched, whatever its name.
    const wantedNames = new Set(wanted.map((s) => s.name));
    const keep = new Set(linked);
    for (const name of ownedList(ctx, 'skills')) {
      if (keep.has(name)) continue;
      const dest = path.join(skillsDir, name);
      const target = common.readLinkTarget(dest);
      if (target === null) continue; // gone, or no longer a link: not ours to remove
      const reason = wantedNames.has(name) ? 'dangling' : 'no longer wanted';
      if (dry) { files.push({ path: dest, action: 'would-prune' }); continue; }
      if (!fs.existsSync(target) || !wantedNames.has(name)) {
        fs.rmSync(dest, { recursive: true, force: true });
        files.push({ path: dest, action: 'pruned' });
        dropped.push({ item: `skill link ${name}`, reason: `pruned (${reason})` });
      }
    }
    if (!dry) setOwned(ctx, 'skills', linked);

    // Duplicate-disable region in config.toml.
    const configFile = ctx.target.hooksConfigFile;
    let disabled = [];
    if (configFile && readText(configFile) != null) {
      disabled = duplicateSkillPaths(ctx);
      const body = disabled.map((p) => `[[skills.config]]\npath = ${common.tomlStr(p)}\nenabled = false`).join('\n\n');
      const text = readText(configFile) || '';
      if (LEGACY_SKILL_REGION.test(text)) {
        LEGACY_SKILL_REGION.lastIndex = 0;
        dropped.push({ item: 'legacy skills region', reason: 'replaced legacy region' });
      }
      LEGACY_SKILL_REGION.lastIndex = 0;
      const next = upsertRegion(text, common.regionMarkers('skills'), body, (t) => t.replace(LEGACY_SKILL_REGION, '\n'));
      const res = ctx.write(configFile, next, { region: true });
      files.push({ path: configFile, action: res.action });
    }

    return {
      status: statusOf(files),
      files,
      dropped,
      note: `${linked.length} linked, ${dropped.length} not ported, ${disabled.length} duplicate(s) disabled in config.toml`,
    };
  } catch (err) {
    return { status: 'error', files: [], dropped: [], error: err.message };
  }
}

// ---------------------------------------------------------------------------
// agents
// ---------------------------------------------------------------------------
function agentHeader(name, source, model, effort, readonly) {
  const modelLine = model
    ? `in Codex the model is fixed by this file (${model}, ${effort}).`
    : 'in Codex this agent inherits the main loop\'s model.';
  return `Generated by agnostic-ai from the ${source} harness agent ${name}. Codex port: "Agent tool"/"subagent_type" `
    + 'means spawn_agent with agent_type; Bash/PowerShell is the shell tool; Edit/Write is apply_patch; '
    + `Read/Grep/Glob are shell reads. Rules referring to a model guard describe the source harness; ${modelLine}`
    + (readonly ? ' This agent is read-only (sandbox_mode = "read-only").' : '');
}

function agents(ctx) {
  try {
    const dir = ctx.target.agentsDir;
    if (!dir) return { status: 'unsupported', files: [], dropped: [], note: 'no agentsDir in the target registry' };
    const ladder = (ctx.port && ctx.port.agents && ctx.port.agents.modelLadder && ctx.port.agents.modelLadder[ID]) || {};
    const source = (ctx.bundle.manifest && ctx.bundle.manifest.source) || 'source';
    const files = [];
    const dropped = [];
    const written = [];
    const slugs = new Set();

    for (const agent of ctx.bundle.agents || []) {
      const meta = agent.meta || {};
      const requested = meta.model || 'inherit';
      let model = null;
      let effort = null;
      if (requested !== 'inherit') {
        if (ladder[requested]) [model, effort] = ladder[requested];
        else { model = requested; effort = 'medium'; } // a raw model id passes through
      }
      if (model) slugs.add(model);
      const readonly = isTrue(meta.readonly);
      const lines = [
        `# ${common.GENERATED_MARK} from ${source} agent ${agent.name}`,
        `name = ${common.tomlStr(agent.name)}`,
        `description = ${common.tomlStr(meta.description || agent.name)}`,
      ];
      if (model) {
        lines.push(`model = ${common.tomlStr(model)}`);
        lines.push(`model_reasoning_effort = ${common.tomlStr(effort)}`);
      }
      if (readonly) lines.push('sandbox_mode = "read-only"');
      lines.push(`developer_instructions = ${common.tomlMultiline(`${agentHeader(agent.name, source, model, effort, readonly)}\n\n${String(agent.body).trim()}`)}`);
      lines.push('');
      const file = path.join(dir, `${agent.name}.toml`);
      const res = ctx.write(file, lines.join('\n'), { header: `# ${common.GENERATED_MARK} from ${source} agent ${agent.name}` });
      files.push({ path: file, action: res.action });
      if (res.action !== 'skipped-hand-edited') written.push(`${agent.name}.toml`);
    }

    // Prune agent files this adapter wrote whose source agent is gone.
    const keep = new Set(ctx.bundle.agents.map((a) => `${a.name}.toml`));
    for (const name of ownedList(ctx, 'agents')) {
      if (keep.has(name)) continue;
      const file = path.join(dir, name);
      if (!fs.existsSync(file)) continue;
      if (readOnly(ctx)) { files.push({ path: file, action: 'would-remove' }); continue; }
      if (ctx.backup) ctx.backup(file);
      fs.unlinkSync(file);
      delete ctx.state.files[file];
      files.push({ path: file, action: 'removed' });
      dropped.push({ item: `agent ${name}`, reason: 'no longer in the bundle; the generated file was removed (backed up)' });
    }
    if (!readOnly(ctx)) setOwned(ctx, 'agents', written);

    // A model id Codex cannot resolve crashes the spawn, so say so before it runs.
    const notes = [`${written.length} agent(s)`];
    const cache = readText(path.join(ctx.target.home, 'models_cache.json'));
    if (cache != null) {
      const unknown = [...slugs].filter((s) => !cache.includes(s));
      if (unknown.length) notes.push(`model id(s) not in models_cache.json: ${unknown.join(', ')}`);
    }
    return { status: statusOf(files), files, dropped, note: notes.join(' | ') };
  } catch (err) {
    return { status: 'error', files: [], dropped: [], error: err.message };
  }
}

// ---------------------------------------------------------------------------
// commands -> ~/.codex/prompts/<name>.md, invoked as /prompts:<name>
// ---------------------------------------------------------------------------
function commands(ctx) {
  try {
    const dir = ctx.target.commandsDir;
    if (!dir) return { status: 'unsupported', files: [], dropped: [], note: 'no commandsDir in the target registry' };
    const files = [];
    const dropped = [];
    const written = [];

    for (const command of ctx.bundle.commands || []) {
      const meta = {};
      if (command.meta && command.meta.description) meta.description = command.meta.description;
      if (command.meta && command.meta['argument-hint']) meta['argument-hint'] = command.meta['argument-hint'];
      const file = path.join(dir, `${command.name}.md`);
      const res = ctx.write(file, common.renderFrontmatter(meta, command.body));
      files.push({ path: file, action: res.action });
      if (res.action !== 'skipped-hand-edited') written.push(`${command.name}.md`);
    }

    const keep = new Set(ctx.bundle.commands.map((c) => `${c.name}.md`));
    for (const name of ownedList(ctx, 'commands')) {
      if (keep.has(name)) continue;
      const file = path.join(dir, name);
      if (!fs.existsSync(file)) continue;
      if (readOnly(ctx)) { files.push({ path: file, action: 'would-remove' }); continue; }
      if (ctx.backup) ctx.backup(file);
      fs.unlinkSync(file);
      delete ctx.state.files[file];
      files.push({ path: file, action: 'removed' });
      dropped.push({ item: `command ${name}`, reason: 'no longer in the bundle; the generated file was removed (backed up)' });
    }
    if (!readOnly(ctx)) setOwned(ctx, 'commands', written);

    return { status: statusOf(files), files, dropped, note: `${written.length} prompt(s) as /prompts:<name>` };
  } catch (err) {
    return { status: 'error', files: [], dropped: [], error: err.message };
  }
}

// ---------------------------------------------------------------------------
// mcp
// ---------------------------------------------------------------------------
const BARE_KEY = /^[A-Za-z0-9_-]+$/;
const tomlKey = (k) => (BARE_KEY.test(k) ? k : common.tomlStr(k));
const envRef = (v) => (typeof v === 'string' ? (v.match(/^\$\{([A-Za-z0-9_]+)\}$/) || [])[1] : undefined);
const inlineTable = (pairs) => `{ ${pairs.map(([k, v]) => `${tomlKey(k)} = ${common.tomlStr(v)}`).join(', ')} }`;

function renderServer(name, server) {
  const lines = [`[mcp_servers.${tomlKey(name)}]`];
  if (server.transport === 'stdio') {
    lines.push(`command = ${common.tomlStr(server.command)}`);
    if (Array.isArray(server.args) && server.args.length) {
      lines.push(`args = [${server.args.map((a) => common.tomlStr(a)).join(', ')}]`);
    }
    const literal = Object.entries(server.env || {}).filter(([, v]) => !envRef(v));
    const refs = Object.entries(server.env || {}).filter(([, v]) => envRef(v));
    if (literal.length) lines.push(`env = ${inlineTable(literal)}`);
    // A "${NAME}" placeholder means the value never left the source machine:
    // Codex reads NAME from the environment it was launched with.
    if (refs.length) lines.push(`env_vars = [${refs.map(([k]) => common.tomlStr(k)).join(', ')}]`);
    if (server.cwd) lines.push(`cwd = ${common.tomlStr(server.cwd)}`);
  } else {
    lines.push(`url = ${common.tomlStr(server.url)}`);
    const literal = Object.entries(server.headers || {}).filter(([, v]) => !envRef(v));
    const refs = Object.entries(server.headers || {}).filter(([, v]) => envRef(v));
    if (literal.length) lines.push(`http_headers = ${inlineTable(literal)}`);
    if (refs.length) lines.push(`env_http_headers = ${inlineTable(refs.map(([k, v]) => [k, envRef(v)]))}`);
  }
  return lines.join('\n');
}

function mcp(ctx) {
  try {
    const configFile = ctx.target.mcpConfigFile;
    if (!configFile) return { status: 'unsupported', files: [], dropped: [], note: 'no mcpConfigFile in the target registry' };
    const markers = common.regionMarkers('mcp');
    const text = readText(configFile) || '';
    // What the user configured themselves: everything the file says with our own
    // region taken out. A second table for the same server breaks Codex's load.
    const { data } = toml.parse(common.replaceRegion(text, markers, ''));
    const existing = new Set(Object.keys((data && data.mcp_servers) || {}));
    const exclude = (ctx.port && ctx.port.mcp && ctx.port.mcp.exclude) || {};

    const dropped = [];
    const blocks = [];
    for (const [name, server] of Object.entries((ctx.bundle.mcp && ctx.bundle.mcp.servers) || {})) {
      if (exclude[name]) { dropped.push({ item: `mcp ${name}`, reason: exclude[name] }); continue; }
      if (existing.has(name)) { dropped.push({ item: `mcp ${name}`, reason: 'already configured in config.toml' }); continue; }
      if (server.transport === 'sse') { dropped.push({ item: `mcp ${name}`, reason: 'Codex has no SSE transport' }); continue; }
      blocks.push(renderServer(name, server));
    }

    const next = upsertRegion(text, markers, blocks.join('\n\n'));
    const res = ctx.write(configFile, next, { region: true });
    const files = [{ path: configFile, action: res.action }];
    return { status: statusOf(files), files, dropped, note: `${blocks.length} server(s) written, ${dropped.length} not ported` };
  } catch (err) {
    return { status: 'error', files: [], dropped: [], error: err.message };
  }
}

// ---------------------------------------------------------------------------
// permissions -> Starlark prefix rules
// ---------------------------------------------------------------------------
const DECISION = { allow: 'allow', deny: 'forbidden', ask: 'prompt' };

/** `Bash(git *)` -> `["git"]`; anything Codex cannot express as a leading-argument match is dropped. */
function toPrefixRule(pattern, decision) {
  const m = String(pattern).match(/^Bash\(([\s\S]*)\)$/);
  if (!m) {
    const tool = (String(pattern).match(/^([A-Za-z_][A-Za-z0-9_]*)\(/) || [])[1];
    return { drop: tool ? `${tool}() has no Codex equivalent; only Bash(...) becomes a prefix rule` : 'not a Bash(...) pattern; only Bash(...) becomes a prefix rule' };
  }
  // Claude Code's `Bash(git push --force:*)` means "the command starts with
  // `git push --force`": the `:*` is a whole-string prefix operator, which is
  // exactly a Codex prefix rule. Strip it before tokenising.
  const tokens = m[1].trim().replace(/:\*$/, '').trim().split(/\s+/).filter(Boolean);
  if (tokens[tokens.length - 1] === '*') tokens.pop(); // trailing * IS a prefix rule
  if (!tokens.length) return { drop: 'matches every command; a Codex prefix rule needs at least one leading argument' };
  const bad = tokens.find((t) => t.includes('*'));
  if (bad) return { drop: `"${bad}" is a partial-token wildcard; Codex prefix rules match whole leading arguments` };
  return { line: `prefix_rule(pattern = [${tokens.map((t) => JSON.stringify(t)).join(', ')}], decision = ${JSON.stringify(decision)})` };
}

function permissions(ctx) {
  try {
    const file = ctx.target.permissionsFile;
    if (!file) return { status: 'unsupported', files: [], dropped: [], note: 'no permissionsFile in the target registry' };
    const source = (ctx.bundle.manifest && ctx.bundle.manifest.source) || 'source';
    const dropped = [];
    const seen = new Set();
    const sections = [];
    // forbidden first, then prompt, then allow: a broad allow written above a
    // narrow deny would make the deny unreachable under first-match evaluation.
    for (const kind of ['deny', 'ask', 'allow']) {
      const lines = [];
      for (const pattern of (ctx.bundle.permissions && ctx.bundle.permissions[kind]) || []) {
        const out = toPrefixRule(pattern, DECISION[kind]);
        if (out.drop) { dropped.push({ item: `${kind}: ${pattern}`, reason: out.drop }); continue; }
        if (seen.has(out.line)) continue;
        seen.add(out.line);
        lines.push(out.line);
      }
      if (lines.length) sections.push(`# ${kind} -> ${DECISION[kind]}\n${lines.join('\n')}`);
    }

    if (!sections.length) {
      // Nothing survived. Remove the file only if this adapter wrote it before.
      if (!Object.prototype.hasOwnProperty.call(ctx.state.files, file) || !fs.existsSync(file)) {
        return { status: 'synced', files: [], dropped, note: 'no Bash(...) permission maps to a Codex prefix rule' };
      }
      if (readOnly(ctx)) return { status: 'stale', files: [{ path: file, action: 'would-remove' }], dropped, note: 'the generated rules file is now empty' };
      if (ctx.backup) ctx.backup(file);
      fs.unlinkSync(file);
      delete ctx.state.files[file];
      return { status: 'written', files: [{ path: file, action: 'removed' }], dropped, note: 'no rule survived translation; the generated file was removed' };
    }

    const header = `# ${common.GENERATED_MARK} from the ${source} harness — do not hand-edit.`;
    const content = [header, '# Edit permissions in the source client and re-run the port.', '', ...sections, ''].join('\n');
    const res = ctx.write(file, content, { header });
    const files = [{ path: file, action: res.action }];
    return { status: statusOf(files), files, dropped, note: `${seen.size} prefix rule(s), ${dropped.length} not ported` };
  } catch (err) {
    return { status: 'error', files: [], dropped: [], error: err.message };
  }
}

module.exports = {
  id: ID,
  components: COMPONENTS,
  rules, identity, hooks, skills, agents, commands, mcp, permissions,
  // exported for the port's own tests
  _internal: { translateHooks, translateMatcher, hookHash, selfTestTrustHash, toPrefixRule, upsertRegion },
};
