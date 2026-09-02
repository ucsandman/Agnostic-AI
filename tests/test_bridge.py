"""
tests/test_bridge.py — Subscription CLI bridge (agent/llm/client.py)
Covers multi-block tool-call parsing, per-CLI session continuity (claude
--session-id/--resume, codex exec resume), the resets that force a full
re-flatten, claude's --output-format json envelope and its fallback, and the
usage hint handed to the usage journal.
"""

import json
import subprocess
import uuid
from types import SimpleNamespace

import pytest

from agent.llm import client as client_mod
from agent.llm.client import BridgeSession, SubprocessSubscriptionBridge


# --- Test doubles ---------------------------------------------------------


class FakeStdin:
    """Captures what the bridge pipes to the CLI; on close, appends it to the
    recorded argv as a trailing `<stdin>` marker so prompt_of can find it."""

    def __init__(self, cmd):
        self._cmd = cmd
        self._data = []

    def write(self, s):
        self._data.append(s)

    def close(self):
        self._cmd.extend(["<stdin>", "".join(self._data)])


class FakeProc:
    """Popen stand-in: yields one canned stdout chunk, exits clean."""

    returncode = 0

    def __init__(self, output: str, cmd=None):
        self.stdout = iter([output])
        self.stdin = FakeStdin(cmd) if cmd is not None else None

    def communicate(self):
        return "", ""

    def kill(self):  # pragma: no cover - only a timeout would reach it
        pass


def fake_cli(monkeypatch, *outputs):
    """Patch subprocess.Popen to replay `outputs`; returns the recorded argv list."""
    seen = []
    queue = list(outputs)

    def fake_popen(cmd, **kwargs):
        seen.append(cmd)
        piped = kwargs.get("stdin") is subprocess.PIPE
        return FakeProc(queue.pop(0) if queue else "", cmd if piped else None)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return seen


def claude_json(result, session_id="sess-abc", **extra):
    payload = {"type": "result", "is_error": False, "result": result, "session_id": session_id}
    payload.update(extra)
    return json.dumps(payload)


def prompt_of(cmd):
    """The prompt a recorded invocation carried: piped stdin (claude/codex) or
    the argv positional (agy --print)."""
    if "<stdin>" in cmd:
        return cmd[cmd.index("<stdin>") + 1]
    if "--print" in cmd:
        return cmd[cmd.index("--print") + 1]
    return cmd[-1]


@pytest.fixture(autouse=True)
def _forget_codex_help():
    """The codex --help probe is process-cached; no test may inherit another's."""
    client_mod._codex_exec_help.cache_clear()
    yield
    client_mod._codex_exec_help.cache_clear()


# --- Tool-call parsing ----------------------------------------------------


def test_every_json_block_becomes_its_own_tool_call(monkeypatch):
    """Only the first ```json block used to survive: a CLI that batched a read
    and a grep silently lost the grep."""
    reply = (
        "I will look at both files.\n"
        '```json\n{"name": "read_file", "arguments": {"path": "a.py"}}\n```\n'
        "and then\n"
        '```json\n{"name": "grep_search", "arguments": {"pattern": "TODO"}}\n```\n'
        "Reporting back once those land."
    )
    fake_cli(monkeypatch, claude_json(reply))

    resp = SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub", [{"role": "user", "content": "hi"}]
    )
    calls = resp.choices[0].message.tool_calls

    assert [c.function.name for c in calls] == ["read_file", "grep_search"]
    assert json.loads(calls[1].function.arguments) == {"pattern": "TODO"}
    assert len({c.id for c in calls}) == 2, "tool call ids collided"
    assert all(c.id.startswith("call_sub_") for c in calls)


def test_prose_and_non_tool_json_blocks_are_not_tool_calls(monkeypatch):
    reply = (
        'Here is some config:\n```json\n{"just": "data"}\n```\n'
        "and a broken one:\n```json\n{not json\n```\nDone."
    )
    fake_cli(monkeypatch, claude_json(reply))

    resp = SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub", [{"role": "user", "content": "hi"}]
    )
    assert resp.choices[0].message.tool_calls is None
    assert resp.choices[0].message.content == reply


# --- claude session continuity -------------------------------------------


def test_claude_opens_a_session_then_resumes_with_only_the_new_messages(monkeypatch):
    seen = fake_cli(
        monkeypatch,
        claude_json("answer one", session_id="sess-abc"),
        claude_json("answer two", session_id="sess-abc"),
    )
    session = BridgeSession()
    history = [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "first question"},
    ]

    SubprocessSubscriptionBridge.execute_turn("anthropic-sub", history, session=session)

    first = seen[0]
    assert "--resume" not in first
    uuid.UUID(first[first.index("--session-id") + 1])  # raises if not a uuid4 string
    assert first[first.index("--output-format") + 1] == "json"
    assert "first question" in prompt_of(first)

    history = history + [
        {"role": "assistant", "content": "answer one"},
        {"role": "user", "content": "second question"},
    ]
    SubprocessSubscriptionBridge.execute_turn("anthropic-sub", history, session=session)

    second = seen[1]
    assert second[second.index("--resume") + 1] == "sess-abc"
    assert "--session-id" not in second
    body = prompt_of(second)
    assert "second question" in body
    assert "first question" not in body, "the resumed turn re-sent delivered history"
    assert "system rules" not in body


