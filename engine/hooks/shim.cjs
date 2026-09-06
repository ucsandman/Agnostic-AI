#!/usr/bin/env node
/**
 * engine/hooks/shim.cjs — run an unmodified Claude Code hook under another client.
 *
 * Hooks are written once, in the Claude Code dialect (JSON on stdin, a decision
 * on stdout or exit 2). Cursor, Gemini CLI and Antigravity each speak their own
 * dialect. Rather than maintain a second copy of every guard, this translates
 * the payload in, runs the real guards, and translates the decision back out.
 *
 *   node shim.cjs --client cursor --event preToolUse -- node a.cjs ++ node b.cjs
 *
 * `++` chains several guards inside ONE hook entry. That is not a convenience:
 * Gemini and agy merge the results of every hook registered for an event and the
 * LAST result's reason wins, so a guard that denies with an explanation gets its
 * explanation blanked by any later no-opinion hook. One entry per event means one
 * result, and the reason survives. The first deny/ask in the chain wins and
 * short-circuits.
 *
 * Fail-open by design: an unparseable payload, a crashed guard, a bad argument
 * list or an internal error all print `{}` and exit 0. A broken shim must never
 * wedge the client it is guarding.
 *
 * Codex needs no shim; its dialect is a near clone of Claude Code's.
 */

const fs = require('fs');
const { spawnSync } = require('child_process');

const PER_COMMAND_TIMEOUT_MS = 25_000;

const HELP = `engine/hooks/shim.cjs — run Claude Code hooks under another client.

Usage:
  node shim.cjs --client <cursor|gemini|agy> --event <clientEvent> -- <cmd...> [++ <cmd...>]*

Options:
  --client   the client whose dialect is on stdin and expected on stdout
  --event    the client's own event name (preToolUse, BeforeTool, PreToolUse, ...)
  --         everything after this is the guard chain; ++ separates commands
  --help     this text

Reads the client's hook payload as JSON on stdin, translates it to the Claude
Code shape, runs every command in the chain with that payload, and translates
the first deny/ask back into the client's dialect. Exits 0 always, except a
Gemini BeforeTool deny, which also exits 2 with the reason on stderr.

Examples:
  node shim.cjs --client cursor --event beforeShellExecution -- node ~/.claude/hooks/secret-guard.cjs
  node shim.cjs --client gemini --event BeforeTool -- node a.cjs ++ node b.cjs
`;

// ---------------------------------------------------------------------------
// Arguments
// ---------------------------------------------------------------------------

const stripQuotes = (s) => (/^".*"$/.test(s) && s.length > 1 ? s.slice(1, -1) : s);

/** Split one command STRING into argv, honouring double quotes. */
function tokenize(text) {
  const out = [];
  let current = '';
  let quoted = false;
  let started = false;
  for (const ch of String(text)) {
    if (ch === '"') { quoted = !quoted; started = true; continue; }
    if (!quoted && /\s/.test(ch)) {
      if (current || started) { out.push(current); current = ''; started = false; }
      continue;
    }
    current += ch;
    started = true;
  }
  if (current || started) out.push(current);
  return out;
}

/**
 * The chain arrives either already split into argv by the client's shell, or as
 * one quoted string per command when the shell left the quotes alone. Both work.
 */
function splitChain(tokens) {
  const parts = [[]];
  for (const t of tokens) {
    if (t === '++') parts.push([]);
    else parts[parts.length - 1].push(t);
  }
  return parts
    .filter((p) => p.length)
    .map((p) => (p.length === 1 && /\s/.test(p[0]) ? tokenize(p[0]) : p.map(stripQuotes)))
    .filter((p) => p.length);
}

function parseArgs(argv) {
  const out = { client: '', event: '', help: false, chain: [] };
  let i = 0;
  for (; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--') { i++; break; }
    if (a === '--client') out.client = argv[++i] || '';
    else if (a === '--event') out.event = argv[++i] || '';
    else if (a === '--help' || a === '-h') out.help = true;
  }
  out.chain = splitChain(argv.slice(i));
  return out;
}

// ---------------------------------------------------------------------------
// Dialect maps
// ---------------------------------------------------------------------------

