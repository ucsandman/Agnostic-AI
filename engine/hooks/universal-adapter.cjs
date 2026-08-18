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
  if (payload.toolCall && payload.toolCall.args) return 'agy';
  if (payload.permissionDecision !== undefined || payload.tool_input !== undefined) return 'claude';
  if (payload.event && payload.shell_command) return 'codex';
  if (payload.agent_id || payload.client_type) return payload.client_type || 'generic';
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
    default: {
      event = rawPayload.event || 'pre_tool';
      toolName = rawPayload.tool || rawPayload.tool_name || 'unknown';
      args = rawPayload.params || rawPayload.args || {};
      command = args.command || args.cmd || null;
      targetFile = args.path || args.target || null;
      break;
    }
  }

  // Normalize shell command aliases
  const isShell = ['bash', 'powershell', 'shell', 'shell_command', 'run_command', 'exec'].includes(toolName.toLowerCase());
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
    default:
      return { allowed: true };
  }
}

module.exports = {
  detectClient,
  normalizePayload,
  formatDenial,
  formatApproval
};
