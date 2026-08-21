"""
tests/test_headless.py — Regression tests for agent/headless.py (`agnostic -p ...`).

`-p` is the subagent entrypoint: whatever calls it parses stdout, so the split
between stdout (the answer, and nothing else) and stderr (tool/system/error
chatter) is the contract, together with the exit code and the json shape. No
network, no textual, no real AgentLoop — the loop is faked and only the plumbing
around it is under test.
"""

import ast
import inspect
import io
import json
from types import SimpleNamespace

import pytest

import agent.headless as headless
from agent.ui_common import build_arg_parser


class _FakeLoop:
    """Stands in for AgentLoop: replays one tool_start/tool_end pair, returns 'FINAL'."""

    last = None
    events = ()  # class-level: each test sets the events its turn should replay

    def __init__(self, llm_config=None, confirm_callback=None, **kw):
        self.llm_client = SimpleNamespace(
            config=llm_config,
            switch_model=lambda **_kw: "Switched to preset 'fake'",
        )
        self.confirm_callback = confirm_callback
        self.output_callback = kw.get("output_callback")
        _FakeLoop.last = self

    def _load_harness_system_prompt(self, compact=True):
        self.compact = compact

    def run_turn(self, prompt):
        self.prompt = prompt
        for msg_type, content in self.events:
            self.output_callback(msg_type, content)
        return "FINAL"


def _install(monkeypatch, events=()):
    """Swap in the fake loop. Nothing may touch the network or the workspace index."""
    monkeypatch.setattr(headless, "AgentLoop", _FakeLoop)
    monkeypatch.setattr(headless, "expand_prompt_references", lambda p, _idx: p)
    monkeypatch.setattr(_FakeLoop, "events", events, raising=False)


def _args(**over):
    base = dict(
        prompt="hi",
        url="http://localhost:1234/v1",
        model="sub-claude-code",  # a preset, so no endpoint probe runs
        api_key="k",
        full_prompt=False,
        output_format="text",
        yes=False,
        web=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _events():
    return [
        ("tool_start", 'run_command({"command": "ls"})'),
        ("tool_end", "a.py b.py"),
    ]


def test_text_mode_prints_only_the_answer_on_stdout(capsys, monkeypatch):
    _install(monkeypatch, _events())
    code = headless.run_headless(_args())
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "FINAL\n"
    assert "run_command" in captured.err


def test_json_mode_reports_the_answer_and_the_tool_calls(capsys, monkeypatch):
    _install(monkeypatch, _events())
    code = headless.run_headless(_args(output_format="json"))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["result"] == "FINAL"
    assert payload["ok"] is True
    assert [t["name"] for t in payload["tool_calls"]] == ["run_command"]
    assert payload["tool_calls"][0]["preview"].startswith("run_command(")


def test_an_error_event_fails_the_run_but_still_prints_the_text(capsys, monkeypatch):
    _install(monkeypatch, [("error", "boom")])
    code = headless.run_headless(_args())
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == "FINAL\n"
    assert "boom" in captured.err


def test_hard_stops_are_denied_without_yes_and_approved_with_it(capsys, monkeypatch):
    _install(monkeypatch)
    headless.run_headless(_args())
    assert _FakeLoop.last.confirm_callback("git push") is False
    headless.run_headless(_args(yes=True))
    assert _FakeLoop.last.confirm_callback("git push") is True
    capsys.readouterr()


def test_empty_prompt_exits_two(capsys, monkeypatch):
    _install(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        headless.run_headless(_args(prompt="   "))
    assert exc.value.code == 2
    assert "--prompt was empty" in capsys.readouterr().err


def test_a_dash_prompt_reads_stdin_and_refuses_a_terminal(capsys, monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(headless.sys, "stdin", io.StringIO("from a pipe"))
    assert headless.run_headless(_args(prompt="-")) == 0
    assert _FakeLoop.last.prompt == "from a pipe"

    monkeypatch.setattr(headless.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    with pytest.raises(SystemExit) as exc:
        headless.run_headless(_args(prompt="-"))
    assert exc.value.code == 2
    assert "stdin is a terminal" in capsys.readouterr().err


def test_build_arg_parser_accepts_print_as_an_alias_of_prompt():
    args = build_arg_parser().parse_args(["--print", "X"])
    assert args.prompt == "X"
    assert args.output_format == "text"
    assert args.yes is False


def test_headless_never_imports_textual():
    """A headless run must not pay for (or depend on) the TUI framework."""
    tree = ast.parse(inspect.getsource(headless))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    assert modules and not any(m.split(".")[0] == "textual" for m in modules)
