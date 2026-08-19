
# MCP Integration in Google Antigravity SDK

Reference guide for connecting and using Model Context Protocol (MCP) servers in
the Google Antigravity SDK.

## Overview

The Model Context Protocol (MCP) allows agents to connect to external servers
that expose tools, resources, and prompts. The Google Antigravity SDK supports
integrating MCP servers to extend the capabilities of your custom agents.

For a concrete code example of setting up and using MCP, see
[mcp_tools.md](../../examples/getting_started/mcp_tools.md).

## Configuration Modes

Google Antigravity SDK supports two main ways to connect to MCP servers:

1.  **Stdio Transport**: The SDK launches and manages the MCP server process,
    communicating over standard input/output.
2.  **Streamable HTTP Transport**: The SDK connects to a remote MCP server
    running as a web service using Streamable HTTP.

## Stdio Transport Configuration

Use Stdio transport when you want to manage the lifecycle of the MCP server
locally. This is configured in `LocalAgentConfig` using `mcp_servers`.

### Example

```python
from google.antigravity import Agent, LocalAgentConfig, types

mcp_servers = [
    types.McpStdioServer(
        name="my_stdio_server",
        command="python3",
        args=["mcp_server.py"],
    )
]

config = LocalAgentConfig(mcp_servers=mcp_servers)

async with Agent(config) as agent:
    response = await agent.chat("Use the MCP server to perform a task.")
    print(await response.text())
```

## Streamable HTTP Transport Configuration

Use Streamable HTTP transport when you want to connect to a remote MCP server
running as a web service.

### Example

```python
from google.antigravity import Agent, LocalAgentConfig, types

mcp_servers = [
    types.McpStreamableHttpServer(
        name="my_http_server",
        url="https://example.com/mcp",
        headers={"Authorization": "Bearer your-token-here"},  # Optional headers
    )
]

config = LocalAgentConfig(mcp_servers=mcp_servers)

async with Agent(config) as agent:
    response = await agent.chat("Ask the remote MCP server to perform a task.")
    print(await response.text())
```

## Tool Filtering (Configuring Exposed Tools)

By default, when you connect an MCP server, all of its tools are exposed to the
agent. If you want to limit which tools the agent can see (to save context
tokens or keep the agent focused), you can configure `enabled_tools` or
`disabled_tools` directly on the server configuration. These fields are mutually
exclusive.

### Limit to a specific list of tools (Allowlist)

```python
stdio_server = types.McpStdioServer(
    name="my_stdio_server",
    command="python3",
    args=["mcp_server.py"],
    enabled_tools=["pirate_multiply"],  # Only this tool will be exposed
)
```

### Hide a specific list of tools (Denylist)

```python
stdio_server = types.McpStdioServer(
    name="my_stdio_server",
    command="python3",
    args=["mcp_server.py"],
    disabled_tools=["pirate_divide"],  # All tools except pirate_divide will be exposed
)
```

## Accessing Tools & Safety Policies

Tools exposed by the MCP server are automatically registered with the agent. To
allow the agent to use these tools, you must ensure your safety policy grants
permission.

### Permissions and Overloaded Policies

By default, the SDK's default policy (`confirm_run_command()`) is permissive and
**allows all MCP tools** (it only blocks or asks for confirmation on
`run_command`).

However, if you configure a strict **deny-by-default** setup (using
`policy.deny_all()`), you must explicitly allow your MCP tools.

To make configuring safety policies simple and secure, the safety policy helpers
(`policy.allow`, `policy.deny`, and `policy.ask_user`) are **overloaded** to
accept the MCP server configuration object (`BaseMcpServerConfig`) and an
optional sequence of tool names:

#### Allow all tools on a server

```python
stdio_server = types.McpStdioServer(name="pirate_math", ...)

policies = [
    policy.deny_all(),
    policy.allow(stdio_server),  # Allows all tools exposed by pirate_math
]
```

#### Allow a specific list of tools on a server

```python
stdio_server = types.McpStdioServer(name="pirate_math", ...)

policies = [
    policy.deny_all(),
    policy.allow(stdio_server, ["pirate_multiply"]),  # Allows only pirate_multiply
]
```

#### Require user confirmation for specific tools

```python
async def my_handler(tool_call: types.ToolCall) -> bool:
  # Custom logic to ask user or auto-approve
  # Return True to allow, False to deny
  return True


stdio_server = types.McpStdioServer(name="pirate_math", ...)

policies = [
    policy.deny_all(),
    policy.allow(stdio_server, ["pirate_multiply"]),
    policy.ask_user(
        stdio_server, ["pirate_divide"], handler=my_handler
    ),  # Ask for divide
]
```

See [Safety Policies](safety_policies.md) for more details on how to configure
policies.

## Gotchas

> [!WARNING] **Identifier Safety**: FastMCP (used under the hood) requires tool
> and parameter names to be valid Python identifiers. Ensure your MCP server
> adheres to this.

> [!IMPORTANT] **Permissions**: Failing to grant permissions for MCP tools will
> prevent the agent from using them, even if the server is correctly connected.

> [!NOTE] **Timeouts**: External processes can cause timeouts if they block the
> customization server. Ensure your MCP server is responsive.
