/**
 * engine/harness/targets/agy.cjs — Antigravity CLI (`agy`).
 *
 * Rules land in ~/.gemini/GEMINI.md, which the Gemini CLI target writes too:
 * the registry gives both the same rulesFile and the same preamble, so whichever
 * adapter runs first writes the file and the other sees it unchanged.
 *
 * Hooks are agy's own dialect. The file format is verified on this machine from
 * the CLI's own shipped documentation:
 *   ~/.gemini/antigravity-cli/builtin/skills/agy-customizations/docs/hooks.md
 * "The `hooks.json` file is a JSON object where each top-level key is a hook
 * name, mapping to its event configuration." PreToolUse and PostToolUse are
 * *grouped* (a `matcher` + `hooks` wrapper); PreInvocation, PostInvocation and
 * Stop are *flat* lists of handler objects. Each handler is
 * `{ type?: "command", command, timeout?: seconds }`.
 *
 * That one top-level key is also the ownership boundary: the harness owns the
 * key `agnostic-ai` and nothing else in the file, so a hook another plugin or
 * the operator registered under its own name survives every run untouched.
 *
 * Every ported guard runs through engine/hooks/shim.cjs, which speaks agy's
 * camelCase protojson payloads and its allow/deny/ask/force_ask decisions.
 * agy merges the results of several hooks for one event and the LAST reason
 * wins, so the guards for one event are chained inside ONE entry with `++`.
 */

const common = require('../common.cjs');
const generic = require('./generic.cjs');

const I = generic._internals;

/** The single top-level key in hooks.json that this harness owns: the configured brand id. */
const hookName = () => common.config.brand.id;

const EVENT_MAP = {
  PreToolUse: 'PreToolUse',
  PostToolUse: 'PostToolUse',
  UserPromptSubmit: 'PreInvocation',
  Stop: 'Stop',
};

// Only these two carry a matcher/hooks wrapper; the rest are flat handler lists.
const GROUPED = new Set(['PreToolUse', 'PostToolUse']);

// Claude tool token -> agy tool name (the reverse of the adapter's own map).
const MATCHER_MAP = {
  Bash: 'run_command', PowerShell: 'run_command',
  Write: 'write_to_file',
  Edit: 'replace_file_content', MultiEdit: 'replace_file_content', NotebookEdit: 'replace_file_content',
  Read: 'view_file', Grep: 'grep_search', Glob: 'list_dir',
  Agent: 'invoke_subagent', Task: 'invoke_subagent', Workflow: 'invoke_subagent',
  WebFetch: 'read_url_content', WebSearch: 'search_web',
};

function hooks(ctx) {
  const file = I.at(ctx, ctx.target.hooksConfigFile);
  if (!file) return I.unsupported('no hooks config file in the target registry');
  const config = I.readUserJson(file);
  if (config === null) return { status: 'error', files: [{ path: file, action: 'unchanged' }], dropped: [], error: `${common.tildePath(file, ctx.home)} is not valid JSON; nothing was written` };

  const dropped = [];
  const buckets = new Map(); // `${agyEvent} ${matcher ?? ''}` -> { event, matcher, handlers }

  for (const [event, groups] of Object.entries(ctx.bundle.hooks.events || {})) {
    const agyEvent = EVENT_MAP[event];
    if (!agyEvent) { dropped.push({ item: `hook event ${event}`, reason: 'no Antigravity event (it has only PreToolUse, PostToolUse, PreInvocation, PostInvocation, Stop)' }); continue; }
    for (const group of groups || []) {
      const { kept, dropped: gone } = I.portedHandlers(ctx, event, group);
      dropped.push(...gone);
      if (!kept.length) continue;
      let matcher;
      if (GROUPED.has(agyEvent)) {
        matcher = I.translateMatcher(group.matcher, MATCHER_MAP, { keepUnknown: true });
        if (matcher === null) { dropped.push({ item: `${event} [${group.matcher}]`, reason: 'no Antigravity tool behind this matcher' }); continue; }
      }
      const key = `${agyEvent} ${matcher === undefined ? '' : matcher}`;
      if (!buckets.has(key)) buckets.set(key, { event: agyEvent, matcher, handlers: [] });
      buckets.get(key).handlers.push(...kept);
    }
  }

  const block = {};
  for (const { event, matcher, handlers } of buckets.values()) {
    const handler = { type: 'command', command: I.shimCommand('agy', event, handlers.map((h) => h.command)) };
    const timeout = I.chainTimeout(handlers);
    if (timeout !== undefined) handler.timeout = timeout;
    block[event] = block[event] || [];
    // Grouped events wrap the handler; flat events take it directly.
    block[event].push(GROUPED.has(event) ? (matcher === undefined ? { hooks: [handler] } : { matcher, hooks: [handler] }) : handler);
  }
  for (const [event, groups] of Object.entries(I.extraGroups(ctx))) {
    (block[event] = block[event] || []).push(...groups);
  }

  // A previous installer wrote a flat `{"preToolUse": "<command>"}` shape here.
  // It is not ours, so it is left byte for byte and only reported.
  for (const [name, value] of Object.entries(config)) {
    if (name === hookName()) continue;
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      dropped.push({ item: `hooks.json key "${name}"`, reason: 'not a named-hook object (legacy installer format); left untouched because the harness does not own it' });
    }
  }

  I.owned(ctx, 'hooks'); // initialise this target's ownership record
  if (Object.keys(block).length) config[hookName()] = block;
  else delete config[hookName()];
  const res = I.writeUserJson(ctx, file, config);
  if (!ctx.check && !ctx.dryRun) ctx.state.owned[ctx.target.id].hooks = Object.keys(block).length ? [hookName()] : [];
  const entries = Object.values(block).reduce((n, list) => n + list.length, 0);
  return I.result(ctx, [{ path: file, action: res.action }], dropped, `${entries} chained entr(ies) under the "${hookName()}" hook`);
}

module.exports = Object.assign({}, generic, { id: 'agy', hooks });
