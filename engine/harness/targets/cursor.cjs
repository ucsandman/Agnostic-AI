/**
 * engine/harness/targets/cursor.cjs — Cursor.
 *
 * Rules (.mdc), skills, agents, commands and mcp.json all come from the generic
 * adapter; only the hook surface is Cursor's own.
 *
 *   ~/.cursor/hooks.json = { "version": 1, "hooks": { "<event>": [ { command, matcher? } ] } }
 *
 * Cursor's events are camelCase and its payload dialect is its own, so every
 * ported group becomes one entry whose command runs engine/hooks/shim.cjs with
 * the group's guards chained behind `++`. Entries the operator or another tool
 * put in the file are never touched: ownership is the exact JSON of what this
 * adapter inserted last run.
 *
 * Dialect facts: Cursor hooks documentation, read 2026-09-06.
 */

const common = require('../common.cjs');
const generic = require('./generic.cjs');

const I = generic._internals;

const EVENT_MAP = {
  PreToolUse: 'preToolUse',
  PostToolUse: 'postToolUse',
  PostToolUseFailure: 'postToolUseFailure',
  Stop: 'stop',
  SessionStart: 'sessionStart',
  SessionEnd: 'sessionEnd',
  UserPromptSubmit: 'beforeSubmitPrompt',
  SubagentStart: 'subagentStart',
  SubagentStop: 'subagentStop',
  PreCompact: 'preCompact',
};

// Claude tool token -> Cursor tool name. A token with no Cursor tool behind it
// is dropped, and a group whose every token drops is not ported at all.
const MATCHER_MAP = {
  Bash: 'Shell', PowerShell: 'Shell',
  Read: 'Read',
  Write: 'Write|Edit', Edit: 'Write|Edit', MultiEdit: 'Write|Edit', NotebookEdit: 'Write|Edit',
  Agent: 'Task', Task: 'Task', Workflow: 'Task',
  'mcp__.*': 'MCP',
};

// Only the tool events take a matcher.
const TOOL_EVENTS = new Set(['preToolUse', 'postToolUse', 'postToolUseFailure']);

function hooks(ctx) {
  const file = I.at(ctx, ctx.target.hooksConfigFile);
  if (!file) return I.unsupported('no hooks config file in the target registry');
  const config = I.readUserJson(file);
  if (config === null) return { status: 'error', files: [{ path: file, action: 'unchanged' }], dropped: [], error: `${common.tildePath(file, ctx.home)} is not valid JSON; nothing was written` };

  const dropped = [];
  const next = {};

  for (const [event, groups] of Object.entries(ctx.bundle.hooks.events || {})) {
    const cursorEvent = EVENT_MAP[event];
    if (!cursorEvent) { dropped.push({ item: `hook event ${event}`, reason: 'no Cursor event' }); continue; }
    for (const group of groups || []) {
      const { kept, dropped: gone } = I.portedHandlers(ctx, event, group);
      dropped.push(...gone);
      if (!kept.length) continue;
      let matcher;
      if (TOOL_EVENTS.has(cursorEvent)) {
        matcher = I.translateMatcher(group.matcher, MATCHER_MAP, { keepUnknown: false });
        if (matcher === null) { dropped.push({ item: `${event} [${group.matcher}]`, reason: 'no Cursor tool behind this matcher' }); continue; }
      }
      const entry = { command: I.shimCommand('cursor', cursorEvent, kept.map((h) => h.command)) };
      if (matcher !== undefined) entry.matcher = matcher;
      (next[cursorEvent] = next[cursorEvent] || []).push(entry);
    }
  }
  for (const [event, groups] of Object.entries(I.extraGroups(ctx))) {
    (next[event] = next[event] || []).push(...groups);
  }

  config.version = config.version || 1;
  config.hooks = config.hooks && typeof config.hooks === 'object' && !Array.isArray(config.hooks) ? config.hooks : {};
  const keys = I.applyOwnedGroups(config.hooks, I.owned(ctx, 'hooks'), next);
  const res = I.writeUserJson(ctx, file, config);
  if (!ctx.check && !ctx.dryRun) ctx.state.owned[ctx.target.id].hooks = keys;
  return I.result(ctx, [{ path: file, action: res.action }], dropped, `${keys.length} hook entr(ies) via the shim`);
}

module.exports = Object.assign({}, generic, { id: 'cursor', hooks });