const CURSOR_EVENTS = {
  preToolUse: 'PreToolUse', beforeShellExecution: 'PreToolUse', beforeMCPExecution: 'PreToolUse', beforeReadFile: 'PreToolUse',
  postToolUse: 'PostToolUse', postToolUseFailure: 'PostToolUse', afterShellExecution: 'PostToolUse',
  afterMCPExecution: 'PostToolUse', afterFileEdit: 'PostToolUse',
  beforeSubmitPrompt: 'UserPromptSubmit', sessionStart: 'SessionStart', sessionEnd: 'SessionEnd',
  preCompact: 'PreCompact', stop: 'Stop', afterAgentResponse: 'Stop',
  subagentStart: 'SubagentStart', subagentStop: 'SubagentStop',
};
const CURSOR_TOOLS = { Shell: 'Bash', Read: 'Read', Write: 'Write', Edit: 'Edit', Task: 'Agent' };
const CURSOR_PRE = new Set(['preToolUse', 'beforeShellExecution', 'beforeMCPExecution', 'beforeReadFile']);

const GEMINI_EVENTS = {
  BeforeTool: 'PreToolUse', BeforeToolSelection: 'PreToolUse', AfterTool: 'PostToolUse',
  BeforeAgent: 'UserPromptSubmit', AfterAgent: 'Stop',
  SessionStart: 'SessionStart', SessionEnd: 'SessionEnd', PreCompress: 'PreCompact',
};
const GEMINI_TOOLS = {
  run_shell_command: 'Bash', write_file: 'Write', replace: 'Edit', read_file: 'Read',
  glob: 'Glob', list_directory: 'Glob', grep_search: 'Grep', search_file_content: 'Grep',
  web_fetch: 'WebFetch', google_web_search: 'WebSearch',
};
// Gemini's read_file names the path `absolute_path`; the guards read `file_path`.
const GEMINI_ARGS = { absolute_path: 'file_path' };

// agy is camelCase protojson with PascalCase tool args.
const AGY_TOOLS = {
  run_command: 'Bash', write_to_file: 'Write', replace_file_content: 'Edit', view_file: 'Read',
  grep_search: 'Grep', list_dir: 'Glob',
  invoke_subagent: 'Agent', define_subagent: 'Agent', manage_subagents: 'Agent',
  read_url_content: 'WebFetch', search_web: 'WebSearch',
};
const AGY_ARGS = {
  CommandLine: 'command', Cwd: 'cwd', TargetFile: 'file_path', AbsolutePath: 'file_path',
  CodeContent: 'content', TargetContent: 'old_string', ReplacementContent: 'new_string',
  Query: 'pattern', SearchDirectory: 'path',
};

/**
 * agy caps and ASCII-folds the reason it shows. The guards' teaching text is the
 * payload; the typography is not.
 */
function asciiReason(s) {
  return String(s || '')
    .replace(/[—–]/g, '-')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[…]/g, '...')
    .replace(/[→]/g, '->')
    .replace(/[^\x20-\x7E]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 400);
}

// ---------------------------------------------------------------------------
// Payload in: client dialect -> Claude Code shape
// ---------------------------------------------------------------------------

/**
 * Returns { payload, renames } where `renames` maps a Claude tool_input key back
 * to the client's own key, so a rewriting guard's updatedInput can be handed
 * back in the client's spelling.
 */
