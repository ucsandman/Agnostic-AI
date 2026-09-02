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
import agent.tui_commands as tui_commands
from agent.ui_common import (
    SLASH_COMMANDS,
    expand_prompt_references,
    fold_summary,
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
            self.confirm_mode = None

        def _set_confirm_mode(self, on):
            self.confirm_mode = on

        def _post(self, fn, *a, **kw):
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
    assert fake.confirm_mode is True, "the input box must show that it wants a y/n answer"

    # Simulate the human answering "n" in the input box.
    fake._confirm_response = False
    fake._confirm_event.set()
    t.join(timeout=2)
    assert result_holder["approved"] is False
    assert fake.confirm_mode is False, "the prompt must be restored once the human answered"


def test_parse_confirm_answer_denies_but_flags_an_unrecognized_answer():
    """A typed prompt submitted while a hard-stop confirmation is pending must NOT
    read as an answer at all — the caller queues it. A verdict may carry a reason."""
    from agent.ui_common import parse_confirm_answer

    assert parse_confirm_answer("y") == (True, False, "")
    assert parse_confirm_answer("YES") == (True, False, "")
    assert parse_confirm_answer("n") == (False, False, "")
    assert parse_confirm_answer(" No ") == (False, False, "")
    assert parse_confirm_answer("n: too risky") == (False, False, "too risky")
    assert parse_confirm_answer("y run it, it is a scratch repo") == (
        True,
        False,
        "run it, it is a scratch repo",
    )
    assert parse_confirm_answer("write a test for parse_slash_command") == (False, True, "")
    assert parse_confirm_answer("now fix the parser") == (False, True, "")


def test_unrecognized_confirm_answer_is_queued_not_denied():
    """The old contract (echo the text back into the input box) is gone: an
    unrecognised submission is a prompt, it gets queued, and the confirm stays
    pending so the safety decision survives a mistimed keystroke."""
    src = inspect.getsource(tui.AgnosticTUI.on_input_submitted)
    assert "parse_confirm_answer" in src
    assert "event.input.value = user_input" not in src, (
        "a non-y/n answer must no longer be echoed back — it is queued as a prompt"
    )
    unrecognized_path = src.split("if unrecognized:", 1)[1].split("return", 1)[0]
    assert "self._prompt_queue.append(user_input)" in unrecognized_path
    assert "self._confirm_event.set()" not in unrecognized_path, (
        "a typo must never release the blocked worker"
    )


def test_typing_ahead_during_a_confirm_queues_instead_of_answering():
    import threading
    from types import SimpleNamespace

    app = _make_tui(
        SimpleNamespace(confirm_callback=None, output_callback=None, cancel_event=threading.Event())
    )
    # The app is never mounted here, so there is no #output-log / #queue-indicator.
    app._write_output = [].append
    app._update_queue_indicator = lambda: None
    app._awaiting_confirm = True
    app._confirm_event.clear()
    app.on_input_submitted(SimpleNamespace(value="now fix the parser", input=SimpleNamespace()))

    assert app._confirm_event.is_set() is False, "the worker must stay blocked"
    assert app._confirm_response is False
    assert list(app._prompt_queue) == ["now fix the parser"]


def test_esc_during_a_confirm_denies_so_the_worker_can_never_hang():
    import threading
    from types import SimpleNamespace

    app = _make_tui(
        SimpleNamespace(confirm_callback=None, output_callback=None, cancel_event=threading.Event())
    )
    app._write_output = [].append
    app._awaiting_confirm = True
    app._confirm_event.clear()
    app._confirm_reason = "stale"
    app.action_cancel_turn()

    assert app._confirm_event.is_set() is True
    assert app._confirm_response is False
    assert app._confirm_reason == ""
    assert app.agent.cancel_event.is_set() is False, "Esc denies the confirm, it does not cancel"


def test_confirm_reason_is_prepended_to_the_next_prompt_exactly_once():
    src = inspect.getsource(tui.AgnosticTUI._process_input)
    assert "Operator note on the last approval" in src
    assert 'self._confirm_reason = ""' in src, "the reason must be consumed, not replayed"


# --- Bug 3: expensive slash commands run in background workers (structural) ------


# Call names whose implementations hit the network, shell out, spawn a subagent
# (i.e. an LLM round-trip), or walk the whole workspace. None of them may run on
# the Textual UI thread — they must be handed to a background worker.
EXPENSIVE_WORK = frozenset(
    {
        "quick_fix",  # AutoTestRunner: subprocess + agent turns
        "auto_repair_loop",  # AutoTestRunner: subprocess + agent turns
        "format_report",  # ModelDoctor.inspect(): httpx GET, 4s timeout
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
    """Parses the module that defines AgnosticTUI._handle_slash_command
    (agent/tui_commands.py) and yields (commands, names) for every branch of
    its if/elif chain: the slash commands the branch matches, and every
    identifier its body (nested functions included) references."""
    import ast
    from pathlib import Path

    src_file = inspect.getsourcefile(tui.AgnosticTUI._handle_slash_command)
    tree = ast.parse(Path(src_file).read_text(encoding="utf-8"))
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


# --- One double-tap timer serves every destructive key (Ctrl+C, Ctrl+L) ----------


def test_double_tap_fires_only_on_the_second_press_and_then_resets():
    """One helper, one timer per name. A consumed double-tap must reset, or a third
    press would immediately count as another one."""
    import threading
    from types import SimpleNamespace

    app = _make_tui(
        SimpleNamespace(confirm_callback=None, output_callback=None, cancel_event=threading.Event())
    )
    assert app._double_tap("quit") is False
    assert app._double_tap("quit") is True
    assert app._double_tap("quit") is False
    # Independent timers: Ctrl+C then Ctrl+L is never a double-tap.
    assert app._double_tap("clear") is False
    # A zero window can never fire, however fast the presses arrive.
    for _ in range(5):
        assert app._double_tap("x", window=0.0) is False


def test_ctrl_c_cancels_the_turn_before_it_force_exits():
    src = inspect.getsource(tui.AgnosticTUI.action_quit_safe)
    assert "self.agent.cancel()" in src, "Ctrl+C while busy must cancel, not scold"
    assert "_double_tap" in src, "the second press is the escalation"
    assert "_double_tap" in inspect.getsource(tui.AgnosticTUI.action_clear_output), (
        "Ctrl+L must ask twice before clearing the log"
    )


# --- Shift+Tab cycles the trust tier, and the bar reads it live from the guard ---


def test_trust_cycle_walks_the_documented_order_and_wraps():
    """Shift+Tab must step strict → trust-reads → trust-tests → trust-all → strict,
    and the tier must live in SafetyGuard, never in a copy on the app."""
    import threading
    from types import SimpleNamespace

    from agent.governance.guard import guard

    guard.set_trust_tier("strict")
    app = _make_tui(
        SimpleNamespace(confirm_callback=None, output_callback=None, cancel_event=threading.Event())
    )
    # The app is never mounted here, so there is no #output-log to write to.
    written = []
    app._write_output = written.append
    app.action_cycle_trust()
    assert guard.get_trust_tier() == "trust-reads"
    assert "trust-reads" in written[-1].plain
    app.action_cycle_trust()
    assert guard.get_trust_tier() == "trust-tests"
    guard.set_trust_tier("trust-all")
    app.action_cycle_trust()
    assert guard.get_trust_tier() == "strict"


def test_trust_cycle_badge_is_read_from_the_guard_and_never_cached():
    """The Codex #33702 failure class: a cached label drifts from the policy the
    guard actually enforces. The status bar must re-read it on every repaint."""
    assert "get_trust_tier()" in inspect.getsource(tui.AgnosticTUI._update_status_bar)
    assert "self._trust" not in inspect.getsource(tui), (
        "the trust tier must never be stored on the app"
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
    monkeypatch.setattr(web, "start_companion_server", lambda _port: (False, "port in use"))
    monkeypatch.setattr(web.companion_telemetry, "bind_agent", lambda a: None)
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))

    ok, msg = maybe_start_web_companion(object(), open_browser=True)
    assert ok is False
    assert msg == "port in use"
    assert opened == [], f"browser was opened for a server that never started: {opened}"


def test_harvest_shells_out_to_the_one_node_harvester_in_both_uis():
    """There used to be two harvesters: engine/harvest/harvest.cjs and a 45-line
    Python one whose ~/.gemini path could never match its own filename guard. Both
    UIs must drive the node engine, like /distill does."""
    for mod in (cli, tui, tui_commands):
        src = inspect.getsource(mod)
        if mod is not tui:  # tui.py delegates its /commands to tui_commands.py
            assert "engine/harvest/harvest.cjs" in src, f"{mod.__name__} does not run the harvester"
        assert "governance.harvester" not in src, f"{mod.__name__} still uses the dead harvester"

    with pytest.raises(ImportError):
        import agent.governance.harvester  # noqa: F401


def test_web_slash_command_reports_the_failure_instead_of_claiming_success():
    src = inspect.getsource(tui.AgnosticTUI._handle_slash_command)
    assert "Companion server is active at" not in src, (
        "/web must not claim the server is active when start returned ok=False"
    )
    assert "Companion server failed to start" in src


# --- Bug 10: the banner claimed a model even with the endpoint offline -----------


def test_endpoint_status_line_is_honest_when_offline():
    from agent.ui_common import endpoint_status_line

    text, style = endpoint_status_line(
        {"status": "offline", "base_url": "http://localhost:1234/v1"}, "local-model"
    )
    assert "offline" in text
    assert "http://localhost:1234/v1" in text
    assert "/doctor" in text, "the offline line must give a next step"
    assert "✓" not in text
    assert "yellow" in style


def test_endpoint_status_line_reports_the_connection_when_online():
    from agent.ui_common import endpoint_status_line

    text, style = endpoint_status_line({"status": "online", "base_url": "http://h:1/v1"}, "qwen-7b")
    assert "qwen-7b" in text
    assert "http://h:1/v1" in text
    assert "green" in style


def test_tui_banner_does_not_claim_a_model_when_the_endpoint_is_offline():
    """_print_banner printed a green '✓ Model: <name>' unconditionally — including
    for the literal default '--model local-model' against a dead endpoint."""
    src = inspect.getsource(tui.AgnosticTUI._print_banner)
    assert "✓ Model:" not in src, "the TUI banner still claims a model unconditionally"
    assert "_show_endpoint_status" in src
    assert "endpoint_status_line" in inspect.getsource(tui.AgnosticTUI._show_endpoint_status)


def test_both_uis_share_one_endpoint_status_render():
    assert "endpoint_status_line" in inspect.getsource(cli.main)


# --- /model in the TUI lists the presets instead of dead-ending -------------------


def test_model_preset_rows_marks_the_active_preset_and_reports_availability(monkeypatch):
    from agent.ui_common import model_preset_rows

    presets = {
        "sub-claude-code": {
            "name": "Claude Code (subscription)",
            "provider": "anthropic-sub",
            "model": "claude-code-subscription",
            "base_url": "subscription://definitely-not-a-real-cli",
            "default_effort": "high",
            "context_window": 200000,
        },
        "hosted": {
            "name": "Hosted model",
            "provider": "google",
            "model": "gemini-x",
            "api_key_env": "AGNOSTIC_TEST_KEY",
            "alt_api_key_envs": ["AGNOSTIC_TEST_ALT_KEY"],
            "default_effort": "low",
            "context_window": 1000000,
        },
        "local-lmstudio": {
            "name": "Local",
            "provider": "local",
            "model": "local-model",
            "default_effort": "low",
            "context_window": 32768,
        },
    }
    monkeypatch.delenv("AGNOSTIC_TEST_KEY", raising=False)
    monkeypatch.setenv("AGNOSTIC_TEST_ALT_KEY", "sk-x")

    rows = model_preset_rows(presets, active_model="local-model", local_online=True)
    assert [r[0] for r in rows] == ["1", "2", "3"]  # numbers match /model <n>
    assert [r[1] for r in rows] == ["", "", "●"]  # only the running model is marked
    assert rows[0][6] == "definitely-not-a-real-cli CLI not on PATH"
    assert rows[1][6] == "AGNOSTIC_TEST_ALT_KEY set"  # falls back to the alt env var
    assert rows[2][6] == "endpoint online"
    assert rows[1][4] == "1000k"

    offline = model_preset_rows(presets, active_model="", local_online=False)
    assert offline[2][6] == "endpoint offline"
    assert all(r[1] == "" for r in offline)


def test_tui_model_command_opens_the_interactive_picker_instead_of_deferring_to_the_legacy_cli():
    src = inspect.getsource(tui.AgnosticTUI._handle_slash_command)
    assert "Use the original CLI for the interactive model picker" not in src
    assert "ModelPickerScreen" in src
    assert "parse_model_args" in src


# --- The TUI input has prompt history, shared with the legacy CLI -----------------


def test_prompt_history_ring_walks_and_persists(tmp_path):
    from agent.ui_common import PromptHistoryRing

    path = tmp_path / "agent_history.txt"
    ring = PromptHistoryRing(path)
    assert ring.prev() is None  # nothing recorded yet

    ring.append("first")
    ring.append("second")
    ring.append("second")  # a repeat of the last entry is not stored twice
    ring.append("   ")  # blank input is not history
    assert ring.entries == ["first", "second"]

    assert ring.prev() == "second"
    assert ring.prev() == "first"
    assert ring.prev() is None  # nothing older
    assert ring.next() == "second"
    assert ring.next() == ""  # back at the live line
    assert ring.next() is None

    ring.append("third")  # submitting resets the walk to the live line
    assert ring.prev() == "third"

    assert PromptHistoryRing(path).entries == ["first", "second", "third"]


def test_prompt_history_is_written_in_the_legacy_cli_format(tmp_path):
    """Both shells read ~/.agnostic/agent_history.txt, so the TUI must append in the
    prompt_toolkit FileHistory format the legacy CLI parses."""
    from prompt_toolkit.history import FileHistory

    from agent.ui_common import PromptHistoryRing

    path = tmp_path / "agent_history.txt"
    PromptHistoryRing(path).append("/test tests/test_ui_common.py")
    assert list(FileHistory(str(path)).load_history_strings()) == ["/test tests/test_ui_common.py"]


def test_tui_binds_up_and_down_to_prompt_history():
    keys = {b.key for b in tui.AgnosticTUI.BINDINGS}
    assert {"up", "down"} <= keys, f"no history bindings on the TUI input: {sorted(keys)}"


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


# --- /help is rendered from SLASH_COMMANDS, and the doc lists the same commands ---


def _documented_commands():
    """Every /command in a backticked span of docs/slash-commands.md."""
    import re
    from pathlib import Path

    doc = (Path(tui.__file__).parents[1] / "docs" / "slash-commands.md").read_text(encoding="utf-8")
    first_tokens = (span.split()[0] for span in re.findall(r"`([^`]+)`", doc) if span.split())
    return {t for t in first_tokens if re.fullmatch(r"/[a-z][a-z-]*", t)}


def test_documented_commands_and_the_table_are_the_same_set():
    """The table, both /help screens and the doc drifted apart three ways. /help now
    renders from the table; this keeps the doc in the same set."""
    documented = _documented_commands()
    table = set(SLASH_COMMANDS)
    assert documented - table == set(), "documented but missing from SLASH_COMMANDS"
    assert table - documented == set(), "in SLASH_COMMANDS but undocumented"


def test_both_help_screens_render_from_the_table():
    from agent.ui_common import help_text

    body = help_text()
    for cmd, hint in SLASH_COMMANDS.items():
        assert cmd in body and hint in body
    for mod in (cli, tui_commands):
        assert "help_text()" in inspect.getsource(mod), (
            f"{mod.__name__} still hand-maintains its own /help text"
        )


# --- Tab completion for @file / #symbol tokens (README promised it) ----------------


def test_complete_token_ranks_prefix_matches_before_substring_matches():
    from agent.ui_common import complete_token

    candidates = ["agent/ui_common.py", "common.py", "tests/test_ui_common.py", "COMMON_NOTES.md"]
    assert complete_token("common", candidates) == [
        "common.py",  # prefix match, case-insensitive
        "COMMON_NOTES.md",
        "agent/ui_common.py",  # substring matches keep source order after those
        "tests/test_ui_common.py",
    ]


def test_complete_token_is_capped_and_matches_everything_for_an_empty_token():
    from agent.ui_common import complete_token

    candidates = ["f{}.py".format(i) for i in range(50)]
    assert complete_token("", candidates) == candidates[:8]
    assert len(complete_token("f1", candidates, limit=3)) == 3


def test_tab_binding_takes_priority_over_the_default_focus_next():
    """Textual's Screen binds Tab to focus_next and screen bindings are matched
    before the App's own, so pressing Tab moved focus to the output log and the
    completion action never ran at all (verified with a headless pilot)."""
    tab = next(b for b in tui.AgnosticTUI.BINDINGS if b.key == "tab")
    assert tab.priority is True, "Tab is swallowed by focus_next; completion never fires"


def test_tui_tab_completes_file_and_symbol_tokens():
    src = inspect.getsource(tui.AgnosticTUI)
    assert "_complete_reference" in src
    assert "get_all_symbols" in src and "get_indexed_files" in src, (
        "Tab completion must use the workspace index, as the README claims"
    )


# --- Streaming renders as ONE growing block per reply -----------------------------


def test_stream_tail_accumulates_chunks_and_clips_to_the_last_lines():
    from agent.ui_common import stream_tail

    assert stream_tail([]) == ""
    assert stream_tail(["Hel", "lo ", "world"]) == "Hello world"  # no separators added
    chunks = ["line{}\n".format(i) for i in range(20)]
    assert stream_tail(chunks, max_lines=3) == "line17\nline18\nline19"


def test_streaming_updates_one_block_instead_of_relabelling_every_flush():
    """_flush_stream used to drain the buffer into the log every 8 tokens, so one
    reply arrived as a dozen '🛡️ Agnostic Agent:' fragments."""
    flush_src = inspect.getsource(tui.AgnosticTUI._flush_stream)
    assert "_set_stream_view" in flush_src
    assert "_post_output" not in flush_src, "streaming must not append to the log per flush"
    end_src = inspect.getsource(tui.AgnosticTUI._end_stream)
    assert "_set_stream_view" in end_src and "Panel" in end_src, (
        "the finished reply must replace the live block with one panel"
    )


# --- The endpoint probe must not block the first frame ----------------------------


def test_tui_probes_the_endpoint_on_a_worker_not_before_the_app_starts():
    """detect_model() is a 4s-timeout httpx GET; main() used to run it before
    App.run(), so a dead endpoint delayed the whole UI."""
    assert "detect_model(" not in inspect.getsource(tui.main)
    assert '@work(thread=True, group="detector")' in inspect.getsource(tui)
    assert "doctor.inspect()" in inspect.getsource(tui.AgnosticTUI._detect_model_bg)
    assert "_detect_model_bg" in inspect.getsource(tui.AgnosticTUI.on_mount)


def test_tui_banner_shows_the_probing_state_until_the_endpoint_answers():
    src = inspect.getsource(tui.AgnosticTUI._show_endpoint_status)
    assert "endpoint_status_line" in src
    assert "probing" in src, "an unprobed endpoint must not be rendered as offline"


# --- /model: argument parsing and the interactive picker ---------------------------


def test_parse_model_args_accepts_number_sub_model_and_effort_in_any_order():
    from agent.ui_common import parse_model_args
    from agent.llm.client import LLMConfig

    keys = list(LLMConfig.PRESETS)
    assert parse_model_args(["2", "claude-fable-5", "high"], LLMConfig.PRESETS) == (
        keys[1],
        "claude-fable-5",
        "high",
        None,
    )
    assert parse_model_args(["sub-claude-code", "HIGH", "fable"], LLMConfig.PRESETS) == (
        "sub-claude-code",
        "fable",
        "high",
        None,
    )
    assert parse_model_args(["3", "low"], LLMConfig.PRESETS) == (keys[2], None, "low", None)
    assert parse_model_args(["99"], LLMConfig.PRESETS)[3].startswith("No preset #99")
    assert parse_model_args([], LLMConfig.PRESETS) == (None, None, None, None)


def test_model_picker_walks_preset_sub_model_and_effort_with_the_keyboard():
    import asyncio
    from textual.app import App
    from agent.llm.client import LLMConfig
    from agent.tui_model_picker import ModelPickerScreen

    keys = list(LLMConfig.PRESETS)
    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(ModelPickerScreen("claude-code-subscription"), callback=results.append)

    async def drive(keys_to_press):
        results.clear()
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            for k in keys_to_press:
                await pilot.press(k)
                await pilot.pause()

    # Active preset is highlighted; Enter on sub-claude-code -> sub-model list -> pick
    # the 2nd model with Space; claude CLI ignores effort so it finishes there.
    asyncio.run(drive(["enter", "down", "down", "space"]))
    sub = LLMConfig.sub_models("sub-claude-code")
    assert results == [("sub-claude-code", sub[1], None)]

    # Esc on the first step cancels; on a later step it goes back.
    asyncio.run(drive(["escape"]))
    assert results == [None]
    asyncio.run(drive(["enter", "escape", "escape"]))
    assert results == [None]

    # Antigravity subscription: sub-model then effort (agy takes --effort).
    asyncio.run(drive(["up", "enter", "enter", "down", "enter"]))  # medium (default) -> high
    assert results == [(keys[0], None, "high")]

    # Number 4 (an API-key Gemini preset) skips the sub-model step, asks effort.
    asyncio.run(drive(["down", "down", "enter", "enter"]))
    assert results == [(keys[3], None, LLMConfig.PRESETS[keys[3]]["default_effort"])]


# --- The live busy indicator: elapsed clock + per-turn verb + the interrupt key ---


def test_busy_indicator_formats_the_clock_and_always_names_the_interrupt_key():
    """'is it hung?' is what makes people kill a session. The fragment must always
    carry an elapsed clock AND the key that stops it."""
    from agent.ui_common import busy_indicator

    assert busy_indicator(0, "X").endswith("esc to cancel")
    assert busy_indicator(47, "X").endswith("esc to cancel")
    assert "47s" in busy_indicator(47, "X")
    assert "1m05s" in busy_indicator(65, "X")
    assert "0s" in busy_indicator(-3.0, "X")  # a clock that never runs backwards


def test_busy_indicator_is_pure_so_a_repaint_cannot_flicker():
    """The 1s tick re-renders the same (elapsed, verb) many times — it must be the
    same string every time, not a re-rolled verb or a wall-clock read."""
    from agent.ui_common import busy_indicator

    assert busy_indicator(12.7, "Noodling") == busy_indicator(12.7, "Noodling")


def test_busy_indicator_is_byte_identical_after_the_clock_extraction():
    """The '{s}s' / '{m}m{s:02d}s' two-liner moved into ui_common._clock so the
    turn-done toast could reuse it. The status bar must not have shifted by a byte:
    these are the exact strings busy_indicator produced before that extraction."""
    from agent.ui_common import busy_indicator

    frozen = {
        (0, "Percolating"): "∴ Percolating… 0s · esc to cancel",
        (9.9, "Noodling"): "∴ Noodling… 9s · esc to cancel",
        (59, "Noodling"): "∴ Noodling… 59s · esc to cancel",
        (60, "Noodling"): "∴ Noodling… 1m00s · esc to cancel",
        (65, "X"): "∴ X… 1m05s · esc to cancel",
        (134.6, "Wrangling"): "∴ Wrangling… 2m14s · esc to cancel",
        (3600, "X"): "∴ X… 60m00s · esc to cancel",
        (-3.0, "X"): "∴ X… 0s · esc to cancel",
    }
    for (elapsed, verb), expected in frozen.items():
        assert busy_indicator(elapsed, verb) == expected


def test_busy_indicator_verb_pool_honours_the_env_override():
    from agent.ui_common import BUSY_VERBS, busy_verbs

    assert busy_verbs({"AGNOSTIC_SPINNER_VERBS": "a, b"}) == ("a", "b")
    # An override that parses to nothing must never leave random.choice an empty pool.
    assert busy_verbs({"AGNOSTIC_SPINNER_VERBS": " , "}) == BUSY_VERBS
    assert busy_verbs({}) == BUSY_VERBS


def test_mark_busy_is_the_single_place_the_busy_flag_is_set():
    """Three call sites used to flip _agent_busy by hand, so any new one silently
    skipped the clock/verb. _mark_busy() owns the transition."""
    assert "_agent_busy = True" in inspect.getsource(tui.AgnosticTUI._mark_busy)
    assert inspect.getsource(tui).count("_agent_busy = True") == 1
    assert "_agent_busy = True" not in inspect.getsource(tui_commands)


def test_mark_busy_starts_a_monotonic_clock_and_picks_one_verb_per_turn():
    import threading
    from types import SimpleNamespace
    from agent.ui_common import busy_verbs

    agent = SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        history=[],
        cancel_event=threading.Event(),
    )
    app = _make_tui(agent)
    assert app._busy_started == 0.0 and not app._agent_busy
    app._mark_busy()
    assert app._agent_busy is True
    assert app._busy_started > 0.0
    assert app._busy_verb in busy_verbs()
    # The verb is chosen per turn, not per tick: a repaint must not re-roll it.
    verb = app._busy_verb
    app._tick_busy()
    assert app._busy_verb == verb


# --- Context gauge, the one-shot nudge, and an undoable /compact ------------------


def test_context_segment_colours_the_bar_and_never_jitters():
    from agent.ui_common import context_segment

    text, style = context_segment(
        {"percentage": 31.0, "used_tokens": 620000, "max_tokens": 2000000}
    )
    assert "31%" in text, text
    assert "620k/2.0M" in text, text
    assert style == "green"

    widths = set()
    for pct, expected in ((5.0, "green"), (70.0, "yellow"), (95.0, "red")):
        seg, seg_style = context_segment(
            {"percentage": pct, "used_tokens": 620000, "max_tokens": 2000000}
        )
        assert seg_style == expected, (pct, seg)
        widths.add(len(seg))
    # A segment that changes width shifts everything after it on every repaint.
    assert len(widths) == 1, f"the status bar jitters as context fills: {widths}"

    # The real default is 2M tokens, so most sessions render an empty bar — it must
    # still be a full-width bar, not a crash or a stub.
    empty, _ = context_segment({"percentage": 0.04, "used_tokens": 843, "max_tokens": 2000000})
    assert "░" * 10 in empty and "█" not in empty
    assert "843/2.0M" in empty


def test_context_segment_and_the_nudge_are_wired_into_the_status_bar():
    src = inspect.getsource(tui.AgnosticTUI._update_status_bar)
    assert "context_segment(st)" in src
    assert "📊" not in src, "the old jittering token fragment is gone"
    assert 'st["near_limit"]' in src and "self._ctx_warned = True" in src
    assert "/compact undo" in src, "the nudge must name the exact remediation"
    # Re-armed in exactly two places: a manual /compact and an auto-compaction.
    assert "self._ctx_warned = False" in inspect.getsource(tui.AgnosticTUI._output_callback)
    assert "self._ctx_warned = False" in inspect.getsource(tui_commands)


def test_compact_undo_restores_the_pre_compaction_history():
    """/compact stashes the history, shows what the distillation kept, and
    '/compact undo' puts the original messages back."""
    from types import SimpleNamespace

    class FakeTUI:
        _handle_slash_command = tui_commands.SlashCommandMixin._handle_slash_command

        def __init__(self, agent):
            self.agent = agent
            self.written = []
            self._ctx_warned = True
            self._pre_compact_history = None

        def _write_output(self, *args, **kwargs):
            self.written.append(args[0])

    def plain(written):
        return "\n".join(
            r.renderable.plain if isinstance(r, Panel) else getattr(r, "plain", str(r))
            for r in written
        )

    history = [{"role": "system", "content": "You are an autonomous AI coding agent."}]
    history += [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} on agent/tui.py"}
        for i in range(9)
    ]
    app = FakeTUI(SimpleNamespace(history=list(history)))

    assert app._handle_slash_command("/compact") is True
    assert len(app.agent.history) < len(history), "nothing was compacted"
    assert "Session Distillation" in plain(app.written)
    assert app._ctx_warned is False, "a compaction re-arms the one-shot nudge"

    app.written.clear()
    assert app._handle_slash_command("/compact undo") is True
    assert app.agent.history == history
    assert "Restored 10 pre-compaction messages" in plain(app.written)

    # The stash is consumed once — a second undo has nothing to restore.
    app.written.clear()
    assert app._handle_slash_command("/compact undo") is True
    assert "Nothing to undo" in plain(app.written)


