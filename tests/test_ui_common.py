"""
tests/test_ui_common.py — Regression tests for agent/ui_common.py (the shared pieces
extracted from agent/cli.py and agent/tui.py).

Covers: the Rich-markup-injection crash (a grep hit like '[/etc/hosts]' or a model
emitting '[/]' must never raise rich.errors.MarkupError), the slash-command arg
parser (str.replace used to corrupt args containing the command token), and that
cli.py/tui.py share one definition of SLASH_COMMANDS / expand_prompt_references
instead of two hand-maintained copies.
"""

import inspect

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.errors import MarkupError

import agent.cli as cli
import agent.tui as tui
from agent.ui_common import (
    SLASH_COMMANDS,
    expand_prompt_references,
    parse_slash_command,
    safe_text,
)


# --- Bug 1: Rich markup injection must not crash the turn -------------------------


def _render(renderable) -> str:
    """Renders a Rich renderable to a plain string, raising MarkupError if the
    renderable (or its content) gets parsed as console markup and is malformed."""
    console = Console(file=None, width=80, record=True, force_terminal=False)
    console.print(renderable)
    return console.export_text()


@pytest.mark.parametrize(
    "dangerous",
    [
        "grep hit: [/etc/hosts]",
        "model said [/] then stopped",
        "[/bold]orphan close tag",
        "path [x/y] and [/etc/hosts] again",
    ],
)
def test_safe_text_does_not_raise_markup_error(dangerous):
    """safe_text() must render dangerous bracket content without raising MarkupError —
    this is the fix for tool_end/tool_start/subagent/system/error panels in both UIs."""
    # Proves the danger is real: raw string through Panel() DOES raise.
    with pytest.raises(MarkupError):
        _render(Panel(dangerous))

    # The fix: wrapping in safe_text() (a plain, unparsed Text) must not raise.
    _render(Panel(safe_text(dangerous)))


def test_safe_text_preserves_content():
    t = safe_text("[/etc/hosts] and other brackets [x]")
    assert t.plain == "[/etc/hosts] and other brackets [x]"


# --- Bug 5: slash-command arg parsing must not use str.replace --------------------


def test_parse_slash_command_splits_on_first_token():
    """str.replace('/test', '') would corrupt args that repeat the command token
    anywhere in the line — the parser must split on the first whitespace token."""
    cmd, args = parse_slash_command("/test some [bracket] arg")
    assert cmd == "test"
    assert args == "some [bracket] arg"


def test_parse_slash_command_replace_bug_reproduction():
    """Demonstrates the exact str.replace bug this parser replaces: a naive
    line.replace('/fix', '').strip() strips the token ANYWHERE in the line, not
    just the leading command, corrupting an arg that happens to contain it (e.g.
    a file path like 'src/fix_parser.py')."""
    line = "/fix src/fix_parser.py"
    buggy_args = line.replace("/fix", "").strip()
    assert buggy_args == "src_parser.py"  # corrupted: the embedded "/fix" got eaten too
    assert buggy_args != "src/fix_parser.py"

    _, correct_args = parse_slash_command(line)
    assert correct_args == "src/fix_parser.py"


def test_parse_slash_command_non_slash_line_is_not_a_command():
    """A plain prompt that happens to start with a command word ('fix this bug')
    must not be mistaken for the '/fix' slash command."""
    cmd, args = parse_slash_command("fix this bug please")
    assert cmd == ""


def test_parse_slash_command_empty_line():
    assert parse_slash_command("") == ("", "")
    assert parse_slash_command("/") == ("", "")


# --- Bug 2: shared definitions, not two hand-maintained copies --------------------


def test_slash_commands_defined_once_and_shared():
    assert cli.SLASH_COMMANDS is SLASH_COMMANDS
    assert tui.SLASH_COMMANDS is SLASH_COMMANDS


def test_expand_prompt_references_defined_once_and_shared():
    assert cli.expand_prompt_references is expand_prompt_references
    assert tui.expand_prompt_references is expand_prompt_references


def test_format_user_display_defined_once_and_shared():
    from agent.ui_common import format_user_display

    assert cli.format_user_display is format_user_display
    assert tui.format_user_display is format_user_display


