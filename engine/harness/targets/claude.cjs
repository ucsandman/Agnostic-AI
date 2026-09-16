/**
 * engine/harness/targets/claude.cjs — Claude Code as a TARGET.
 *
 * The reverse direction: a harness captured from another client (Codex, say)
 * rendered back into ~/.claude. Claude Code's dialect is the bundle's own
 * dialect, so hooks and matcher tokens need no shim and almost no translation.
 *
 * Surfaces written here:
 *   ~/.claude/agnostic-rules.md  the agreement (plus the @import line in CLAUDE.md)
 *   ~/.claude/SOUL.md            identity
 *   ~/.claude/settings.json      hooks + permissions (managed keys, user keys kept)
 *   ~/.claude.json               mcpServers
 *   ~/.claude/agents/*.md        subagents
 *   ~/.claude/commands/*.md      slash commands
 *   ~/.claude/skills/<name>      junctions to the captured skills
 */

const path = require('path');
const common = require('../common.cjs');
const bundleLib = require('../bundle.cjs');
const generic = require('./generic.cjs');

const I = generic._internals;

// Codex renames the edit tool; every other Claude matcher token round-trips.
const MATCHER_MAP = { apply_patch: 'Edit|Write', spawn_agent: 'Agent', wait_agent: 'Agent' };

/** `@~/.claude/agnostic-rules.md` — present in any spelling that resolves to the rules file. */
function importsRules(text, rulesFile, home) {
  const want = path.resolve(rulesFile).toLowerCase();
  for (const line of String(text || '').split(/\r?\n/)) {
    const m = /^@(\S+)\s*$/.exec(line.trim());
    if (m && path.resolve(common.expandPath(m[1], home)).toLowerCase() === want) return true;
  }
  return false;
}

function rules(ctx) {
  const base = generic.rules(ctx);
  if (base.status === 'unsupported' || base.status === 'error') return base;

  const rulesFile = I.at(ctx, ctx.target.rulesFile);
  // beside the client's configured home (CLAUDE_CONFIG_DIR moves it), not a hardcoded ~/.claude
  const claudeMd = path.join(I.at(ctx, ctx.target.home) || path.join(ctx.home, '.claude'), 'CLAUDE.md');
  const importLine = `@${common.tildePath(rulesFile, ctx.home)}`;
  const existing = common.readText(claudeMd);

  if (existing !== null && importsRules(existing, rulesFile, ctx.home)) {
    base.files.push({ path: claudeMd, action: 'unchanged' });
    return I.result(ctx, base.files, base.dropped, base.note);
  }
  // Never rewrite what is already there: append the import, or create the
  // smallest file that loads the agreement.
  const next = existing === null
    ? `# CLAUDE.md\n\n${importLine}\n`
    : `${existing.replace(/\s*$/, '')}\n\n${importLine}\n`;
  const res = ctx.write(claudeMd, next, { region: true });
  base.files.push({ path: claudeMd, action: res.action });
  return I.result(ctx, base.files, base.dropped, `added ${importLine} to CLAUDE.md`);
}

function hooks(ctx) {
  const file = I.at(ctx, ctx.target.hooksConfigFile);
  if (!file) return I.unsupported('no hooks config file in the target registry');
  const settings = I.readUserJson(file);
  if (settings === null) return { status: 'error', files: [{ path: file, action: 'unchanged' }], dropped: [], error: `${common.tildePath(file, ctx.home)} is not valid JSON; nothing was written` };

  const dropped = [];
  const next = {};
  for (const [event, groups] of Object.entries(ctx.bundle.hooks.events || {})) {
    for (const group of groups || []) {
      const { kept, dropped: gone } = I.portedHandlers(ctx, event, group);
      dropped.push(...gone);
      if (!kept.length) continue;
      const matcher = I.translateMatcher(group.matcher, MATCHER_MAP, { keepUnknown: true });
      if (matcher === null) { dropped.push({ item: `${event} [${group.matcher}]`, reason: 'every tool token in the matcher was dropped' }); continue; }
      const out = matcher === undefined ? { hooks: kept } : { matcher, hooks: kept };
      (next[event] = next[event] || []).push(out);
    }
  }
  for (const [event, groups] of Object.entries(I.extraGroups(ctx))) {
    (next[event] = next[event] || []).push(...groups);
  }

  settings.hooks = settings.hooks && typeof settings.hooks === 'object' && !Array.isArray(settings.hooks) ? settings.hooks : {};
  const keys = I.applyOwnedGroups(settings.hooks, I.owned(ctx, 'hooks'), next);
  if (!Object.keys(settings.hooks).length) delete settings.hooks;
  const res = I.writeUserJson(ctx, file, settings);
  if (!ctx.check && !ctx.dryRun) ctx.state.owned[ctx.target.id].hooks = keys;
  return I.result(ctx, [{ path: file, action: res.action }], dropped, `${keys.length} hook group(s) in settings.json`);
}