# --- `!cmd`: a local shell escape that costs zero context ------------------------


def _pilot_tui(agent, monkeypatch):
    """A mountable AgnosticTUI for `async with app.run_test()` pilot tests.

    A non-empty `detection` is what stops on_mount from launching _detect_model_bg,
    which would AttributeError on doctor=None inside a worker thread."""
    from types import SimpleNamespace

    monkeypatch.setattr(tui, "index_workspace", lambda: None)
    return tui.AgnosticTUI(
        agent=agent,
        code_indexer_inst=SimpleNamespace(get_all_symbols=list, get_indexed_files=list),
        detected_model="test-model",
        doctor=None,
        test_runner=None,
        detection={"status": "offline", "base_url": "http://x/v1"},
    )


def test_bang_prefix_runs_the_command_without_spending_a_turn(monkeypatch):
    """`!echo hi` must go through the registry's run_command (so the guard and the
    hard-stop confirm still apply) and must not touch the model or the history."""
    import asyncio
    import threading
    from types import SimpleNamespace

    calls = []
    turns = []

    def execute(name, args, confirm_callback=None):
        calls.append((name, args))
        return SimpleNamespace(output="hello-from-bang", is_error=False)

    agent = SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        history=[],
        cancel_event=threading.Event(),
        registry=SimpleNamespace(execute=execute),
        run_turn=turns.append,
    )
    app = _pilot_tui(agent, monkeypatch)

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#prompt-input").value = "!echo hi"
            await pilot.press("enter")
            for _ in range(200):
                await pilot.pause()
                if calls and not app._agent_busy:
                    break
                await asyncio.sleep(0.02)

    asyncio.run(drive())

    assert calls == [("run_command", {"command": "echo hi"})]
    assert turns == [], "a shell escape must never spend an LLM turn"
    assert agent.history == [], "a shell escape must cost zero context"


