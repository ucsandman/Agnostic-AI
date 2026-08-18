"""
agent/web/server.py — Local Real-Time Visual Companion Server (Port 7843 / --web)
Provides a rich local web GUI for rendered diffs, visual subagent trees, state whiteboards,
and one-click governance controls with REST API support.
"""

import json
import http.server
import socketserver
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any

from agent.governance.state import state_manager
from agent.governance.context import context_manager
from agent.governance.undo import undo_manager
from agent.governance.guard import guard
from agent.governance.audit import audit_manager
from agent.governance.session_manager import session_manager

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ Agnostic AI Visual Companion</title>
    <style>
        :root { --bg: #0d1117; --panel: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; --green: #3fb950; --red: #f85149; --yellow: #d29922; }
        body { margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 20px; }
        .badge { background: #238636; color: #fff; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
        .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
        .card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        h3 { margin-top: 0; color: var(--accent); font-size: 16px; display: flex; justify-content: space-between; align-items: center; }
        pre { background: #000; padding: 12px; border-radius: 6px; overflow-x: auto; color: #7ee787; font-family: monospace; font-size: 13px; max-height: 280px; }
        .btn { background: #21262d; border: 1px solid var(--border); color: var(--text); padding: 7px 14px; border-radius: 6px; cursor: pointer; margin-right: 8px; margin-bottom: 8px; font-size: 13px; font-weight: 500; }
        .btn:hover { background: #30363d; }
        .btn-green { background: #238636; color: #fff; border-color: #2ea043; }
        .btn-green:hover { background: #2ea043; }
        .btn-red { background: #da3633; color: #fff; border-color: #f85149; }
        .progress-bar { background: #21262d; border-radius: 4px; height: 10px; width: 100%; overflow: hidden; margin-top: 8px; }
        .progress-fill { background: var(--green); height: 100%; width: 10%; transition: width 0.3s; }
        .tag { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; background: #30363d; color: #8b949e; }
        .tag-active { background: #1f6feb; color: #fff; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h2 style="margin:0;">🛡️ Agnostic AI Coding Agent — Live Companion</h2>
            <small style="color: #8b949e;">AST Symbol Indexer · Swarm Engine · Governed Autonomy</small>
        </div>
        <div>
            <span id="trust-badge" class="badge">TRUST: READS</span>
            <span class="badge" style="background:#1f6feb;">PORT 7843</span>
        </div>
    </div>
    <div class="grid">
        <div>
            <div class="card">
                <h3>⚡ Live Telemetry & Diff Inspector <span class="tag tag-active" id="live-indicator">LIVE</span></h3>
                <pre id="diff-box">Ready for task input in CLI. Real-time diffs, tool executions, and audit records will render here.</pre>
            </div>
            <div class="card">
                <h3>🎯 State Whiteboard (.agnostic/state.md)</h3>
                <div id="whiteboard-box" style="font-size: 14px; white-space: pre-wrap; font-family: monospace; background:#000; padding:12px; border-radius:6px; max-height:220px; overflow-y:auto;">Loading whiteboard state...</div>
            </div>
            <div class="card">
                <h3>🐝 Subagent Swarm Hierarchy</h3>
                <div style="font-size: 14px; line-height: 1.8;">
                    <div>• 👑 <b>Lead Orchestrator</b> <span class="tag tag-active">Active</span></div>
                    <div style="padding-left: 20px; color: #8b949e;">↳ 🔍 <b>Researcher</b> (Read-Only AST & Codebase Graph)</div>
                    <div style="padding-left: 20px; color: #8b949e;">↳ 🧪 <b>Test Runner</b> (Autonomous Trace Analysis & Repair)</div>
                    <div style="padding-left: 20px; color: #8b949e;">↳ 🛡️ <b>Security Reviewer</b> (Non-Negotiable Policy Guard)</div>
                </div>
            </div>
        </div>
        <div>
            <div class="card">
                <h3>⚙️ Quick Actions</h3>
                <button class="btn btn-green" onclick="triggerApi('/api/test')">🧪 Run Test Suite</button>
                <button class="btn" onclick="triggerApi('/api/undo')">⏪ Undo Last Edit</button>
                <button class="btn" onclick="triggerApi('/api/compact')">🧹 Compact Context</button>
                <button class="btn" onclick="triggerApi('/api/distill')">🧠 Distill Rules</button>
                <div id="action-status" style="margin-top: 8px; font-size: 12px; color: var(--yellow);"></div>
            </div>
            <div class="card">
                <h3>📊 Token & Context Budget</h3>
                <div id="context-info" style="font-size: 13px;">
                    <div>Usage: <b id="token-usage">0</b> / <span id="token-max">16,384</span> tokens (<span id="token-pct">0%</span>)</div>
                    <div class="progress-bar"><div id="token-bar" class="progress-fill"></div></div>
                </div>
            </div>
            <div class="card">
                <h3>💾 Saved Sessions</h3>
                <div id="sessions-list" style="font-size: 13px; max-height: 160px; overflow-y: auto;">
                    <div style="color:#8b949e;">No saved sessions yet. Use /session save in CLI.</div>
                </div>
            </div>
        </div>
    </div>
    <script>
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                document.getElementById('token-usage').innerText = data.context.used_tokens.toLocaleString();
                document.getElementById('token-max').innerText = data.context.max_tokens.toLocaleString();
                document.getElementById('token-pct').innerText = data.context.percentage.toFixed(1) + '%';
                document.getElementById('token-bar').style.width = data.context.percentage + '%';
                document.getElementById('token-bar').style.backgroundColor = data.context.percentage > 75 ? 'var(--red)' : (data.context.percentage > 50 ? 'var(--yellow)' : 'var(--green)');
                document.getElementById('trust-badge').innerText = 'TRUST: ' + data.trust_tier.toUpperCase();
                document.getElementById('whiteboard-box').innerText = data.whiteboard || 'No active whiteboard.';
                
                if (data.sessions && data.sessions.length > 0) {
                    document.getElementById('sessions-list').innerHTML = data.sessions.map(s => 
                        `<div style="padding:4px 0; border-bottom:1px solid #21262d;">🔖 <b>${s.name}</b> <small style="color:#8b949e;">(${s.turn_count} turns, ${s.saved_at})</small></div>`
                    ).join('');
                }
            } catch(e) {}
        }
        async function triggerApi(endpoint) {
            const statusBox = document.getElementById('action-status');
            statusBox.innerText = 'Triggering ' + endpoint + '...';
            try {
                const res = await fetch(endpoint);
                const data = await res.json();
                statusBox.innerText = data.message || 'Done.';
                fetchStatus();
            } catch(e) {
                statusBox.innerText = 'Error: ' + e;
            }
        }
        setInterval(fetchStatus, 3000);
        fetchStatus();
    </script>
</body>
</html>"""


class CompanionHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        # API Endpoints
        if self.path == "/api/status":
            ctx = context_manager.get_status([])
            status_data = {
                "status": "online",
                "context": ctx,
                "trust_tier": guard.get_trust_tier(),
                "whiteboard": state_manager.read_state(),
                "sessions": session_manager.list_sessions(),
                "undo_count": len(undo_manager.history),
            }
            self._send_json(status_data)
            return

        elif self.path == "/api/undo":
            ok, msg = undo_manager.rollback_last()
            self._send_json({"success": ok, "message": msg})
            return

        elif self.path == "/api/test":
            res = subprocess.run(
                "node engine/tests/run-all.cjs"
                if Path("engine/tests/run-all.cjs").exists()
                else "npm test",
                shell=True,
                capture_output=True,
                text=True,
            )
            self._send_json(
                {
                    "success": res.returncode == 0,
                    "message": f"Tests {'passed' if res.returncode == 0 else 'failed'} (Exit {res.returncode})",
                    "output": (res.stdout or "") + (res.stderr or ""),
                }
            )
            return

        elif self.path == "/api/distill":
            res = subprocess.run(
                "node engine/distill/distill.cjs",
                shell=True,
                capture_output=True,
                text=True,
            )
            self._send_json(
                {
                    "success": res.returncode == 0,
                    "message": "Distillation run complete.",
                    "output": (res.stdout or "") + (res.stderr or ""),
                }
            )
            return

        elif self.path == "/api/retro":
            self._send_json({"markdown": audit_manager.generate_retro_markdown()})
            return

        self.send_response(404)
        self.end_headers()

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        self.send_response(status)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, *_args):
        pass  # Quiet logging


def start_companion_server(port: int = 7843):
    try:
        server = socketserver.TCPServer(("", port), CompanionHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return True, f"http://127.0.0.1:{port}"
    except Exception as e:
        return False, str(e)
