"""
agent/tui_commands.py — the TUI's slash-command dispatcher, split out of tui.py.

AgnosticTUI mixes this in; every method here runs on the Textual UI thread and
relies on the host app for output (_write_output/_post_output), background
dispatch (_dispatch_background/_run_agent_turn) and state (agent, doctor,
detection, test_runner). Anything that does network/subprocess/LLM work must go
through _dispatch_background — tests/test_ui_common.py parses this file's
if/elif chain to enforce that.
"""

import subprocess
from typing import Optional

from textual.widgets import RichLog

from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from rich import box

from agent.llm.client import LLMConfig
from agent.tools.diff_viewer import DiffViewer
from agent.governance.undo import undo_manager, theme_manager
from agent.governance.context import context_manager
from agent.governance.guard import guard
from agent.governance.audit import audit_manager
from agent.governance.session_manager import session_manager
from agent.governance.memory import MemoryStore
from agent.governance.state import state_manager
from agent.ui_common import (
    MEMORY_USAGE,
    help_text,
    maybe_start_web_companion,
    mcp_table,
    org_command,
    parse_model_args,
    parse_slash_command,
    safe_text,
    save_settings,
)


class SlashCommandMixin:
    """/commands for AgnosticTUI. Host must provide: agent, doctor, detection,
    test_runner, query_one, _write_output, _post_output, _print_banner,
    _dispatch_background, _run_agent_turn, _update_status_bar, _mark_busy, _agent_busy."""

    def _apply_model_pick(self, pick) -> None:
        """Picker/argument result -> switch_model -> echo. pick is
        (preset_key, sub_model, effort) or None when the picker was cancelled."""
        if not pick:
            return
        key, sub_model, effort = pick
        msg = self.agent.llm_client.switch_model(
            preset_key=key, sub_model=sub_model, reasoning_effort=effort
        )
        ok = msg.startswith(("Switched", "Updated"))
        if ok and key:
            # Remembered across sessions: startup re-picks this preset first.
            save_settings(preset=key, sub_model=sub_model or "", effort=effort or "")
        self._write_output(Text(f"🧠 {msg}", style="bold green" if ok else "bold yellow"))
        self._update_status_bar()

    def _load_session_pick(self, name) -> None:
        """Resume-picker result -> the existing load path. name is the chosen
        session, or None when the picker was cancelled."""
        if not name:
            return
        hist, msg = session_manager.load_session(name)
        if hist:
            self.agent.history = hist
            self._write_output(Text(f"📂 {msg}", style="bold green"))
        else:
            self._write_output(Text(f"❌ {msg}", style="bold red"))
        self._update_status_bar()

    def _show_turn_diff(self, name) -> None:
        """Picker/`/diff <turn>` result -> one unified-diff panel per file that turn
        changed. The snapshots hold both texts, so nothing is read from disk and
        nothing needs a background worker. name is None when the picker was cancelled."""
        if not name:
            return
        changes = undo_manager.changed_since(name)
        if not changes:
            self._write_output(Text(f"No file changes since {name}.", style="dim"))
            return
        for path, before, after in changes:
            try:
                label = path.relative_to(self.agent.workspace_root).as_posix()
            except ValueError:
                label = path.name
            # ponytail: DiffViewer parses its title as Rich markup; a '[' in a filename
            # would raise — escape it if that ever happens in the wild
            self._write_output(DiffViewer.render_diff(label, before or "", after, max_lines=60))

    def _show_memory(self, name) -> None:
        """Picker/`/memory show` result -> the whole body in a panel. name is None
        when the picker was cancelled."""
        if not name:
            return
        try:
            memory = MemoryStore(self.agent.workspace_root).get(name)
        except (ValueError, OSError) as e:
            self._write_output(Text(str(e), style="yellow"))
            return
        if memory is None:
            self._write_output(
                Text(f'No memory named "{name}". Try /memory to list them.', style="dim")
            )
            return
        self._write_output(
            Panel(
                # Bodies are code snippets as often as prose: neither the body nor
                # the user-chosen name may reach Rich's markup parser.
                safe_text(memory.body),
                title=safe_text(f"🧠 {memory.name} ({memory.type}, saved {memory.created})"),
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

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
            # No mode to toggle any more: the composer is a TextArea, so it is always
            # multi-line. The command survives as the place people look for the keys.
            self._write_output(
                Text(
                    "The prompt is multi-line: Shift+Enter (or Alt+Enter / Ctrl+J) "
                    "inserts a newline, Enter sends. Pasted text keeps its line breaks.",
                    style="yellow",
                )
            )
            return True

        elif cmd == "compact":
            if args.strip().lower() == "undo":
                prev = getattr(self, "_pre_compact_history", None)
                if prev is None:
                    self._write_output(
                        Text("Nothing to undo — no /compact has run this session.", style="yellow")
                    )
                else:
                    self.agent.history = list(prev)
                    self._pre_compact_history = None
                    self._write_output(
                        Text(
                            f"↩ Restored {len(self.agent.history)} pre-compaction messages.",
                            style="bold green",
                        )
                    )
                return True
            self._pre_compact_history = list(self.agent.history)
            self.agent.history, ok, msg = context_manager.compact_messages(
                self.agent.history, force=True
            )
            self._write_output(Text(msg, style="bold green" if ok else "yellow"))
            if ok:
                self._ctx_warned = False
                # Show what survived, so a session that goes sideways after a
                # compaction is debuggable instead of a black box.
                block = self.agent.history[0]["content"].partition("### [Session Distillation")
                if block[1]:
                    self._write_output(
                        Panel(
                            safe_text(block[1] + block[2]),
                            title="🧹 What compaction kept",
                            border_style="green",
                            box=box.ROUNDED,
                            padding=(0, 1),
                        )
                    )
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
            if not args.strip():
                # Bare /session: resume picker. Never while a worker owns
                # agent.history — a load would race it.
                if self._agent_busy:
                    self._write_output(
                        Text("Finish or cancel the current turn first.", style="yellow")
                    )
                    return True
                from agent.tui_sessions import SessionPickerScreen

                self.push_screen(
                    SessionPickerScreen(session_manager.list_sessions()),
                    callback=self._load_session_pick,
                )
                return True

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
            if args.split():
                target_key, sub_model, effort, err = parse_model_args(
                    args.split(), LLMConfig.PRESETS
                )
                if err:
                    self._write_output(Text(err, style="yellow"))
                    return True
                self._apply_model_pick((target_key, sub_model, effort))
            else:
                from agent.tui_model_picker import ModelPickerScreen

                self.push_screen(
                    ModelPickerScreen(
                        self.agent.llm_client.config.model,
                        local_online=self.detection.get("status") == "online",
                        # Cached by _refresh_usage_bg — reading the journal here
                        # would block the UI thread every time /model opens.
                        usage_summary=self._usage_summary,
                    ),
                    callback=self._apply_model_pick,
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
            self._mark_busy()
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

        elif cmd == "org":
            self._write_output(
                Panel(
                    safe_text(org_command(self.agent, args)),
                    title="Adaptive Orchestration",
                    border_style="cyan",
                )
            )
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

        elif cmd == "mcp":
            sub = args.strip().lower()
            if sub == "reload":
                # Stops and re-spawns child processes: must not run on the UI thread.
                self._dispatch_background(
                    lambda: Text(
                        "MCP reloaded: " + self.agent.registry.reload_mcp(),
                        style="bold green",
                    )
                )
            elif sub in ("", "list"):
                # mcp_status() is an in-memory read — cheap enough to render inline.
                self._write_output(mcp_table(self.agent.registry.mcp_status()))
            else:
                self._write_output(Text("Usage: /mcp [reload]", style="yellow"))
            return True

        elif cmd == "memory":
            # Every form is a read (or one atomic write) over at most 200 small
            # local files — cheap enough to render inline, like /mcp list.
            store = MemoryStore(self.agent.workspace_root)
            parts = args.split(None, 1)
            sub = parts[0].lower() if parts else "list"
            rest = parts[1].strip() if len(parts) > 1 else ""

            if sub == "list" and not rest:
                from agent.tui_memory import MemoryPickerScreen

                self.push_screen(MemoryPickerScreen(store.list()), callback=self._show_memory)
            elif sub == "show":
                self._show_memory(rest)
            elif sub == "save":
                name, sep, body = rest.partition("--")
                name, body = name.strip(), body.strip()
                if not sep or not name or not body:
                    self._write_output(
                        Text(
                            "Usage: /memory save <name> -- <the thing to remember>",
                            style="yellow",
                        )
                    )
                    return True
                first = next((ln for ln in body.splitlines() if ln.strip()), "")[:120]
                try:
                    store.save(name, first, body)
                except (ValueError, OSError) as e:
                    # MemoryStore's own messages are already written for a human.
                    self._write_output(Text(str(e), style="yellow"))
                    return True
                self._write_output(Text(f'🧠 Saved memory "{name}" (project).', style="bold green"))
            elif sub == "forget":
                try:
                    gone = store.delete(rest)
                except (ValueError, OSError) as e:
                    self._write_output(Text(str(e), style="yellow"))
                    return True
                if gone:
                    self._write_output(Text(f'Forgot "{rest}".', style="bold green"))
                else:
                    self._write_output(Text(f'No memory named "{rest}".', style="yellow"))
            else:
                self._write_output(Text(MEMORY_USAGE, style="yellow"))
            return True

        elif cmd == "diff":
            # Read-only, so no _agent_busy guard (unlike /session): looking at what an
            # earlier turn wrote while the current one runs is exactly the point.
            if not self._turn_marks:
                self._write_output(Text("No turns yet.", style="dim"))
                return True
            if args.strip():
                self._show_turn_diff(args.split()[0])
                return True
            from agent.tui_diff import DiffPickerScreen

            marks = list(self._turn_marks)
            # Counted here, not in the screen: the picker does no undo/filesystem work.
            counts = {name: len(undo_manager.changed_since(name)) for name, _clock, _h in marks}
            self.push_screen(DiffPickerScreen(marks, counts), callback=self._show_turn_diff)
            return True

        elif cmd == "notify":
            sub = args.strip().lower()
            if sub in ("on", "off"):
                self._notify_enabled = sub == "on"
                try:
                    state_manager.set_setting("notify", self._notify_enabled)
                    note = ""
                except OSError:
                    # A read-only workspace is not a reason to refuse the toggle —
                    # it is a reason to say the toggle will not survive the session.
                    note = " (for this session only — .agnostic is not writable)"
                self._write_output(
                    Text(
                        f"notifications: {sub}{note}",
                        style="bold green" if sub == "on" else "yellow",
                    )
                )
                return True
            # The second half is the difference between a feature and a bug report:
            # on a terminal that never reports focus, 'on' would be a lie.
            self._write_output(
                Text(
                    "notifications: {} ({})".format(
                        "on" if self._notify_enabled else "off",
                        "this terminal reports focus"
                        if self._saw_focus_event
                        else "this terminal never reported focus — notifications will not fire",
                    ),
                    style="dim",
                )
            )
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