def test_bare_bang_is_not_a_shell_escape():
    """'!' alone (or '! ') falls through to the model — a silent no-op would be worse."""
    src = inspect.getsource(tui.AgnosticTUI._process_input)
    assert 'user_input.startswith("!") and user_input[1:].strip()' in src
    # And it must hand off to a worker like every other shell-outing branch does.
    assert "_dispatch_background" in src


def test_bang_runs_through_the_tool_registry_not_a_raw_subprocess():
    """core/safety/guards.json stays the single policy source: the UI layer must not
    grow its own Popen path around it."""
    src = inspect.getsource(tui.AgnosticTUI._run_bang)
    assert 'execute(\n            "run_command"' in src or 'execute("run_command"' in src
    assert "confirm_callback" in src
    assert "subprocess.run" not in src and "Popen" not in src


# --- Winner 7: folded tool cards say what they hid, and Ctrl+O gives it back -------


def test_fold_summary_keeps_short_output_whole():
    """Nothing under the limit is folded, and nothing is reported as hidden."""
    assert fold_summary("x" * 100) == ("x" * 100, 0)
    assert fold_summary("", 600) == ("", 0)


def test_fold_summary_clips_on_a_line_boundary_and_counts_what_it_hid():
    """A card must never end mid-line, and the count is what makes the fold honest."""
    clipped, hidden = fold_summary("line\n" * 100, limit=20)
    assert clipped.endswith("line"), "clipped mid-line instead of at a newline"
    assert clipped == "line\nline\nline\nline"
    assert hidden == 98


