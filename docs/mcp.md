# MCP servers

The agent can load tools from external [Model Context Protocol](https://modelcontextprotocol.io)
servers, the same way Claude Code and Codex do. No SDK and no extra dependency:
`agent/tools/mcp.py` speaks JSON-RPC 2.0 over the stdio transport (one JSON message
per line) to a child process.

## Config files

Three files, read in this order. The first file to define a server name wins, so a
project can override a user-level entry and `.agnostic/mcp.json` can override a
`.mcp.json` written by another tool.

| Order | File | Scope |
|---|---|---|
| 1 | `<workspace>/.agnostic/mcp.json` | This repo, this agent |
| 2 | `<workspace>/.mcp.json` | This repo, shared with Claude Code / Codex |
| 3 | `~/.agnostic/mcp.json` | You, everywhere |

All three use the Claude Code format:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
    },
    "notes": {
      "type": "stdio",
      "command": "python",
      "args": ["tools/notes_server.py"],
      "cwd": "C:/Projects/notes",
      "timeout": 30
    }
  }
}
```

| Key | Meaning |
|---|---|
| `command` | Executable to spawn. Required. Resolved on `PATH` — on Windows name the real file (`npx.cmd`, not `npx`). |
| `args` | Argument list. |
| `env` | Extra environment for the child, merged over the agent's own. `${VAR}` is expanded from your environment; an unset variable becomes an empty string and the substitution is reported by `/mcp`. |
| `cwd` | Working directory for the child. Defaults to the workspace root. |
| `type` | `stdio` only (the default). `http` and `sse` entries are skipped with a note. |
| `timeout` | Per-request timeout in seconds. Default 60. |

## Tool naming

Every remote tool is registered as `mcp__<server>__<tool>` with the server's own JSON
schema as its parameters, so `echo` on a server named `fake` becomes `mcp__fake__echo`.
Calls go through the normal `ToolRegistry.execute()` path, which means guardrails,
lifecycle hooks and the audit log apply to remote tools exactly as they do to built-ins.
A remote result with `isError: true` is returned as an error `ToolResult`.

## Lifecycle

Servers are discovered when the registry is built and their tool lists are fetched then
(that is the only way to learn the schemas). A server process is spawned on first use,
never at import time, and is terminated at interpreter exit. A server that fails to
spawn, fails the handshake or times out is logged and skipped — the rest of the servers
and every built-in tool stay available.

## Limits

- **stdio only.** No HTTP/SSE transport, so no OAuth flow and no remote-hosted servers.
- **Tools only.** MCP resources, prompts, sampling and roots are not implemented;
  server-to-client requests are ignored.
- Non-text content (images, audio, embedded resources) is replaced by a
  `[image content omitted]` placeholder — the tool channel is text.
- One request in flight per server; long tool calls serialise behind each other.
- Read-only registries (reviewer subagents) do not load MCP servers.

## `/mcp`

The slash command reports what loaded. It calls
`ToolRegistry.mcp_status()`, which returns one row per configured or skipped server:

```python
[{"server": "github", "state": "running", "tool_count": 12, "error": None},
 {"server": "remote", "state": "skipped", "tool_count": 0,
  "error": "skipped: transport 'http' is not supported (stdio only)"}]
```

`state` is `running`, `exited`, `stopped`, `error` or `skipped`; `error` carries the
reason, including the tail of the server's stderr when it died talking to us.
