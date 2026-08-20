"""
tests/test_loop_client.py — Regression Tests for Agent Loop, LLM Client & Compaction
Covers malformed tool arguments, orphaned tool-result compaction, truncated tool calls,
client retry/timeout, reasoning-effort passthrough, and the tool-step cap.
"""

import threading
from types import SimpleNamespace

import pytest

from agent.loop import AgentLoop
from agent.governance.context import ContextManager
from agent.llm.client import LLMClient, LLMConfig


# --- Test doubles ---------------------------------------------------------


class FakeRegistry:
    """Records every execute() call so tests can assert a tool never ran."""

    def __init__(self):
        self.calls = []

    def get_openai_tools(self):
        return []

    def execute(self, name, args, confirm_callback=None):
        self.calls.append((name, args))
        return SimpleNamespace(output=f"ran {name}", is_error=False)


class FakeLLMClient:
    """Replays a scripted list of responses, one per chat_completion() call."""

    def __init__(self, responses):
        self.responses = list(responses)

    def chat_completion(self, **kwargs):
        if not self.responses:
            return _response(content="done")
        return self.responses.pop(0)


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(content="", tool_calls=None, finish_reason="stop"):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)]
    )


def _bare_loop(llm_client, registry):
    """AgentLoop with no filesystem/network construction side effects."""
    loop = object.__new__(AgentLoop)
    loop.llm_client = llm_client
    loop.registry = registry
    loop.history = [{"role": "system", "content": "sys"}]
    loop.confirm_callback = lambda prompt: True
    loop.output_callback = lambda msg_type, content: None
    loop.turn_lock = threading.Lock()
    return loop


def _assert_no_orphan_tool_messages(messages):
    open_ids = set()
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            open_ids = {tc["id"] for tc in (m.get("tool_calls") or [])}
        elif role == "tool":
            assert m.get("tool_call_id") in open_ids, (
                f"orphaned tool message with no preceding assistant tool_calls: {m}"
            )
        else:
            open_ids = set()


# --- Compaction -----------------------------------------------------------


def _history_ending_in_parallel_tool_calls():
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first question about main.py"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                },
                {
                    "id": "call_b",
                    "type": "function",
                    "function": {"name": "grep_search", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "contents of a"},
        {"role": "tool", "tool_call_id": "call_b", "content": "contents of b"},
        {"role": "assistant", "content": "final answer"},
    ]


def test_compaction_never_orphans_parallel_tool_results():
    cm = ContextManager()
    compacted, did, _msg = cm.compact_messages(
        _history_ending_in_parallel_tool_calls(), force=True
    )
    assert did is True
    assert compacted[0]["role"] == "system"
    _assert_no_orphan_tool_messages(compacted)


def test_compaction_preserves_summary_plus_recent_structure():
    cm = ContextManager()
    original = _history_ending_in_parallel_tool_calls()
    compacted, did, _msg = cm.compact_messages(original, force=True)
    assert did is True
    # Distillation folded into the system message, tail retained verbatim.
    assert "[Session Distillation / Compacted History]" in compacted[0]["content"]
    assert compacted[-1] == original[-1]
    assert len(compacted) < len(original)


def test_compaction_leaves_plain_history_tail_intact():
    cm = ContextManager()
    plain = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
    ]
    compacted, did, _msg = cm.compact_messages(plain, force=True)
    assert did is True
    assert compacted[1:] == plain[-3:]


# --- Malformed tool-call arguments ---------------------------------------