def test_fold_summary_falls_back_to_a_hard_cut_when_there_is_no_newline():
    """One enormous single line (a minified bundle, a base64 blob) still gets folded."""
    clipped, hidden = fold_summary("y" * 1000, limit=600)
    assert clipped == "y" * 600
    assert hidden == 1


def test_ctrl_o_expands_the_output_the_tool_card_folded_away(monkeypatch):
    """The escape hatch ships with the fold: the marker at the tail of a long tool
    output is absent from the card and present after Ctrl+O."""
    import asyncio
    import threading
    from types import SimpleNamespace

    from rich.text import Text

    agent = SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        history=[],
        cancel_event=threading.Event(),
    )
    agent.cancel = agent.cancel_event.set  # AgentLoop.cancel() sets the same event
    app = _pilot_tui(agent, monkeypatch)

    writes = []

    def _plain(item) -> str:
        inner = getattr(item, "renderable", item)
        body = inner.plain if isinstance(inner, Text) else str(inner)
        return f"{getattr(item, 'title', '') or ''}\n{body}"

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            real = app._write_output
            app._write_output = lambda *a, **kw: (writes.append(a[0]), real(*a, **kw))[1]
            app._output_callback("tool_start", "run_command")
            app._output_callback("tool_end", "X" * 2000 + "TAIL-MARKER")
            await pilot.pause()
            folded = "\n".join(_plain(w) for w in writes)
            assert "TAIL-MARKER" not in folded, "the card printed the whole output"
            assert "run_command" in folded and "lines hidden — ctrl+o" in folded
            await pilot.press("ctrl+o")
            await pilot.pause()
            expanded = "\n".join(_plain(w) for w in writes)
            assert "TAIL-MARKER" in expanded, "ctrl+o did not give the full output back"

    asyncio.run(drive())