function translateIn(client, event, raw) {
  const renames = {};
  const base = {
    session_id: raw.session_id || raw.conversation_id || raw.conversationId || client,
    transcript_path: raw.transcript_path || raw.transcriptPath || null,
    cwd: raw.cwd || (Array.isArray(raw.workspacePaths) && raw.workspacePaths[0]) || process.cwd(),
    permission_mode: raw.permission_mode || 'default',
    stop_hook_active: false,
  };

  if (client === 'cursor') {
    let toolName = CURSOR_TOOLS[raw.tool_name] || raw.tool_name || '';
    let toolInput = raw.tool_input && typeof raw.tool_input === 'object' ? Object.assign({}, raw.tool_input) : {};
    if (event === 'beforeShellExecution' || event === 'afterShellExecution') {
      toolName = 'Bash';
      toolInput = { command: raw.command };
      if (raw.cwd) toolInput.cwd = raw.cwd;
    } else if (event === 'beforeMCPExecution' || event === 'afterMCPExecution') {
      toolName = /^mcp__/.test(String(raw.tool_name || '')) ? raw.tool_name : `mcp__${raw.tool_name || 'call'}`;
    } else if (event === 'beforeReadFile') {
      toolName = 'Read';
      if (!toolInput.file_path) toolInput.file_path = raw.file_path || raw.path;
    } else if (event === 'afterFileEdit') {
      toolName = 'Edit';
      if (!toolInput.file_path) toolInput.file_path = raw.file_path || raw.path;
    }
    return {
      payload: Object.assign(base, {
        hook_event_name: CURSOR_EVENTS[event] || event,
        model: raw.model || 'cursor',
        tool_name: toolName,
        tool_input: toolInput,
        prompt: raw.prompt,
        cursor: { event, tool_use_id: raw.tool_use_id, sandbox: raw.sandbox },
      }),
      renames,
    };
  }

  if (client === 'gemini') {
    const toolInput = {};
    for (const [k, v] of Object.entries(raw.tool_input || {})) {
      const key = GEMINI_ARGS[k] || k;
      if (key !== k) renames[key] = k;
      toolInput[key] = v;
    }
    return {
      payload: Object.assign(base, {
        hook_event_name: GEMINI_EVENTS[event] || event,
        model: raw.model || 'gemini',
        tool_name: GEMINI_TOOLS[raw.tool_name] || raw.tool_name || '',
        tool_input: toolInput,
        prompt: raw.prompt,
        gemini: { event, tool_name: raw.tool_name },
      }),
      renames,
    };
  }

  // agy
  const toolCall = raw.toolCall || {};
  const toolInput = {};
  for (const [k, v] of Object.entries(toolCall.args || {})) {
    if (k === 'toolAction' || k === 'toolSummary') continue;
    const key = AGY_ARGS[k] || k;
    if (key !== k) renames[key] = k;
    toolInput[key] = v;
  }
  return {
    payload: Object.assign(base, {
      hook_event_name: event,
      model: raw.modelName || 'agy',
      tool_name: AGY_TOOLS[toolCall.name] || toolCall.name || '',
      tool_input: toolInput,
      agy: {
        stepIdx: raw.stepIdx, invocationNum: raw.invocationNum,
        terminationReason: raw.terminationReason, error: raw.error,
      },
    }),
    renames,
  };
}

// ---------------------------------------------------------------------------
// Run the chain
// ---------------------------------------------------------------------------

function runChain(chain, payload) {
  const input = JSON.stringify(payload);
  let decision = null;
  let reason = '';
  let context = '';
  let updatedInput = null;

  for (const cmd of chain) {
    let res;
    try {
      res = spawnSync(cmd[0], cmd.slice(1), {
        input, encoding: 'utf8', shell: false,
        timeout: PER_COMMAND_TIMEOUT_MS, windowsHide: true,
      });
    } catch (_) {
      continue; // a broken guard must never wedge the client
    }
    if (!res || res.error) continue;

    const stdout = (res.stdout || '').trim();
    const stderr = (res.stderr || '').trim();
    let inner = null;
    if (stdout.startsWith('{')) { try { inner = JSON.parse(stdout); } catch (_) { inner = null; } }
    const hso = (inner && inner.hookSpecificOutput) || {};

    // Claude guards signal a block two ways: exit 2 with the reason on stderr, or
    // a permissionDecision / decision of "deny" (Stop hooks say "block").
    let d = hso.permissionDecision || (inner && (inner.permissionDecision || inner.decision)) || null;
    if (d === 'block') d = 'deny';
    if (res.status === 2 && !d && stderr) d = 'deny';

    const r = hso.permissionDecisionReason || (inner && (inner.permissionDecisionReason || inner.reason)) || stderr || '';
    const c = hso.additionalContext || (inner && inner.additionalContext) || (inner ? '' : stdout) || '';
    if (c && !context) context = String(c);

    const u = hso.updatedInput || (inner && inner.updatedInput);
    if (u && typeof u === 'object' && Object.keys(u).length) updatedInput = Object.assign({}, updatedInput || {}, u);

    if (d === 'deny' || d === 'ask' || d === 'force_ask') { decision = d; reason = String(r); break; }
  }
  return { decision, reason, context, updatedInput };
}

/** Claude tool_input keys -> the client's own keys, for a rewrite handed back. */
function rename(obj, renames) {
  const out = {};
  for (const [k, v] of Object.entries(obj || {})) out[renames[k] || k] = v;
  return out;
}

// ---------------------------------------------------------------------------
// Decision out: Claude shape -> client dialect
// ---------------------------------------------------------------------------

