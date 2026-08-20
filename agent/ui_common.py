"""
agent/ui_common.py — Shared pieces for the two hand-maintained agent UIs (cli.py, tui.py).

Both cli.py (prompt_toolkit REPL) and tui.py (Textual app) need the same slash-command
table, @file/#symbol/@image prompt expansion, user-message formatting, safe-text rendering
for untrusted tool/model output, and CLI startup plumbing. This module is the single
definition of each so the two UIs cannot drift apart again.
"""

import argparse
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from rich.text import Text

from agent import __version__
from agent.llm.detector import ModelDoctor
from agent.tools.indexer import code_indexer, CodebaseIndexer

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


def parse_slash_command(line: str) -> Tuple[str, str]:
    """Splits a slash-command line into (command, args) on the first whitespace token.

    e.g. '/test some [bracket] arg' -> ('test', 'some [bracket] arg').
    Using str.replace(cmd, "") to strip the command corrupts args that happen to repeat
    the command token elsewhere in the line — split on the first token instead.

    Returns ("", "") for a line that isn't a slash command at all, so callers can
    safely match on `cmd` without accidentally treating a plain prompt that happens
    to start with a command word (e.g. "fix this bug") as "/fix".
    """
    line = line.strip()
    if not line.startswith("/"):
        return "", ""
    parts = line.split(maxsplit=1)
    cmd = parts[0][1:]
    args = parts[1].strip() if len(parts) > 1 else ""
    return cmd, args


def safe_text(content: str, style: Optional[str] = None) -> Text:
    """Wraps raw/untrusted text (tool output, model text, subprocess output) for Rich
    display WITHOUT parsing it as console markup. A grep hit like '[/etc/hosts]' or a
    model emitting '[/]' must never reach Panel(str) or Text.from_markup(f"...{x}...") —
    both parse brackets as markup and raise rich.errors.MarkupError on malformed tags.
    """
    text = str(content)
    return Text(text, style=style) if style else Text(text)


def format_user_display(raw_input: str) -> str:
    """Formats user input for clean display in the user panel.

    Puts @image: references on their own lines and ensures text body is cleanly
    separated, matching Claude Code's prompt layout.
    """
    formatted = re.sub(r"[ \t]*(@image:\S+)[ \t]*", r"\n\1\n", raw_input)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted).strip()
    return formatted


def expand_prompt_references(user_prompt: str, indexer: CodebaseIndexer) -> str:
    """Injects code snippets and references for any @file, #symbol, or @image found in prompt."""
    image_refs = re.findall(r"@image:([a-zA-Z0-9_\-./\\]+)", user_prompt)
    file_refs = re.findall(r"@([a-zA-Z0-9_\-./\\]+)", user_prompt)
    symbol_refs = re.findall(r"#([a-zA-Z0-9_.:]+)", user_prompt)

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
        # Routes through the guarded indexer — resolve_file itself refuses secret/
        # out-of-workspace paths (see agent/tools/indexer.py _check_access).
        res = indexer.resolve_file(f)
        if res:
            rel, content = res
            injected_context.append(f"### [Context Reference: @{rel}]:\n```\n{content[:2500]}\n```")

    for s in symbol_refs:
        res = indexer.resolve_symbol(s)
        if res:
            loc, snippet = res
            injected_context.append(f"### [Symbol Reference: #{s} ({loc})]:\n```\n{snippet}\n```")

    if injected_context:
        return user_prompt + "\n\n" + "\n\n".join(injected_context)
    return user_prompt


def build_arg_parser() -> argparse.ArgumentParser:
    """Shared argparse setup for both UI entrypoints."""
    parser = argparse.ArgumentParser(description="Agnostic AI Autonomous Coding Agent")
    parser.add_argument("--version", action="version", version=f"agnostic {__version__}")
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
        help="Prompt y/n for hard-stop commands (git push, rm -rf, deploys). Without this flag hard-stops are DENIED, not auto-approved.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the real-time visual web companion on port 7843 (next free port if taken)",
    )
    return parser


def detect_model(url: str, api_key: str, fallback_model: str):
    """Auto-discovers the active model from the endpoint.

    Returns (doctor, detected_model, detection).
    """
    doctor = ModelDoctor(base_url=url, api_key=api_key)
    detection = doctor.inspect()
    detected_model = detection.get("active_model") or fallback_model
    return doctor, detected_model, detection


def index_workspace() -> None:
    """Pre-indexes the workspace for fast fuzzy @file/#symbol autocomplete and lookups."""
    code_indexer.workspace_root = Path(os.getcwd()).resolve()
    code_indexer.index_workspace()


def maybe_start_web_companion(agent, open_browser: bool = True):
    """Starts the live visual web companion server. Returns (ok, web_url)."""
    from agent.web.server import start_companion_server, companion_telemetry

    companion_telemetry.bind_agent(agent)
    ok, web_url = start_companion_server(7843)
    # Only ok=True means a server is listening — web_url otherwise holds the startup
    # exception text, and opening a browser at the port anyway just shows a dead tab.
    if ok and open_browser:
        import webbrowser

        try:
            webbrowser.open(web_url)
        except (OSError, webbrowser.Error):  # no browser available; the URL is still reported
            pass
    return ok, web_url
