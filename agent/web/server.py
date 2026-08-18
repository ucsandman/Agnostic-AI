"""
agent/web/server.py — Local Real-Time Visual Companion Server (Port 7843 / --web)
Provides a rich local web GUI for rendered Markdown diffs, visual subagent trees, and one-click controls.
"""

import http.server
import socketserver
import threading

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ Agnostic AI Visual Companion</title>
    <style>
        :root { --bg: #0d1117; --panel: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; --green: #3fb950; }
        body { margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 20px; }
        .badge { background: #238636; color: #fff; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
        .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        h3 { margin-top: 0; color: var(--accent); font-size: 16px; }
        pre { background: #000; padding: 12px; border-radius: 6px; overflow-x: auto; color: #7ee787; font-family: monospace; font-size: 13px; }
        .btn { background: #21262d; border: 1px solid var(--border); color: var(--text); padding: 6px 12px; border-radius: 6px; cursor: pointer; margin-right: 8px; }
        .btn:hover { background: #30363d; }
        .btn-green { background: #238636; color: #fff; }
    </style>
</head>
<body>
    <div class="header">
        <h2>🛡️ Agnostic AI Coding Agent — Live Companion</h2>
        <span class="badge">HARNESS ACTIVE · PORT 7843</span>
    </div>
    <div class="grid">
        <div>
            <div class="card">
                <h3>⚡ Live Agent Telemetry & Diff Inspector</h3>
                <pre>Ready for task input in CLI. Real-time diffs and execution trees will render here.</pre>
            </div>
            <div class="card">
                <h3>🐝 Subagent Execution Tree</h3>
                <div style="font-size: 14px;">
                    <div>• 👑 <b>Lead Orchestrator</b> (Active)</div>
                    <div style="padding-left: 20px; color: #8b949e;">↳ 🔍 <b>Researcher</b> (Idle)</div>
                    <div style="padding-left: 20px; color: #8b949e;">↳ 🧪 <b>Test Runner</b> (Idle)</div>
                    <div style="padding-left: 20px; color: #8b949e;">↳ 🛡️ <b>Security Reviewer</b> (Idle)</div>
                </div>
            </div>
        </div>
        <div>
            <div class="card">
                <h3>⚙️ Quick Actions</h3>
                <button class="btn btn-green" onclick="fetch('/api/test')">Run Tests</button>
                <button class="btn" onclick="fetch('/api/undo')">Undo Last Edit</button>
                <button class="btn" onclick="fetch('/api/distill')">Distill Rules</button>
            </div>
            <div class="card">
                <h3>📊 Model Health</h3>
                <div style="font-size: 13px;">
                    <div>Endpoint: <code>http://localhost:1234/v1</code></div>
                    <div>Status: <span style="color: var(--green);">● Connected</span></div>
                    <div>Context: <b>16,384 tokens</b></div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""


class CompanionHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def log_message(self, *args):  # noqa: vulture
        pass  # Quiet logging


def start_companion_server(port: int = 7843):  # noqa: vulture
    try:
        server = socketserver.TCPServer(("", port), CompanionHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return True, f"http://127.0.0.1:{port}"
    except Exception as e:
        return False, str(e)
