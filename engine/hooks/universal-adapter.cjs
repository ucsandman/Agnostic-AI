/**
 * universal-adapter.cjs — Protocol translation layer across AI agent hook dialects.
 *
 * Normalizes inputs from Claude Code, Codex, Antigravity (agy), OpenClaw, and custom agents
 * into a single unified event object:
 * {
 *   client: 'claude' | 'codex' | 'agy' | 'openclaw' | 'hermes' | 'generic',
 *   event: 'pre_tool' | 'post_tool' | 'error' | 'user_correction',
 *   toolName: string,
 *   command: string | null,
 *   targetFile: string | null,
 *   args: object,
 *   raw: object
 * }
 */

function detectClient(payload) {
  if (!payload || typeof payload !== 'object') return 'generic';
  if (payload.toolCall && payload.toolCall.args) return 'agy';
  if (payload.permissionDecision !== undefined || payload.tool_input !== undefined) return 'claude';
  if (payload.event && payload.shell_command) return 'codex';
  if (payload.cursorTool || payload.client === 'cursor' || (payload.method === 'tools/call' && payload.editor === 'cursor')) return 'cursor';
  if (payload.cascadeTool || payload.client === 'windsurf') return 'windsurf';
  if (payload.cline_action || payload.client === 'cline') return 'cline';
  if (payload.openhands_action || payload.source === 'openhands' || payload.action === 'execute') return 'openhands';
  if (payload.goose_extension || payload.client === 'goose') return 'goose';
  if (payload.slashCommand || payload.client === 'continue') return 'continue';
  if (payload.agent_id || payload.client_type) return payload.client_type || 'generic';
  if (payload.client) return payload.client;
  return 'generic';
}

function normalizePayload(rawPayload) {
  const client = detectClient(rawPayload);
  let toolName = 'unknown';
  let command = null;
  let targetFile = null;
  let args = {};
  let event = 'pre_tool';

  switch (client) {
    case 'agy': {
      event = rawPayload.eventName === 'PreInvocation' ? 'pre_tool' : 'post_tool';
      const tc = rawPayload.toolCall || {};
      toolName = tc.name || 'unknown';
      args = tc.args || {};
      command = args.CommandLine || args.command || null;
      targetFile = args.TargetFile || args.AbsolutePath || args.path || null;
      break;
    }
    case 'claude':
    case 'codex': {
      event = rawPayload.event || 'pre_tool';
      toolName = rawPayload.tool_name || rawPayload.tool || 'unknown';
      args = rawPayload.tool_input || rawPayload.args || {};
      command = args.command || args.CommandLine || null;
      targetFile = args.file_path || args.path || args.TargetFile || null;
      break;
    }
    case 'cursor':
    case 'windsurf':
    case 'cline': {
      event = rawPayload.event || 'pre_tool';
      toolName = rawPayload.tool || rawPayload.name || rawPayload.tool_name || 'unknown';
      args = rawPayload.arguments || rawPayload.parameters || rawPayload.params || {};
      command = args.command || args.cmd || args.CommandLine || null;
      targetFile = args.path || args.file_path || args.target || args.TargetFile || null;
      break;
    }
    case 'openhands': {
      event = rawPayload.event || 'pre_tool';
      toolName = rawPayload.action || rawPayload.tool || 'unknown';
      args = rawPayload.args || rawPayload.params || {};
      command = args.command || args.cmd || null;
      targetFile = args.path || args.file || null;
      break;
    }
    case 'goose': {
      event = rawPayload.event || 'pre_tool';
      toolName = rawPayload.tool_call || rawPayload.tool || 'unknown';
      args = rawPayload.arguments || rawPayload.params || {};
      command = args.command || args.cmd || null;
      targetFile = args.path || args.file_path || null;
      break;
    }
    case 'continue': {
      event = rawPayload.event || 'pre_tool';
      toolName = rawPayload.name || rawPayload.tool || 'unknown';
      args = rawPayload.arguments || rawPayload.args || {};
      command = args.command || null;
      targetFile = args.path || args.file || null;
      break;
    }
    default: {
      event = rawPayload.event || 'pre_tool';
      toolName = rawPayload.tool || rawPayload.tool_name || rawPayload.name || 'unknown';
      args = rawPayload.params || rawPayload.args || rawPayload.arguments || {};
      command = args.command || args.cmd || args.CommandLine || null;
      targetFile = args.path || args.target || args.file_path || args.TargetFile || null;
      break;
    }
  }

  // Normalize shell command aliases
  const isShell = [
    'bash',
    'powershell',
    'shell',
    'shell_command',
    'run_command',
    'exec',
    'execute_command',
    'execute'
  ].includes(toolName.toLowerCase());

  if (isShell && !command && typeof args === 'string') {
    command = args;
  }

  return {
    client,
    event,
    toolName,
    isShell,
    command,
    targetFile,
    args,
    raw: rawPayload
  };
}

function formatDenial(client, reason) {
  switch (client) {
    case 'agy':
      return {
        decision: 'deny',
        reason
      };
    case 'claude':
    case 'codex':
      return {
        permissionDecision: 'deny',
        reason
      };
    case 'cursor':
    case 'windsurf':
    case 'cline':
      return {
        isError: true,
        permissionDecision: 'deny',
        allowed: false,
        content: [{ type: 'text', text: reason }],
        reason
      };
    case 'openhands':
      return {
        status: 'rejected',
        allowed: false,
        message: reason,
        reason
      };
    case 'goose':
      return {
        block: true,
        allowed: false,
        error: reason,
        reason
      };
    default:
      return {
        allowed: false,
        reason
      };
  }
}

function formatApproval(client) {
  switch (client) {
    case 'agy':
      return { decision: 'allow' };
    case 'claude':
    case 'codex':
      return { permissionDecision: 'allow' };
    case 'cursor':
    case 'windsurf':
    case 'cline':
      return { allowed: true, permissionDecision: 'allow' };
    case 'openhands':
      return { status: 'approved', allowed: true };
    case 'goose':
      return { block: false, allowed: true };
    default:
      return { allowed: true };
  }
}

// Keep the internal decision dialect stable; serialize the lifecycle envelope
// only at stdout, where Codex and Claude expect hook-specific fields nested.
function formatHookOutput(client, result) {
  if (client !== 'claude' && client !== 'codex') return result;
  return {
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: result.permissionDecision,
      ...(result.reason ? { permissionDecisionReason: result.reason } : {}),
    },
  };
}

module.exports = {
  detectClient,
  normalizePayload,
  formatDenial,
  formatApproval,
  formatHookOutput
};
