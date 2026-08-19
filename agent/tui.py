"""
agent/tui.py — Textual-based Interactive Terminal UI for Agnostic AI Agent
Claude Code-style TUI with a fixed bordered input area pinned to the bottom,
scrollable conversation output above, and a status bar. The input is always
available — you can type the next prompt while the LLM is responding.
"""

import sys
import os
import re
import time
import subprocess
import threading
from pathlib import Path
from typing import List
from collections import deque

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Input, RichLog
from textual.binding import Binding
from textual import work
from textual.css.query import NoMatches

from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from rich import box

from agent.loop import AgentLoop
from agent.llm.client import LLMConfig
from agent.llm.detector import ModelDoctor
from agent.governance.undo import undo_manager, theme_manager
from agent.governance.context import context_manager
from agent.governance.guard import guard
from agent.governance.audit import audit_manager
from agent.governance.session_manager import session_manager
from agent.tools.indexer import code_indexer, CodebaseIndexer
from agent.workflows.tester import AutoTestRunner

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SLASH_COMMANDS = [
    "/theme",
    "/plan",
    "/fix",
    "/compact",
    "/trust",
    "/untrust",
    "/session",
    "/audit",
    "/retro",
    "/research",
    "/review",
    "/swarm",
    "/diagram",
    "/pr",
    "/harvest",
    "/test",
    "/doctor",
    "/model",
    "/undo",
    "/checkpoint",
    "/commit",
    "/learn",
    "/grill-me",
    "/schedule",
    "/loop",
    "/state",
    "/distill",
    "/web",
    "/clear",
    "/multiline",
    "/help",
    "/exit",
]


def get_ui_width() -> int:
    """Returns a bounded narrow column width for readable layout."""
    try:
        cols = os.get_terminal_size().columns
    except Exception:
        cols = 100
    return min(max(cols - 4, 60), 94)


def format_user_display(raw_input: str) -> str:
    """Formats user input for clean display in the user panel."""
    formatted = re.sub(r"[ \t]*(@image:\S+)[ \t]*", r"\n\1\n", raw_input)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted).strip()
    return formatted


def expand_prompt_references(user_prompt: str, indexer: CodebaseIndexer) -> str:
    """Injects code snippets and references for any @file, #symbol, or @image found in prompt."""
    image_refs = re.findall(r"@image:([a-zA-Z0-9_\-\./\\]+)", user_prompt)
    file_refs = re.findall(r"@([a-zA-Z0-9_\-\./\\]+)", user_prompt)
    symbol_refs = re.findall(r"#([a-zA-Z0-9_\.\:]+)", user_prompt)

    injected_context = []

    ws_root = getattr(indexer, "workspace_root", Path(os.getcwd()))
    if isinstance(ws_root, str):
        ws_root = Path(ws_root)

    for img_rel in image_refs:
        img_path = (ws_root / img_rel).resolve()
        if not img_path.exists():
            img_path = (Path(os.getcwd()) / img_rel).resolve()
        if img_path.exists() and img_path.is_file():
            try:
                from PIL import Image

                with Image.open(img_path) as im:
                    w, h = im.size
                    fmt = im.format
                size_kb = img_path.stat().st_size / 1024.0
                injected_context.append(
                    f"### [Attached Image Reference: @image:{img_rel} ({w}x{h} {fmt}, {size_kb:.1f} KB)]\n"
                    f"Image file on disk: `{str(img_path)}`"
                )
            except Exception:
                injected_context.append(
                    f"### [Attached Image Reference: @image:{img_rel}]\n"
                    f"Image file on disk: `{str(img_path)}`"
                )

    for f in file_refs:
        if f == "image" or f.startswith("image:"):
            continue
        res = indexer.resolve_file(f)
        if res:
            rel, content = res
            injected_context.append(
                f"### [Context Reference: @{rel}]:\n```\n{content[:2500]}\n```"
            )

    for s in symbol_refs:
        res = indexer.resolve_symbol(s)
        if res:
            loc, snippet = res
            injected_context.append(
                f"### [Symbol Reference: #{s} ({loc})]:\n```\n{snippet}\n```"
            )

    if injected_context:
        return user_prompt + "\n\n" + "\n\n".join(injected_context)
    return user_prompt


# ─── Textual TUI Application ────────────────────────────────────────────────────