function permissions(ctx) {
  const file = I.at(ctx, ctx.target.hooksConfigFile);
  if (!file) return I.unsupported('no settings.json in the target registry');
  const settings = I.readUserJson(file);
  if (settings === null) return { status: 'error', files: [{ path: file, action: 'unchanged' }], dropped: [], error: `${common.tildePath(file, ctx.home)} is not valid JSON; nothing was written` };

  settings.permissions = settings.permissions && typeof settings.permissions === 'object' ? settings.permissions : {};
  const previous = new Set(I.owned(ctx, 'permissions'));
  const keys = [];
  for (const bucket of ['allow', 'deny', 'ask']) {
    const wanted = ctx.bundle.permissions[bucket] || [];
    const current = Array.isArray(settings.permissions[bucket]) ? settings.permissions[bucket] : [];
    // Drop what we put there last time, keep everything the user added, re-add ours.
    const merged = current.filter((e) => !previous.has(`${bucket}:${e}`));
    for (const entry of wanted) {
      if (!merged.includes(entry)) merged.push(entry);
      keys.push(`${bucket}:${entry}`);
    }
    if (merged.length) settings.permissions[bucket] = merged;
    else delete settings.permissions[bucket];
  }
  if (!Object.keys(settings.permissions).length) delete settings.permissions;
  const res = I.writeUserJson(ctx, file, settings);
  if (!ctx.check && !ctx.dryRun) ctx.state.owned[ctx.target.id].permissions = keys;
  return I.result(ctx, [{ path: file, action: res.action }], [], `${keys.length} permission entr(ies)`);
}

// Claude Code enforces read-only through the `tools` list, not through a flag.
// A source that only knows a sandbox mode (Codex: sandbox_mode = "read-only")
// therefore has to be given a concrete list, or the ported agent would silently
// gain write tools it did not have. This is the set this repo's own read-only
// agents carry.
const READONLY_TOOLS = 'Read, Grep, Glob';

function agents(ctx) {
  const dir = I.at(ctx, ctx.target.agentsDir);
  if (!dir) return I.unsupported('client has no subagent directory');
  let derived = 0;
  const { files, dropped } = I.renderMarkdownDir(ctx, 'agents', dir, ctx.bundle.agents, (a) => {
    const readonly = String(a.meta.readonly) === 'true';
    if (readonly && !a.meta.tools) derived++;
    return {
      name: a.name,
      description: a.meta.description,
      model: bundleLib.modelTier(a.meta.model || 'inherit'),
      ...(a.meta.tools ? { tools: a.meta.tools } : readonly ? { tools: READONLY_TOOLS } : {}),
      ...(readonly ? { readonly: true } : {}),
    };
  });
  return I.result(ctx, files, dropped, derived ? `${derived} read-only agent(s) given the tools list "${READONLY_TOOLS}"` : undefined);
}

function commands(ctx) {
  const dir = I.at(ctx, ctx.target.commandsDir);
  if (!dir) return I.unsupported('client has no slash-command directory');
  const { files, dropped } = I.renderMarkdownDir(ctx, 'commands', dir, ctx.bundle.commands, (c) => ({
    description: c.meta.description,
    ...(c.meta['argument-hint'] ? { 'argument-hint': c.meta['argument-hint'] } : {}),
  }));
  return I.result(ctx, files, dropped);
}

module.exports = Object.assign({}, generic, {
  id: 'claude',
  rules, hooks, permissions, agents, commands,
});
