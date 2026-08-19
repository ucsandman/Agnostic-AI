
# Model Context Protocol (MCP)

This example demonstrates how to connect an agent to an external Model Context
Protocol (MCP) server. The SDK supports both `stdio` and `http` (Streamable
HTTP) transports.

For conceptual details and information on permissions, see the
[MCP Integration Reference Guide](../../references/mcp_integration.md).

## Connecting via Stdio

Assume we have an MCP server (e.g., `mcp_server.py`) using the `FastMCP` library
that exposes an `add_numbers` tool:

```python
from mcp.server import fastmcp

mcp = fastmcp.FastMCP("MathServer")


@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Adds two numbers."""
    return a + b


mcp.run()
```

To connect the agent to this MCP server via `stdio` transport:

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
    response = await agent.chat("Add 5 and 3 using the add_numbers tool.")
    print(await response.text())
```

## Connecting via Streamable HTTP

You can also connect to a remote MCP server running as a web service using the
`http` (Streamable HTTP) transport:

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

If an MCP server exposes many tools but you only want the agent to see or use a
subset of them, you can configure `enabled_tools` (allowlist) or
`disabled_tools` (denylist) on the server config. These fields are mutually
exclusive and prevent the model from even seeing the filtered-out tools, saving
token costs.

Here is how to disable the `pirate_divide` tool so that only `pirate_multiply`
is exposed:

```python
from google.antigravity import Agent, LocalAgentConfig, types

stdio_server = types.McpStdioServer(
    name="pirate_math",
    command="python3",
    args=["mcp_server.py"],
    disabled_tools=["pirate_divide"],  # Hide pirate_divide completely
)

config = LocalAgentConfig(mcp_servers=[stdio_server])

async with Agent(config) as agent:
    # The agent can multiply:
    response = await agent.chat("Multiply 6 and 8.")
    print(await response.text())

    # The agent cannot divide because the tool is completely hidden:
    response = await agent.chat("Divide 10 by 2.")
    print(await response.text())
```

## Safety Policies with MCP Servers

When deploying agents to untrusted environments or if you want fine-grained
runtime checks, you can combine MCP servers with the declarative policy hooks.

The policy builders (`policy.allow()`, `policy.deny()`, `policy.ask_user()`) are
overloaded to accept `BaseMcpServerConfig` objects directly. The backend
automatically maps these to the underlying namespaced targets safely.

```python
from google.antigravity import Agent, LocalAgentConfig, types
from google.antigravity.hooks import policy

stdio_server = types.McpStdioServer(
    name="pirate_math",
    command="python3",
    args=["mcp_server.py"],
)

# Start by blocking all tools by default
# Explicitly allow pirate_multiply
# Explicitly deny pirate_divide (will cause a runtime denial, visible to the agent)
policies = [
    policy.deny_all(),
    policy.allow(stdio_server, ["pirate_multiply"]),
    policy.deny(stdio_server, ["pirate_divide"]),
]

config = LocalAgentConfig(mcp_servers=[stdio_server], policies=policies)

async with Agent(config) as agent:
    # This call is allowed:
    response = await agent.chat("Multiply 4 and 9.")
    print(await response.text())

    # This call is denied at runtime by policy (the agent will receive a denial message):
    response = await agent.chat("Divide 12 by 3.")
    print(await response.text())
```