def test_a_shrunken_history_starts_a_fresh_session_and_re_flattens(monkeypatch):
    """/rewind and compaction both shorten the transcript — resuming there would
    leave the CLI holding messages the agent has thrown away."""
    seen = fake_cli(
        monkeypatch,
        claude_json("answer one", session_id="sess-abc"),
        claude_json("answer two", session_id="sess-def"),
    )
    session = BridgeSession()
    history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "answer one"},
        {"role": "user", "content": "second question"},
    ]
    SubprocessSubscriptionBridge.execute_turn("anthropic-sub", history, session=session)

    SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub", [{"role": "user", "content": "fresh start"}], session=session
    )

    second = seen[1]
    assert "--resume" not in second
    new_id = second[second.index("--session-id") + 1]
    assert new_id != seen[0][seen[0].index("--session-id") + 1]
    assert "fresh start" in prompt_of(second)


def test_rewritten_or_re_pinned_history_also_resets_the_session(monkeypatch):
    """Compaction can replace messages without shortening the list, and a /model
    switch changes which CLI session the id even belongs to."""
    seen = fake_cli(monkeypatch, *[claude_json("ok", session_id="sess-abc")] * 3)
    session = BridgeSession()
    history = [{"role": "user", "content": "first question"}]
    SubprocessSubscriptionBridge.execute_turn("anthropic-sub", history, session=session)

    compacted = [{"role": "user", "content": "[summary of earlier turns]"}]
    SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub", compacted + [{"role": "user", "content": "next"}], session=session
    )
    assert "--resume" not in seen[1], "a rewritten transcript was resumed anyway"

    SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub",
        compacted + [{"role": "user", "content": "next"}, {"role": "user", "content": "more"}],
        session=session,
        model="claude-opus-5",
    )
    assert "--resume" not in seen[2], "the session survived a sub-model change"


# --- claude --output-format json -----------------------------------------


def test_json_envelope_is_unwrapped_and_junk_falls_back_to_raw_text(monkeypatch):
    fake_cli(
        monkeypatch,
        "Loading config...\n" + claude_json("the real answer", session_id="sess-abc"),
        "not json at all, just a banner",
    )
    msgs = [{"role": "user", "content": "hi"}]

    good = SubprocessSubscriptionBridge.execute_turn("anthropic-sub", msgs)
    assert good.choices[0].message.content == "the real answer"

    junk = SubprocessSubscriptionBridge.execute_turn("anthropic-sub", msgs)
    assert junk.choices[0].message.content == "not json at all, just a banner"
    assert junk.usage is None


def test_subscription_cli_nonzero_and_error_envelopes_raise(monkeypatch):
    class FailedProc(FakeProc):
        returncode = 2

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda cmd, **kwargs: FailedProc("unsupported model", cmd),
    )
    with pytest.raises(RuntimeError, match="code 2.*unsupported model"):
        SubprocessSubscriptionBridge.execute_turn(
            "anthropic-sub", [{"role": "user", "content": "hi"}]
        )

    fake_cli(
        monkeypatch,
        json.dumps({"type": "result", "is_error": True, "result": "model unavailable"}),
    )
    with pytest.raises(RuntimeError, match="model unavailable"):
        SubprocessSubscriptionBridge.execute_turn(
            "anthropic-sub", [{"role": "user", "content": "hi"}]
        )


def test_json_mode_streams_the_parsed_answer_not_the_envelope(monkeypatch):
    fake_cli(monkeypatch, claude_json("the real answer"))
    chunks = []

    SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub", [{"role": "user", "content": "hi"}], stream_callback=chunks.append
    )
    assert chunks == ["the real answer"]


def test_usage_is_surfaced_for_the_usage_journal(monkeypatch):
    fake_cli(
        monkeypatch,
        claude_json(
            "done",
            usage={"input_tokens": 1200, "output_tokens": 340},
            total_cost_usd=0.021,
        ),
    )

    resp = SubprocessSubscriptionBridge.execute_turn(
        "anthropic-sub", [{"role": "user", "content": "hi"}]
    )
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens) == (1200, 340)
    assert resp.usage.total_tokens == 1540
    assert resp.usage.cost_usd == 0.021

    from agent.llm.usage import UsageLog

    assert UsageLog.record_response  # the hook this feeds


# --- codex / agy ----------------------------------------------------------


def _codex_help(monkeypatch, text):
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_kw: SimpleNamespace(stdout=text, stderr="")
    )


