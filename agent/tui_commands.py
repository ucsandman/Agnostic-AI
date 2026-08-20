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

from agent.llm.client import LLMConfig
from agent.governance.undo import undo_manager, theme_manager
from agent.governance.context import context_manager
from agent.governance.guard import guard
from agent.governance.audit import audit_manager
from agent.governance.session_manager import session_manager
from agent.ui_common import (
    help_text,
    maybe_start_web_companion,
    parse_model_args,
    parse_slash_command,
    safe_text,
)


class SlashCommandMixin:
    """/commands for AgnosticTUI. Host must provide: agent, doctor, detection,
    test_runner, query_one, _write_output, _post_output, _print_banner,
    _dispatch_background, _run_agent_turn, _update_status_bar, _agent_busy."""

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
        self._write_output(Text(f"🧠 {msg}", style="bold green" if ok else "bold yellow"))
        self._update_status_bar()

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
