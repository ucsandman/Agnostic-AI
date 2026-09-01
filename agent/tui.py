"""
agent/tui.py — Textual-based Interactive Terminal UI for Agnostic AI Agent
Claude Code-style TUI with a fixed bordered input area pinned to the bottom,
scrollable conversation output above, and a status bar. The input is always
available — you can type the next prompt while the LLM is responding.
"""

import sys
import os
import contextlib
import random
import time
import subprocess
import threading
from pathlib import Path
from typing import List, Optional
from collections import deque

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, RichLog
from textual.binding import Binding
from textual import events, work
from textual.css.query import NoMatches

from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from rich import box

from agent import __version__
from agent.loop import AgentLoop
from agent.llm.client import LLMConfig
from agent.llm.detector import ModelDoctor
from agent.governance.context import context_manager
from agent.governance.guard import guard
from agent.governance.state import state_manager
from agent.governance.undo import undo_manager
from agent.tools.indexer import code_indexer, CodebaseIndexer
from agent.workflows.tester import AutoTestRunner
from agent.tui_commands import SlashCommandMixin
from agent.tui_composer import PROMPT_PLACEHOLDER, PromptArea
from agent.tui_rewind import RewindScreen
from agent.ui_common import (
    SLASH_COMMANDS,
    LineForwarder,
    PromptHistoryRing,
    build_arg_parser,
    busy_indicator,
    busy_verbs,
    complete_token,
    context_segment,
    endpoint_status_line,
    expand_prompt_references,
    fold_summary,
    format_user_display,
    index_workspace,
    maybe_start_web_companion,
    parse_confirm_answer,
    pick_default_preset,
    slash_hints,
    safe_text,
    should_notify,
    stream_tail,
    turn_summary,
    usage_segment,
)
from agent.llm.usage import UsageLog

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
    /* 8 text lines + the composer's 2 border rows + border-top + 5 hint rows. */
    max-height: 16;
    dock: bottom;
    border-top: heavy $accent;
    padding: 0 1;
    background: $surface-darken-1;
}

#input-row {
    height: auto;
    max-height: 10;
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
    /* content-box so every height here counts LINES OF TEXT: under the default
       border-box the round border ate two of them and an 8-line paste showed 6. */
    box-sizing: content-box;
    height: auto;
    min-height: 1;
    max-height: 8;
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

/* height: auto, not 1 — the assembled bar needs ~142 cells (more with a git branch
   or a queue), so at a normal 100-column terminal a fixed single line silently cut
   off everything from the trust badge rightwards: the context gauge, the queue
   count and the busy/esc-to-cancel indicator all vanished with no ellipsis. It
   wraps to a second line instead; nothing that says what the agent is doing is
   ever the thing that gets dropped. */
#status-bar {
    height: auto;
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