TUI_CSS = """
Screen {
    layout: vertical;
    background: $surface;
}

#output-log {
    height: 1fr;
    border: none;
    scrollbar-size: 1 1;
    padding: 0 1;
}

#input-container {
    height: auto;
    max-height: 8;
    dock: bottom;
    border-top: heavy $accent;
    padding: 0 1;
    background: $surface-darken-1;
}

#prompt-label {
    width: auto;
    height: 1;
    color: $text-muted;
    padding: 0 1 0 0;
    content-align: left middle;
}

#prompt-input {
    width: 1fr;
    height: auto;
    min-height: 1;
    max-height: 5;
    border: round $accent;
    background: $surface-darken-2;
    padding: 0 1;
}

#prompt-input:focus {
    border: round $accent-lighten-2;
}

#status-bar {
    height: 1;
    dock: bottom;
    background: $primary-darken-3;
    color: $text;
    padding: 0 1;
    text-style: dim;
}

#queue-indicator {
    width: auto;
    height: 1;
    color: $warning;
    padding: 0 0 0 1;
    content-align: left middle;
}
"""


class AgnosticTUI(App):
    """Agnostic AI Coding Agent — Textual TUI with always-available input."""

    CSS = TUI_CSS  # noqa: vulture

    BINDINGS = [  # noqa: vulture
        Binding("ctrl+c", "quit_safe", "Exit", show=True),
        Binding("ctrl+l", "clear_output", "Clear", show=True),
    ]

    def __init__(
        self,
        agent: AgentLoop,
        code_indexer_inst: CodebaseIndexer,
        detected_model: str,
        doctor: ModelDoctor,
        test_runner: AutoTestRunner,
        require_confirmation: bool = False,
    ):
        super().__init__()
        self.agent = agent
        self.code_indexer = code_indexer_inst
        self.detected_model = detected_model
        self.doctor = doctor
        self.test_runner = test_runner
        self.require_confirmation = require_confirmation

        # Queue for prompts typed while agent is busy
        self._prompt_queue: deque[str] = deque()
        self._agent_busy = False
        self._stream_buffer: List[str] = []
        self._did_stream = False
        self._lock = threading.Lock()

    def compose(self) -> ComposeResult:  # noqa: vulture
        yield Static(id="status-bar")
        yield RichLog(
            id="output-log", highlight=True, markup=True, wrap=True, max_lines=5000
        )
        with Horizontal(id="input-container"):
            yield Static("❯ ", id="prompt-label")
            yield Input(
                placeholder="Type a message... (Enter to send)", id="prompt-input"
            )
            yield Static("", id="queue-indicator")

    def on_mount(self) -> None:  # noqa: vulture
        """Initialize on app mount."""
        self._print_banner()
        self._update_status_bar()
        self.query_one("#prompt-input", Input).focus()
        # Periodic status bar update
        self.set_interval(3.0, self._update_status_bar)

    def _print_banner(self) -> None:
        log = self.query_one("#output-log", RichLog)
        banner_text = Text()
        banner_text.append(
            "🛡️  AGNOSTIC AI CODING AGENT v1.2.0 (10 Champions Active)\n",
            style="bold cyan",
        )
        banner_text.append(
            "AST Symbol Indexer | Swarm Engine | Web Companion | DashClaw Governed\n",
            style="dim white",
        )
        banner_text.append(
            "Commands: /plan, /fix, /swarm, /test, /compact, /session, /trust, /audit, /undo, /commit, /exit",
            style="yellow",
        )
        log.write(Panel(banner_text, border_style="cyan", box=box.ROUNDED))

        if self.detected_model:
            log.write(Text(f"✓ Model: {self.detected_model}", style="dim green"))
        log.write("")

    def _update_status_bar(self) -> None:
        """Update the bottom status bar with context, model, and git info."""
        try:
            cwd = os.getcwd()
            home = str(Path.home())
            display_cwd = "~" + cwd[len(home) :] if cwd.startswith(home) else cwd

            git_str = ""
            try:
                b_res = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=0.3,
                )
                if b_res.returncode == 0 and b_res.stdout.strip():
                    branch = b_res.stdout.strip()
                    st_res = subprocess.run(
                        ["git", "status", "--porcelain"],
                        capture_output=True,
                        text=True,
                        timeout=0.3,
                    )
                    dirty_count = (
                        len(st_res.stdout.strip().splitlines())
                        if st_res.stdout.strip()
                        else 0
                    )
                    git_str = f" | 🌿 {branch}{'*' if dirty_count else ''}"
            except Exception:
                pass

            curr_model = self.agent.llm_client.config.model
            curr_effort = (
                self.agent.llm_client.config.reasoning_effort or "med"
            ).upper()
            disp_model = curr_model
            for p in LLMConfig.PRESETS.values():
                if p["model"] == curr_model:
                    disp_model = p["name"].split("(")[0].strip()
                    break

            st = context_manager.get_status(self.agent.history)
            used = st["used_tokens"]
            total = st["max_tokens"]
            pct = st["percentage"]

            busy_str = " ⏳ thinking..." if self._agent_busy else ""
            queue_count = len(self._prompt_queue)
            queue_str = f" | 📬 {queue_count} queued" if queue_count > 0 else ""

            status_text = (
                f" 📁 {display_cwd}{git_str}  │  🤖 {disp_model} ({curr_effort})"
                f"  │  📊 {used:,}/{total:,} tok ({pct:.1f}%){queue_str}{busy_str}"
            )
            self.query_one("#status-bar", Static).update(status_text)
        except Exception:
            pass

    def _write_output(self, *args, **kwargs) -> None:
        """Thread-safe write to the output log."""
        try:
            log = self.query_one("#output-log", RichLog)
            log.write(*args, **kwargs)
        except NoMatches:
            pass

    def _output_callback(self, msg_type: str, content: str) -> None:
        """Callback from AgentLoop — runs on worker thread, posts to UI thread."""
        try:
            from agent.web.server import companion_telemetry

            if msg_type != "assistant_chunk":
                companion_telemetry.log_event(msg_type, content)
        except Exception:
            pass

        if msg_type == "assistant_chunk":
            with self._lock:
                self._stream_buffer.append(content)
                buf_len = len(self._stream_buffer)
            # Flush streaming chunks periodically
            if buf_len % 8 == 0:
                self._flush_stream()

        elif msg_type == "assistant":
            # Check if we had streamed content before flushing
            with self._lock:
                had_streamed = len(self._stream_buffer) > 0 or getattr(
                    self, "_did_stream", False
                )
            self._flush_stream()
            if not had_streamed and content:
                # Non-streamed final response — show as panel
                self.call_from_thread(
                    self._write_output,
                    Panel(
                        Markdown(content),
                        title="[bold cyan]🛡️ Agnostic Agent[/bold cyan]",
                        title_align="left",
                        border_style="cyan",
                        box=box.ROUNDED,
                        padding=(0, 1),
                    ),
                )
            with self._lock:
                self._stream_buffer = []
                self._did_stream = False

        elif msg_type == "tool_start":
            self.call_from_thread(
                self._write_output,
                Text.from_markup(
                    f"[dim magenta]⚙️  Executing Tool:[/dim magenta] [yellow]{content}[/yellow]"
                ),
            )

        elif msg_type == "tool_end":
            clipped = content[:600] + ("..." if len(content) > 600 else "")
            self.call_from_thread(
                self._write_output,
                Panel(
                    clipped,
                    title="[dim blue]⚙️ Tool Output[/dim blue]",
                    title_align="left",
                    border_style="dim blue",
                    box=box.ROUNDED,
                    padding=(0, 1),
                ),
            )

        elif msg_type == "subagent":
            self.call_from_thread(
                self._write_output,
                Text.from_markup(
                    f"[bold green]🐝 Subagent Notification:[/bold green] {content}"
                ),
            )

        elif msg_type == "system":
            self.call_from_thread(
                self._write_output,
                Text.from_markup(f"[bold yellow]🔔 {content}[/bold yellow]"),
            )

        elif msg_type == "error":
            self.call_from_thread(
                self._write_output,
                Panel(
                    Text(content, style="bold red"),
                    title="[bold red]❌ Error[/bold red]",
                    title_align="left",
                    border_style="red",
                    box=box.ROUNDED,
                    padding=(0, 1),
                ),
            )

    def _flush_stream(self) -> None:
        """Flush accumulated streaming tokens to the output log."""
        with self._lock:
            if not self._stream_buffer:
                return
            chunk = "".join(self._stream_buffer)
            self._stream_buffer = []
            self._did_stream = True
        if chunk.strip():
            self.call_from_thread(
                self._write_output,
                Text.from_markup(f"[bold cyan]🛡️ Agnostic Agent:[/bold cyan] {chunk}"),
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:  # noqa: vulture
        """Handle Enter key in the input box."""
        user_input = event.value.strip()
        if not user_input:
            return
        event.input.value = ""

        if self._agent_busy:
            # Queue the prompt for later
            self._prompt_queue.append(user_input)
            self._write_output(
                Text.from_markup(
                    f"[dim yellow]📬 Queued (agent busy): {user_input}[/dim yellow]"
                )
            )
            self._update_queue_indicator()
            self._update_status_bar()
            return

        self._process_input(user_input)

    def _update_queue_indicator(self) -> None:
        """Update the visual queue indicator next to the input."""
        try:
            indicator = self.query_one("#queue-indicator", Static)
            count = len(self._prompt_queue)
            if count > 0:
                indicator.update(f"📬{count}")
            else:
                indicator.update("")
        except NoMatches:
            pass

    def _process_input(self, user_input: str) -> None:
        """Route user input to slash commands or agent turn."""

        # Handle exit
        if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
            self.exit()
            return

        # Display user message in output log
        if not user_input.startswith("/"):
            display_text = format_user_display(user_input)
            self._write_output(
                Panel(
                    Text(display_text, style="bold bright_white"),
                    title="[bold #58a6ff]🧑 You[/bold #58a6ff]",
                    title_align="left",
                    border_style="#1f6feb",
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )

        # --- Slash commands (handled synchronously) ---
        handled = self._handle_slash_command(user_input)
        if handled:
            self._update_status_bar()
            return

        # --- Normal prompt: run agent turn in background worker ---
        expanded_input = expand_prompt_references(user_input, self.code_indexer)
        self._agent_busy = True
        self._update_status_bar()
        self._run_agent_turn(expanded_input)

    @work(thread=True, exclusive=True, group="agent_turn")
    def _run_agent_turn(self, expanded_input: str) -> None:
        """Execute agent turn in a background thread so input stays responsive."""
        start_time = time.time()
        try:
            # Swap the output callback to our TUI callback
            original_callback = self.agent.output_callback
            self.agent.output_callback = self._output_callback
            self.agent.run_turn(expanded_input)
            self.agent.output_callback = original_callback
        except Exception as e:
            self.call_from_thread(
                self._write_output,
                Panel(
                    Text(f"Error: {str(e)}", style="bold red"),
                    title="[bold red]❌ Error[/bold red]",
                    title_align="left",
                    border_style="red",
                    box=box.ROUNDED,
                ),
            )
        finally:
            duration = time.time() - start_time
            self.call_from_thread(
                self._write_output,
                Text(f"⏱ Turn completed in {duration:.2f}s", style="dim"),
            )
            self._agent_busy = False
            self.call_from_thread(self._update_status_bar)
            # Process next queued prompt if any
            self.call_from_thread(self._process_queue)

    def _process_queue(self) -> None:
        """Process the next queued prompt if any."""
        if self._prompt_queue and not self._agent_busy:
            next_prompt = self._prompt_queue.popleft()
            self._update_queue_indicator()
            self._write_output(
                Text.from_markup(
                    f"[dim cyan]📬 Processing queued prompt: {next_prompt}[/dim cyan]"
                )
            )
            self._process_input(next_prompt)

    def _handle_slash_command(self, user_input: str) -> bool:
        """Handle slash commands. Returns True if handled, False to fall through to agent."""

        if user_input == "/clear":
            log = self.query_one("#output-log", RichLog)
            log.clear()
            self._print_banner()
            return True

        elif user_input.startswith("/theme"):
            parts = user_input.split()
            if len(parts) > 1:
                msg = theme_manager.set_theme(parts[1])
                self._write_output(Text(f"🎨 {msg}", style="bold green"))
            else:
                available = ", ".join(
                    f"{k} ({v['name']})" for k, v in theme_manager.PALETTES.items()
                )
                self._write_output(
                    Text(
                        f"Usage: /theme <name>\nAvailable: {available}",
                        style="yellow",
                    )
                )
            return True

        elif user_input == "/compact":
            self.agent.history, ok, msg = context_manager.compact_messages(
                self.agent.history, force=True
            )
            self._write_output(Text(msg, style="bold green"))
            return True

        elif user_input.startswith("/fix"):
            custom_cmd = user_input.replace("/fix", "").strip() or None
            self.test_runner.quick_fix(custom_command=custom_cmd)
            return True

        elif user_input.startswith("/trust"):
            mode = user_input.replace("/trust", "").strip() or "reads"
            msg = guard.set_trust_tier(mode)
            self._write_output(Text(f"🛡️ {msg}", style="bold green"))
            return True

        elif user_input == "/untrust":
            msg = guard.set_trust_tier("strict")
            self._write_output(Text(f"🛡️ {msg}", style="bold yellow"))
            return True

        elif user_input.startswith("/session"):
            parts = user_input.split()
            subcmd = parts[1].lower() if len(parts) > 1 else "list"
            sess_name = parts[2] if len(parts) > 2 else "latest"

            if subcmd == "save":
                ok, msg = session_manager.save_session(sess_name, self.agent.history)
                self._write_output(Text(f"💾 {msg}", style="bold green"))
            elif subcmd == "load":
                hist, msg = session_manager.load_session(sess_name)
                if hist:
                    self.agent.history = hist
                    self._write_output(Text(f"📂 {msg}", style="bold green"))
                else:
                    self._write_output(Text(f"❌ {msg}", style="bold red"))
            elif subcmd == "list":
                sessions = session_manager.list_sessions()
                if not sessions:
                    self._write_output(Text("No saved sessions found.", style="dim"))
                else:
                    self._write_output(Text("Saved Sessions:", style="bold cyan"))
                    for s in sessions:
                        self._write_output(
                            Text(
                                f"• {s['name']} ({s['turn_count']} turns, {s['saved_at']})",
                                style="green",
                            )
                        )
            return True

        elif user_input in ("/audit", "/retro"):
            report = audit_manager.generate_retro_markdown()
            self._write_output(
                Panel(
                    Markdown(report),
                    title="📋 Session Audit & Retrospective",
                    border_style="cyan",
                )
            )
            path = audit_manager.export_audit_file()
            self._write_output(Text(f"Exported to {path}", style="dim"))
            return True

        elif user_input == "/undo":
            success, msg = undo_manager.rollback_last()
            style = "bold green" if success else "bold yellow"
            icon = "⏪" if success else "⚠️"
            self._write_output(Text(f"{icon} {msg}", style=style))
            return True

        elif user_input.startswith("/checkpoint"):
            parts = user_input.split()
            subcmd = parts[1].lower() if len(parts) > 1 else "list"
            cp_name = parts[2] if len(parts) > 2 else "latest"

            if subcmd == "save":
                msg = undo_manager.create_checkpoint(cp_name)
                self._write_output(Text(f"🏷️ {msg}", style="bold green"))
            elif subcmd in ("rollback", "load", "restore"):
                success, msg = undo_manager.rollback_to_checkpoint(cp_name)
                style = "bold green" if success else "bold yellow"
                self._write_output(Text(f"⏪ {msg}", style=style))
            elif subcmd == "list":
                if not undo_manager.checkpoints:
                    self._write_output(
                        Text(
                            "No checkpoints saved. Use: /checkpoint save <name>",
                            style="dim",
                        )
                    )
                else:
                    self._write_output(
                        Text("Available Checkpoints:", style="bold cyan")
                    )
                    for name, history in undo_manager.checkpoints.items():
                        self._write_output(
                            Text(
                                f"• {name} ({len(history)} history entries)",
                                style="green",
                            )
                        )
            return True

        elif user_input == "/commit":
            self._handle_commit()
            return True

        elif user_input.startswith("/test"):
            custom_cmd = user_input.replace("/test", "").strip() or None
            self.test_runner.auto_repair_loop(custom_command=custom_cmd)
            return True

        elif user_input == "/doctor":
            self._write_output(
                Panel(
                    self.doctor.format_report(),
                    title="Agnostic Doctor / Endpoint Inspector",
                    border_style="cyan",
                )
            )
            return True

        elif user_input.startswith("/model"):
            parts = user_input.split()
            if len(parts) > 1:
                target_key = parts[1].lower()
                effort = parts[2].lower() if len(parts) > 2 else None
                msg = self.agent.llm_client.switch_model(
                    preset_key=target_key, reasoning_effort=effort
                )
                self._write_output(Text(f"🧠 {msg}", style="bold green"))
            else:
                self._write_output(
                    Text(
                        "Usage: /model <preset_key> [effort]\n"
                        "Example: /model gemini-pro high\n"
                        "Use the original CLI for the interactive model picker.",
                        style="yellow",
                    )
                )
            return True

        elif user_input.startswith("/plan"):
            task = user_input.replace("/plan", "").strip() or "General Task Plan"
            self._write_output(
                Text(f"Initiating Dynamic Planning Workflow for: {task}", style="cyan")
            )
            plan_prompt = (
                f"Create a deterministic execution plan for the following objective:\n'{task}'\n"
                "State ASSUMPTIONS, then a numbered step-by-step PLAN with specific verification criteria for each step."
            )
            self._agent_busy = True
            self._update_status_bar()
            self._run_agent_turn(plan_prompt)
            return True

        elif user_input.startswith("/research"):
            topic = user_input.replace("/research", "").strip()
            if not topic:
                self._write_output(
                    Text(
                        "Please provide a research query, e.g. /research database connection pooling",
                        style="yellow",
                    )
                )
                return True
            self._write_output(Text(f"Subagent researching '{topic}'...", style="cyan"))
            try:
                report = self.agent.subagents.spawn("researcher", topic)
                self._write_output(
                    Panel(
                        Markdown(report), title="Research Results", border_style="cyan"
                    )
                )
            except Exception as e:
                self._write_output(Text(f"Research error: {e}", style="red"))
            return True

        elif user_input.startswith("/review"):
            self._write_output(
                Text("Subagent reviewing workspace diffs...", style="cyan")
            )
            try:
                report = self.agent.subagents.spawn(
                    "reviewer",
                    "Inspect git status and recent diffs for bugs, missing tests, or security concerns.",
                )
                self._write_output(
                    Panel(Markdown(report), title="Code Review", border_style="cyan")
                )
            except Exception as e:
                self._write_output(Text(f"Review error: {e}", style="red"))
            return True

        elif user_input.startswith("/swarm"):
            task = user_input.replace("/swarm", "").strip()
            if not task:
                self._write_output(
                    Text("Usage: /swarm <complex task or feature>", style="yellow")
                )
                return True
            from agent.workflows.swarm import SwarmCoordinator

            swarm = SwarmCoordinator(self.agent.subagents, self.agent.llm_client)
            synthesis = swarm.dispatch_swarm(task)
            self._write_output(
                Panel(
                    Markdown(synthesis),
                    title="🐝 Swarm Unified Strategy",
                    border_style="green",
                )
            )
            return True

        elif user_input.startswith(("/diagram", "/map")):
            from agent.workflows.diagram import ArchitectureDiagrammer

            diag = ArchitectureDiagrammer(self.agent.workspace_root)
            m_code = diag.generate_mermaid_map()
            self._write_output(
                Panel(
                    m_code, title="📊 Mermaid Architecture Diagram", border_style="cyan"
                )
            )
            return True

        elif user_input.startswith("/pr"):
            from agent.workflows.pr_pilot import PRAutoPilot

            pilot = PRAutoPilot(self.agent.workspace_root, self.agent.llm_client)
            pilot.generate_pr_summary()
            return True

        elif user_input.startswith("/harvest"):
            from agent.governance.harvester import harvester

            count = harvester.scan_and_harvest()
            self._write_output(
                Text(
                    f"🌾 Harvested {count} cross-agent corrections into candidate ladder.",
                    style="bold green",
                )
            )
            return True

        elif user_input.startswith("/learn"):
            lesson = user_input.replace("/learn", "").strip()
            if not lesson:
                self._write_output(
                    Text("Usage: /learn <lesson or constraint>", style="yellow")
                )
                return True
            from agent.governance.learn import learner

            ok, msg = learner.record_lesson(lesson)
            audit_manager.record(event_type="lesson_learned", description=lesson)
            self._write_output(Text(f"🧠 {msg}", style="bold green"))
            return True

        elif user_input.startswith(("/schedule", "/loop")):
            from agent.workflows.scheduler import scheduler

            resp = scheduler.parse_and_schedule(user_input, self.agent.run_turn)
            self._write_output(Text(f"⏰ {resp}", style="bold magenta"))
            return True

        elif user_input.startswith("/grill-me") or user_input.startswith("/grill"):
            self._write_output(
                Text(
                    "Interactive /grill-me requires the original CLI for interactive prompts.\n"
                    "Use: agnostic --legacy",
                    style="yellow",
                )
            )
            return True

        elif user_input.startswith("/state"):
            from agent.governance.state import state_manager

            self._write_output(
                Panel(
                    state_manager.read_state(),
                    title="🎯 Persistent State Whiteboard (.agnostic/state.md)",
                    border_style="green",
                )
            )
            return True

        elif user_input == "/distill":
            self._write_output(
                Text("Triggering Harness Distillation Engine...", style="cyan")
            )
            res = subprocess.run(
                "node engine/distill/distill.cjs",
                cwd=str(self.agent.workspace_root),
                shell=True,
                capture_output=True,
                text=True,
            )
            self._write_output(
                Panel(
                    res.stdout or res.stderr or "Distillation complete.",
                    title="Distillation Results",
                    border_style="cyan",
                )
            )
            return True

        elif user_input == "/web":
            from agent.web.server import start_companion_server, companion_telemetry
            import webbrowser

            companion_telemetry.bind_agent(self.agent)
            ok, web_url = start_companion_server(7843)
            try:
                webbrowser.open(web_url if ok else "http://127.0.0.1:7843")
            except Exception:
                pass
            msg = (
                f"🌐 Live Visual Companion active at: {web_url}"
                if ok
                else "Companion server is active at: http://127.0.0.1:7843"
            )
            self._write_output(Text(msg, style="bold green" if ok else "yellow"))
            return True

        elif user_input == "/help":
            help_text = (
                "[bold]Available Commands & Slash Shortcuts:[/bold]\n"
                "• [bold cyan]/fix [cmd][/]         - One-click diagnosis & automated test repair\n"
                "• [bold cyan]/compact[/]           - Manual context compression & history distillation\n"
                "• [bold cyan]/session save <name>[/] - Snapshot conversation turns & whiteboard state\n"
                "• [bold cyan]/session load <name>[/] - Restore saved session snapshot\n"
                "• [bold cyan]/session list[/]        - List saved snapshots\n"
                "• [bold cyan]/trust [reads|tests|all][/] - Adjust session trust level\n"
                "• [bold cyan]/audit / /retro[/]     - Compile & export session retrospective report\n"
                "• [bold cyan]/web[/]                 - Start live visual browser companion (Port 7843)\n"
                "• [bold cyan]/swarm <task>[/]       - Dispatch 3 parallel subagents simultaneously\n"
                "• [bold cyan]/diagram[/]            - Generate instant Mermaid architecture dependency diagram\n"
                "• [bold cyan]/pr[/]                 - Generate GitHub Pull Request summary and description\n"
                "• [bold cyan]/harvest[/]            - Harvest corrections across local transcripts\n"
                "• [bold cyan]/learn <lesson>[/]    - Record candidate rule/lesson into harness SSOT\n"
                "• [bold cyan]/grill-me <task>[/]   - Interactive lead architect interview (legacy CLI)\n"
                '• [bold cyan]/schedule every 30s "cmd"[/] - Run recurring background routine\n'
                "• [bold cyan]/state[/]              - View persistent state whiteboard\n"
                "• [bold cyan]/distill[/]            - Run 4-Tier Promotion Ladder & prune candidate rules\n"
                "• [bold cyan]/test [cmd][/]         - Run autonomous test-and-repair loop until tests pass\n"
                "• [bold cyan]/undo[/]               - Instant snapshot rollback of the last file edit/write\n"
                "• [bold cyan]/commit[/]             - Auto-generate conventional git commit\n"
                "• [bold cyan]/plan <task>[/]        - Generate a step-by-step goal-driven plan\n"
                "• [bold cyan]/doctor[/]             - Auto-detect model status & endpoint health\n"
                "• [bold cyan]/model [preset] [effort][/] - Switch model and effort level\n"
                "• [bold cyan]/clear[/]              - Clear the output log\n"
                "• [bold cyan]/exit[/]               - Exit the interactive REPL\n"
            )
            self._write_output(Text.from_markup(help_text))
            return True

        # Not a slash command
        if user_input.startswith("/"):
            self._write_output(
                Text(
                    f"Unknown command: {user_input}. Type /help for available commands.",
                    style="yellow",
                )
            )
            return True

        return False

    def _handle_commit(self) -> None:
        """Autonomous Git Commit generator workflow."""
        self._write_output(
            Text("Inspecting staged changes and git status...", style="cyan")
        )
        try:
            st = subprocess.run(
                "git status --short", shell=True, capture_output=True, text=True
            ).stdout.strip()
            if not st:
                self._write_output(
                    Text("No changes detected in git working tree.", style="dim")
                )
                return

            diff = subprocess.run(
                "git diff --cached", shell=True, capture_output=True, text=True
            ).stdout.strip()
            if not diff:
                diff = subprocess.run(
                    "git diff", shell=True, capture_output=True, text=True
                ).stdout.strip()

            self._write_output(Panel(st, title="Git Status", border_style="yellow"))

            commit_prompt = (
                f"Based on the following git changes:\n```\n{st}\n```\nDiff preview:\n```\n{diff[:1500]}\n```\n"
                "Generate a single, precise Conventional Commit message. Output ONLY the commit message."
            )
            msg = (
                self.agent.llm_client.chat_completion(
                    [
                        {
                            "role": "system",
                            "content": "You are a git commit assistant. Output only the commit title and optional bullet body.",
                        },
                        {"role": "user", "content": commit_prompt},
                    ]
                )
                .choices[0]
                .message.content.strip()
            )

            self._write_output(
                Text(f"Suggested Commit Message:\n{msg}", style="bold green")
            )
            self._write_output(
                Text(
                    'To commit, type: git add -A && git commit -m "<message>" in your terminal.',
                    style="dim yellow",
                )
            )
        except Exception as e:
            self._write_output(
                Text(f"Git commit workflow error: {str(e)}", style="red")
            )

    def action_quit_safe(self) -> None:  # noqa: vulture
        """Ctrl+C handler."""
        if self._agent_busy:
            self._write_output(
                Text("Agent is busy. Press Ctrl+C again to force quit.", style="yellow")
            )
            self._agent_busy = False
        else:
            self.exit()

    def action_clear_output(self) -> None:  # noqa: vulture
        """Ctrl+L handler."""
        log = self.query_one("#output-log", RichLog)
        log.clear()
        self._print_banner()


# ─── Entry Point ─────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Agnostic AI Autonomous Coding Agent")
    parser.add_argument(
        "--url",
        default="http://localhost:1234/v1",
        help="LLM API Base URL (LM Studio, Ollama, etc.)",
    )
    parser.add_argument("--model", default="local-model", help="Model name / ID")
    parser.add_argument("--api-key", default="lm-studio", help="API Key")
    parser.add_argument(
        "--compact",
        action="store_true",
        default=True,
        help="Use compact harness prompt for local context limits (default: True)",
    )
    parser.add_argument(
        "--full-prompt",
        action="store_true",
        help="Force loading full 14KB system prompt",
    )
    parser.add_argument("--prompt", "-p", help="Single prompt execution mode")
    parser.add_argument(
        "--ask-permissions",
        action="store_true",
        default=False,
        help="Enable manual confirmation gates for hard-stop commands",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the real-time visual web companion on port 7843",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use the legacy prompt_toolkit CLI instead of the TUI",
    )
    args = parser.parse_args()

    # If --legacy, delegate to the old CLI
    if args.legacy:
        from agent.cli import main as legacy_main

        legacy_main()
        return

    # Auto-discover active model
    doctor = ModelDoctor(base_url=args.url, api_key=args.api_key)
    detection = doctor.inspect()
    detected_model = detection.get("active_model") or args.model

    config = LLMConfig(
        base_url=args.url,
        api_key=args.api_key,
        model=detected_model,
    )

    use_compact = not args.full_prompt
    require_confirmation = args.ask_permissions

    def _noop_confirm(_: str) -> bool:
        return True

    def _noop_output(msg_type: str, content: str) -> None:
        pass  # TUI overrides this

    agent = AgentLoop(
        workspace_root=os.getcwd(),
        llm_config=config,
        confirm_callback=_noop_confirm if not require_confirmation else None,
        output_callback=_noop_output,
    )
    if use_compact:
        agent._load_harness_system_prompt(compact=True)

    # Pre-index workspace
    code_indexer.workspace_root = Path(os.getcwd()).resolve()
    code_indexer.index_workspace()

    from agent.web.server import companion_telemetry

    companion_telemetry.bind_agent(agent)

    if args.web:
        from agent.web.server import start_companion_server
        import webbrowser

        ok, web_url = start_companion_server(7843)
        try:
            webbrowser.open(web_url if ok else "http://127.0.0.1:7843")
        except Exception:
            pass

    # Single prompt mode: run without TUI
    if args.prompt:
        expanded_prompt = expand_prompt_references(args.prompt, code_indexer)
        # Use the old-style output callback for single-prompt
        from agent.cli import rich_output_callback

        agent.output_callback = rich_output_callback
        agent.run_turn(expanded_prompt)
        sys.exit(0)

    # Set context window limit
    if hasattr(config, "context_window") and config.context_window:
        context_manager.set_max_tokens(config.context_window)

    test_runner = AutoTestRunner(
        workspace_root=Path(os.getcwd()),
        agent_loop_func=agent.run_turn,
    )

    # Launch TUI
    app = AgnosticTUI(
        agent=agent,
        code_indexer_inst=code_indexer,
        detected_model=detected_model,
        doctor=doctor,
        test_runner=test_runner,
        require_confirmation=require_confirmation,
    )
    app.run()


if __name__ == "__main__":
    main()
