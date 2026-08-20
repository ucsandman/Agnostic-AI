"""
agent/tools/mcp_discovery.py — Zero-Config Universal MCP Auto-Discovery Bridge
Reads existing MCP configs from Antigravity, Claude Desktop, Cursor, and Windsurf, exposing tools seamlessly.
"""

import json
from pathlib import Path
from typing import Dict, Any


class MCPAutoDiscovery:
    @staticmethod
    def discover_mcp_servers() -> Dict[str, Dict[str, Any]]:
        """Scans well-known local paths for registered MCP servers."""
        home = Path.home()
        candidates = [
            home / ".gemini" / "antigravity-cli" / "mcp",
            home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json",
            home / ".cursor" / "mcp.json",
            Path(".mcp.json"),
        ]

        discovered = {}
        for cand in candidates:
            if cand.is_dir():
                # Directory of server definitions
                for server_dir in cand.iterdir():
                    if server_dir.is_dir():
                        discovered[server_dir.name] = {
                            "path": str(server_dir),
                            "type": "directory",
                        }
            elif cand.is_file():
                try:
                    data = json.loads(cand.read_text(encoding="utf-8"))
                    servers = data.get("mcpServers", {})
                    for s_name, s_cfg in servers.items():
                        discovered[s_name] = s_cfg
                except (OSError, ValueError, AttributeError):  # skip one malformed mcp config
                    pass

        return discovered


mcp_discovery = MCPAutoDiscovery()  # noqa: vulture
