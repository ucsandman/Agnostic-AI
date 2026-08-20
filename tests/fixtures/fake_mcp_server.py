"""tests/fixtures/fake_mcp_server.py — minimal stdio MCP server for the MCP client tests.

Stdlib only, newline-delimited JSON-RPC 2.0 on stdin/stdout. Exposes echo(text) and
fail(). Set FAKE_MCP_NOISE_KB to have it dump that much stderr at startup, which is how
the tests prove the stderr drain thread stops the child from deadlocking on a full pipe.
"""

import json
import os
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "Echo the supplied text back.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to echo."}},
            "required": ["text"],
        },
    },
    {
        "name": "fail",
        "description": "Always answers with an error result.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _result(msg_id, result):
    _send({"jsonrpc": "2.0", "id": msg_id, "result": result})


def _error(msg_id, code, message):
    _send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def _handle(msg):
    method = msg.get("method")
    msg_id = msg.get("id")
    if msg_id is None:
        return  # notification (e.g. notifications/initialized): nothing to answer
    if method == "initialize":
        _result(
            msg_id,
            {
                "protocolVersion": (msg.get("params") or {}).get("protocolVersion"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.1"},
            },
        )
    elif method == "tools/list":
        _result(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "echo":
            _result(
                msg_id,
                {
                    "content": [{"type": "text", "text": arguments.get("text", "")}],
                    "isError": False,
                },
            )
        elif name == "fail":
            _result(
                msg_id,
                {"content": [{"type": "text", "text": "fake tool blew up"}], "isError": True},
            )
        else:
            _error(msg_id, -32602, f"unknown tool: {name}")
    else:
        _error(msg_id, -32601, f"method not found: {method}")


def main():
    # UTF-8 both ways: the client decodes as UTF-8 and Windows would otherwise use cp1252.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    noise_kb = int(os.environ.get("FAKE_MCP_NOISE_KB", "0"))
    for _ in range(noise_kb):
        sys.stderr.write("x" * 1023 + "\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        _handle(msg)


if __name__ == "__main__":
    main()
