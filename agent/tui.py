"""
agent/tui.py — Textual-based Interactive Terminal UI for Agnostic AI Agent
Claude Code-style TUI with a fixed bordered input area pinned to the bottom,
scrollable conversation output above, and a status bar. The input is always
available — you can type the next prompt while the LLM is responding.
"""

import sys
import os
import contextlib
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
from rich.table import Table
from rich import box

from agent import __version__
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
    LineForwarder,
    PromptHistoryRing,
    build_arg_parser,
    complete_token,
    endpoint_status_line,
    expand_prompt_references,
    format_user_display,
    help_text,
    index_workspace,
    maybe_start_web_companion,
    model_preset_rows,
    parse_confirm_answer,
    parse_slash_command,
    safe_text,
    stream_tail,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):  # stream already detached/redirected; keep its default encoding
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):  # stream already detached/redirected; keep its default encoding
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

#stream-view {
    height: auto;
    max-height: 14;
    dock: bottom;
    padding: 0 1;
    background: $surface;
    overflow: hidden;
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

#prompt-input.confirm {
    border: round red;
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

    CSS = TUI_CSS

    BINDINGS = [
        Binding("ctrl+c", "quit_safe", "Exit", show=True),
        Binding("escape", "cancel_turn", "Cancel", show=True),
        Binding("ctrl+l", "clear_output", "Clear", show=True),
        # priority: without it the Screen's default focus_next binding swallows Tab
        # (it moved focus to the output log instead of ever completing anything).
        Binding("tab", "complete_slash", "Complete", show=False, priority=True),
        Binding("up", "history_prev", "History", show=False),
        Binding("down", "history_next", "History", show=False),
    ]

    def __init__(
        self,
        agent: AgentLoop,
        code_indexer_inst: CodebaseIndexer,
        detected_model: str,
        doctor: ModelDoctor,
        test_runner: AutoTestRunner,
        require_confirmation: bool = False,
        detection: Optional[dict] = None,
    ):
        super().__init__()
        self.agent = agent
        self.code_indexer = code_indexer_inst
        self.detected_model = detected_model
        self.detection = detection or {}
        self.doctor = doctor
        self.test_runner = test_runner
        self.require_confirmation = require_confirmation

        # Prompt history shared with the legacy CLI (~/.agnostic/agent_history.txt)
        self._history = PromptHistoryRing()

        # Queue for prompts typed while agent is busy
        self._prompt_queue: deque[str] = deque()
        self._agent_busy = False
        self._stream_buffer: List[str] = []
        self._lock = threading.Lock()
        # Tab-completion cycle state: (input value we set, head, sigil, matches, index)
        self._completion: Optional[tuple] = None
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

    def compose(self) -> ComposeResult:
        yield Static(id="status-bar")
        yield RichLog(id="output-log", highlight=True, markup=True, wrap=True, max_lines=5000)
        with Horizontal(id="input-container"):
            yield Static("❯ ", id="prompt-label")
            yield Input(placeholder="Type a message... (Enter to send)", id="prompt-input")
            yield Static("", id="queue-indicator")
        # The live reply grows in this one block; the finished reply is written to
        # the log as a single panel and the block is emptied again.
        yield Static("", id="stream-view")

    def on_mount(self) -> None:
        """Initialize on app mount."""
        # Textual runs the whole process inside redirect_stdout(_PrintCapture); that
        # capture only forwards to targets registered here, so without this every
        # Console().print() from a tool (diff cards, the test
        # runner) is silently dropped.
        self.begin_capture_print(self)
        self._print_banner()
        self._set_stream_view("")
        self._update_status_bar()
        self.query_one("#prompt-input", Input).focus()
        if not self.detection:
            self._detect_model_bg()
        # Periodic status bar update (render only — git shells out on a worker)
        self.set_interval(3.0, self._update_status_bar)
        self._refresh_git_status()
        self.set_interval(3.0, self._refresh_git_status)
        self._index_workspace_bg()

    @work(thread=True, group="detector")
    def _detect_model_bg(self) -> None:
        """Probes the endpoint off the UI thread. ModelDoctor.inspect() is a plain
        httpx GET with a 4s timeout — running it before App.run() (as main() used
        to) meant a slow or dead endpoint blocked the first frame for 4 seconds."""
        detection = self.doctor.inspect()
        detected = detection.get("active_model")
        # A /model switch typed during the probe wins over whatever the endpoint says.
        if detected and self.agent.llm_client.config.model == self.detected_model:
            self.agent.llm_client.config.model = detected
        self.detection = detection
        self.detected_model = detected or self.detected_model
        self.call_from_thread(self._show_endpoint_status)
        self.call_from_thread(self._update_status_bar)

    @work(thread=True, group="indexer")
    def _index_workspace_bg(self) -> None:
        """Warms the symbol index off the UI thread. The indexer self-indexes on the
        first miss anyway, so this only saves the first @file/#symbol lookup a wait —
        it must never delay the first frame."""
        index_workspace()

    def on_print(self, event: events.Print) -> None:
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
            f"🛡️  AGNOSTIC AI CODING AGENT v{__version__}\n",
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
        self._show_endpoint_status()
        log.write("")

    def _show_endpoint_status(self) -> None:
        """The endpoint line under the banner: 'probing' until _detect_model_bg
        answers, then the honest online/offline line."""
        if not self.detection:
            self._write_output(Text(f"… probing {self.doctor.base_url}", style="dim"))
            return
        text, style = endpoint_status_line(self.detection, self.detected_model)
        self._write_output(Text(text, style=style))

    def _update_status_bar(self) -> None:
        """Update the bottom status bar with context, model, and git info."""
        try:
            cwd = os.getcwd()
            home = str(Path.home())
            display_cwd = "~" + cwd[len(home) :] if cwd.startswith(home) else cwd

            git_str = self._git_status

            curr_model = self.agent.llm_client.config.model
            curr_effort = (self.agent.llm_client.config.reasoning_effort or "med").upper()
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
        except (NoMatches, KeyError, AttributeError):  # widget torn down, or agent not wired yet
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
                    len(st_res.stdout.strip().splitlines()) if st_res.stdout.strip() else 0
                )
                git_str = f" | 🌿 {branch}{'*' if dirty_count else ''}"
        except (OSError, subprocess.SubprocessError):  # no git / not a repo; status line omits it
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

    def _post(self, fn, *args) -> None:
        """Runs a UI-thread callable from the UI thread or from any worker thread."""
        if threading.get_ident() == self._thread_id:
            fn(*args)
        else:
            self.call_from_thread(fn, *args)

    def _post_output(self, *args) -> None:
        """Thread-safe write to the output log — safe to call from the UI thread
        or from any worker thread."""
        self._post(self._write_output, *args)

    def _output_callback(self, msg_type: str, content: str) -> None:
        """Callback from AgentLoop — runs on worker thread, posts to UI thread."""
        try:
            from agent.web.server import companion_telemetry

            # Per-chunk events are excluded: the companion log holds 150 entries, so
            # one noisy build would evict the whole session's tool calls and diffs.
            if msg_type not in ("assistant_chunk", "tool_chunk"):
                companion_telemetry.log_event(msg_type, content)
        except ImportError:  # web companion is optional; the TUI is the real UI
            pass

        if msg_type == "assistant_chunk":
            with self._lock:
                self._stream_buffer.append(content)
                buf_len = len(self._stream_buffer)
            # Repaint the live block every few tokens (per token is pure overhead).
            if buf_len % 8 == 0:
                self._flush_stream()

        elif msg_type == "assistant":
            self._end_stream(content)

        elif msg_type == "tool_start":
            label = Text.from_markup("[dim magenta]⚙️  Executing Tool:[/dim magenta] ")
            label.append(content, style="yellow")
            self._post_output(label)

        elif msg_type == "tool_chunk":
            # Live run_command output grows in the same one block the reply uses.
            with self._lock:
                self._stream_buffer.append(content + "\n")
            self._flush_stream()

        elif msg_type == "tool_end":
            # The live block held this tool's streamed lines; the result card replaces it.
            with self._lock:
                self._stream_buffer = []
            self._post(self._set_stream_view, "")
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
            label = Text.from_markup("[bold green]🐝 Subagent Notification:[/bold green] ")
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

    def _set_stream_view(self, text: str) -> None:
        """Repaints the live streaming block (UI thread only). Empty text hides it."""
        try:
            view = self.query_one("#stream-view", Static)
        except NoMatches:
            return
        view.display = bool(text)
        # Raw model text ('[/]' and friends) must never be parsed as markup.
        view.update(safe_text(text, style="cyan"))

    def _flush_stream(self) -> None:
        """Repaints the ONE growing block with everything streamed so far — the
        reply used to be posted to the log as a fresh labelled fragment every 8
        tokens, so a single answer arrived as a dozen '🛡️ Agnostic Agent:' lines."""
        with self._lock:
            text = stream_tail(self._stream_buffer)
        self._post(self._set_stream_view, text)

    def _end_stream(self, final: str) -> None:
        """Closes the live block: the finished reply replaces it as ONE panel in
        the log. Called with "" from the turn's `finally` so a cancelled turn's
        partial text still lands in the log instead of vanishing."""
        with self._lock:
            text = final or "".join(self._stream_buffer)
            self._stream_buffer = []
        self._post(self._set_stream_view, "")
        if text.strip():
            self._post_output(
                Panel(
                    Markdown(text),
                    title="[bold cyan]🛡️ Agnostic Agent[/bold cyan]",
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )

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
        self.call_from_thread(self._set_confirm_mode, True)
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
        self.call_from_thread(self._set_confirm_mode, False)
        return self._confirm_response

    def _set_confirm_mode(self, on: bool) -> None:
        """Makes a pending hard-stop confirmation visible at the input box itself —
        an unchanged '❯' prompt gave no hint that the next Enter answers y/n."""
        try:
            self.query_one("#prompt-label", Static).update("approve? [y/n] " if on else "❯ ")
            self.query_one("#prompt-input", Input).set_class(on, "confirm")
        except NoMatches:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the input box."""
        user_input = event.value.strip()
        if not user_input:
            return
        event.input.value = ""

        if self._awaiting_confirm:
            approved, unrecognized = parse_confirm_answer(user_input)
            self._confirm_response = approved
            self._confirm_event.set()
            if unrecognized:
                # Deny (safe default) but hand the typed text back — it was a prompt,
                # not an answer, and swallowing it silently loses the user's work.
                event.input.value = user_input
            self._write_output(
                Text(
                    "→ Denied (not a y/n answer — your text was put back in the input box)"
                    if unrecognized
                    else "→ {}".format("Approved" if approved else "Denied"),
                    style="bold green" if approved else "bold yellow",
                )
            )
            return

        self._history.append(user_input)

        if self._agent_busy:
            # Queue the prompt for later
            self._prompt_queue.append(user_input)
            self._write_output(
                Text.from_markup(f"[dim yellow]📬 Queued (agent busy): {user_input}[/dim yellow]")
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
        self._agent_busy = True
        self._update_status_bar()
        self._run_agent_turn(user_input)

    @work(thread=True, exclusive=True, group="agent_turn")
    def _run_agent_turn(self, raw_input: str) -> None:
        """Execute agent turn in a background thread so input stays responsive.
        @file/#symbol expansion happens here, not on the UI thread: a #symbol miss
        triggers a full workspace index and froze the app for over a second."""
        start_time = time.time()
        try:
            self.agent.run_turn(expand_prompt_references(raw_input, self.code_indexer))
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
            # A cancelled turn never sends a final 'assistant' message — close the
            # live streaming block here so its text is not left dangling.
            self._end_stream("")
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
        log instead of scribbling raw ANSI over the Textual canvas, line by line as
        it is printed rather than in one dump when fn() finally returns.
        """
        sink = LineForwarder(
            lambda line: self.call_from_thread(self._write_output, safe_text(line))
        )
        try:
            with contextlib.redirect_stdout(sink):
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
            sink.flush_remainder()
            self._agent_busy = False
            self.call_from_thread(self._update_status_bar)
            self.call_from_thread(self._process_queue)

    def _process_queue(self) -> None:
        """Process the next queued prompt if any."""
        if self._prompt_queue and not self._agent_busy:
            next_prompt = self._prompt_queue.popleft()
            self._update_queue_indicator()
            self._write_output(
                Text.from_markup(f"[dim cyan]📬 Processing queued prompt: {next_prompt}[/dim cyan]")
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

        elif user_input == "/multiline":
            # Textual's Input is single-line and collapses a pasted newline, so there
            # is nothing to toggle here — be honest instead of silently doing nothing.
            self._write_output(
                Text(
                    "The TUI prompt is a single-line input and cannot accept multi-line "
                    "text. Run `agnostic-legacy` and use /multiline there.",
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
            self._dispatch_background(lambda: self.test_runner.quick_fix(custom_command=custom_cmd))
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
                    self._write_output(Text("Available Checkpoints:", style="bold cyan"))
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
                if target_key.isdigit():
                    keys = list(LLMConfig.PRESETS)
                    idx = int(target_key) - 1
                    if not 0 <= idx < len(keys):
                        self._write_output(
                            Text(f"No preset #{target_key}. Type /model to list.", style="yellow")
                        )
                        return True
                    target_key = keys[idx]
                effort = parts[1].lower() if len(parts) > 1 else None
                msg = self.agent.llm_client.switch_model(
                    preset_key=target_key, reasoning_effort=effort
                )
                self._write_output(Text(f"🧠 {msg}", style="bold green"))
            else:
                table = Table(title="Model presets", box=box.ROUNDED, border_style="cyan")
                for col in ("#", "", "key", "name", "ctx", "effort", "availability"):
                    table.add_column(col, overflow="fold")
                for row in model_preset_rows(
                    LLMConfig.PRESETS,
                    self.agent.llm_client.config.model,
                    local_online=self.detection.get("status") == "online",
                ):
                    table.add_row(*row)
                self._write_output(table)
                self._write_output(
                    Text(
                        "Pick with /model <key|number> [low|medium|high] — e.g. /model 3 high",
                        style="dim yellow",
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
                return Panel(Markdown(report), title="Research Results", border_style="cyan")

            self._dispatch_background(_do_research)
            return True

        elif cmd == "review":
            self._write_output(Text("Subagent reviewing workspace diffs...", style="cyan"))

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
                self._write_output(Text("Usage: /swarm <complex task or feature>", style="yellow"))
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
            self._write_output(Text("Running Cross-Agent Harvester...", style="cyan"))

            def _do_harvest():
                res = subprocess.run(
                    "node engine/harvest/harvest.cjs",
                    cwd=str(self.agent.workspace_root),
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                return Panel(
                    safe_text(res.stdout or res.stderr or "Harvest complete."),
                    title="Harvest Results",
                    border_style="cyan",
                )

            self._dispatch_background(_do_harvest)
            return True

        elif cmd == "learn":
            lesson = args
            if not lesson:
                self._write_output(Text("Usage: /learn <lesson or constraint>", style="yellow"))
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
            self._write_output(Text("Triggering Harness Distillation Engine...", style="cyan"))

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
            self._write_output(Text("Available commands:", style="bold"))
            self._write_output(safe_text(help_text(), style="cyan"))
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
        self._post_output(Text("Inspecting staged changes and git status...", style="cyan"))
        try:
            st = subprocess.run(
                "git status --short", shell=True, capture_output=True, text=True
            ).stdout.strip()
            if not st:
                self._post_output(Text("No changes detected in git working tree.", style="dim"))
                return None

            diff = subprocess.run(
                "git diff --cached", shell=True, capture_output=True, text=True
            ).stdout.strip()
            if not diff:
                diff = subprocess.run(
                    "git diff", shell=True, capture_output=True, text=True
                ).stdout.strip()

            self._post_output(Panel(safe_text(st), title="Git Status", border_style="yellow"))

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

    def action_quit_safe(self) -> None:
        """Ctrl+C handler."""
        if self._agent_busy:
            # A worker thread cannot be forcibly interrupted mid-run — do NOT clear
            # _agent_busy here, or a second overlapping turn could start on the same
            # agent.history while the first is still writing to it.
            self._write_output(
                Text(
                    "Agent turn is still running in the background. Press Esc to cancel "
                    "it, then Ctrl+C again once it finishes to exit.",
                    style="yellow",
                )
            )
        else:
            self.exit()

    def action_cancel_turn(self) -> None:
        """Esc handler: cooperative cancel. The worker clears _agent_busy itself."""
        if not self._agent_busy:
            return
        self.agent.cancel_event.set()
        self._write_output(Text("⏹ cancelling after the current step…", style="yellow"))

    def action_clear_output(self) -> None:
        """Ctrl+L handler."""
        log = self.query_one("#output-log", RichLog)
        log.clear()
        self._print_banner()

    def action_history_prev(self) -> None:
        """Up: walk back through the prompt history."""
        self._walk_history(self._history.prev)

    def action_history_next(self) -> None:
        """Down: walk forward again, ending at the live (empty) line."""
        self._walk_history(self._history.next)

    def _walk_history(self, step) -> None:
        """Only walks from the start of the line, or while already walking, so
        editing a line you typed yourself still works."""
        try:
            inp = self.query_one("#prompt-input", Input)
        except NoMatches:
            return
        walking = self._history.index < len(self._history.entries)
        if inp.value and inp.cursor_position != 0 and not walking:
            return
        entry = step()
        if entry is not None:
            inp.value = entry
            inp.cursor_position = len(entry)

    def action_complete_slash(self) -> None:
        """Tab handler: completes a partially typed slash command against the
        shared SLASH_COMMANDS table (cli.py's prompt_toolkit completer uses the
        same table — restores the tab-completion the TUI had lost), or an
        @file/#symbol token against the workspace index."""
        try:
            inp = self.query_one("#prompt-input", Input)
        except NoMatches:
            return
        val = inp.value
        if val.startswith("/") and " " not in val:
            matches = [c for c in SLASH_COMMANDS if c.startswith(val)]
            if len(matches) == 1:
                inp.value = matches[0] + " "
                inp.cursor_position = len(inp.value)
            elif matches:
                self._write_output(Text("  ".join(matches), style="dim"))
            return
        self._complete_reference(inp)

    def _complete_reference(self, inp) -> None:
        """Tab on an @file / #symbol token: fills in the best candidate from the
        index and cycles through the rest on repeated Tab (the README promised
        this completion in the TUI; only the legacy CLI ever had it)."""
        state = self._completion
        if state and state[0] == inp.value:
            _, head, sigil, matches, index = state
            index = (index + 1) % len(matches)
        else:
            head, _, token = inp.value.rpartition(" ")
            sigil = token[:1]
            if sigil not in ("@", "#"):
                return
            source = (
                self.code_indexer.get_all_symbols()
                if sigil == "#"
                else self.code_indexer.get_indexed_files()
            )
            matches = complete_token(token[1:], source)
            if not matches:
                return
            head, index = (head + " " if head else ""), 0
            if len(matches) > 1:
                self._write_output(safe_text("  ".join(sigil + m for m in matches), style="dim"))
        inp.value = head + sigil + matches[index]
        inp.cursor_position = len(inp.value)
        self._completion = (inp.value, head, sigil, matches, index)


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

    # The endpoint probe is a 4s-timeout HTTP GET: the TUI runs it on a worker
    # (AgnosticTUI._detect_model_bg) so a dead endpoint cannot delay the first frame.
    doctor = ModelDoctor(base_url=args.url, api_key=args.api_key)
    detected_model = args.model

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

    from agent.web.server import companion_telemetry

    companion_telemetry.bind_agent(agent)

    if args.web:
        maybe_start_web_companion(agent)

    # Single prompt mode: run without TUI. No frame to keep responsive here, so
    # probe synchronously — `-p` must talk to the model the endpoint actually serves.
    if args.prompt:
        agent.llm_client.config.model = doctor.inspect().get("active_model") or detected_model
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
