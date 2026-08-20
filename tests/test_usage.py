"""
tests/test_usage.py — Usage / Cost / Latency Journal (.agnostic/usage.jsonl)
Covers the record+summarize round trip with hand-checked p50/p95, unknown vs known
vs subscription pricing, size rotation, corrupt-line tolerance, the record_response
hook against OpenAI-style and usage-less responses, and the picker stat strings.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from agent.llm import usage as usage_mod
from agent.llm.usage import UsageLog, estimate_cost, format_model_stats, load_pricing


@pytest.fixture(autouse=True)
def no_user_pricing(tmp_path, monkeypatch):
    """A real ~/.agnostic/pricing.json on the dev box must not steer these tests."""
    monkeypatch.setattr(usage_mod, "USER_PRICING_PATH", tmp_path / "absent.json")


@pytest.fixture
def log(tmp_path):
    return UsageLog(str(tmp_path))


def _priced(monkeypatch, tmp_path, model, inp, out):
    """Point the user-override at a temp file that prices exactly one model."""
    path = tmp_path / "pricing.json"
    path.write_text(
        json.dumps(
            {
                "models": {
                    model: {
                        "input_per_mtok": inp,
                        "output_per_mtok": out,
                        "currency": "USD",
                        "source": "test",
                        "as_of": "2026-08-20",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(usage_mod, "USER_PRICING_PATH", path)


# --- record + summarize ---------------------------------------------------


def test_record_writes_one_json_object_per_call_with_the_documented_fields(log):
    log.record("codex-o4-mini", "openai", "o4-mini", prompt_tokens=10, completion_tokens=5)

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert set(entry) == {
        "ts",
        "preset_key",
        "provider",
        "model",
        "sub_model",
        "prompt_tokens",
        "completion_tokens",
        "latency_s",
        "cost_usd",
        "ok",
        "error",
    }
    assert entry["preset_key"] == "codex-o4-mini"
    assert entry["provider"] == "openai"
    assert entry["ok"] is True
    assert entry["error"] is None
    assert log.path.parent.name == ".agnostic"


def test_summarize_round_trip_with_hand_checked_percentiles(log):
    # Latencies 1,2,3,4 -> nearest rank p50 = element 2 of 4 = 2.0, p95 = 4.0
    for latency in (3.0, 1.0, 4.0, 2.0):
        log.record(
            "codex-o4-mini",
            "openai",
            "o4-mini",
            prompt_tokens=100,
            completion_tokens=50,
            latency_s=latency,
        )
    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=9.0, ok=False, error="boom")

    summary = log.summarize(days=1)
    bucket = summary["models"]["openai/o4-mini"]
    assert bucket["calls"] == 5
    assert bucket["errors"] == 1
    assert bucket["prompt_tokens"] == 400
    assert bucket["completion_tokens"] == 200
    assert bucket["total_tokens"] == 600
    # 5 latencies 1,2,3,4,9 -> p50 = ceil(2.5)=3rd = 3.0, p95 = ceil(4.75)=5th = 9.0
    assert bucket["p50"] == 3.0
    assert bucket["p95"] == 9.0
    assert summary["presets"]["codex-o4-mini"]["calls"] == 5
    assert summary["totals"]["calls"] == 5


def test_summarize_window_excludes_older_entries(log):
    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=1.0)
    old = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    old["ts"] = (datetime.now().astimezone() - timedelta(days=3)).isoformat()
    with open(log.path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(old) + "\n")

    assert log.summarize(days=1)["totals"]["calls"] == 1
    assert log.summarize(days=7)["totals"]["calls"] == 2


def test_sub_model_is_the_aggregation_key(log):
    log.record(
        "sub-claude-code",
        "anthropic-sub",
        "claude-code-subscription",
        sub_model="claude-fable-5",
        latency_s=2.0,
    )
    summary = log.summarize()
    assert "anthropic-sub/claude-fable-5" in summary["models"]


# --- pricing --------------------------------------------------------------


def test_unknown_pricing_yields_null_cost_and_the_unknown_flag(log):
    log.record(
        "claude-opus-5",
        "anthropic",
        "claude-opus-5",
        prompt_tokens=1000,
        completion_tokens=1000,
        latency_s=1.0,
    )

    entry = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["cost_usd"] is None

    bucket = log.summarize()["models"]["anthropic/claude-opus-5"]
    assert bucket["cost_unknown"] is True
    assert bucket["cost_usd"] is None
    assert bucket["cost_known_usd"] == 0.0


def test_shipped_pricing_covers_every_preset_model_with_null_prices():
    from agent.llm.client import LLMConfig

    table = load_pricing()
    for preset in LLMConfig.PRESETS.values():
        assert preset["model"] in table, preset["model"]
    api_models = [
        p["model"]
        for p in LLMConfig.PRESETS.values()
        if not p["provider"].endswith("-sub") and p["provider"] != "local"
    ]
    # Never ship an invented number: every real API model is explicitly unknown.
    assert all(table[m]["input_per_mtok"] is None for m in api_models)


def test_known_pricing_produces_a_real_cost(monkeypatch, tmp_path, log):
    _priced(monkeypatch, tmp_path, "o4-mini", 2.0, 8.0)

    assert estimate_cost("o4-mini", 1_000_000, 1_000_000) == pytest.approx(10.0)
    log.record(
        "codex-o4-mini",
        "openai",
        "o4-mini",
        prompt_tokens=500_000,
        completion_tokens=250_000,
        latency_s=1.0,
    )

    bucket = log.summarize()["models"]["openai/o4-mini"]
    assert bucket["cost_unknown"] is False
    assert bucket["cost_usd"] == pytest.approx(3.0)  # 0.5*2 + 0.25*8


def test_user_override_merges_over_the_shipped_table(monkeypatch, tmp_path):
    assert load_pricing()["claude-opus-5"]["input_per_mtok"] is None
    _priced(monkeypatch, tmp_path, "claude-opus-5", 15.0, 75.0)
    table = load_pricing()
    assert table["claude-opus-5"]["input_per_mtok"] == 15.0
    assert "o4-mini" in table  # shipped entries survive the merge


def test_a_transient_unreadable_shipped_table_does_not_blank_prices(monkeypatch, tmp_path):
    warm = load_pricing()  # first successful read is cached for good
    assert warm

    monkeypatch.setattr(usage_mod, "PRICING_PATH", tmp_path / "vanished.json")
    assert load_pricing() == warm


def test_one_unknown_call_poisons_the_total_but_keeps_the_subtotal(monkeypatch, tmp_path, log):
    _priced(monkeypatch, tmp_path, "o4-mini", 2.0, 0.0)
    log.record("codex-o4-mini", "openai", "o4-mini", prompt_tokens=1_000_000, latency_s=1.0)
    log.record("claude-opus-5", "anthropic", "claude-opus-5", prompt_tokens=10, latency_s=1.0)

    totals = log.summarize()["totals"]
    assert totals["cost_usd"] is None
    assert totals["cost_known_usd"] == pytest.approx(2.0)
    assert totals["cost_unknown"] is True


def test_subscription_and_local_are_always_free(log):
    log.record(
        "sub-claude-code",
        "anthropic-sub",
        "claude-code-subscription",
        sub_model="claude-fable-5",
        prompt_tokens=999_999,
        completion_tokens=999_999,
        latency_s=1.0,
    )
    log.record(
        "local-lmstudio",
        "local",
        "local-model",
        prompt_tokens=999_999,
        completion_tokens=999_999,
        latency_s=1.0,
    )

    costs = [
        json.loads(line)["cost_usd"] for line in log.path.read_text(encoding="utf-8").splitlines()
    ]
    assert costs == [0.0, 0.0]
    assert log.summarize()["totals"]["cost_unknown"] is False
    assert log.today_cost() == 0.0


def test_today_cost_sums_known_costs_only(monkeypatch, tmp_path, log):
    _priced(monkeypatch, tmp_path, "o4-mini", 4.0, 0.0)
    log.record("codex-o4-mini", "openai", "o4-mini", prompt_tokens=500_000, latency_s=1.0)
    log.record("claude-opus-5", "anthropic", "claude-opus-5", prompt_tokens=10, latency_s=1.0)

    assert log.today_cost() == pytest.approx(2.0)


# --- robustness -----------------------------------------------------------


def test_corrupt_lines_are_skipped_never_raised(log):
    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=1.0)
    with open(log.path, "a", encoding="utf-8") as fh:
        fh.write("{not json at all\n")
        fh.write("\n")
        fh.write('"a bare string"\n')
    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=2.0)

    assert len(list(log.entries())) == 2
    assert log.summarize()["totals"]["calls"] == 2
    assert log.last_latency("o4-mini") == 2.0


def test_missing_log_reads_as_empty(log):
    assert list(log.entries()) == []
    assert log.summarize()["totals"]["calls"] == 0
    assert log.today_cost() == 0.0
    assert log.last_latency("o4-mini") is None


def test_rotation_keeps_exactly_one_previous_generation(monkeypatch, log):
    rotated = log.path.with_name(log.path.name + ".1")

    monkeypatch.setattr(usage_mod, "MAX_BYTES", 10_000)
    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=1.0)
    assert not rotated.exists()  # under the threshold, nothing moves

    monkeypatch.setattr(usage_mod, "MAX_BYTES", 10)
    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=2.0)
    assert rotated.exists()
    assert json.loads(rotated.read_text(encoding="utf-8"))["latency_s"] == 1.0
    assert len(log.path.read_text(encoding="utf-8").splitlines()) == 1
    assert log.summarize()["totals"]["calls"] == 1  # only the live file is read

    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=3.0)
    assert json.loads(rotated.read_text(encoding="utf-8"))["latency_s"] == 2.0  # replaced
    assert not log.path.with_name(log.path.name + ".2").exists()  # only one kept


# --- the client.py hook ---------------------------------------------------


def _config(provider="openai", model="o4-mini", sub_model=None):
    return SimpleNamespace(provider=provider, model=model, sub_model=sub_model)


def test_record_response_extracts_openai_style_usage(log):
    response = SimpleNamespace(
        choices=[], usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=340)
    )
    entry = log.record_response("codex-o4-mini", _config(), response, 12.34)

    assert entry["prompt_tokens"] == 1200
    assert entry["completion_tokens"] == 340
    assert entry["latency_s"] == 12.34
    assert entry["ok"] is True
    assert log.summarize()["models"]["openai/o4-mini"]["calls"] == 1


def test_record_response_tolerates_a_response_without_usage(log):
    bridge_response = SimpleNamespace(choices=[SimpleNamespace(message=None)])
    entry = log.record_response(
        "sub-claude-code",
        _config("anthropic-sub", "claude-code-subscription", "claude-fable-5"),
        bridge_response,
        5.0,
    )

    assert entry["prompt_tokens"] == 0
    assert entry["completion_tokens"] == 0
    assert entry["sub_model"] == "claude-fable-5"
    assert entry["cost_usd"] == 0.0


def test_record_response_accepts_dict_usage_and_failures(log):
    entry = log.record_response(
        "codex-o4-mini", _config(), {"usage": {"prompt_tokens": 7, "completion_tokens": 3}}, 1.5
    )
    assert (entry["prompt_tokens"], entry["completion_tokens"]) == (7, 3)

    failed = log.record_response("codex-o4-mini", _config(), None, 0.5, ok=False, error="timeout")
    assert failed["ok"] is False
    assert failed["error"] == "timeout"
    assert log.summarize()["totals"]["errors"] == 1


# --- picker strings -------------------------------------------------------


def test_format_model_stats_known_cost(monkeypatch, tmp_path, log):
    _priced(monkeypatch, tmp_path, "o4-mini", 0.84, 0.0)
    log.record("codex-o4-mini", "openai", "o4-mini", prompt_tokens=500_000, latency_s=12.34)

    assert format_model_stats(log.summarize(days=1), "o4-mini") == "p50 12.3s | $0.42 today"


def test_format_model_stats_unknown_cost_and_missing_model(log):
    log.record("claude-opus-5", "anthropic", "claude-opus-5", latency_s=12.34)
    summary = log.summarize(days=1)

    assert format_model_stats(summary, "claude-opus-5") == "p50 12.3s | cost n/a"
    assert format_model_stats(summary, "anthropic/claude-opus-5") == "p50 12.3s | cost n/a"
    assert format_model_stats(summary, "never-called") == ""


def test_format_model_stats_merges_the_same_model_across_providers(log):
    log.record("claude-fable-5", "anthropic", "claude-fable-5", latency_s=1.0)
    log.record(
        "sub-claude-code",
        "anthropic-sub",
        "claude-code-subscription",
        sub_model="claude-fable-5",
        latency_s=3.0,
    )

    # Merged latencies [1.0, 3.0] -> nearest-rank p50 is the 1st of 2 = 1.0.
    # One provider prices it (unknown), the other is free -> the honest answer is n/a.
    assert format_model_stats(log.summarize(), "claude-fable-5") == "p50 1.0s | cost n/a"


def test_last_latency_returns_the_most_recent_call(log):
    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=1.0)
    log.record("codex-o4-mini", "openai", "o4-mini", latency_s=7.5)
    log.record("claude-opus-5", "anthropic", "claude-opus-5", latency_s=2.0)

    assert log.last_latency("o4-mini") == 7.5
    assert log.last_latency("openai/o4-mini") == 7.5
    assert log.last_latency("nobody") is None
