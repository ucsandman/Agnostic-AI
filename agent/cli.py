"""
agent/cli.py — Rich Interactive Terminal UI for Agnostic AI Agent
Provides an open-source Claude Code-style interactive shell with syntax highlighting,
live loading spinners, real-time token streaming, context % meter, visual diffs,
hotkeys, session memory, auto-completion, and multi-line modes.
"""

import sys
import os
import time
import argparse
import subprocess
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.prompt import Prompt

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter

from agent.loop import AgentLoop
from agent.llm.client import LLMConfig
from agent.llm.detector import ModelDoctor
from agent.governance.undo import undo_manager
from agent.governance.context import context_manager
from agent.workflows.tester import AutoTestRunner

console = Console()

SLASH_COMMANDS = [
    "/plan",
    "/research",
    "/review",
    "/swarm",
    "/diagram",
    "/pr",
    "/harvest",
    "/test",
    "/doctor",
    "/undo",
    "/commit",
    "/learn",
    "/grill-me",
    "/schedule",
    "/loop",
    "/state",
    "/distill",
    "/clear",
    "/multiline",
    "/help",
    "/exit",
]


def print_banner():
    banner_text = Text()
    banner_text.append(
        "🛡️  AGNOSTIC AI CODING AGENT v1.2.0 (10 Champions Active)\n", style="bold cyan"
    )
    banner_text.append(
        "AST Symbol Indexer | Swarm Engine | Web Companion | DashClaw Governed\n",
        style="dim white",
    )
    banner_text.append(
        "Commands: /plan, /swarm <task>, /diagram, /pr, /test, /doctor, /undo, /commit, /learn, /grill-me, /exit",
        style="yellow",
    )
    console.print(Panel(banner_text, border_style="cyan"))


def rich_output_callback(msg_type: str, content: str):
    if msg_type == "tool_start":
        console.print(
            f"[bold magenta]⚙️  Executing Tool:[/bold magenta] [yellow]{content}[/yellow]"
        )
    elif msg_type == "tool_end":
        clipped = content[:600] + ("..." if len(content) > 600 else "")
        console.print(
            Panel(clipped, title="Tool Output", border_style="dim blue", expand=False)
        )
    elif msg_type == "assistant":
        console.print(Markdown(content))
    elif msg_type == "subagent":
        console.print(f"[bold green]🐝 Subagent Notification:[/bold green] {content}")
    elif msg_type == "system":
        console.print(f"[bold yellow]🔔 {content}[/bold yellow]")
    elif msg_type == "error":
        console.print(f"[bold red]❌ Error:[/bold red] {content}")


def rich_confirm_callback(prompt_msg: str) -> bool:
    console.print(f"\n[bold red]⚠️  GOVERNANCE HARD-STOP:[/bold red]\n{prompt_msg}")
    ans = Prompt.ask("Proceed with execution?", choices=["y", "n"], default="n")
    return ans.lower() == "y"


