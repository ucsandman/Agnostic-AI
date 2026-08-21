"""
tests/test_usage_wiring.py — LLMClient → .agnostic/usage.jsonl, and its two readers.

agent/llm/usage.py itself is covered by tests/test_usage.py. This file only proves
the wiring: every chat_completion path writes exactly one entry (success, failure,
streaming, subscription bridge), the streaming path keeps the usage chunk that
arrives with an EMPTY choices list, and the two UI surfaces read the journal off
the render path.
"""

import inspect
import json
import time
from types import SimpleNamespace

import pytest

from agent.llm.client import LLMClient, LLMConfig, SubprocessSubscriptionBridge
from agent.ui_common import usage_segment


def _client(tmp_path, monkeypatch, **overrides):
    """A client whose UsageLog resolves into tmp_path (it resolves cwd at build)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(LLMClient, "_init_client", lambda self: None)
    cfg = LLMConfig(provider="openai", model="o4-mini", **overrides)
    cfg.retry_backoff = 0.0
    return LLMClient(cfg)


def _entries(tmp_path):
    path = tmp_path / ".agnostic" / "usage.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _response(prompt_tokens=7, completion_tokens=2):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


class FakeOpenAI:
    """Replays one scripted item per create() call; Exceptions are raised."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        # A real call takes time. Comfortably more than one tick of time.monotonic(),
        # which on Windows is GetTickCount64 at ~15.6ms — a 10ms fake call measures 0.
        time.sleep(0.05)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --- the journal ----------------------------------------------------------


def test_a_successful_call_appends_exactly_one_entry_with_a_real_latency(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.client = FakeOpenAI([_response()])

    c.chat_completion(messages=[{"role": "user", "content": "hi"}])

    entries = _entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["ok"] is True
    assert entries[0]["error"] is None
    assert entries[0]["latency_s"] > 0
    assert entries[0]["model"] == "o4-mini"
    assert (entries[0]["prompt_tokens"], entries[0]["completion_tokens"]) == (7, 2)


def test_a_failed_call_is_journalled_and_still_raises(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.client = FakeOpenAI([RuntimeError("endpoint said no")])

    with pytest.raises(RuntimeError):
        c.chat_completion(messages=[{"role": "user", "content": "hi"}])

    entries = _entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["ok"] is False
    assert entries[0]["error"]


def test_the_streaming_usage_chunk_survives_its_empty_choices_list(tmp_path, monkeypatch):
    """The regression the `if not chunk.choices: continue` guard causes: OpenAI-
    compatible servers ship the token counts in a chunk with NO choices."""
    c = _client(tmp_path, monkeypatch)
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="hello", tool_calls=None),
                    finish_reason=None,
                )
            ]
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        ),
    ]
    c.client = FakeOpenAI([iter(chunks)])

    res = c.chat_completion(messages=[{"role": "user", "content": "hi"}], stream=True)

    assert res.choices[0].message.content == "hello"
    assert c.client.calls[0]["stream_options"] == {"include_usage": True}
    entries = _entries(tmp_path)
    assert len(entries) == 1
    assert (entries[0]["prompt_tokens"], entries[0]["completion_tokens"]) == (10, 5)


def test_a_local_endpoint_is_never_sent_stream_options(tmp_path, monkeypatch):
    """LM Studio / Ollama builds reject unknown request fields outright."""
    c = _client(tmp_path, monkeypatch)
    c.config.provider = "local"
    c.client = FakeOpenAI([iter([])])

    c.chat_completion(messages=[{"role": "user", "content": "hi"}], stream=True)

    assert "stream_options" not in c.client.calls[0]


def test_the_subscription_bridge_path_is_journalled_too(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.config.provider = "anthropic-sub"
    monkeypatch.setattr(
        SubprocessSubscriptionBridge,
        "execute_turn",
        lambda **kw: SimpleNamespace(
            choices=[], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4)
        ),
    )

    c.chat_completion([{"role": "user", "content": "hi"}])

    entries = _entries(tmp_path)
    assert len(entries) == 1
    assert (entries[0]["prompt_tokens"], entries[0]["completion_tokens"]) == (3, 4)
    assert entries[0]["cost_usd"] == 0.0  # a subscription turn is free by definition


# --- the status-bar segment -----------------------------------------------


def test_usage_segment_shows_nothing_until_there_is_something_to_show():
    assert usage_segment({}, "o4-mini") == ("", "dim")
    assert usage_segment({"totals": {"calls": 0}}, "o4-mini") == ("", "dim")


def test_usage_segment_omits_the_money_half_for_an_unpriced_model():
    summary = {
        "totals": {"calls": 2, "cost_known_usd": 0.0, "cost_unknown": True},
        "models": {"openai/o4-mini": {"p50": 12.34, "cost_usd": None}},
    }
    text, style = usage_segment(summary, "o4-mini")
    assert text == "p50 12.3s"
    assert "$" not in text
    assert style == "dim"


def test_usage_segment_reports_cost_and_p50_when_both_are_known():
    summary = {
        "totals": {"calls": 2, "cost_known_usd": 0.42, "cost_unknown": False},
        "models": {"openai/o4-mini": {"p50": 12.34, "cost_usd": 0.42}},
    }
    assert usage_segment(summary, "o4-mini") == ("$ 0.42 - p50 12.3s", "dim")
    # No latency for this model in the window -> the p50 half is dropped, not faked.
    assert usage_segment(summary, "some-other-model")[0] == "$ 0.42"


# --- the readers ----------------------------------------------------------


def test_the_ui_reads_the_journal_off_the_render_path():
    from agent import tui, tui_model_picker

    picker = inspect.getsource(tui_model_picker.ModelPickerScreen._show_presets)
    assert "format_model_stats(" in picker
    assert picker.count("summarize(") == 1  # once for the list, not once per row

    bar = inspect.getsource(tui.AgnosticTUI._update_status_bar)
    assert "self._usage_fragment" in bar
    assert "summarize" not in bar
    assert "summarize(" in inspect.getsource(tui.AgnosticTUI._refresh_usage_bg)
