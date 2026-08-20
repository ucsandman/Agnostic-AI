"""
agent/tui.py — Textual-based Interactive Terminal UI for Agnostic AI Agent
Claude Code-style TUI with a fixed bordered input area pinned to the bottom,
scrollable conversation output above, and a status bar. The input is always
available — you can type the next prompt while the LLM is responding.
"""

import sys
import os
import contextlib
import io
import time
import subprocess
import threading
from pathlib import Path
from typing import List, Optional
from collections import deque

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Input, RichLog
from textual.binding import Binding
from textual import events, work
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
from agent.ui_common import (
    SLASH_COMMANDS,
    build_arg_parser,
    detect_model,
    expand_prompt_references,
    format_user_display,
    index_workspace,
    maybe_start_web_companion,
    parse_slash_command,
    safe_text,
)

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
        Binding("tab", "complete_slash", "Complete", show=False),
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
        # Rendered by the UI thread, refreshed by a background worker (see
        # _refresh_git_status) — `git rev-parse` + `git status` on the UI thread
        # stalled the app on every 3s tick.
        self._git_status = ""

        # Human-in-the-loop confirmation for hard-stop commands. Blocks the calling
        # worker thread via this event until the human answers in the input box.
        self._confirm_event = threading.Event()
        self._confirm_response = False
        self._awaiting_confirm = False
        # Always wire a REAL confirm callback. A missing/None callback is treated as
        # auto-approve by AgentLoop/the tool registry — the TUI must never rely on
        # that fallback, so this is set unconditionally, not gated on --ask-permissions.
        self.agent.confirm_callback = self._tui_confirm_callback
        # Wired ONCE, for the life of the app. Swapping it in only for the duration
        # of _run_agent_turn threw away everything /fix, /test, /schedule and /loop
        # produced — those drive the agent from their own worker/scheduler threads.
        self.agent.output_callback = self._output_callback

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
        # Textual runs the whole process inside redirect_stdout(_PrintCapture); that
        # capture only forwards to targets registered here, so without this every
        # Console().print() from a tool (ask_question prompts, diff cards, the test
        # runner) is silently dropped.
        self.begin_capture_print(self)
        self._print_banner()
        self._update_status_bar()
        self.query_one("#prompt-input", Input).focus()
        # Periodic status bar update (render only — git shells out on a worker)
        self.set_interval(3.0, self._update_status_bar)
        self._refresh_git_status()
        self.set_interval(3.0, self._refresh_git_status)

    def on_print(self, event: events.Print) -> None:  # noqa: vulture
        """Show stray stdout/stderr writes in the log. Print events arrive through
        post_message(), which hands off to the event loop via call_soon_threadsafe
        when the print came from a worker thread — so this handler always runs on
        the UI thread and can write directly."""
        text = event.text.rstrip("\n")
        if text.strip():
            self._write_output(safe_text(text))

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

            git_str = self._git_status

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

    @work(thread=True, exclusive=True, group="statusbar")
    def _refresh_git_status(self) -> None:
        """Shells out for branch/dirty state on a worker thread and caches the
        rendered fragment for _update_status_bar."""
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
        if git_str != self._git_status:
            self._git_status = git_str
            self.call_from_thread(self._update_status_bar)

    def _write_output(self, *args, **kwargs) -> None:
        """Write to the output log. MUST be called from the app/UI thread — use
        _post_output() from a worker thread instead."""
        try:
            log = self.query_one("#output-log", RichLog)
            log.write(*args, **kwargs)
        except NoMatches:
            pass

    def _post_output(self, *args, **kwargs) -> None:
        """Thread-safe write to the output log — safe to call from the UI thread
        or from any worker thread."""
        if threading.get_ident() == self._thread_id:
            self._write_output(*args, **kwargs)
        else:
            self.call_from_thread(self._write_output, *args, **kwargs)

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
                self._post_output(
                    Panel(
                        Markdown(content),
                        title="[bold cyan]🛡️ Agnostic Agent[/bold cyan]",
                        title_align="left",
                        border_style="cyan",
                        box=box.ROUNDED,
                        padding=(0, 1),
                    )
                )
            with self._lock:
                self._stream_buffer = []
                self._did_stream = False

        elif msg_type == "tool_start":
            label = Text.from_markup("[dim magenta]⚙️  Executing Tool:[/dim magenta] ")
            label.append(content, style="yellow")
            self._post_output(label)

        elif msg_type == "tool_end":
            # Raw tool output (e.g. a grep hit containing '[/etc/hosts]') must never be
            # parsed as Rich console markup — Panel(str) would raise MarkupError on it.
            clipped = content[:600] + ("..." if len(content) > 600 else "")
            self._post_output(
                Panel(
                    safe_text(clipped),
                    title="[dim blue]⚙️ Tool Output[/dim blue]",
                    title_align="left",
                    border_style="dim blue",
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )

        elif msg_type == "subagent":
            label = Text.from_markup(
                "[bold green]🐝 Subagent Notification:[/bold green] "
            )
            label.append(content)
            self._post_output(label)

        elif msg_type == "system":
            label = Text.from_markup("[bold yellow]🔔[/bold yellow] ")
            label.append(content, style="bold yellow")
            self._post_output(label)

        elif msg_type == "error":
            self._post_output(
                Panel(
                    safe_text(content, style="bold red"),
                    title="[bold red]❌ Error[/bold red]",
                    title_align="left",
                    border_style="red",
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
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
            # Raw model text ('[/]' and friends) must never be parsed as markup.
            line = Text.from_markup("[bold cyan]🛡️ Agnostic Agent:[/bold cyan] ")
            line.append(chunk)
            self._post_output(line)

    def _tui_confirm_callback(self, prompt_msg: str) -> bool:
        """Real human-in-the-loop confirmation for hard-stop commands.

        Called by the tool registry from a worker thread (the tool call chain
        always runs via a Textual @work worker — see _run_agent_turn /
        _run_background). Blocks that worker thread until the human answers in
        the input box; the UI thread stays fully responsive and renders the
        prompt.
        """
        self._confirm_response = False
        self._confirm_event.clear()
        self._awaiting_confirm = True
        self.call_from_thread(
            self._write_output,
            Panel(
                safe_text(
                    f"{prompt_msg}\n\nType y/yes to approve or n/no to deny, then press Enter."
                ),
                title="[bold red]⚠️  GOVERNANCE HARD-STOP[/bold red]",
                title_align="left",
                border_style="red",
                box=box.ROUNDED,
                padding=(0, 1),
            ),
        )
        self._confirm_event.wait()
        self._awaiting_confirm = False
        return self._confirm_response

    def on_input_submitted(self, event: Input.Submitted) -> None:  # noqa: vulture
        """Handle Enter key in the input box."""
        user_input = event.value.strip()
        if not user_input:
            return
        event.input.value = ""

        if self._awaiting_confirm:
            approved = user_input.lower() in ("y", "yes")
            self._confirm_response = approved
            self._confirm_event.set()
            self._write_output(
                Text(
                    f"→ {'Approved' if approved else 'Denied'}",
                    style="bold green" if approved else "bold yellow",
                )
            )
            return

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

        # --- Slash commands (dispatched synchronously; expensive ones hand off
        # to a background worker before returning) ---
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
            self.agent.run_turn(expanded_input)
        except Exception as e:
            self.call_from_thread(
                self._write_output,
                Panel(
                    safe_text(f"Error: {str(e)}", style="bold red"),
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

    def _dispatch_background(self, fn) -> None:
        """Marks the agent busy and runs fn() on a background worker so the input
        box stays responsive. Use for any slash command that talks to the LLM,
        subagents, or shells out — never run those inline on the UI thread."""
        self._agent_busy = True
        self._update_status_bar()
        self._run_background(fn)

    @work(thread=True, exclusive=True, group="agent_turn")
    def _run_background(self, fn) -> None:
        """Runs fn() on a background thread. fn may return a Rich renderable to
        display, or None. Captures fn's raw stdout — workflows like AutoTestRunner
        print through their own Rich Console — so it lands in the TUI's own output
        log instead of scribbling raw ANSI over the Textual canvas.
        """
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                result = fn()
            if result is not None:
                self.call_from_thread(self._write_output, result)
        except Exception as e:
            self.call_from_thread(
                self._write_output,
                Panel(
                    safe_text(f"Error: {e}", style="bold red"),
                    title="[bold red]❌ Error[/bold red]",
                    title_align="left",
                    border_style="red",
                    box=box.ROUNDED,
                    padding=(0, 1),
                ),
            )
        finally:
            captured = buf.getvalue()
            if captured.strip():
                self.call_from_thread(self._write_output, safe_text(captured))
            self._agent_busy = False
            self.call_from_thread(self._update_status_bar)
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
        cmd, args = parse_slash_command(user_input)

        if user_input == "/clear":
            log = self.query_one("#output-log", RichLog)
            log.clear()
            self._print_banner()
            return True

        elif cmd == "theme":
            if args:
                theme_key = args.split()[0]
                msg = theme_manager.set_theme(theme_key)
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

        elif cmd == "fix":
            custom_cmd = args or None
            self._dispatch_background(
                lambda: self.test_runner.quick_fix(custom_command=custom_cmd)
            )
            return True

        elif cmd == "trust":
            mode = args or "reads"
            msg = guard.set_trust_tier(mode)
            self._write_output(Text(f"🛡️ {msg}", style="bold green"))
            return True

        elif user_input == "/untrust":
            msg = guard.set_trust_tier("strict")
            self._write_output(Text(f"🛡️ {msg}", style="bold yellow"))
            return True

        elif cmd == "session":
            parts = args.split()
            subcmd = parts[0].lower() if parts else "list"
            sess_name = parts[1] if len(parts) > 1 else "latest"

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

        elif cmd == "checkpoint":
            parts = args.split()
            subcmd = parts[0].lower() if parts else "list"
            cp_name = parts[1] if len(parts) > 1 else "latest"

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
            self._dispatch_background(self._handle_commit)
            return True

        elif cmd == "test":
            custom_cmd = args or None
            self._dispatch_background(
                lambda: self.test_runner.auto_repair_loop(custom_command=custom_cmd)
            )
            return True

        elif user_input == "/doctor":

            def _do_doctor():
                return Panel(
                    self.doctor.format_report(),
                    title="Agnostic Doctor / Endpoint Inspector",
                    border_style="cyan",
                )

            self._dispatch_background(_do_doctor)
            return True

        elif cmd == "model":
            parts = args.split()
            if parts:
                target_key = parts[0].lower()
                effort = parts[1].lower() if len(parts) > 1 else None
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

        elif cmd == "plan":
            task = args or "General Task Plan"
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

        elif cmd == "research":
            topic = args
            if not topic:
                self._write_output(
                    Text(
                        "Please provide a research query, e.g. /research database connection pooling",
                        style="yellow",
                    )
                )
                return True
            self._write_output(Text(f"Subagent researching '{topic}'...", style="cyan"))

            def _do_research():
                report = self.agent.subagents.spawn("researcher", topic)
                return Panel(
                    Markdown(report), title="Research Results", border_style="cyan"
                )

            self._dispatch_background(_do_research)
            return True

        elif cmd == "review":
            self._write_output(
                Text("Subagent reviewing workspace diffs...", style="cyan")
            )

            def _do_review():
                report = self.agent.subagents.spawn(
                    "reviewer",
                    "Inspect git status and recent diffs for bugs, missing tests, or security concerns.",
                )
                return Panel(Markdown(report), title="Code Review", border_style="cyan")

            self._dispatch_background(_do_review)
            return True

        elif cmd == "swarm":
            task = args
            if not task:
                self._write_output(
                    Text("Usage: /swarm <complex task or feature>", style="yellow")
                )
                return True

            def _do_swarm():
                from agent.workflows.swarm import SwarmCoordinator

                swarm = SwarmCoordinator(self.agent.subagents, self.agent.llm_client)
                synthesis = swarm.dispatch_swarm(task)
                return Panel(
                    Markdown(synthesis),
                    title="🐝 Swarm Unified Strategy",
                    border_style="green",
                )

            self._dispatch_background(_do_swarm)
            return True

        elif user_input.startswith(("/diagram", "/map")):

            def _do_diagram():
                from agent.workflows.diagram import ArchitectureDiagrammer

                diag = ArchitectureDiagrammer(self.agent.workspace_root)
                return Panel(
                    safe_text(diag.generate_mermaid_map()),
                    title="📊 Mermaid Architecture Diagram",
                    border_style="cyan",
                )

            self._dispatch_background(_do_diagram)
            return True

        elif cmd == "pr":

            def _do_pr():
                from agent.workflows.pr_pilot import PRAutoPilot

                pilot = PRAutoPilot(self.agent.workspace_root, self.agent.llm_client)
                pilot.generate_pr_summary()
                return None

            self._dispatch_background(_do_pr)
            return True

        elif user_input.startswith("/harvest"):

            def _do_harvest():
                from agent.governance.harvester import harvester

                count = harvester.scan_and_harvest()
                return Text(
                    f"🌾 Harvested {count} cross-agent corrections into candidate ladder.",
                    style="bold green",
                )

            self._dispatch_background(_do_harvest)
            return True

        elif cmd == "learn":
            lesson = args
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
                    safe_text(state_manager.read_state()),
                    title="🎯 Persistent State Whiteboard (.agnostic/state.md)",
                    border_style="green",
                )
            )
            return True

        elif user_input == "/distill":
            self._write_output(
                Text("Triggering Harness Distillation Engine...", style="cyan")
            )

            def _do_distill():
                res = subprocess.run(
                    "node engine/distill/distill.cjs",
                    cwd=str(self.agent.workspace_root),
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                return Panel(
                    safe_text(res.stdout or res.stderr or "Distillation complete."),
                    title="Distillation Results",
                    border_style="cyan",
                )

            self._dispatch_background(_do_distill)
            return True

        elif user_input == "/web":
            ok, web_url = maybe_start_web_companion(self.agent)
            msg = (
                f"🌐 Live Visual Companion active at: {web_url}"
                if ok
                else f"Companion server failed to start: {web_url}"
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

    def _handle_commit(self) -> Optional[Panel]:
        """Autonomous Git Commit generator workflow. Runs on a background worker
        (see _dispatch_background) — writes go through _post_output()."""
        self._post_output(
            Text("Inspecting staged changes and git status...", style="cyan")
        )
        try:
            st = subprocess.run(
                "git status --short", shell=True, capture_output=True, text=True
            ).stdout.strip()
            if not st:
                self._post_output(
                    Text("No changes detected in git working tree.", style="dim")
                )
                return None

            diff = subprocess.run(
                "git diff --cached", shell=True, capture_output=True, text=True
            ).stdout.strip()
            if not diff:
                diff = subprocess.run(
                    "git diff", shell=True, capture_output=True, text=True
                ).stdout.strip()

            self._post_output(
                Panel(safe_text(st), title="Git Status", border_style="yellow")
            )

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

            self._post_output(
                Panel(
                    safe_text(f"Suggested Commit Message:\n{msg}"),
                    border_style="green",
                )
            )
            self._post_output(
                Text(
                    'To commit, type: git add -A && git commit -m "<message>" in your terminal.',
                    style="dim yellow",
                )
            )
        except Exception as e:
            self._post_output(Text(f"Git commit workflow error: {str(e)}", style="red"))
        return None

    def action_quit_safe(self) -> None:  # noqa: vulture
        """Ctrl+C handler."""
        if self._agent_busy:
            # A worker thread cannot be forcibly interrupted mid-run — do NOT clear
            # _agent_busy here, or a second overlapping turn could start on the same
            # agent.history while the first is still writing to it.
            # ponytail: no cooperative-cancel hook in AgentLoop yet; add one if a hard
            # abort becomes necessary.
            self._write_output(
                Text(
                    "Agent turn is still running in the background and can't be "
                    "force-stopped yet. Press Ctrl+C again once it finishes to exit.",
                    style="yellow",
                )
            )
        else:
            self.exit()

    def action_clear_output(self) -> None:  # noqa: vulture
        """Ctrl+L handler."""
        log = self.query_one("#output-log", RichLog)
        log.clear()
        self._print_banner()

    def action_complete_slash(self) -> None:  # noqa: vulture
        """Tab handler: completes a partially typed slash command against the
        shared SLASH_COMMANDS table (cli.py's prompt_toolkit completer uses the
        same table — restores the tab-completion the TUI had lost)."""
        try:
            inp = self.query_one("#prompt-input", Input)
        except NoMatches:
            return
        val = inp.value
        if not val.startswith("/") or " " in val:
            return
        matches = [c for c in SLASH_COMMANDS if c.startswith(val)]
        if len(matches) == 1:
            inp.value = matches[0] + " "
            inp.cursor_position = len(inp.value)  # noqa: vulture
        elif matches:
            self._write_output(Text("  ".join(matches), style="dim"))


# ─── Entry Point ─────────────────────────────────────────────────────────────────


def main():
    parser = build_arg_parser()
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use the legacy prompt_toolkit CLI instead of the TUI",
    )
    args = parser.parse_args()

    # If --legacy, delegate to the old CLI
    if args.legacy:
        from agent.cli import main as legacy_main

        # cli.main() re-parses sys.argv, which still carries --legacy (its parser
        # has no such flag) — hand it the argv it can actually parse.
        legacy_main([a for a in sys.argv[1:] if a != "--legacy"])
        return

    # Auto-discover active model
    doctor, detected_model, detection = detect_model(args.url, args.api_key, args.model)

    config = LLMConfig(
        base_url=args.url,
        api_key=args.api_key,
        model=detected_model,
    )

    use_compact = not args.full_prompt
    require_confirmation = args.ask_permissions

    def _noop_output(msg_type: str, content: str) -> None:
        pass  # TUI overrides this

    agent = AgentLoop(
        workspace_root=os.getcwd(),
        llm_config=config,
        # No confirm_callback here on purpose: AgentLoop falls back to a real
        # (blocking) confirm, never an auto-approve, and AgnosticTUI wires its own
        # human-in-the-loop confirm the moment it's constructed below.
        output_callback=_noop_output,
    )
    if use_compact:
        agent._load_harness_system_prompt(compact=True)

    # Pre-index workspace
    index_workspace()

    from agent.web.server import companion_telemetry

    companion_telemetry.bind_agent(agent)

    if args.web:
        maybe_start_web_companion(agent)

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