#hint-bar {
    height: auto;
    max-height: 5;
    padding: 0 2;
    background: $surface-darken-1;
}
"""

# The four tiers SafetyGuard.set_trust_tier normalises to, in escalation order.
TRUST_TIERS = ("strict", "trust-reads", "trust-tests", "trust-all")


class AgnosticTUI(SlashCommandMixin, App):
    """Agnostic AI Coding Agent — Textual TUI with always-available input."""

    CSS = TUI_CSS

    BINDINGS = [
        # priority: TextArea binds ctrl+c to copy, so with a selection in the
        # composer the plain App binding never fired and Ctrl+C silently copied
        # instead of cancelling/exiting.
        Binding("ctrl+c", "quit_safe", "Cancel/Exit", show=True, priority=True),
        Binding("escape", "cancel_turn", "Cancel", show=True),
        Binding("ctrl+l", "clear_output", "Clear ×2", show=True),
        # priority: without it the Screen's default focus_next binding swallows Tab
        # (it moved focus to the output log instead of ever completing anything).
        Binding("tab", "complete_slash", "Complete", show=False, priority=True),
        # priority: without it the Screen's default focus_previous binding swallows
        # Shift+Tab while #prompt-input has focus, so the App binding never fires.
        Binding("shift+tab", "cycle_trust", "Trust", show=True, priority=True),
        Binding("ctrl+o", "expand_output", "Full output", show=True),
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
        startup_model_msg: Optional[str] = None,
    ):
        super().__init__()
        self.agent = agent
        # Set when startup auto-picked a non-local preset; replaces the local
        # endpoint probe line under the banner.
        self.startup_model_msg = startup_model_msg
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
        # Set by _mark_busy(), read by the 1s tick that redraws the busy fragment.
        self._busy_started: float = 0.0
        self._busy_verb: str = ""
        # Last press time per destructive key name, for _double_tap().
        self._taps: dict[str, float] = {}
        # One mark per turn — (checkpoint name, clock, history snapshot) — for the
        # double-Esc rewind. Bounded: the checkpoint is cheap, the history is not.
        self._turn_marks: deque[tuple[str, str, list]] = deque(maxlen=20)
        # Never len(_turn_marks): the deque evicts, and two marks named 'turn-21'
        # would both point at the last checkpoint written under that name.
        self._turn_no = 0
        # The last 10 unfolded tool outputs — (tool name, seconds, full text) — so
        # Ctrl+O can hand back what the card folded away. Bounded: a build log is big.
        self._tool_outputs: deque[tuple[str, float, str]] = deque(maxlen=10)
        self._tool_name = ""
        self._tool_t0 = 0.0
        # Turn-done notification. SAFE-OFF by default: _focused starts True, so a
        # terminal that never reports focus (older conhost, tmux without
        # focus-events) never rings at all — the alternative is a bell that fires
        # while the user is watching and cannot be explained.
        self._focused = True
        self._saw_focus_event = False
        self._notify_enabled = bool(state_manager.get_setting("notify", True))
        # The context-limit nudge fires once per fill cycle; re-armed whenever a
        # compaction (manual or automatic) frees the window again.
        self._ctx_warned = False
        # The history as it was just before the last MANUAL /compact, for /compact
        # undo. Auto-compaction runs on a worker thread and never sets this.
        self._pre_compact_history: Optional[list] = None
        self._stream_buffer: List[str] = []
        self._lock = threading.Lock()
        # Tab-completion cycle state: (input value we set, head, sigil, matches, index)
        self._completion: Optional[tuple] = None
        # Rendered by the UI thread, refreshed by a background worker (see
        # _refresh_git_status) — `git rev-parse` + `git status` on the UI thread
        # stalled the app on every 3s tick.
        self._git_status = ""
        # Same deal for spend/latency: rendered by the UI thread, recomputed every
        # 10s by _refresh_usage_bg (summarize() reads the whole journal).
        self._usage_fragment: str = ""
        # The raw summary behind that fragment, handed to the /model picker so it
        # never reads the journal on the UI thread. Empty until the first refresh.
        self._usage_summary: dict = {}

        # Human-in-the-loop confirmation for hard-stop commands. Blocks the calling
        # worker thread via this event until the human answers in the input box.
        self._confirm_event = threading.Event()
        self._confirm_response = False
        self._awaiting_confirm = False
        # A reason typed alongside the verdict ('n: too risky') — prepended to the
        # next prompt exactly once, so a denial becomes an instruction.
        self._confirm_reason: str = ""
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
        # A Vertical, not the old bare Horizontal: same-edge docked siblings
        # OVERLAP in Textual, so the hint bar must live inside the one docked
        # container to get flow layout under the composer row.
        with Vertical(id="input-container"):
            with Horizontal(id="input-row"):
                yield Static("❯ ", id="prompt-label")
                yield PromptArea(
                    id="prompt-input",
                    placeholder=PROMPT_PLACEHOLDER,
                    soft_wrap=True,
                    show_line_numbers=False,
                    compact=True,
                    # 'indent' would swallow Tab AND remap Escape to focus_next, killing
                    # both the Tab completion binding and the Esc-Esc rewind.
                    tab_behavior="focus",
                )
                yield Static("", id="queue-indicator")
            # The live slash-command menu, directly under the composer;
            # display:none whenever there is nothing to hint.
            yield Static("", id="hint-bar")
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
        self.query_one("#prompt-input", PromptArea).focus()
        # Probing localhost:1234 is only meaningful when the session is actually
        # on the local provider — a subscription default has no endpoint to probe.
        if not self.detection and self.agent.llm_client.config.provider == "local":
            self._detect_model_bg()
        # Periodic status bar update (render only — git shells out on a worker)
        self.set_interval(3.0, self._update_status_bar)
        # The busy clock ticks every second — render only, no subprocess (git keeps
        # its own 3s worker interval below).
        self.set_interval(1.0, self._tick_busy)
        self._refresh_git_status()
        self.set_interval(3.0, self._refresh_git_status)
        self._refresh_usage_bg()
        self.set_interval(10.0, self._refresh_usage_bg)
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
        self._post(self._show_endpoint_status)
        self._post(self._update_status_bar)

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
            "Commands: /plan, /fix, /swarm, /test, /compact, /session, /trust, /audit, "
            "/undo, /commit, /exit · !cmd runs a shell command locally",
            style="yellow",
        )
        log.write(Panel(banner_text, border_style="cyan", box=box.ROUNDED))
        self._show_endpoint_status()
        log.write("")

    def _show_endpoint_status(self) -> None:
        """The endpoint line under the banner: the auto-picked preset when startup
        chose one, else 'probing' until _detect_model_bg answers, then the honest
        online/offline line."""
        if self.startup_model_msg:
            self._write_output(Text(f"🧠 {self.startup_model_msg}", style="bold green"))
            return
        if not self.detection:
            self._write_output(Text(f"… probing {self.doctor.base_url}", style="dim"))
            return
        text, style = endpoint_status_line(self.detection, self.detected_model)
        self._write_output(Text(text, style=style))

    def on_app_blur(self, event: events.AppBlur) -> None:
        """The terminal lost focus. Textual's Windows and Linux drivers both enable
        DECSET 1004 focus reporting, so this arrives on any terminal that speaks it —
        and its arrival is the only proof we have that this terminal reports focus
        at all, which is what /notify tells the user."""
        self._focused = False
        self._saw_focus_event = True

    def on_app_focus(self, event: events.AppFocus) -> None:
        """The terminal got focus back — the user is looking, so nothing rings."""
        self._focused = True
        self._saw_focus_event = True

    def _notify_turn_done(self, duration_s: float, ok: bool = True) -> None:
        """Bell + toast when a long turn ends while the terminal is unfocused.

        Called once from each worker's `finally`, so /test and /fix announce
        themselves too. notify() is thread-safe; bell() writes straight to the
        driver, so it goes through _post().
        """
        if not should_notify(self._notify_enabled, self._focused, duration_s):
            return
        # _run_background can run a command that never marked a turn (a queue drain
        # racing an empty deque) — no mark simply means nothing to count.
        files = len(undo_manager.changed_since(self._turn_marks[-1][0])) if self._turn_marks else 0
        self._post(self.bell)
        self.notify(
            turn_summary(files, duration_s),
            title="Turn complete",
            severity="information" if ok else "warning",
            timeout=10,
        )

    def _mark_busy(self) -> None:
        """The ONE place _agent_busy flips True. Every busy-entry point routes here
        so the elapsed clock and the per-turn verb can never go out of sync with the
        flag (and so later features have a single hook for 'a turn just started')."""
        self._turn_no += 1
        name = f"turn-{self._turn_no}"
        # The file half of a rewind (a list copy of FileSnapshot refs) and the
        # conversation half, taken at the same instant so they can be restored
        # together — or separately — from one gesture.
        undo_manager.create_checkpoint(name)
        self._turn_marks.append(
            (name, time.strftime("%H:%M:%S"), list(getattr(self.agent, "history", [])))
        )
        self._agent_busy = True
        self._busy_started = time.monotonic()
        self._busy_verb = random.choice(busy_verbs())
        self._update_status_bar()

    def _tick_busy(self) -> None:
        """1s repaint while busy. Idle ticks do nothing — the status bar keeps its
        own 3s interval for everything else."""
        if self._agent_busy:
            self._update_status_bar()

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
            if self.agent.llm_client.config.sub_model:
                disp_model += f" › {self.agent.llm_client.config.sub_model}"

            st = context_manager.get_status(self.agent.history)

            # A Text builder, not an f-string: Static.update(str) parses its argument
            # as Rich markup, so a cwd or model name containing '[' blew up the bar.
            line = Text(" ", style="dim")
            line.append(f"📁 {display_cwd}{git_str}")
            line.append(f"  │  🤖 {disp_model} ({curr_effort})")
            # Read LIVE from the guard every repaint, never cached on the app: the
            # badge must be the tier check_command_safety actually enforces, even
            # when /trust or a subagent changed it behind the UI's back.
            tier = guard.get_trust_tier()
            line.append("  │  ")
            line.append(
                f"🛡 {tier}",
                style={
                    "strict": "dim",
                    "trust-reads": "dim",
                    "trust-tests": "yellow",
                    "trust-all": "bold red",
                }.get(tier, "dim"),
            )
            seg, seg_style = context_segment(st)
            line.append("  │  ")
            line.append(seg, style=seg_style)
            # Told once, before the cliff, with the exact remediation — a repeating
            # warning on every 1s repaint would be noise the user learns to ignore.
            if st["near_limit"] and not self._ctx_warned:
                self._ctx_warned = True
                self._write_output(
                    Text(
                        f"Context at {st['percentage']:.0f}% of {st['max_tokens']:,} tok. "
                        "Auto-compaction fires at "
                        f"{context_manager.compaction_threshold * 100:.0f}% (ContextManager "
                        "default) and rewrites older turns. Run /compact now to do it "
                        "deliberately — /compact undo reverses it.",
                        style="yellow",
                    )
                )
            # Cached by _refresh_usage_bg; empty until a call has been journalled.
            if self._usage_fragment:
                line.append("  │  ")
                line.append(self._usage_fragment, style="dim")
            # A dead MCP server only logs, so missing tools look like an idle model.
            # getattr: a SimpleNamespace agent (tests) has no registry.
            mcp_status = getattr(getattr(self.agent, "registry", None), "mcp_status", None)
            if mcp_status and any(r.get("state") == "error" for r in mcp_status()):
                line.append("  │  ")
                line.append("!mcp", style="bold red")
            queue_count = len(self._prompt_queue)
            if queue_count:
                line.append(f"  │  📬 {queue_count} queued", style="yellow")
            if self._agent_busy:
                line.append(
                    "  " + busy_indicator(time.monotonic() - self._busy_started, self._busy_verb),
                    style="dim",
                )
            self.query_one("#status-bar", Static).update(line)
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
            self._post(self._update_status_bar)

    @work(thread=True, exclusive=True, group="usage")
    def _refresh_usage_bg(self) -> None:
        """Builds the spend/latency fragment off the UI thread and caches it.

        summarize() scans the whole of .agnostic/usage.jsonl — doing that on the
        1s busy repaint would put a growing file read in the render path."""
        fragment = ""
        try:
            config = self.agent.llm_client.config
            # The journal aggregates on the model actually executed, which for a
            # subscription preset is the sub-model, not the CLI placeholder.
            self._usage_summary = UsageLog().summarize(days=1)
            fragment, _ = usage_segment(self._usage_summary, config.sub_model or config.model)
        except Exception:  # a missing/locked/corrupt journal must not kill the bar
            fragment = ""
        if fragment != self._usage_fragment:
            self._usage_fragment = fragment
            self._post(self._update_status_bar)

    def _write_output(self, *args, **kwargs) -> None:
        """Write to the output log. MUST be called from the app/UI thread — use
        _post_output() from a worker thread instead."""
        try:
            log = self.query_one("#output-log", RichLog)
            log.write(*args, **kwargs)
        except NoMatches:
            pass

    def _post(self, fn, *args) -> None:
        """Runs a UI-thread callable from the UI thread or from any worker thread.

        Every worker→UI hop goes through here so exactly one place has to know that
        call_from_thread blocks on a future the app's event loop resolves: once the
        app is exiting there is nobody left to resolve it, and the worker would park
        in that future forever. Textual runs thread workers on the default
        ThreadPoolExecutor, whose atexit hook joins every such thread with no
        timeout — one parked worker hangs the whole interpreter at shutdown. Drop
        the update instead; the UI it would have painted is already gone.
        """
        if threading.get_ident() == self._thread_id:
            fn(*args)
        elif self.is_running:
            try:
                self.call_from_thread(fn, *args)
            except RuntimeError:  # app stopped between the check and the call
                pass

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
            self._tool_name, self._tool_t0 = content, time.monotonic()
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
            # tool_start/tool_end are not strictly paired for every tool; an unpaired
            # end (t0 == 0.0) would clock a 55-year run, so it renders with no duration.
            secs = max(0.0, time.monotonic() - self._tool_t0) if self._tool_t0 else 0.0
            self._tool_outputs.append((self._tool_name or "tool", secs, content))
            clipped, hidden = fold_summary(content)
            # A plain str title, never markup: a tool name or path containing '[' would
            # raise MarkupError on the panel border the same way the body would.
            title = f"⚙️ {self._tool_name or 'Tool Output'}"
            if self._tool_t0:
                title += f" · {secs:.1f}s"
            if hidden:
                title += f" · +{hidden} lines hidden — ctrl+o"
            self._tool_t0 = 0.0
            self._post_output(
                Panel(
                    safe_text(clipped),
                    title=title,
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
            # An automatic compaction just freed the window (agent/loop.py emits
            # ContextManager.compact_messages' message verbatim) — re-arm the nudge
            # so the next approach to the ceiling is announced again.
            if content.startswith("🧹 Compacted"):
                self._ctx_warned = False
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
        self._post(self._set_confirm_mode, True)
        self._post(
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
        self._post(self._set_confirm_mode, False)
        return self._confirm_response

    def _set_confirm_mode(self, on: bool) -> None:
        """Makes a pending hard-stop confirmation visible at the input box itself —
        an unchanged '❯' prompt gave no hint that the next Enter answers y/n."""
        try:
            self.query_one("#prompt-label", Static).update("approve? [y/n] " if on else "❯ ")
            self.query_one("#prompt-input", PromptArea).set_class(on, "confirm")
        except NoMatches:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the input box."""
        user_input = event.value.strip()
        # Cleared before the early return too: a box holding only blank lines would
        # otherwise stay dirty and the next Enter would resubmit nothing forever.
        event.input.value = ""
        if not user_input:
            return

        if self._awaiting_confirm:
            approved, unrecognized, reason = parse_confirm_answer(user_input)
            if unrecognized:
                # NOT an answer: queue it as a prompt. The confirm stays pending and the
                # worker stays blocked — a typo must never revoke a safety decision.
                self._prompt_queue.append(user_input)
                self._update_queue_indicator()
                self._write_output(
                    Text(
                        "📬 Queued — still waiting on approve? [y/n] (or 'n <reason>')",
                        style="yellow",
                    )
                )
                return
            self._confirm_reason = reason
            self._confirm_response = approved
            self._confirm_event.set()
            self._write_output(
                Text(
                    "→ {}{}".format(
                        "Approved" if approved else "Denied", (": " + reason) if reason else ""
                    ),
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

    def on_text_area_changed(self, event) -> None:
        """Grow the composer with its content, up to 8 lines, then let it scroll.
        TextArea has no auto-height in Textual 8.1.1 (its DEFAULT_CSS is height: 1fr),
        so the height is set here on every edit and paste."""
        event.text_area.styles.height = max(1, min(8, event.text_area.document.line_count))
        self._update_hint_bar(event.text_area.text)

    def _update_hint_bar(self, text: str) -> None:
        """The live slash-command menu above the composer: matching commands while
        a bare '/token' is being typed, hidden the rest of the time."""
        try:
            bar = self.query_one("#hint-bar", Static)
        except NoMatches:
            return
        hints = slash_hints(text)
        bar.display = bool(hints)
        if hints:
            menu = Text()
            for i, (cmd, blurb) in enumerate(hints):
                if i:
                    menu.append("\n")
                menu.append(cmd, style="bold cyan")
                menu.append(f"  {blurb}", style="dim")
            bar.update(menu)

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

        # `!cmd` — a local shell escape. A bare '!' is deliberately NOT special: it
        # falls through to the model rather than becoming a silent no-op.
        if user_input.startswith("!") and user_input[1:].strip():
            cmd = user_input[1:].strip()
            self._write_output(Text(f"$ {cmd}", style="dim cyan"))
            self._dispatch_background(lambda: self._run_bang(cmd))
            return

        # A reason typed with the verdict ('n: too risky') rides along with the next
        # prompt — consumed exactly once, and never smuggled into a slash command.
        if self._confirm_reason and not user_input.startswith("/"):
            user_input = (
                f"### [Operator note on the last approval]: {self._confirm_reason}\n\n{user_input}"
            )
            self._confirm_reason = ""

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
        self._mark_busy()
        self._run_agent_turn(user_input)

    def _run_bang(self, cmd: str):
        """Local shell escape. Deliberately routed through the registry's run_command so
        SafetyGuard.check_command_safety and the hard-stop confirm apply exactly as they do
        to a model-issued call — never subprocess directly from the UI layer.

        Nothing is appended to agent.history: a sanity check costs zero context and
        zero LLM calls. The live output and the Tool Output panel come for free from
        the tool's own tool_chunk/tool_end events through agent.output_callback."""
        res = self.agent.registry.execute(
            "run_command", {"command": cmd}, confirm_callback=self.agent.confirm_callback
        )
        if not res.is_error:
            return None
        return Panel(
            safe_text(res.output, style="bold red"),
            title="[bold red]❌ Command failed[/bold red]",
            title_align="left",
            border_style="red",
            box=box.ROUNDED,
            padding=(0, 1),
        )

    @work(thread=True, exclusive=True, group="agent_turn")
    def _run_agent_turn(self, raw_input: str) -> None:
        """Execute agent turn in a background thread so input stays responsive.
        @file/#symbol expansion happens here, not on the UI thread: a #symbol miss
        triggers a full workspace index and froze the app for over a second."""
        start_time = time.time()
        ok = True
        try:
            self.agent.run_turn(expand_prompt_references(raw_input, self.code_indexer))
        except Exception as e:
            ok = False
            self._post(
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
            self._post(
                self._write_output,
                Text(f"⏱ Turn completed in {duration:.2f}s", style="dim"),
            )
            self._agent_busy = False
            self._notify_turn_done(duration, ok)
            self._post(self._update_status_bar)
            # Process next queued prompt if any
            self._post(self._process_queue)

    def _dispatch_background(self, fn) -> None:
        """Marks the agent busy and runs fn() on a background worker so the input
        box stays responsive. Use for any slash command that talks to the LLM,
        subagents, or shells out — never run those inline on the UI thread."""
        self._mark_busy()
        self._run_background(fn)

    @work(thread=True, exclusive=True, group="agent_turn")
    def _run_background(self, fn) -> None:
        """Runs fn() on a background thread. fn may return a Rich renderable to
        display, or None. Captures fn's raw stdout — workflows like AutoTestRunner
        print through their own Rich Console — so it lands in the TUI's own output
        log instead of scribbling raw ANSI over the Textual canvas, line by line as
        it is printed rather than in one dump when fn() finally returns.
        """
        sink = LineForwarder(lambda line: self._post(self._write_output, safe_text(line)))
        start = time.monotonic()
        ok = True
        try:
            with contextlib.redirect_stdout(sink):
                result = fn()
            if result is not None:
                self._post(self._write_output, result)
        except Exception as e:
            ok = False
            self._post(
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
            self._notify_turn_done(time.monotonic() - start, ok)
            self._post(self._update_status_bar)
            self._post(self._process_queue)

    def _process_queue(self) -> None:
        """Process the next queued prompt if any."""
        if self._prompt_queue and not self._agent_busy:
            next_prompt = self._prompt_queue.popleft()
            self._update_queue_indicator()
            self._write_output(
                Text.from_markup(f"[dim cyan]📬 Processing queued prompt: {next_prompt}[/dim cyan]")
            )
            self._process_input(next_prompt)

    def _double_tap(self, name: str, window: float = 1.5) -> bool:
        """True only on the second press of `name` within `window` seconds. One
        timer per name, so Ctrl+C then Ctrl+L is never a double-tap."""
        now = time.monotonic()
        # '>=', not '>': time.monotonic() on Windows ticks at 15.6ms, so two presses
        # (or two calls in a test) can read the exact same instant — with '>' a
        # window of 0 would count that as a double-tap.
        first = now - self._taps.get(name, 0.0) >= window
        self._taps[name] = 0.0 if not first else now  # a consumed double-tap resets the timer
        return not first

    def exit(self, *args, **kwargs):
        """Every way out of the app funnels here, so this is the one place that has to
        release a worker blocked in _tui_confirm_callback: that thread waits on an
        Event only the input box or Esc can set, and once the app is gone neither can
        ever run again. Leaving it parked hangs the process at interpreter shutdown.
        An exit is not an approval — the pending hard-stop is denied on the way out."""
        if self._awaiting_confirm:
            self._confirm_response = False
            self._confirm_reason = ""
            self._confirm_event.set()
        # Released or not, the worker must stop making new calls into a dead UI.
        cancel = getattr(self.agent, "cancel_event", None)
        if cancel is not None:
            cancel.set()
        return super().exit(*args, **kwargs)

    def action_quit_safe(self) -> None:
        """Ctrl+C handler: cancel while busy, force-exit on a second press."""
        if self._agent_busy:
            # A worker thread cannot be interrupted mid-run: the flag is left alone so a
            # second overlapping turn can never start on the same agent.history.
            if self._double_tap("quit", 1.5):
                self.exit()
                return
            self.agent.cancel_event.set()
            self._write_output(
                Text(
                    "⏹ cancelling after the current step — press Ctrl+C again to force-exit.",
                    style="yellow",
                )
            )
            return
        if self._double_tap("quit", 1.5):
            self.exit()
            return
        self._write_output(Text("Press Ctrl+C again to exit.", style="dim yellow"))

    def action_cancel_turn(self) -> None:
        """Esc handler, in order: deny a pending confirm, else cooperatively cancel a
        running turn (the worker clears _agent_busy itself), else — idle, empty input,
        pressed twice — open the rewind picker."""
        if self._awaiting_confirm:
            # The explicit deny path: typed text is queued instead of answering, so Esc
            # is what guarantees a blocked worker can always be released.
            self._confirm_response = False
            self._confirm_reason = ""
            self._confirm_event.set()
            self._write_output(Text("→ Denied (Esc)", style="bold yellow"))
            return
        if self._agent_busy:
            self.agent.cancel_event.set()
            self._write_output(Text("⏹ cancelling after the current step…", style="yellow"))
            return
        # Idle, empty input, second Esc within 800ms: rewind. Anything typed keeps
        # Esc harmless, so clearing a half-written prompt can never open a modal.
        inp = self.query_one("#prompt-input", PromptArea)
        if inp.value.strip() or not self._double_tap("rewind", 0.8):
            return
        self.push_screen(RewindScreen(list(self._turn_marks)), callback=self._apply_rewind)

    def _apply_rewind(self, pick) -> None:
        """Restore the files, the conversation, or both, from one turn mark. Only
        reachable while idle, so no worker can be writing agent.history under us."""
        if not pick:
            return
        name, history, scope = pick
        if scope in ("files", "both"):
            ok, msg = undo_manager.rollback_to_checkpoint(name)
            self._write_output(Text(f"↩ {msg}", style="bold green" if ok else "bold yellow"))
        if scope in ("conversation", "both"):
            # list(), never the snapshot itself: the next turn would mutate the mark.
            self.agent.history = list(history)
            self._write_output(
                Text(
                    f"↩ Conversation restored to {name} ({len(history)} messages).",
                    style="bold green",
                )
            )
        self._update_status_bar()

    def action_clear_output(self) -> None:
        """Ctrl+L handler: asks twice, so a slipped keystroke never nukes the log."""
        if not self._double_tap("clear", 2.0):
            self._write_output(Text("Press Ctrl+L again to clear the log.", style="dim yellow"))
            return
        log = self.query_one("#output-log", RichLog)
        log.clear()
        self._print_banner()

    def action_expand_output(self) -> None:
        """Ctrl+O: print the last tool's output unfolded. The fold ships with its own
        escape hatch — a card that hides evidence with no way back is a bug report."""
        if not self._tool_outputs:
            self._write_output(Text("No tool output captured yet.", style="dim"))
            return
        name, secs, full = self._tool_outputs[-1]
        self._write_output(
            Text(f"── full output: {name} ({secs:.1f}s, {len(full)} chars) ──", style="dim blue")
        )
        self._write_output(safe_text(full))

    def action_cycle_trust(self) -> None:
        """Shift+Tab: dial autonomy up (and wrap back to strict) mid-task. The tier
        lives in SafetyGuard only — an unknown value restarts the cycle at strict
        instead of raising."""
        current = guard.get_trust_tier()
        nxt = (
            TRUST_TIERS[(TRUST_TIERS.index(current) + 1) % len(TRUST_TIERS)]
            if current in TRUST_TIERS
            else TRUST_TIERS[0]
        )
        self._write_output(
            Text(
                f"🛡️ {guard.set_trust_tier(nxt)}",
                style="bold yellow" if nxt == "trust-all" else "bold green",
            )
        )
        self._update_status_bar()

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
            inp = self.query_one("#prompt-input", PromptArea)
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
            inp = self.query_one("#prompt-input", PromptArea)
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

    # Headless first: `-p` must not print a banner, start a companion or build a
    # single Textual widget — its stdout belongs to whoever is parsing it.
    if args.prompt:
        from agent.headless import run_headless

        sys.exit(run_headless(args))

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

    # Auto-pick the best available preset (last /model choice, else best
    # subscription CLI, else first API key) — local is only the last resort, and
    # only when the user didn't point us somewhere with --url/--model.
    startup_model_msg = None
    if args.url == "http://localhost:1234/v1" and args.model == "local-model":
        pick = pick_default_preset(LLMConfig.PRESETS)
        if pick:
            key, sub_model, effort = pick
            startup_model_msg = agent.llm_client.switch_model(
                preset_key=key, sub_model=sub_model, reasoning_effort=effort
            )

    from agent.web.server import companion_telemetry

    companion_telemetry.bind_agent(agent)

    if args.web:
        maybe_start_web_companion(agent)

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
        startup_model_msg=startup_model_msg,
    )
    app.run()


if __name__ == "__main__":
    main()