def test_expand_output_says_so_when_no_tool_has_run():
    """Ctrl+O on a fresh session explains itself instead of doing nothing."""
    src = inspect.getsource(tui.AgnosticTUI.action_expand_output)
    assert "No tool output captured yet." in src
    assert "self._tool_outputs[-1]" in src


def test_tool_card_title_is_a_plain_string_not_markup():
    """A tool name or path containing '[' would raise MarkupError on the border."""
    src = inspect.getsource(tui.AgnosticTUI._output_callback)
    assert "title=title" in src
    assert "[dim blue]⚙️ Tool Output[/dim blue]" not in src


# --- Winner 8: double-Esc rewind — pick a turn, then pick what to restore ---------


def test_rewind_picker_lists_turns_newest_first_then_asks_for_the_scope():
    """Two steps, one gesture: the turn, then files / conversation / both. Esc on the
    first step cancels outright — a rewind must never happen by accident."""
    import asyncio
    from textual.app import App
    from agent.tui_rewind import RewindScreen

    marks = [
        ("turn-1", "10:00:00", [{"role": "user", "content": "a"}]),
        ("turn-2", "10:01:00", [{"role": "user", "content": "b"}]),
    ]
    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(RewindScreen(list(marks)), callback=results.append)

    async def drive(keys_to_press):
        results.clear()
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            for k in keys_to_press:
                await pilot.press(k)
                await pilot.pause()

    # Newest first: the highlighted row is turn-2. Enter -> scope step, down -> the
    # second scope ('conversation'), Enter finishes.
    asyncio.run(drive(["enter", "down", "enter"]))
    assert results == [("turn-2", marks[1][2], "conversation")]

    asyncio.run(drive(["escape"]))
    assert results == [None]

    # The default scope is the file-only one, and Esc backs out of the scope step.
    asyncio.run(drive(["enter", "enter"]))
    assert results == [("turn-2", marks[1][2], "files")]
    asyncio.run(drive(["enter", "escape", "escape"]))
    assert results == [None]