def test_expand_prompt_references_resolves_file(tmp_path):
    """Sanity check the shared helper still does its job after extraction: routes
    through indexer.resolve_file (the guarded lookup) and injects the content."""
    from agent.tools.indexer import CodebaseIndexer

    (tmp_path / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    indexer = CodebaseIndexer(workspace_root=str(tmp_path))
    indexer.index_workspace()

    result = expand_prompt_references("look at @hello.py", indexer)
    assert "hello.py" in result
    assert "print('hi')" in result


# --- Bug 4: TUI must never auto-approve hard-stops (structural check) -------------


def test_tui_never_passes_none_or_auto_true_confirm_callback():
    """AgentLoop's own default falls back to a real (blocking) confirm when given
    None — but the TUI used to defeat that by passing a lambda that always returns
    True. That auto-approve function must be gone from the module, and the TUI app
    must wire a real bound-method confirm callback in __init__."""
    source = inspect.getsource(tui)
    assert "_noop_confirm" not in source, (
        "tui.py must not define an unconditional auto-approve confirm callback"
    )
    assert "self.agent.confirm_callback = self._tui_confirm_callback" in source, (
        "AgnosticTUI must always wire a real human-prompting confirm callback"
    )


def test_tui_confirm_callback_blocks_until_answered():
    """Focused unit test on the extracted confirm logic (a full Textual harness is
    impractical here — see test above for the App-wiring check). Simulates the
    worker-thread/UI-thread handshake without a running Textual event loop."""
    import threading

    class FakeTUI:
        _tui_confirm_callback = tui.AgnosticTUI._tui_confirm_callback

        def __init__(self):
            self._confirm_event = threading.Event()
            self._confirm_response = False
            self._awaiting_confirm = False
            self.written = []

        def call_from_thread(self, fn, *a, **kw):
            fn(*a, **kw)

        def _write_output(self, *a, **kw):
            self.written.append((a, kw))

    fake = FakeTUI()
    result_holder = {}

    def worker():
        result_holder["approved"] = fake._tui_confirm_callback("dangerous command")

    t = threading.Thread(target=worker)
    t.start()
    # Wait for the callback to actually block and post the prompt.
    for _ in range(200):
        if fake._awaiting_confirm:
            break
        threading.Event().wait(0.01)
    assert fake._awaiting_confirm is True
    assert fake.written  # the hard-stop panel was posted

    # Simulate the human answering "n" in the input box.
    fake._confirm_response = False
    fake._confirm_event.set()
    t.join(timeout=2)
    assert result_holder["approved"] is False


# --- Bug 3: expensive slash commands run in background workers (structural) ------


# Call names whose implementations hit the network, shell out, spawn a subagent
# (i.e. an LLM round-trip), or walk the whole workspace. None of them may run on
# the Textual UI thread — they must be handed to a background worker.
EXPENSIVE_WORK = frozenset(
    {
        "quick_fix",  # AutoTestRunner: subprocess + agent turns
        "auto_repair_loop",  # AutoTestRunner: subprocess + agent turns
        "format_report",  # ModelDoctor.inspect(): httpx GET, 4s timeout
        "scan_and_harvest",  # harvester: reads transcript files off disk
        "generate_mermaid_map",  # ArchitectureDiagrammer: os.walk of the workspace
        "spawn",  # subagent dispatch => LLM call
        "dispatch_swarm",  # 3 parallel subagents
        "generate_pr_summary",  # git + LLM
        "chat_completion",  # direct LLM call
        "subprocess",  # shells out
        "_handle_commit",  # git + LLM
    }
)
DISPATCHERS = frozenset({"_dispatch_background", "_run_agent_turn"})


def _slash_command_branches():
    """Parses agent/tui.py and yields (commands, names) for every branch of the
    if/elif chain in AgnosticTUI._handle_slash_command: the slash commands the
    branch matches, and every identifier its body (nested functions included)
    references."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(tui.__file__).read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_handle_slash_command"
    )
    node = next(s for s in fn.body if isinstance(s, ast.If))
    while node is not None:
        commands = {
            c.value.lstrip("/")
            for c in ast.walk(node.test)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        }
        names = set()
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
                elif isinstance(sub, ast.Attribute):
                    names.add(sub.attr)
        yield commands, names
        node = (
            node.orelse[0] if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If) else None
        )


def test_expensive_commands_dispatch_to_background_workers():
    """Every slash command whose body does network/subprocess/LLM/workspace-walk
    work must hand it to _dispatch_background or _run_agent_turn. The old version
    of this test only counted '@work(thread=True' occurrences in the module, which
    passed happily while /doctor (httpx GET) and /harvest (disk scan) still ran
    inline on the UI thread."""
    source = inspect.getsource(tui)
    assert source.count("@work(thread=True") >= 2
    assert "_run_background" in source
    assert "_dispatch_background" in source

    branches = list(_slash_command_branches())
    all_commands = set().union(*(cmds for cmds, _ in branches))
    assert len(branches) >= 20, f"parsed only {len(branches)} slash-command branches"
    assert {"doctor", "harvest", "fix", "test", "swarm", "diagram"} <= all_commands, (
        f"branch parser missed known commands; found {sorted(all_commands)}"
    )

    checked, inline = [], []
    for commands, names in branches:
        work = names & EXPENSIVE_WORK
        if not work:
            continue
        checked.append(sorted(commands))
        if not (names & DISPATCHERS):
            inline.append((sorted(commands), sorted(work)))

    assert len(checked) >= 8, f"only {len(checked)} expensive branches found: {checked}"
    assert not inline, (
        f"{len(inline)} of {len(checked)} expensive slash commands run inline on the "
        f"UI thread instead of a background worker: {inline}"
    )


# --- Bug 6: Ctrl+C must not falsely clear the busy flag mid-turn ------------------


def test_ctrl_c_does_not_clear_busy_flag_mid_turn():
    """action_quit_safe used to set self._agent_busy = False while a turn was still
    running in its worker thread, letting a second overlapping turn start on the
    same agent.history. It must leave the flag alone while busy."""
    source = inspect.getsource(tui.AgnosticTUI.action_quit_safe)
    assert "_agent_busy = False" not in source


# --- Bug 7: the TUI output callback must be wired for EVERY worker, not just turns ---


def _make_tui(agent):
    return tui.AgnosticTUI(
        agent=agent,
        code_indexer_inst=None,
        detected_model="test-model",
        doctor=None,
        test_runner=None,
    )


def test_output_callback_is_wired_once_in_init():
    """/fix, /test, /schedule and /loop never go through _run_agent_turn, so a
    callback swapped in only for the duration of that worker threw their agent
    output away. The callback must be bound in __init__ and stay bound."""
    from types import SimpleNamespace

    agent = SimpleNamespace(confirm_callback=None, output_callback=None, history=[])
    app = _make_tui(agent)
    assert agent.output_callback == app._output_callback


def test_run_agent_turn_does_not_swap_the_output_callback():
    """The swap/restore pair must be gone — restoring it at the end of a turn
    re-installs the no-op callback for every non-turn worker."""
    turn_src = inspect.getsource(tui.AgnosticTUI._run_agent_turn)
    assert "output_callback" not in turn_src, (
        "_run_agent_turn must not swap/restore agent.output_callback"
    )


# --- Bug 8: --legacy must not be re-parsed by the legacy CLI ----------------------


def test_legacy_flag_is_stripped_before_delegating_to_the_cli(monkeypatch):
    """`agnostic --legacy` used to call agent.cli.main() with no arguments, which
    re-parsed sys.argv and died with 'unrecognized arguments: --legacy'."""
    import sys

    import agent.cli as cli_mod

    seen = {}

    def fake_main(argv=None):
        seen["argv"] = argv

    monkeypatch.setattr(cli_mod, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["agnostic", "--legacy", "--model", "foo"])

    tui.main()
    assert seen["argv"] == ["--model", "foo"]


# --- Bug 9: a failed web companion must not be reported as a success -------------


def test_web_companion_does_not_open_a_browser_when_it_failed_to_start(monkeypatch):
    import webbrowser

    from agent.ui_common import maybe_start_web_companion
    from agent.web import server as web

    opened = []
    monkeypatch.setattr(web, "start_companion_server", lambda port: (False, "port in use"))
    monkeypatch.setattr(web.companion_telemetry, "bind_agent", lambda a: None)
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))

    ok, msg = maybe_start_web_companion(object(), open_browser=True)
    assert ok is False
    assert msg == "port in use"
    assert opened == [], f"browser was opened for a server that never started: {opened}"


def test_web_slash_command_reports_the_failure_instead_of_claiming_success():
    src = inspect.getsource(tui.AgnosticTUI._handle_slash_command)
    assert "Companion server is active at" not in src, (
        "/web must not claim the server is active when start returned ok=False"
    )
    assert "Companion server failed to start" in src


# --- Version is single-sourced from agent.__version__ ------------------------------


def test_version_flag_prints_the_package_version(capsys):
    from agent import __version__
    from agent.ui_common import build_arg_parser

    with pytest.raises(SystemExit) as exc:
        build_arg_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_banners_do_not_hardcode_a_version_string():
    from agent import __version__

    for mod in (cli, tui):
        src = inspect.getsource(mod)
        assert f"v{__version__} (" not in src, (
            f"{mod.__name__} still hardcodes the version in its banner"
        )
    assert "__version__" in inspect.getsource(cli.print_banner)
    assert "__version__" in inspect.getsource(tui.AgnosticTUI._print_banner)


# --- Every advertised slash command is dispatched by at least one UI ---------------

# /help, /exit and /clear are matched by literal-string branches inside the loops.
_SPECIAL_CASED = {"/help", "/exit", "/clear"}


def _handles(src: str, cmd: str) -> bool:
    name = cmd.lstrip("/")
    return f'"{cmd}"' in src or f'cmd == "{name}"' in src


def test_every_slash_command_has_a_dispatch_branch():
    cli_src = inspect.getsource(cli)
    tui_src = inspect.getsource(tui)
    missing = [
        c
        for c in SLASH_COMMANDS
        if c not in _SPECIAL_CASED and not (_handles(cli_src, c) or _handles(tui_src, c))
    ]
    assert not missing, f"advertised but unhandled slash commands: {missing}"


def test_tui_handles_multiline_instead_of_sending_it_to_the_model():
    src = inspect.getsource(tui.AgnosticTUI._handle_slash_command)
    assert _handles(src, "/multiline"), "/multiline falls through to the LLM in the TUI"