def handle_commit(agent: AgentLoop):
    """Autonomous Git Commit generator workflow."""
    console.print("[cyan]Inspecting staged changes and git status...[/cyan]")
    try:
        st = subprocess.run(
            "git status --short", shell=True, capture_output=True, text=True
        ).stdout.strip()
        if not st:
            console.print("[dim]No changes detected in git working tree.[/dim]")
            return

        diff = subprocess.run(
            "git diff --cached", shell=True, capture_output=True, text=True
        ).stdout.strip()
        if not diff:
            diff = subprocess.run(
                "git diff", shell=True, capture_output=True, text=True
            ).stdout.strip()

        console.print(Panel(st, title="Git Status", border_style="yellow"))

        commit_prompt = (
            f"Based on the following git changes:\n```\n{st}\n```\nDiff preview:\n```\n{diff[:1500]}\n```\n"
            "Generate a single, precise Conventional Commit message (e.g. 'feat(agent): add undo manager and test workflow'). "
            "Output ONLY the commit message without commentary."
        )
        msg = (
            agent.llm_client.chat_completion(
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

        console.print(f"\n[bold green]Suggested Commit Message:[/bold green]\n{msg}\n")
        confirm = Prompt.ask(
            "Stage all and commit with this message?", choices=["y", "n"], default="y"
        )
        if confirm.lower() == "y":
            subprocess.run("git add -A", shell=True)
            subprocess.run(["git", "commit", "-m", msg])
            console.print("[bold green]✅ Changes committed successfully![/bold green]")
    except Exception as e:
        console.print(f"[red]Git commit workflow error: {str(e)}[/red]")


def main():
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
        help="Enable manual confirmation gates for hard-stop commands (Default is fully autonomous)",
    )
    args = parser.parse_args()

    # 1. Auto-discover active model from endpoint
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

    agent = AgentLoop(
        workspace_root=os.getcwd(),
        llm_config=config,
        confirm_callback=rich_confirm_callback
        if require_confirmation
        else (lambda _: True),
        output_callback=rich_output_callback,
    )
    if use_compact:
        agent._load_harness_system_prompt(compact=True)

    if args.prompt:
        # Non-interactive CLI invocation
        with console.status(
            f"[bold cyan]Thinking ({detected_model})...[/bold cyan]", spinner="dots"
        ):
            agent.run_turn(args.prompt)
        sys.exit(0)

    print_banner()
    if detection["status"] == "online":
        console.print(
            f"[dim green]✓ Connected to {args.url} (Model: {detected_model})[/dim green]"
        )
    else:
        console.print(
            f"[dim yellow]⚠️ Local endpoint offline at {args.url} (Run LM Studio/Ollama)[/dim yellow]"
        )

    # Setup persistent terminal history and command autocompletion
    history_dir = Path.home() / ".agnostic"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "agent_history.txt"

    session = PromptSession(
        history=FileHistory(str(history_file)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=WordCompleter(SLASH_COMMANDS, ignore_case=True),
    )

    test_runner = AutoTestRunner(
        workspace_root=Path(os.getcwd()),
        agent_loop_func=agent.run_turn,
    )

    while True:
        try:
            # Render live context usage meter above prompt
            gauge_str = context_manager.render_gauge(agent.history)
            console.print(f"\n{gauge_str}")

            user_input = session.prompt("agnostic > ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
                console.print("[dim]Exiting Agnostic Coding Agent. Goodbye![/dim]")
                break

            elif user_input == "/clear":
                console.clear()
                print_banner()
                continue

            elif user_input == "/multiline":
                console.print(
                    "[cyan]Multi-line input mode activated. Paste or write content, then press [bold yellow]Ctrl+D (or Ctrl+Z on Windows then Enter)[/bold yellow] to submit:[/cyan]"
                )
                lines = []
                while True:
                    try:
                        line = input()
                        lines.append(line)
                    except EOFError:
                        break
                user_input = "\n".join(lines).strip()
                if not user_input:
                    continue

            elif user_input == "/doctor":
                console.print(
                    Panel(
                        doctor.format_report(),
                        title="Agnostic Doctor / Endpoint Inspector",
                        border_style="cyan",
                    )
                )
                continue

            elif user_input == "/undo":
                success, msg = undo_manager.rollback_last()
                if success:
                    console.print(f"[bold green]⏪ {msg}[/bold green]")
                else:
                    console.print(f"[bold yellow]⚠️ {msg}[/bold yellow]")
                continue

            elif user_input == "/commit":
                handle_commit(agent)
                continue

            elif user_input.startswith("/test"):
                custom_cmd = user_input.replace("/test", "").strip() or None
                test_runner.auto_repair_loop(custom_command=custom_cmd)
                continue

            elif user_input.startswith("/research"):
                topic = user_input.replace("/research", "").strip()
                if not topic:
                    console.print(
                        "[yellow]Please provide a research query, e.g. /research database connection pooling[/yellow]"
                    )
                    continue
                with console.status(
                    f"[bold cyan]Subagent researching '{topic}'...[/bold cyan]",
                    spinner="dots",
                ):
                    report = agent.subagents.spawn("researcher", topic)
                console.print(Markdown(report))
                continue

            elif user_input.startswith("/review"):
                with console.status(
                    "[bold cyan]Subagent reviewing workspace diffs...[/bold cyan]",
                    spinner="dots",
                ):
                    report = agent.subagents.spawn(
                        "reviewer",
                        "Inspect git status and recent diffs for bugs, missing tests, or security concerns.",
                    )
                console.print(Markdown(report))
                continue

            elif user_input.startswith("/plan"):
                task = user_input.replace("/plan", "").strip() or "General Task Plan"
                console.print(
                    f"[cyan]Initiating Dynamic Planning Workflow for: {task}[/cyan]"
                )
                plan_prompt = (
                    f"Create a deterministic execution plan for the following objective:\n'{task}'\n"
                    "State ASSUMPTIONS, then a numbered step-by-step PLAN with specific verification criteria for each step."
                )
                with console.status(
                    "[bold cyan]Generating execution plan...[/bold cyan]",
                    spinner="dots",
                ):
                    agent.run_turn(plan_prompt)
                continue

            elif user_input.startswith("/learn"):
                lesson = user_input.replace("/learn", "").strip()
                if not lesson:
                    console.print(
                        "[yellow]Usage: /learn <lesson or constraint>[/yellow]"
                    )
                    continue
                from agent.governance.learn import learner

                ok, msg = learner.record_lesson(lesson)
                console.print(f"[bold green]🧠 {msg}[/bold green]")
                continue

            elif user_input.startswith(("/schedule", "/loop")):
                from agent.workflows.scheduler import scheduler

                resp = scheduler.parse_and_schedule(user_input, agent.run_turn)
                console.print(f"[bold magenta]⏰ {resp}[/bold magenta]")
                continue

            elif user_input.startswith("/grill-me") or user_input.startswith("/grill"):
                task = user_input.replace("/grill-me", "").replace("/grill", "").strip()
                if not task:
                    task = Prompt.ask(
                        "[cyan]What feature or architecture task do you want to be grilled on?[/cyan]"
                    ).strip()
                from agent.workflows.grill import DesignInterviewer

                interviewer = DesignInterviewer(agent.llm_client)
                aligned_summary = interviewer.interview(task)
                # Feed aligned requirements into next agent turn
                proceed = Prompt.ask(
                    "\nProceed to implement based on aligned choices?",
                    choices=["y", "n"],
                    default="y",
                )
                if proceed.lower() == "y":
                    with console.status(
                        "[bold cyan]Implementing aligned specifications...[/bold cyan]",
                        spinner="dots",
                    ):
                        agent.run_turn(
                            f"Implement the following feature based on aligned architecture choices:\nObjective: {task}\n\nAligned Specifications:\n{aligned_summary}"
                        )
                continue

            elif user_input.startswith("/state"):
                from agent.governance.state import state_manager

                console.print(
                    Panel(
                        state_manager.read_state(),
                        title="🎯 Persistent State Whiteboard (.agnostic/state.md)",
                        border_style="green",
                    )
                )
                continue

            elif user_input == "/distill":
                console.print("[cyan]Triggering Harness Distillation Engine...[/cyan]")
                res = subprocess.run(
                    "node engine/distill/distill.cjs",
                    cwd=agent.workspace_root,
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                console.print(
                    Panel(
                        res.stdout or res.stderr or "Distillation complete.",
                        title="Distillation Results",
                        border_style="cyan",
                    )
                )
                continue

            elif user_input.startswith("/swarm"):
                task = user_input.replace("/swarm", "").strip()
                if not task:
                    console.print(
                        "[yellow]Usage: /swarm <complex task or feature>[/yellow]"
                    )
                    continue
                from agent.workflows.swarm import SwarmCoordinator

                swarm = SwarmCoordinator(agent.subagents, agent.llm_client)
                synthesis = swarm.dispatch_swarm(task)
                console.print(
                    Panel(
                        Markdown(synthesis),
                        title="🐝 Swarm Unified Strategy",
                        border_style="green",
                    )
                )
                continue

            elif user_input.startswith("/diagram") or user_input.startswith("/map"):
                from agent.workflows.diagram import ArchitectureDiagrammer

                diag = ArchitectureDiagrammer(agent.workspace_root)
                m_code = diag.generate_mermaid_map()
                console.print(
                    Panel(
                        m_code,
                        title="📊 Mermaid Architecture Diagram",
                        border_style="cyan",
                    )
                )
                continue

            elif user_input.startswith("/pr"):
                from agent.workflows.pr_pilot import PRAutoPilot

                pilot = PRAutoPilot(agent.workspace_root, agent.llm_client)
                pilot.generate_pr_summary()
                continue

            elif user_input.startswith("/harvest"):
                from agent.governance.harvester import harvester

                count = harvester.scan_and_harvest()
                console.print(
                    f"[bold green]🌾 Harvested {count} cross-agent corrections into candidate ladder.[/bold green]"
                )
                continue

            elif user_input == "/help":
                console.print("""
[bold]Available Commands & Slash Shortcuts:[/bold]
• [bold cyan]/swarm <task>[/bold cyan]       - Dispatch 3 parallel subagents (Research, Test, Review) simultaneously
• [bold cyan]/diagram[/bold cyan]            - Generate instant Mermaid architecture dependency diagram
• [bold cyan]/pr[/bold cyan]                 - Generate GitHub Pull Request summary and description
• [bold cyan]/harvest[/bold cyan]            - Harvest corrections across local Claude, Cursor, and Codex transcripts
• [bold cyan]/learn <lesson>[/bold cyan]    - Record candidate rule/lesson directly into harness SSOT
• [bold cyan]/grill-me <task>[/bold cyan]   - Interactive lead architect interview to align on design & specs
• [bold cyan]/schedule every 30s "cmd"[/bold cyan] - Run recurring background routine
• [bold cyan]/loop 3 "cmd"[/bold cyan]       - Repeat a command N times sequentially
• [bold cyan]/state[/bold cyan]              - View persistent state whiteboard (.agnostic/state.md)
• [bold cyan]/distill[/bold cyan]            - Run 4-Tier Promotion Ladder & prune candidate rules
• [bold cyan]/test [cmd][/bold cyan]         - Run autonomous test-and-repair loop until tests pass
• [bold cyan]/undo[/bold cyan]               - Instant snapshot rollback of the last file edit/write
• [bold cyan]/commit[/bold cyan]             - Auto-generate conventional git commit and stage changes
• [bold cyan]/multiline[/bold cyan]          - Paste large multi-line logs/specs without premature sending
• [bold cyan]/clear[/bold cyan]              - Clear the terminal screen while keeping session memory
• [bold cyan]/plan <task>[/bold cyan]         - Generate a step-by-step goal-driven plan before coding
• [bold cyan]/doctor[/bold cyan]             - Auto-detect local model status, context size & endpoint health
• [bold cyan]/exit[/bold cyan]               - Exit the interactive REPL
                """)
                continue

            # Standard agent turn with animated loading status
            start_time = time.time()
            with console.status(
                f"[bold cyan]Thinking ({detected_model})...[/bold cyan]", spinner="dots"
            ):
                agent.run_turn(user_input)
            duration = time.time() - start_time
            console.print(f"[dim]⏱ Turn completed in {duration:.2f}s[/dim]")

        except KeyboardInterrupt:
            console.print("\n[dim]Use /exit to quit.[/dim]")
        except EOFError:
            break


if __name__ == "__main__":
    main()