def test_malformed_tool_args_are_not_executed():
    registry = FakeRegistry()
    llm = FakeLLMClient(
        [
            _response(
                tool_calls=[_tool_call("call_1", "read_file", '{"path": "a.py"')]
            ),
            _response(content="recovered"),
        ]
    )
    loop = _bare_loop(llm, registry)
    out = loop.run_turn("go", max_steps=5)

    assert registry.calls == [], "tool must not run with fabricated arguments"
    tool_msgs = [m for m in loop.history if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    assert "JSON" in tool_msgs[0]["content"]
    assert out == "recovered"


def test_malformed_tool_args_are_not_executed_in_parallel_batch():
    registry = FakeRegistry()
    llm = FakeLLMClient(
        [
            _response(
                tool_calls=[
                    _tool_call("call_1", "read_file", '{"path": "a.py"'),
                    _tool_call("call_2", "read_file", '{"path": "b.py"}'),
                ]
            ),
            _response(content="recovered"),
        ]
    )
    loop = _bare_loop(llm, registry)
    loop.run_turn("go", max_steps=5)

    assert [c[0] for c in registry.calls] == ["read_file"], (
        "only the well-formed parallel call may execute"
    )
    assert registry.calls[0][1] == {"path": "b.py"}
    bad = [m for m in loop.history if m.get("tool_call_id") == "call_1"][0]
    assert "JSON" in bad["content"]


def test_empty_tool_args_still_execute():
    registry = FakeRegistry()
    llm = FakeLLMClient(
        [
            _response(tool_calls=[_tool_call("call_1", "find_files", "")]),
            _response(content="ok"),
        ]
    )
    loop = _bare_loop(llm, registry)
    loop.run_turn("go", max_steps=5)
    assert registry.calls == [("find_files", {})]


# --- Truncated tool calls (finish_reason == "length") ---------------------


def test_truncated_tool_call_is_not_executed():
    registry = FakeRegistry()
    llm = FakeLLMClient(
        [
            _response(
                tool_calls=[
                    _tool_call("call_1", "write_file", '{"path": "a.py", "con')
                ],
                finish_reason="length",
            ),
            _response(content="recovered"),
        ]
    )
    loop = _bare_loop(llm, registry)
    loop.run_turn("go", max_steps=5)

    assert registry.calls == [], "truncated tool call must not execute"
    tool_msgs = [m for m in loop.history if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "truncated" in tool_msgs[0]["content"].lower()


# --- Tool step cap --------------------------------------------------------


def test_tool_step_cap_is_reported():
    registry = FakeRegistry()
    llm = FakeLLMClient(
        [
            _response(tool_calls=[_tool_call(f"call_{i}", "read_file", "{}")])
            for i in range(4)
        ]
    )
    seen = []
    loop = _bare_loop(llm, registry)
    loop.output_callback = lambda msg_type, content: seen.append((msg_type, content))
    out = loop.run_turn("go", max_steps=3)

    assert "maximum tool call limit" in out
    assert any("maximum tool call limit" in c for _t, c in seen), (
        "cap must be visible to the operator, not silent"
    )


# --- LLM client retry / timeout / effort ---------------------------------


class _Transient(Exception):
    status_code = 503


class FakeOpenAI:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(**overrides):
    cfg = LLMConfig(provider="openai", model="o4-mini", **overrides)
    cfg.retry_backoff = 0.0
    return LLMClient(cfg)


def test_client_retries_transient_then_succeeds():
    c = _client(max_retries=3)
    fake = FakeOpenAI([_Transient("503"), _Transient("503"), _response(content="ok")])
    c.client = fake
    res = c.chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert res.choices[0].message.content == "ok"
    assert len(fake.calls) == 3


def test_client_raises_clear_error_after_retries():
    c = _client(max_retries=2)
    fake = FakeOpenAI([_Transient("503"), _Transient("503")])
    c.client = fake
    with pytest.raises(RuntimeError) as exc:
        c.chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert "o4-mini" in str(exc.value)
    assert "2 attempt" in str(exc.value)
    assert len(fake.calls) == 2


def test_client_does_not_retry_non_transient():
    c = _client(max_retries=3)
    fake = FakeOpenAI([ValueError("invalid api key")])
    c.client = fake
    with pytest.raises(ValueError):
        c.chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert len(fake.calls) == 1


def test_client_sends_timeout_and_effort_for_supported_model():
    c = _client()
    c.config.reasoning_effort = "high"
    fake = FakeOpenAI([_response(content="ok")])
    c.client = fake
    c.chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert fake.calls[0]["reasoning_effort"] == "high"
    assert fake.calls[0]["timeout"] == c.config.timeout


@pytest.mark.parametrize(
    "preset_key", ["agy-pro-3.1", "agy-flash-3.6", "codex-gpt-5.6-sol", "codex-o3-pro"]
)
def test_reasoning_effort_reaches_api_for_supporting_presets(preset_key):
    preset = LLMConfig.PRESETS[preset_key]
    c = _client()
    c.config.provider = preset["provider"]
    c.config.model = preset["model"]
    c.config.reasoning_effort = "high"
    assert c.supports_reasoning_effort() is True
    fake = FakeOpenAI([_response(content="ok")])
    c.client = fake
    c.chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert fake.calls[0]["reasoning_effort"] == "high"


def test_unsupported_effort_is_not_sent_and_not_claimed(monkeypatch):
    # switch_model now refuses a preset whose key env is unset; this test is about
    # effort reporting, so give it a key regardless of the machine's env.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    c = _client()
    c.config.provider = "anthropic"
    c.config.model = "claude-opus-5"
    assert c.supports_reasoning_effort() is False
    fake = FakeOpenAI([_response(content="ok")])
    c.client = fake
    c.chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert "reasoning_effort" not in fake.calls[0]

    note = c.switch_model(preset_key="claude-opus-5")
    assert "not supported" in note.lower()


# --- Read-only tool set must come from the registry ----------------------


def test_parallel_batch_uses_registry_read_only_constant():
    from agent.tools.registry import READ_ONLY_TOOLS

    assert "get_outline" in READ_ONLY_TOOLS
    registry = FakeRegistry()
    llm = FakeLLMClient(
        [
            _response(
                tool_calls=[
                    _tool_call("call_1", "read_file", '{"file_path": "a.py"}'),
                    _tool_call("call_2", "get_outline", '{"file_path": "b.py"}'),
                ]
            ),
            _response(content="done"),
        ]
    )
    seen = []
    loop = _bare_loop(llm, registry)
    loop.output_callback = lambda msg_type, content: seen.append((msg_type, content))
    loop.run_turn("go", max_steps=5)

    assert {c[0] for c in registry.calls} == {"read_file", "get_outline"}
    assert any("[Parallel]" in c for t, c in seen if t == "tool_start"), (
        "a batch of registry read-only tools must run in parallel"
    )


# --- Turn lock / busy state ----------------------------------------------


def test_is_busy_is_true_during_turn_and_false_after():
    registry = FakeRegistry()
    loop = _bare_loop(None, registry)
    states = []

    class _Probe:
        def chat_completion(self, **_kwargs):
            states.append(loop.is_busy)
            return _response(content="done")

    loop.llm_client = _Probe()
    out = loop.run_turn("go", max_steps=2)

    assert out == "done"
    assert states == [True], "turn_lock must be held for the whole turn"
    assert loop.is_busy is False, "turn_lock must be released when the turn ends"


def test_turn_lock_is_released_after_an_error():
    registry = FakeRegistry()

    class _Boom:
        def chat_completion(self, **_kwargs):
            raise ValueError("endpoint exploded")

    loop = _bare_loop(_Boom(), registry)
    loop.run_turn("go", max_steps=2)
    assert loop.is_busy is False


# --- Subagent tool-argument parsing --------------------------------------


def test_subagent_malformed_tool_args_are_not_executed(tmp_path):
    from agent.tools.subagent import SubagentWorker

    registry = FakeRegistry()
    llm = FakeLLMClient(
        [
            _response(
                tool_calls=[_tool_call("call_1", "read_file", '{"file_path": "a.py"')]
            ),
            _response(content="recovered"),
        ]
    )
    worker = SubagentWorker(
        role="researcher",
        system_prompt="",
        client=llm,
        workspace_root=tmp_path,
    )
    worker.build_registry = lambda: registry
    out = worker.run_task("go", max_turns=3)

    assert registry.calls == [], "subagent must not run a tool with unparsable args"
    assert out == "recovered"


# --- Model switching must not silently reuse the previous provider key ---


def test_switch_model_refuses_when_api_key_env_is_missing(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    c = _client()
    c.config.api_key = "previous-provider-placeholder"
    msg = c.switch_model(preset_key="deepseek-v4-pro")

    assert "DEEPSEEK_API_KEY" in msg, msg
    assert c.config.model == "o4-mini", "must not switch without a usable key"
    assert c.config.provider == "openai"
    assert c.config.api_key is None, "the previous provider's key must be cleared"


def test_switch_model_succeeds_when_api_key_env_is_present(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder-value")
    c = _client()
    msg = c.switch_model(preset_key="deepseek-v4-pro")
    assert "DeepSeek V4-Pro" in msg
    assert c.config.model == "deepseek-v4-pro"
    assert c.config.api_key == "placeholder-value"


# --- Timeouts: slow endpoints must not be retried into a 6-minute wedge ---


class _FakeTimeout(Exception):
    """Stands in for openai.APITimeoutError (a read timeout)."""


class _FakeConnectionError(Exception):
    """Stands in for openai.APIConnectionError."""


def test_default_read_timeout_is_generous_for_local_models():
    assert LLMConfig().timeout == 300.0


def test_client_uses_bounded_connect_timeout():
    c = _client()
    assert c.client.timeout.connect == 10.0
    assert c.client.timeout.read == c.config.timeout


def test_client_does_not_retry_read_timeouts():
    c = _client(max_retries=3)
    fake = FakeOpenAI([_FakeTimeout("read timed out")])
    c.client = fake
    with pytest.raises(_FakeTimeout):
        c.chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert len(fake.calls) == 1, "a wedged endpoint must fail fast, not retry"


def test_client_still_retries_connection_errors():
    c = _client(max_retries=3)
    fake = FakeOpenAI([_FakeConnectionError("connection reset"), _response("ok")])
    c.client = fake
    res = c.chat_completion(messages=[{"role": "user", "content": "hi"}])
    assert res.choices[0].message.content == "ok"
    assert len(fake.calls) == 2


# --- Streaming aggregation ------------------------------------------------


def _chunk(content=None, tool_calls=None, finish_reason=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ]
    )


def _tc_delta(index, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeStreamingOpenAI:
    """Replays streaming chunks and records the request kwargs."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.chunks)


def test_streaming_aggregates_content_tool_calls_and_finish_reason():
    c = _client()
    fake = FakeStreamingOpenAI(
        [
            _chunk(content="Let me "),
            _chunk(content="look."),
            _chunk(
                tool_calls=[
                    _tc_delta(0, call_id="call_1", name="read_", arguments='{"file')
                ]
            ),
            _chunk(tool_calls=[_tc_delta(0, name="file", arguments='_path": "a.py"}')]),
            _chunk(finish_reason="tool_calls"),
        ]
    )
    c.client = fake
    streamed = []
    res = c.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        stream_callback=streamed.append,
    )

    assert fake.calls[0]["stream"] is True
    assert streamed == ["Let me ", "look."]
    msg = res.choices[0].message
    assert msg.content == "Let me look."
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].id == "call_1"
    assert msg.tool_calls[0].function.name == "read_file"
    assert msg.tool_calls[0].function.arguments == '{"file_path": "a.py"}'
    assert res.choices[0].finish_reason == "tool_calls"