function cursorOut(event, { decision, reason, context, updatedInput }, renames) {
  if (CURSOR_PRE.has(event)) {
    if (decision === 'deny') return { permission: 'deny', agent_message: reason, user_message: reason };
    if (decision === 'ask' || decision === 'force_ask') return { permission: 'ask', agent_message: reason, user_message: reason };
    // A rewrite only takes effect alongside an explicit allow. With no decision
    // and no rewrite we say nothing, so Cursor's own permission prompts stand.
    if (updatedInput) return { permission: 'allow', updated_input: rename(updatedInput, renames) };
    return {};
  }
  if (event === 'beforeSubmitPrompt') {
    if (decision) return { continue: false, user_message: reason };
    return context ? { additional_context: context } : {};
  }
  if (event === 'stop' || event === 'afterAgentResponse') {
    return decision ? { followup_message: reason } : {};
  }
  if (event === 'sessionStart') return context ? { additional_context: context } : {};
  return {};
}

function geminiOut(event, { decision, reason, context, updatedInput }, renames, toolInput) {
  if (decision) {
    // Gemini's BeforeTool has no "ask"; a guard that wants a human in the loop
    // is honoured as a deny that says so, rather than silently letting it pass.
    const text = decision === 'deny' ? reason : `Confirm first: ${reason}`;
    return { body: { decision: 'deny', reason: text }, denyReason: text };
  }
  if (updatedInput) {
    const merged = rename(Object.assign({}, toolInput, updatedInput), renames);
    return { body: { hookSpecificOutput: { tool_input: merged } } };
  }
  if (context) return { body: { hookSpecificOutput: { additionalContext: context } } };
  return { body: {} };
}

function agyOut(event, { decision, reason, context, updatedInput }, renames) {
  const out = {};
  if (event === 'PreToolUse') {
    out.decision = 'allow';
    if (decision === 'deny' || decision === 'ask' || decision === 'force_ask') {
      out.decision = decision;
      const r = asciiReason(reason);
      if (r) out.reason = r;
    } else if (updatedInput) {
      // A rewriting guard returns updatedInput and no decision at all, so this
      // must not be gated on decision === "allow". agy merges `overwrite`
      // shallowly into the tool call's args.
      out.overwrite = rename(updatedInput, renames);
    }
  } else if (event === 'Stop') {
    // Claude: {"decision":"block"} keeps the agent working. agy: "continue".
    if (decision === 'deny') {
      out.decision = 'continue';
      const r = asciiReason(reason);
      if (r) out.reason = r;
    }
  } else if (event === 'PreInvocation' || event === 'PostInvocation') {
    if (context) out.injectSteps = [{ ephemeralMessage: String(context).slice(0, 20_000) }];
    if (decision === 'deny' && event === 'PostInvocation') out.terminationBehavior = 'force_continue';
  }
  // PostToolUse: agy expects {} — nothing to translate.
  return out;
}

// ---------------------------------------------------------------------------

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) { process.stdout.write(HELP); return 0; }
  if (!['cursor', 'gemini', 'agy'].includes(args.client) || !args.event || !args.chain.length) {
    process.stdout.write('{}');
    return 0;
  }

  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
  } catch (_) {
    process.stdout.write('{}');
    return 0;
  }
  if (!raw || typeof raw !== 'object') raw = {};

  const { payload, renames } = translateIn(args.client, args.event, raw);
  const outcome = runChain(args.chain, payload);

  if (args.client === 'cursor') {
    process.stdout.write(JSON.stringify(cursorOut(args.event, outcome, renames)));
    return 0;
  }
  if (args.client === 'agy') {
    process.stdout.write(JSON.stringify(agyOut(args.event, outcome, renames)));
    return 0;
  }
  const { body, denyReason } = geminiOut(args.event, outcome, renames, payload.tool_input);
  process.stdout.write(JSON.stringify(body));
  // Gemini honours both channels for BeforeTool; exit 2 + stderr is the one it
  // reports verbatim to the model.
  if (denyReason && args.event === 'BeforeTool') {
    process.stderr.write(denyReason + '\n');
    return 2;
  }
  return 0;
}

if (require.main === module) {
  let code = 0;
  try {
    code = main();
  } catch (_) {
    process.stdout.write('{}');
    code = 0;
  }
  process.exit(code);
}

module.exports = { parseArgs, splitChain, tokenize, translateIn, runChain, cursorOut, geminiOut, agyOut, asciiReason };