def test_rewind_picker_with_no_turns_yet_dismisses_instead_of_hanging():
    """A fresh session has no marks: the picker says so and closes on any key."""
    import asyncio
    from textual.app import App
    from agent.tui_rewind import RewindScreen

    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(RewindScreen([]), callback=results.append)

    async def drive():
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(drive())
    assert results == [None]


def test_rewind_restores_the_files_without_touching_the_conversation(tmp_path, monkeypatch):
    """The 2-axis restore is the point: 'files' reverts the writes made since the
    turn and leaves agent.history exactly as it is."""
    import threading
    from types import SimpleNamespace

    from agent.governance.undo import UndoManager

    manager = UndoManager()
    monkeypatch.setattr(tui, "undo_manager", manager)

    target = tmp_path / "app.py"
    target.write_text("original\n", encoding="utf-8")
    manager.create_checkpoint("turn-1")
    target.write_text("wrecked\n", encoding="utf-8")
    manager.record_change(target, "original\n", "wrecked\n", "write")

    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    app = _make_tui(
        SimpleNamespace(
            confirm_callback=None,
            output_callback=None,
            history=list(history),
            cancel_event=threading.Event(),
        )
    )
    # The app is never mounted here, so there is no #output-log to write to.
    app._write_output = [].append
    app._apply_rewind(("turn-1", [], "files"))

    assert target.read_text(encoding="utf-8") == "original\n"
    assert len(app.agent.history) == len(history)


def test_rewind_copies_the_history_snapshot_instead_of_aliasing_it():
    """Restoring the conversation must not hand the live history the stored list —
    the next turn would then append into the mark itself."""
    import threading
    from types import SimpleNamespace

    snapshot = [{"role": "user", "content": "a"}]
    app = _make_tui(
        SimpleNamespace(
            confirm_callback=None,
            output_callback=None,
            history=[],
            cancel_event=threading.Event(),
        )
    )
    app._write_output = [].append
    app._apply_rewind(("turn-1", snapshot, "conversation"))
    assert app.agent.history == snapshot
    app.agent.history.append({"role": "user", "content": "next"})
    assert snapshot == [{"role": "user", "content": "a"}]


def test_esc_only_rewinds_when_idle_with_an_empty_input_and_pressed_twice():
    """Branch order is the whole safety story: confirm-deny, then cancel, then
    rewind — and the rewind reuses the one double-tap timer."""
    src = inspect.getsource(tui.AgnosticTUI.action_cancel_turn)
    assert src.index("_awaiting_confirm") < src.index("self.agent.cancel()")
    assert src.index("self.agent.cancel()") < src.index("_double_tap")
    assert 'self._double_tap("rewind", 0.8)' in src
    assert "inp.value.strip()" in src


