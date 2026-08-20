"""
agent/web/server.py — Local Real-Time Visual Companion Server (Port 7843 / --web)
Provides a rich local web GUI for rendered diffs, visual subagent trees, state whiteboards,
live telemetry logs, and one-click governance controls with REST API support.
"""

import json
import http.server
import secrets
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

from agent.governance.state import state_manager
from agent.governance.context import context_manager
from agent.governance.undo import undo_manager
from agent.governance.guard import guard
from agent.governance.audit import audit_manager
from agent.governance.session_manager import session_manager
from agent.tools.subagent import subagent_registry


class CompanionTelemetry:
    """Singleton buffer for live streaming telemetry, tool logs, diffs, and active agent binding."""

    def __init__(self, max_logs: int = 150):
        self._max_logs = max_logs
        self._logs: List[Dict[str, Any]] = []
        self._active_diff: str = ""
        self._active_file: str = ""
        self._agent_instance = None
        self._lock = threading.Lock()

    def bind_agent(self, agent_instance):
        with self._lock:
            self._agent_instance = agent_instance

    def log_event(
        self,
        event_type: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        with self._lock:
            timestamp = time.strftime("%H:%M:%S")
            entry = {
                "id": str(uuid.uuid4())[:8],
                "time": timestamp,
                "type": event_type,
                "message": message,
                "details": details or {},
            }
            self._logs.append(entry)
            if len(self._logs) > self._max_logs:
                self._logs.pop(0)

    def set_diff(self, diff_content: str, file_name: str = ""):
        with self._lock:
            self._active_diff = diff_content
            self._active_file = file_name

    def get_active_diff(self) -> str:
        with self._lock:
            return self._active_diff

    def get_active_file(self) -> str:
        with self._lock:
            return self._active_file

    def get_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._logs[-limit:])

    def clear_logs(self):
        with self._lock:
            self._logs.clear()
            self._active_diff = ""
            self._active_file = ""

    def get_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            if self._agent_instance and hasattr(self._agent_instance, "history"):
                return self._agent_instance.history
            return []

    def get_model_info(self) -> Dict[str, str]:
        with self._lock:
            if self._agent_instance and hasattr(self._agent_instance, "llm_client"):
                cfg = self._agent_instance.llm_client.config
                return {
                    "model": cfg.model or "local-model",
                    "effort": (cfg.reasoning_effort or "med").upper(),
                }
            return {"model": "Agnostic Agent", "effort": "MED"}


companion_telemetry = CompanionTelemetry()

# Per-process secret required on every mutating route (defeats drive-by CSRF).
SESSION_TOKEN = secrets.token_urlsafe(32)