CODEX_SESSION = "019b1c2d-3e4f-5061-8293-a4b5c6d7e8f9"
CODEX_HEADER = f"OpenAI Codex\nsession id: {CODEX_SESSION}\n"


def test_codex_resumes_only_when_its_help_advertises_the_subcommand(monkeypatch):
    seen = fake_cli(monkeypatch, CODEX_HEADER + "answer one", "answer two")
    _codex_help(monkeypatch, "Usage: codex exec\n\nCommands:\n  resume  Resume a session\n")
    session = BridgeSession()
    history = [{"role": "user", "content": "first question"}]
    SubprocessSubscriptionBridge.execute_turn("openai-sub", history, session=session)
    assert seen[0][:2] == ["codex.cmd" if client_mod.os.name == "nt" else "codex", "exec"]

    SubprocessSubscriptionBridge.execute_turn(
        "openai-sub",
        history + [{"role": "user", "content": "second question"}],
        session=session,
    )
    assert seen[1][1:4] == ["exec", "resume", CODEX_SESSION]
    assert "first question" not in prompt_of(seen[1])


def test_an_old_codex_without_resume_keeps_the_full_flatten(monkeypatch):
    seen = fake_cli(monkeypatch, CODEX_HEADER + "answer one", "answer two")
    _codex_help(monkeypatch, "Usage: codex exec [OPTIONS] [PROMPT]\n")
    session = BridgeSession()
    history = [{"role": "user", "content": "first question"}]
    SubprocessSubscriptionBridge.execute_turn("openai-sub", history, session=session)
    SubprocessSubscriptionBridge.execute_turn(
        "openai-sub",
        history + [{"role": "user", "content": "second question"}],
        session=session,
    )

    assert "resume" not in seen[1]
    body = prompt_of(seen[1])
    assert "first question" in body and "second question" in body


def test_codex_gets_the_approval_flag_current_builds_actually_accept(monkeypatch):
    """`--dangerously-bypass-approvals` is `error: unexpected argument` on codex
    0.147 — openai-sub died before it ever read the prompt."""
    seen = fake_cli(monkeypatch, "ok")

    SubprocessSubscriptionBridge.execute_turn("openai-sub", [{"role": "user", "content": "hi"}])
    assert "--dangerously-bypass-approvals-and-sandbox" in seen[0]


def test_claude_and_codex_prompts_ride_stdin_never_argv(monkeypatch):
    """A real transcript exceeds Windows' 8,191-char cmd.exe argv limit, so a
    prompt in argv is 'The command line is too long' on the first big turn."""
    seen = fake_cli(monkeypatch, claude_json("ok"), "ok")
    big = "x" * 20_000

    SubprocessSubscriptionBridge.execute_turn("anthropic-sub", [{"role": "user", "content": big}])
    SubprocessSubscriptionBridge.execute_turn("openai-sub", [{"role": "user", "content": big}])

    for cmd in seen:
        marker = cmd.index("<stdin>")
        assert big in cmd[marker + 1]
        assert all(len(arg) < 8191 for arg in cmd[:marker]), "prompt leaked into argv"
    assert "-" in seen[1], "codex was not told to read stdin"


def test_agy_always_re_sends_the_whole_transcript(monkeypatch):
    """`agy --print` exposes no session flag, so there is nothing to resume."""
    seen = fake_cli(monkeypatch, "answer one", "answer two")
    session = BridgeSession()
    history = [{"role": "user", "content": "first question"}]
    SubprocessSubscriptionBridge.execute_turn("google-sub", history, session=session)
    SubprocessSubscriptionBridge.execute_turn(
        "google-sub",
        history + [{"role": "user", "content": "second question"}],
        session=session,
    )

    assert "--resume" not in seen[1]
    assert "first question" in prompt_of(seen[1])


def test_the_client_hands_its_own_session_to_the_bridge(monkeypatch):
    """Continuity is per LLMClient — chat_completion must pass its session in."""
    from agent.llm.client import LLMClient

    seen = {}

    def fake_turn(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(choices=[])

    monkeypatch.setattr(SubprocessSubscriptionBridge, "execute_turn", fake_turn)
    client = LLMClient()
    client.config.provider = "anthropic-sub"
    client.chat_completion([{"role": "user", "content": "hi"}])

    assert seen["session"] is client.bridge_session


def test_codex_receives_the_reasoning_effort_as_a_config_override(monkeypatch):
    """The status line used to say 'Effort: HIGH (not supported ... ignored)' for
    codex — but `codex exec -c model_reasoning_effort=...` has accepted it all along."""
    seen = fake_cli(monkeypatch, "ok")

    SubprocessSubscriptionBridge.execute_turn(
        "openai-sub", [{"role": "user", "content": "hi"}], reasoning_effort="high"
    )
    assert 'model_reasoning_effort="high"' in seen[0][seen[0].index("-c") + 1]
