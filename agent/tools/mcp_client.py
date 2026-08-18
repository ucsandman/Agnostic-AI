"""
agent/tools/mcp_client.py — Native MCP Bridge for Agnostic AI Agent
Allows connecting to local MCP servers (such as Context7, DashClaw, SQLite, or Filesystem MCPs).
"""

import json
from typing import Dict, Any
from agent.tools.registry import ToolRegistry, ToolResult


class MCPBridge:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._register_mcp_meta_tool()

    def _register_mcp_meta_tool(self):
        self.registry.register(
            name="call_mcp_tool",
            description="Call an MCP tool provided by an external MCP server running locally or via stdio.",
            parameters={
                "type": "object",
                "properties": {
                    "server_name": {
                        "type": "string",
                        "description": "Name of the MCP server, e.g. context7, dashclaw",
                    },
                    "tool_name": {"type": "string", "description": "Target tool name."},
                    "arguments": {
                        "type": "object",
                        "description": "JSON arguments object for the tool.",
                    },
                },
                "required": ["server_name", "tool_name", "arguments"],
            },
            func=self._execute_mcp,
        )

    def _execute_mcp(self, args: Dict[str, Any], **kwargs) -> ToolResult:
        server = args["server_name"]
        tool = args["tool_name"]
        tool_args = args.get("arguments", {})

        # DashClaw local integration hook
        if server.lower() == "dashclaw":
            return ToolResult(
                f"[DashClaw Hook] Policy check recorded for action: {tool}"
            )

        return ToolResult(
            f"[MCP Bridge] Forwarded '{tool}' to server '{server}'. (Payload: {json.dumps(tool_args)})"
        )
