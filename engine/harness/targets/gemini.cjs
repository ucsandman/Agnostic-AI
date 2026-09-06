/**
 * engine/harness/targets/gemini.cjs — Gemini CLI.
 *
 * Rules, skills and MCP come straight from the generic adapter. Two surfaces
 * are Gemini's own:
 *
 *   hooks     ~/.gemini/settings.json -> "hooks". Gemini has its own event and
 *             tool names, and its own payload dialect, so every ported hook runs
 *             through engine/hooks/shim.cjs. Gemini MERGES the results of every
 *             hook registered for one event and the last reason wins, so all the
 *             guards for one (event, matcher) pair are chained inside ONE entry
 *             with `++`; the shim stops at the first deny and that reason is the
 *             only one Gemini sees.
 *   commands  ~/.gemini/commands/<name>.toml, not markdown.
 *
 * Dialect facts: Gemini CLI hooks documentation, read 2026-09-06.
 */

const fs = require('fs');
const path = require('path');
const common = require('../common.cjs');
const generic = require('./generic.cjs');

const I = generic._internals;

const EVENT_MAP = {
  PreToolUse: 'BeforeTool',
  PostToolUse: 'AfterTool',
  UserPromptSubmit: 'BeforeAgent',
  Stop: 'AfterAgent',
  SessionStart: 'SessionStart',
  SessionEnd: 'SessionEnd',
  PreCompact: 'PreCompress',
};

// Claude tool token -> Gemini CLI tool name. null drops the token.
const MATCHER_MAP = {
  Bash: 'run_shell_command', PowerShell: 'run_shell_command',
  Write: 'write_file',
  Edit: 'replace', MultiEdit: 'replace', NotebookEdit: 'replace',
  Read: 'read_file', Glob: 'glob',
  Grep: 'search_file_content',
  WebFetch: 'web_fetch', WebSearch: 'google_web_search',
  Agent: null, Task: null, Workflow: null,
};

// Only the tool events take a matcher; the rest fire once per turn.
const TOOL_EVENTS = new Set(['BeforeTool', 'AfterTool']);

function hooks(ctx) {
  const file = I.at(ctx, ctx.target.hooksConfigFile);
  if (!file) return I.unsupported('no hooks config file in the target registry');
  const settings = I.readUserJson(file);
  if (settings === null) return { status: 'error', files: [{ path: file, action: 'unchanged' }], dropped: [], error: `${common.tildePath(file, ctx.home)} is not valid JSON; nothing was written` };

  const dropped = [];
  const buckets = new Map(); // `${geminiEvent} ${matcher ?? ''}` -> handlers[]

  for (const [event, groups] of Object.entries(ctx.bundle.hooks.events || {})) {
    const geminiEvent = EVENT_MAP[event];
    if (!geminiEvent) { dropped.push({ item: `hook event ${event}`, reason: 'no Gemini CLI event' }); continue; }
    for (const group of groups || []) {
      const { kept, dropped: gone } = I.portedHandlers(ctx, event, group);
      dropped.push(...gone);
      if (!kept.length) continue;
      let matcher;
      if (TOOL_EVENTS.has(geminiEvent)) {
        matcher = I.translateMatcher(group.matcher, MATCHER_MAP, { keepUnknown: true });
        if (matcher === null) { dropped.push({ item: `${event} [${group.matcher}]`, reason: 'no Gemini CLI tool behind this matcher' }); continue; }
      }
      const key = `${geminiEvent} ${matcher === undefined ? '' : matcher}`;
      if (!buckets.has(key)) buckets.set(key, { event: geminiEvent, matcher, handlers: [] });
      buckets.get(key).handlers.push(...kept);
    }
  }

  const next = {};
  for (const { event, matcher, handlers } of buckets.values()) {
    const hook = { type: 'command', command: I.shimCommand('gemini', event, handlers.map((h) => h.command)) };
    const timeout = I.chainTimeout(handlers);
    if (timeout !== undefined) hook.timeout = timeout;
    const group = matcher === undefined ? { hooks: [hook] } : { matcher, hooks: [hook] };
    (next[event] = next[event] || []).push(group);
  }
  for (const [event, groups] of Object.entries(I.extraGroups(ctx))) {
    (next[event] = next[event] || []).push(...groups);
  }

  settings.hooks = settings.hooks && typeof settings.hooks === 'object' && !Array.isArray(settings.hooks) ? settings.hooks : {};
  const keys = I.applyOwnedGroups(settings.hooks, I.owned(ctx, 'hooks'), next);
  if (!Object.keys(settings.hooks).length) delete settings.hooks;
  const res = I.writeUserJson(ctx, file, settings);
  if (!ctx.check && !ctx.dryRun) ctx.state.owned[ctx.target.id].hooks = keys;
  return I.result(ctx, [{ path: file, action: res.action }], dropped, `${keys.length} chained hook entr(ies) via the shim`);
}

function commands(ctx) {
  const dir = I.at(ctx, ctx.target.commandsDir);
  if (!dir) return I.unsupported('client has no custom-command directory');
  const files = [];
  const dropped = [];
  const keep = [];
  const header = `# ${common.GENERATED_MARK} from the ${ctx.bundle.manifest.source} harness`;

  for (const command of ctx.bundle.commands) {
    const file = path.join(dir, `${command.name}.toml`);
    if (fs.existsSync(file) && !I.weWroteIt(ctx, 'commands', file)) {
      dropped.push({ item: `command ${command.name}`, reason: `${common.tildePath(file, ctx.home)} already exists and was not created by the harness` });
      continue;
    }
    // Gemini interpolates {{args}}; Claude and Codex write $ARGUMENTS.
    const prompt = String(command.body).replace(/\$ARGUMENTS/g, '{{args}}').trim();
    const body = [
      header,
      `description = ${common.tomlStr(command.meta.description || command.name)}`,
      `prompt = ${common.tomlMultiline(prompt)}`,
      '',
    ].join('\n');
    const res = ctx.write(file, body);
    files.push({ path: file, action: res.action });
    // Still wanted even when the write was refused; see generic.renderMarkdownDir.
    keep.push(file);
  }
  files.push(...I.pruneFiles(ctx, 'commands', keep));
  return I.result(ctx, files, dropped, `${keep.length} .toml command(s)`);
}

module.exports = Object.assign({}, generic, { id: 'gemini', hooks, commands });
