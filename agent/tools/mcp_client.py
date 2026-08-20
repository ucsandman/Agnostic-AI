"""
agent/tools/mcp_client.py — Native MCP Bridge for Agnostic AI Agent
Placeholder for connecting to local MCP servers (such as Context7, DashClaw, SQLite, or Filesystem MCPs).

No stdio/HTTP transport is implemented yet, so no MCP tool is advertised to the model:
a tool that reports success without forwarding anything is worse than no tool at all.
Wire a real transport here, then re-register the meta tool.
"""

from agent.tools.registry import ToolRegistry


class MCPBridge:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
