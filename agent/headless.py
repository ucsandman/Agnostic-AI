"""
agent/headless.py — `agnostic -p "<prompt>"`: one turn, no TUI, machine-readable.

This is the subagent entrypoint: stdout carries the answer (plain text, or one
JSON object with --output-format json), stderr carries every tool/system/error
line, and the exit code is 0 only when no `error` event was emitted. Both UIs
(agent/tui.py, agent/cli.py) hand `-p` straight here before they build anything
interactive.

Deliberately importless of `textual`, `prompt_toolkit` and `rich`: this output is
consumed by pipes, logs and other agents, so it is plain `print`, never a Console
that would inject ANSI or wrap at a terminal width that does not exist. A test
asserts the module never imports textual.
"""

import json
import os
import sys

from agent.llm.client import LLMConfig
from agent.llm.usage import UsageLog
from agent.loop import AgentLoop
from agent.tools.indexer import code_indexer
from agent.ui_common import detect_model, expand_prompt_references, maybe_start_web_companion

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


def _make_callback(state: dict):
    """The output callback: everything but the answer goes to stderr, prefixed.

    `assistant_chunk` is dropped — the final text is printed once, from run_turn's
    return value, so a streaming backend cannot duplicate it. Every `tool_start`
    is collected for the json report, and any `error` event latches state['error']:
    AgentLoop emits one on every failure path (including the max-steps cap), so
    that flag — never a string match on the returned text — is the exit code.
    """

    def callback(msg_type: str, content: str) -> None:
        text = str(content)
        if msg_type == "assistant_chunk":
            return
        if msg_type == "tool_start":
            state["tool_calls"].append(
                {"name": text.split("(", 1)[0].strip(), "preview": text[:200]}
            )
        elif msg_type == "error":
            state["error"] = True
        print(f"[{msg_type}] {text}", file=sys.stderr)

    return callback


def _read_prompt(raw: str) -> str:
    """The prompt text, with '-' meaning stdin. Exits 2 rather than hanging on a tty."""
    if raw.strip() == "-":
        if sys.stdin.isatty():
            print("error: --prompt was '-' but stdin is a terminal", file=sys.stderr)
            raise SystemExit(2)
        raw = sys.stdin.read()
    if not raw.strip():
        print("error: --prompt was empty", file=sys.stderr)
        raise SystemExit(2)
    return raw


def _usage_since(log: UsageLog, n0: int):
    """The usage dict for the entries this run appended, or None if it recorded none.

    cost_usd is None when any call in the run had no price — an unpriced model must
    not report $0.00 of spend.
    """
    entries = list(log.entries())[n0:]
    if not entries:
        return None
    costs = [e.get("cost_usd") for e in entries]
    return {
        "prompt_tokens": sum(int(e.get("prompt_tokens") or 0) for e in entries),
        "completion_tokens": sum(int(e.get("completion_tokens") or 0) for e in entries),
        "cost_usd": None if any(c is None for c in costs) else round(sum(costs), 6),
        "calls": len(entries),
    }


def run_headless(args) -> int:
    """Run exactly one turn with no UI. Returns the process exit code."""
    prompt = _read_prompt(args.prompt or "")

    preset = LLMConfig.PRESETS.get(args.model)
    config = LLMConfig(base_url=args.url, api_key=args.api_key, model=args.model)
    if not preset:
        # Local endpoint: probe synchronously — there is no frame to keep responsive,
        # and `-p` must talk to the model the endpoint actually serves.
        _, config.model, _ = detect_model(args.url, args.api_key, args.model)

    state = {"tool_calls": [], "error": False}
    callback = _make_callback(state)
    agent = AgentLoop(
        workspace_root=os.getcwd(),
        llm_config=config,
        # Hard stops are DENIED without --yes, exactly like the legacy `-p` path:
        # --ask-permissions is meaningless with no terminal to answer on.
        confirm_callback=lambda _p: bool(args.yes),
        output_callback=callback,
    )
    if preset:
        callback("system", agent.llm_client.switch_model(preset_key=args.model))
    agent._load_harness_system_prompt(compact=not args.full_prompt)

    if getattr(args, "web", False):
        # Honoured, but never opens a browser: nobody is watching this shell.
        ok, web_url = maybe_start_web_companion(agent, open_browser=False)
        callback(
            "system", f"web companion: {web_url}" if ok else f"web companion failed: {web_url}"
        )

    log = UsageLog()
    n0 = sum(1 for _ in log.entries())
    try:
        result = agent.run_turn(expand_prompt_references(prompt, code_indexer))
    except Exception as e:  # an escaped exception is a failed run, not a crash report
        print(f"[error] {e}", file=sys.stderr)
        result, state["error"] = f"Turn execution error: {e}", True

    result = str(result or "")
    if getattr(args, "output_format", "text") == "json":
        print(
            json.dumps(
                {
                    "result": result,
                    "tool_calls": state["tool_calls"],
                    "usage": _usage_since(log, n0),
                    "model": config.display_model(),
                    "ok": not state["error"],
                },
                ensure_ascii=False,
            )
        )
    else:
        print(result)
    return 1 if state["error"] else 0
