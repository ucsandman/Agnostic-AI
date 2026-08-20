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
    assert fake.confirm_mode is True, "the input box must show that it wants a y/n answer"

    # Simulate the human answering "n" in the input box.
    fake._confirm_response = False
    fake._confirm_event.set()
    t.join(timeout=2)
    assert result_holder["approved"] is False
    assert fake.confirm_mode is False, "the prompt must be restored once the human answered"


def test_parse_confirm_answer_denies_but_flags_an_unrecognized_answer():
    """A typed prompt submitted while a hard-stop confirmation is pending used to be
    swallowed as a silent denial. It must still deny — but say so, so the caller can
    put the text back in the input box."""
    from agent.ui_common import parse_confirm_answer

    assert parse_confirm_answer("y") == (True, False)
    assert parse_confirm_answer("YES") == (True, False)
    assert parse_confirm_answer("n") == (False, False)
    assert parse_confirm_answer(" No ") == (False, False)
    assert parse_confirm_answer("write a test for parse_slash_command") == (False, True)


def test_unrecognized_confirm_answer_is_echoed_back_into_the_input():
    src = inspect.getsource(tui.AgnosticTUI.on_input_submitted)
    assert "parse_confirm_answer" in src
    assert "event.input.value = user_input" in src, (
        "a non-y/n answer must be restored to the input box, not discarded"
    )


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