def test_every_turn_is_checkpointed_by_mark_busy():
    """The file half and the conversation half are snapshotted at the same instant,
    off the single busy-entry point — not from a second hook of our own."""
    src = inspect.getsource(tui.AgnosticTUI._mark_busy)
    assert "undo_manager.create_checkpoint(name)" in src
    assert "self._turn_marks.append" in src
    # Never len(_turn_marks): the deque evicts, and the names would then collide.
    assert "len(self._turn_marks)" not in src


# --- Bare /session opens a resume picker instead of printing a flat list ---------


def test_session_picker_lists_saved_sessions_and_loads_the_chosen_one():
    """Newest first (list_sessions' own order), one keystroke to resume. Each row
    carries the turn count, the timestamp and any note, so the names need not be
    self-documenting."""
    import asyncio
    from textual.app import App
    from textual.widgets import OptionList

    from agent.tui_sessions import SessionPickerScreen

    sessions = [
        {"name": "alpha", "turn_count": 4, "saved_at": "2026-08-19 10:00", "notes": ""},
        {"name": "beta", "turn_count": 9, "saved_at": "2026-08-20 09:00", "notes": "wip"},
    ]
    results, labels = [], []

    class Host(App):
        def on_mount(self):
            self.push_screen(SessionPickerScreen(list(sessions)), callback=results.append)

    async def drive(keys_to_press):
        results.clear()
        labels.clear()
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            lst = app.screen.query_one("#picker-list", OptionList)
            labels.extend(str(lst.get_option_at_index(i).prompt) for i in range(lst.option_count))
            for k in keys_to_press:
                await pilot.press(k)
                await pilot.pause()

    asyncio.run(drive(["down", "enter"]))
    assert results == ["beta"]
    assert "9 turns" in labels[1] and "wip" in labels[1]
    assert "4 turns" in labels[0]

    asyncio.run(drive(["escape"]))
    assert results == [None]


def test_session_picker_with_nothing_saved_dismisses_instead_of_hanging():
    """An empty .agnostic/sessions must still close on a keypress."""
    import asyncio
    from textual.app import App

    from agent.tui_sessions import SessionPickerScreen

    results = []

    class Host(App):
        def on_mount(self):
            self.push_screen(SessionPickerScreen([]), callback=results.append)

    async def drive():
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(drive())
    assert results == [None]


def test_session_picker_never_opens_while_a_turn_is_running():
    """Replacing agent.history under a live worker is the hazard the rewind picker
    avoids too — the bare /session branch guards on _agent_busy before pushing."""
    src = inspect.getsource(tui_commands.SlashCommandMixin._handle_slash_command)
    branch = src[src.index('elif cmd == "session"') :]
    assert branch.index("self._agent_busy") < branch.index("SessionPickerScreen")


# --- The status bar must actually fit on a real terminal -------------------------


def test_status_bar_shows_the_busy_and_context_segments_at_100_columns(monkeypatch):
    """The bar is built as one long Text; at a fixed height of 1 everything past
    ~98 cells was cut off with no ellipsis — the context gauge, the queue count and
    the busy indicator, i.e. exactly the segments that say what the agent is doing.
    Asserted against the RENDERED strips, not the source Text."""
    import asyncio
    import threading
    import time
    from types import SimpleNamespace

    from textual.geometry import Region
    from textual.widgets import Static

    agent = SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        history=[{"role": "user", "content": "x" * 400}],
        cancel_event=threading.Event(),
        llm_client=SimpleNamespace(
            config=SimpleNamespace(
                model="qwen2.5-coder-32b-instruct", reasoning_effort="high", sub_model=None
            )
        ),
    )
    app = _pilot_tui(agent, monkeypatch)
    rendered = []

    async def drive():
        async with app.run_test(size=(100, 24)) as pilot:
            await pilot.pause()
            app._git_status = " | 🌿 master*"
            app._prompt_queue.append("later prompt")
            app._agent_busy = True
            app._busy_started = time.monotonic() - 5
            app._busy_verb = "Percolating"
            app._update_status_bar()
            await pilot.pause()
            bar = app.query_one("#status-bar", Static)
            strips = bar.render_lines(Region(0, 0, bar.size.width, bar.size.height))
            rendered.append("\n".join(s.text for s in strips))

    asyncio.run(drive())

    visible = rendered[0]
    assert "esc to cancel" in visible, "the busy indicator never reached the screen"
    assert "Percolating… 5s" in visible
    assert "CTX" in visible and "1 queued" in visible
    assert "🤖 qwen2.5-coder-32b-instruct" in visible


# --- Exiting must never leave a confirm-blocked worker parked forever ------------


def test_force_exit_releases_a_worker_blocked_on_a_hard_stop_confirm(monkeypatch):
    """Double-tap Ctrl+C during a GOVERNANCE HARD-STOP prompt: the worker thread is
    parked in _tui_confirm_callback's Event.wait(), and after self.exit() neither the
    input box nor Esc can ever set that Event again. Textual runs thread workers on
    the default ThreadPoolExecutor, whose atexit hook joins them with no timeout — a
    parked worker hangs the whole process at shutdown. Exit denies the pending
    confirm on the way out instead."""
    import asyncio
    import threading
    import time
    from types import SimpleNamespace

    agent = SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        history=[],
        cancel_event=threading.Event(),
    )
    agent.cancel = agent.cancel_event.set  # AgentLoop.cancel() sets the same event
    app = _pilot_tui(agent, monkeypatch)
    answers = []

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._agent_busy = True  # a turn is running: Ctrl+C takes the cancel branch
            app._busy_started = time.monotonic()
            app._busy_verb = "Percolating"
            # daemon: a regression must fail this test, not hang the whole suite.
            worker = threading.Thread(
                target=lambda: answers.append(app._tui_confirm_callback("rm -rf /")),
                daemon=True,
            )
            worker.start()
            for _ in range(200):
                await pilot.pause()
                if app._awaiting_confirm:
                    break
                await asyncio.sleep(0.01)
            assert app._awaiting_confirm, "the confirm prompt never came up"

            app.action_quit_safe()  # first press: cancel
            assert answers == [], "a cancel must not answer the confirm"
            app.action_quit_safe()  # second press within 1.5s: force-exit
            for _ in range(200):
                await pilot.pause()
                if answers:
                    break
                await asyncio.sleep(0.01)
        worker.join(timeout=5)
        assert not worker.is_alive(), "the worker is still parked in _confirm_event.wait()"

    asyncio.run(drive())

    assert answers == [False], "an exit is not an approval"