# Routes that change state: POST-only, token-gated, loopback-Origin-gated.
MUTATING_ROUTES = frozenset(
    {"/api/undo", "/api/compact", "/api/test", "/api/distill", "/api/clear_telemetry"}
)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ Agnostic AI Visual Companion</title>
    <style>
        :root {
            --bg: #0d1117;
            --panel: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --text-dim: #8b949e;
            --accent: #58a6ff;
            --green: #3fb950;
            --red: #f85149;
            --yellow: #d29922;
            --purple: #bc8cff;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            padding: 20px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
            margin-bottom: 20px;
        }
        .badge {
            background: #238636;
            color: #fff;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 6px;
        }
        .badge-live {
            background: #1f6feb;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.6; }
            100% { opacity: 1; }
        }
        .grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
        }
        .card {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }
        h3 {
            margin-top: 0;
            color: var(--accent);
            font-size: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .log-box {
            background: #000;
            padding: 12px;
            border-radius: 6px;
            overflow-x: auto;
            color: #c9d1d9;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 12.5px;
            line-height: 1.5;
            max-height: 320px;
            overflow-y: auto;
            border: 1px solid #21262d;
        }
        .btn {
            background: #21262d;
            border: 1px solid var(--border);
            color: var(--text);
            padding: 7px 14px;
            border-radius: 6px;
            cursor: pointer;
            margin-right: 8px;
            margin-bottom: 8px;
            font-size: 13px;
            font-weight: 500;
            transition: background 0.2s;
        }
        .btn:hover { background: #30363d; }
        .btn-green { background: #238636; color: #fff; border-color: #2ea043; }
        .btn-green:hover { background: #2ea043; }
        .btn-red { background: #da3633; color: #fff; border-color: #f85149; }
        .btn-sm { padding: 3px 8px; font-size: 11px; margin-right: 4px; margin-bottom: 0; }
        .progress-bar {
            background: #21262d;
            border-radius: 4px;
            height: 10px;
            width: 100%;
            overflow: hidden;
            margin-top: 8px;
        }
        .progress-fill {
            background: var(--green);
            height: 100%;
            width: 0%;
            transition: width 0.3s, background-color 0.3s;
        }
        .tag {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
            background: #30363d;
            color: #8b949e;
        }
        .tag-active { background: #1f6feb; color: #fff; }
        .tag-completed { background: #238636; color: #fff; }
        .tag-killed { background: #da3633; color: #fff; }
        .log-entry { margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid #161b22; }
        .log-time { color: #8b949e; font-size: 11px; margin-right: 6px; }
        .log-tool { color: #d29922; font-weight: bold; }
        .log-output { color: #7ee787; white-space: pre-wrap; word-break: break-word; }
        .log-diff-add { color: #3fb950; }
        .log-diff-sub { color: #f85149; }
        .log-diff-hunk { color: #bc8cff; }
        .log-subagent { color: #a371f7; }
        .log-agent { color: #58a6ff; white-space: pre-wrap; }
        .log-error { color: #f85149; font-weight: bold; }
        .tab-btn { background: transparent; border: none; color: #8b949e; cursor: pointer; padding: 4px 8px; font-size: 12px; font-weight: bold; }
        .tab-btn.active { color: var(--accent); border-bottom: 2px solid var(--accent); }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h2 style="margin:0; font-size: 20px;">🛡️ Agnostic AI Coding Agent — Live Companion</h2>
            <small style="color: #8b949e;">AST Symbol Indexer · Swarm Engine · Governed Autonomy · Real-Time Parity</small>
        </div>
        <div style="display: flex; align-items: center;">
            <span id="model-badge" class="badge" style="background:#30363d; color:#58a6ff;">MODEL: LOADING...</span>
            <span id="trust-badge" class="badge">TRUST: READS</span>
            <span class="badge badge-live" id="live-badge">● LIVE 1s</span>
        </div>
    </div>
    <div class="grid">
        <div>
            <div class="card">
                <h3>
                    <span>⚡ Live Telemetry & Diff Inspector</span>
                    <div>
                        <button class="tab-btn active" id="tab-telemetry" onclick="setTab('telemetry')">Activity Stream</button>
                        <button class="tab-btn" id="tab-diff" onclick="setTab('diff')">Active Diff</button>
                        <button class="btn btn-sm" onclick="clearTelemetry()">Clear</button>
                    </div>
                </h3>
                <div id="telemetry-view" class="log-box">
                    <div style="color:#8b949e;">Ready for task input in CLI. Real-time tool executions, assistant thoughts, subagents, and diffs stream here live.</div>
                </div>
                <div id="diff-view" class="log-box" style="display:none;">
                    <div id="diff-content" style="color:#8b949e;">No active file diffs recorded yet. Modify a file in CLI to inspect unified diffs.</div>
                </div>
            </div>
            <div class="card">
                <h3>🎯 State Whiteboard (.agnostic/state.md)</h3>
                <div id="whiteboard-box" style="font-size: 13px; white-space: pre-wrap; font-family: monospace; background:#000; padding:12px; border-radius:6px; max-height:220px; overflow-y:auto; border: 1px solid #21262d;">Loading whiteboard state...</div>
            </div>
            <div class="card">
                <h3>🐝 Subagent Swarm Hierarchy</h3>
                <div id="subagent-tree" style="font-size: 13px; line-height: 1.8;">
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
        const SESSION_TOKEN = '__COMPANION_TOKEN__';
        let currentTab = 'telemetry';
        let autoScroll = true;

        function mutate(endpoint) {
            return fetch(endpoint, {
                method: 'POST',
                headers: { 'X-Companion-Token': SESSION_TOKEN },
            });
        }

        function setTab(tab) {
            currentTab = tab;
            document.getElementById('tab-telemetry').className = 'tab-btn' + (tab === 'telemetry' ? ' active' : '');
            document.getElementById('tab-diff').className = 'tab-btn' + (tab === 'diff' ? ' active' : '');
            document.getElementById('telemetry-view').style.display = tab === 'telemetry' ? 'block' : 'none';
            document.getElementById('diff-view').style.display = tab === 'diff' ? 'block' : 'none';
        }

        function formatLogEntry(entry) {
            const time = `<span class="log-time">[${entry.time}]</span>`;
            const type = entry.type;
            const msg = entry.message || '';

            if (type === 'tool_start') {
                return `<div class="log-entry">${time} <span class="log-tool">⚙️ Executing Tool:</span> <span style="color:#e3b341;">${escapeHtml(msg)}</span></div>`;
            } else if (type === 'tool_end') {
                return `<div class="log-entry">${time} <span style="color:#58a6ff; font-weight:bold;">✔️ Tool Output:</span><div class="log-output">${escapeHtml(msg.slice(0, 1000))}</div></div>`;
            } else if (type === 'assistant_chunk' || type === 'assistant') {
                return `<div class="log-entry">${time} <span style="color:#58a6ff; font-weight:bold;">🤖 Agent:</span><div class="log-agent">${escapeHtml(msg.slice(0, 1000))}</div></div>`;
            } else if (type === 'subagent' || type === 'subagent_start' || type === 'subagent_end') {
                return `<div class="log-entry">${time} <span class="log-subagent">🐝 Subagent Swarm:</span> <span>${escapeHtml(msg)}</span></div>`;
            } else if (type === 'diff') {
                return `<div class="log-entry">${time} <span style="color:#3fb950; font-weight:bold;">📝 File Diff:</span><div class="log-output">${formatDiffHtml(msg)}</div></div>`;
            } else if (type === 'error') {
                return `<div class="log-entry">${time} <span class="log-error">❌ Error:</span> <span style="color:#f85149;">${escapeHtml(msg)}</span></div>`;
            } else {
                return `<div class="log-entry">${time} <span style="color:#8b949e;">🔔 ${escapeHtml(msg)}</span></div>`;
            }
        }

        function formatDiffHtml(diffText) {
            const lines = diffText.split('\\n');
            return lines.map(line => {
                const escaped = escapeHtml(line);
                if (line.startsWith('+') && !line.startsWith('+++')) {
                    return `<span class="log-diff-add">${escaped}</span>`;
                } else if (line.startsWith('-') && !line.startsWith('---')) {
                    return `<span class="log-diff-sub">${escaped}</span>`;
                } else if (line.startsWith('@@')) {
                    return `<span class="log-diff-hunk">${escaped}</span>`;
                } else if (line.startsWith('+++') || line.startsWith('---')) {
                    return `<span style="color:#58a6ff; font-weight:bold;">${escaped}</span>`;
                }
                return `<span>${escaped}</span>`;
            }).join('\\n');
        }

        function escapeHtml(str) {
            return String(str)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) return;
                const data = await res.json();

                // 1. Context & Model
                document.getElementById('token-usage').innerText = (data.context.used_tokens || 0).toLocaleString();
                document.getElementById('token-max').innerText = (data.context.max_tokens || 16384).toLocaleString();
                const pct = data.context.percentage || 0;
                document.getElementById('token-pct').innerText = pct.toFixed(1) + '%';
                const bar = document.getElementById('token-bar');
                bar.style.width = Math.min(100, pct) + '%';
                bar.style.backgroundColor = pct > 75 ? 'var(--red)' : (pct > 50 ? 'var(--yellow)' : 'var(--green)');

                if (data.model) {
                    document.getElementById('model-badge').innerText = `MODEL: ${data.model.toUpperCase()} (${data.effort || 'MED'})`;
                }
                document.getElementById('trust-badge').innerText = 'TRUST: ' + (data.trust_tier || 'READS').toUpperCase();
                document.getElementById('whiteboard-box').innerText = data.whiteboard || 'No active whiteboard.';

                // 2. Telemetry Logs
                if (data.telemetry && data.telemetry.length > 0) {
                    const tv = document.getElementById('telemetry-view');
                    const wasAtBottom = tv.scrollHeight - tv.scrollTop <= tv.clientHeight + 40;
                    tv.innerHTML = data.telemetry.map(formatLogEntry).join('');
                    if (wasAtBottom && autoScroll) {
                        tv.scrollTop = tv.scrollHeight;
                    }
                }

                // 3. Active Diff View
                if (data.active_diff) {
                    document.getElementById('diff-content').innerHTML = formatDiffHtml(data.active_diff);
                }

                // 4. Subagent Swarm Hierarchy
                const subTree = document.getElementById('subagent-tree');
                let swarmHtml = '<div>• 👑 <b>Lead Orchestrator</b> <span class="tag tag-active">Active</span></div>';
                if (data.subagents && data.subagents.length > 0) {
                    data.subagents.forEach(s => {
                        const stateTag = s.state === 'running' ? 'tag-active' : (s.state === 'completed' ? 'tag-completed' : 'tag-killed');
                        swarmHtml += `<div style="padding-left: 20px; color: #c9d1d9;">↳ 🤖 <b>${escapeHtml(s.role)}</b> <small style="color:#8b949e;">(${escapeHtml(s.conversationId)}, mode: ${s.workspace_mode || 'inherit'})</small> <span class="tag ${stateTag}">${s.state.toUpperCase()}</span></div>`;
                    });
                } else {
                    swarmHtml += `
                        <div style="padding-left: 20px; color: #8b949e;">↳ 🔍 <b>Researcher</b> (Read-Only AST & Codebase Graph)</div>
                        <div style="padding-left: 20px; color: #8b949e;">↳ 🧪 <b>Test Runner</b> (Autonomous Trace Analysis & Repair)</div>
                        <div style="padding-left: 20px; color: #8b949e;">↳ 🛡️ <b>Security Reviewer</b> (Non-Negotiable Policy Guard)</div>
                    `;
                }
                subTree.innerHTML = swarmHtml;

                // 5. Sessions List
                if (data.sessions && data.sessions.length > 0) {
                    document.getElementById('sessions-list').innerHTML = data.sessions.map(s =>
                        `<div style="padding:4px 0; border-bottom:1px solid #21262d;">🔖 <b>${escapeHtml(s.name)}</b> <small style="color:#8b949e;">(${s.turn_count} turns, ${s.saved_at})</small></div>`
                    ).join('');
                }
            } catch(e) {
                console.error("Telemetry fetch error:", e);
            }
        }

        async function triggerApi(endpoint) {
            const statusBox = document.getElementById('action-status');
            statusBox.innerText = 'Triggering ' + endpoint + '...';
            try {
                const res = await mutate(endpoint);
                const data = await res.json();
                statusBox.innerText = data.message || 'Done.';
                fetchStatus();
            } catch(e) {
                statusBox.innerText = 'Error: ' + e;
            }
        }

        async function clearTelemetry() {
            try {
                await mutate('/api/clear_telemetry');
                document.getElementById('telemetry-view').innerHTML = '<div style="color:#8b949e;">Telemetry logs cleared.</div>';
            } catch(e) {}
        }

        setInterval(fetchStatus, 1000);
        fetchStatus();
    </script>
</body>
</html>"""


class CompanionHandler(http.server.BaseHTTPRequestHandler):
    # BaseHTTPRequestHandler, not SimpleHTTPRequestHandler: the latter would serve
    # the entire working directory (incl. dotfiles) to any GET/HEAD we don't handle.
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            page = HTML_PAGE.replace("__COMPANION_TOKEN__", SESSION_TOKEN)
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        if self.path in MUTATING_ROUTES:
            # State-changing routes are POST-only, so a bare <img>/GET cannot fire them.
            self._send_json({"success": False, "message": "Method not allowed. Use POST."}, 405)
            return

        # API Endpoints
        if self.path == "/api/status":
            history = companion_telemetry.get_history()
            ctx = context_manager.get_status(history)
            model_info = companion_telemetry.get_model_info()
            status_data = {
                "status": "online",
                "context": ctx,
                "model": model_info["model"],
                "effort": model_info["effort"],
                "trust_tier": guard.get_trust_tier(),
                "whiteboard": state_manager.read_state(),
                "sessions": session_manager.list_sessions(),
                "undo_count": len(undo_manager.history),
                "subagents": subagent_registry.list_subagents(),
                "active_diff": companion_telemetry.get_active_diff(),
                "telemetry": companion_telemetry.get_logs(limit=40),
            }
            self._send_json(status_data)
            return

        elif self.path == "/api/retro":
            self._send_json({"markdown": audit_manager.generate_retro_markdown()})
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):  # noqa: vulture
        if self.path not in MUTATING_ROUTES:
            self.send_response(404)
            self.end_headers()
            return

        if not self._authorized():
            self._send_json(
                {
                    "success": False,
                    "message": "Forbidden: bad session token or origin.",
                },
                403,
            )
            return

        if self.path == "/api/clear_telemetry":
            companion_telemetry.clear_logs()
            self._send_json({"success": True, "message": "Telemetry cleared."})
            return

        elif self.path == "/api/undo":
            ok, msg = undo_manager.rollback_last()
            companion_telemetry.log_event("system", f"Undo triggered: {msg}")
            self._send_json({"success": ok, "message": msg})
            return

        elif self.path == "/api/compact":
            agent = companion_telemetry._agent_instance
            if getattr(agent, "is_busy", False):
                # Replacing history from the HTTP thread mid-turn corrupts the
                # conversation the running turn is still appending to.
                self._send_json(
                    {
                        "success": False,
                        "message": "Agent turn in progress — try again when idle.",
                    },
                    409,
                )
                return
            history = companion_telemetry.get_history()
            if history:
                compacted, ok, msg = context_manager.compact_messages(history, force=True)
                if ok and companion_telemetry._agent_instance:
                    companion_telemetry._agent_instance.history = compacted
                companion_telemetry.log_event("system", f"Compaction triggered: {msg}")
                self._send_json({"success": ok, "message": msg})
            else:
                self._send_json(
                    {
                        "success": False,
                        "message": "No active conversation history to compact.",
                    }
                )
            return

        elif self.path == "/api/test":
            if Path("tests/test_agent_qol.py").exists():
                cmd = [sys.executable, "-m", "pytest", "tests/test_agent_qol.py"]
            elif Path("engine/tests/run-all.cjs").exists():
                cmd = ["node", "engine/tests/run-all.cjs"]
            else:
                cmd = [shutil.which("npm") or "npm", "test"]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except subprocess.TimeoutExpired:
                self._send_json(
                    {
                        "success": False,
                        "message": "Test run timed out after 600s and was killed.",
                        "output": "",
                    }
                )
                return
            msg = f"Tests {'passed' if res.returncode == 0 else 'failed'} (Exit {res.returncode})"
            companion_telemetry.log_event("system", f"Test runner executed: {msg}")
            self._send_json(
                {
                    "success": res.returncode == 0,
                    "message": msg,
                    "output": (res.stdout or "") + (res.stderr or ""),
                }
            )
            return

        elif self.path == "/api/distill":
            try:
                res = subprocess.run(
                    ["node", "engine/distill/distill.cjs"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except subprocess.TimeoutExpired:
                self._send_json(
                    {
                        "success": False,
                        "message": "Distillation timed out after 120s and was killed.",
                        "output": "",
                    }
                )
                return
            companion_telemetry.log_event("system", "Distillation run completed.")
            self._send_json(
                {
                    "success": res.returncode == 0,
                    "message": "Distillation run complete.",
                    "output": (res.stdout or "") + (res.stderr or ""),
                }
            )
            return

        self.send_response(404)
        self.end_headers()

    def _authorized(self) -> bool:
        """Mutating routes need the session token AND a loopback Origin/Referer."""
        if not secrets.compare_digest(self.headers.get("X-Companion-Token", ""), SESSION_TOKEN):
            return False
        source = self.headers.get("Origin") or self.headers.get("Referer")
        if source and urlparse(source).hostname not in LOOPBACK_HOSTS:
            return False
        return True

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        self.send_response(status)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, *_args):
        pass  # Quiet logging


class _CompanionServer(socketserver.ThreadingTCPServer):
    """Threading, so a slow /api/test or a parked connection can't stall the page's
    1 Hz /api/status poll. Daemon threads so they never hold up interpreter exit."""

    allow_reuse_address = True
    daemon_threads = True


_server_instance: Optional[socketserver.TCPServer] = None
_server_thread: Optional[threading.Thread] = None


def start_companion_server(port: int = 7843):
    global _server_instance, _server_thread
    if _server_instance is not None:
        return True, f"http://127.0.0.1:{port}"
    try:
        # A busy port usually means another local app (or a second agent), not a
        # broken install — walk up until one is free rather than failing outright.
        for candidate in range(port, port + 10) if port else [0]:
            try:
                _server_instance = _CompanionServer(("127.0.0.1", candidate), CompanionHandler)
                break
            except OSError:
                if candidate == port + 9:
                    raise
        bound_port = _server_instance.server_address[1]
        _server_thread = threading.Thread(
            # Short poll so shutdown() returns promptly instead of waiting out the
            # default 0.5s tick.
            target=lambda: _server_instance.serve_forever(poll_interval=0.05),
            daemon=True,
        )
        _server_thread.start()
        print(f"🔑 Companion session token: {SESSION_TOKEN}")
        return True, f"http://127.0.0.1:{bound_port}"
    except Exception as e:
        return False, str(e)