# --- Ctrl+C beats the composer's inherited copy-on-select binding ----------------


def test_ctrl_c_cancels_even_with_a_selection_in_the_composer(monkeypatch):
    """TextArea binds ctrl+c to copy. Without priority=True on the App binding the
    copy won whenever the prompt box held a selection, so Ctrl+C silently did
    nothing while a turn was running."""
    import asyncio
    import threading
    from types import SimpleNamespace
    from textual.widgets.text_area import Selection

    agent = SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        history=[],
        cancel_event=threading.Event(),
    )
    agent.cancel = agent.cancel_event.set  # AgentLoop.cancel() sets the same event
    app = _pilot_tui(agent, monkeypatch)

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            box = app.query_one("#prompt-input")
            box.value = "type-ahead while it thinks"
            box.selection = Selection((0, 0), (0, 9))
            box.focus()
            await pilot.pause()
            app._agent_busy = True  # a turn is running: Ctrl+C takes the cancel branch
            await pilot.press("ctrl+c")
            await pilot.pause()

    asyncio.run(drive())

    assert agent.cancel_event.is_set(), "Ctrl+C was swallowed by the composer's copy"


# --- /model never reads the usage journal on the UI thread ----------------------


def test_model_picker_uses_the_cached_summary_instead_of_reading_the_journal(monkeypatch):
    """summarize() walks the whole of .agnostic/usage.jsonl; on_mount runs on the UI
    thread, so the picker must use the summary _refresh_usage_bg already cached."""
    import asyncio
    from textual.app import App
    from agent.llm import usage as usage_mod
    from agent.tui_model_picker import ModelPickerScreen

    def boom(*a, **kw):
        raise AssertionError("the picker read the journal on the UI thread")

    monkeypatch.setattr(usage_mod.UsageLog, "summarize", boom)

    class Host(App):
        def on_mount(self):
            self.push_screen(ModelPickerScreen("claude-code-subscription", usage_summary={}))

    async def drive():
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert app.screen.query_one("#picker-list").option_count > 0

    asyncio.run(drive())


def test_tui_hands_its_cached_usage_summary_to_the_picker():
    src = inspect.getsource(tui.AgnosticTUI._handle_slash_command)
    assert "usage_summary=self._usage_summary" in src


# --- default preset pick (settings + availability) -------------------------


def test_pick_default_preset_prefers_saved_then_best_cli_then_api_key(monkeypatch, tmp_path):
    import shutil as shutil_mod

    from agent import ui_common
    from agent.llm.client import LLMConfig

    monkeypatch.setattr(ui_common, "settings_path", lambda: tmp_path / "settings.json")

    # Nothing installed, no keys -> stay on local (None).
    monkeypatch.setattr(shutil_mod, "which", lambda _cli: None)
    for env in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)
    assert ui_common.pick_default_preset(LLMConfig.PRESETS) is None

    # An API key set -> its preset.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    key, _, _ = ui_common.pick_default_preset(LLMConfig.PRESETS)
    assert LLMConfig.PRESETS[key]["api_key_env"] == "DEEPSEEK_API_KEY"

    # A subscription CLI on PATH beats an API key; claude outranks codex.
    monkeypatch.setattr(
        shutil_mod, "which", lambda cli: "/bin/" + cli if cli in ("claude", "codex") else None
    )
    assert ui_common.pick_default_preset(LLMConfig.PRESETS)[0] == "sub-claude-code"

    # The saved /model choice beats everything while its CLI is still there.
    ui_common.save_settings(preset="sub-openai-codex", sub_model="gpt-5.6-sol", effort="")
    assert ui_common.pick_default_preset(LLMConfig.PRESETS) == (
        "sub-openai-codex",
        "gpt-5.6-sol",
        None,
    )

    # ...but a saved preset whose CLI vanished falls through to the next best.
    monkeypatch.setattr(shutil_mod, "which", lambda cli: "/bin/claude" if cli == "claude" else None)
    assert ui_common.pick_default_preset(LLMConfig.PRESETS)[0] == "sub-claude-code"


def test_model_switch_is_persisted_for_next_startup():
    src = inspect.getsource(tui_commands.SlashCommandMixin._apply_model_pick)
    assert "save_settings(" in src


# --- composer: paste collapse + live slash hints ---------------------------


def test_slash_hints_menu_matches_and_hides():
    from agent.ui_common import slash_hints, SLASH_COMMANDS

    assert slash_hints("/mo") == [("/model", SLASH_COMMANDS["/model"])]
    assert [c for c, _ in slash_hints("/m")] == [c for c in SLASH_COMMANDS if c.startswith("/m")][
        :4
    ]
    assert len(slash_hints("/")) == 4, "a bare '/' shows the first few, capped"
    assert slash_hints("/model 2") == [], "arguments typed -> menu out of the way"
    assert slash_hints("hello") == []
    assert slash_hints("/te\nst") == []


def test_tall_paste_collapses_to_a_marker_and_expands_on_send(monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace

    from textual import events

    sent = []
    agent = SimpleNamespace(
        confirm_callback=None,
        output_callback=None,
        history=[],
        cancel_event=threading.Event(),
        run_turn=sent.append,
    )
    app = _pilot_tui(agent, monkeypatch)
    blob = "\n".join(f"line-{i}" for i in range(40))

    async def drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            box = app.query_one("#prompt-input")
            box.post_message(events.Paste(blob))
            await pilot.pause()
            await pilot.pause()
            # The composer shows one marker line, not 40 pasted lines.
            assert box.text == "[Pasted text #1 +40 lines]"
            assert box.document.line_count == 1
            # And what is sent is the real paste, not the marker.
            assert box.expand_pastes(box.text) == blob

    asyncio.run(drive())


def test_small_paste_stays_inline():
    from agent.tui_composer import PASTE_COLLAPSE_LINES, PromptArea

    area = PromptArea()
    assert PASTE_COLLAPSE_LINES >= 5
    # expand_pastes on text without markers is the identity.
    assert area.expand_pastes("just words") == "just words"
    # An unknown marker (typed by hand) stays literal instead of KeyError-ing.
    assert area.expand_pastes("[Pasted text #9 +100 lines]") == "[Pasted text #9 +100 lines]"
