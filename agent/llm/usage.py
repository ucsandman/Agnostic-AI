"""
agent/llm/usage.py — Usage / Cost / Latency Memory (.agnostic/usage.jsonl)

Pure stdlib. Records one JSON object per LLM call and answers the two questions
the UI asks: "what has this cost me today?" and "how slow is that model?".

Integration contract (the sequential UI phase wires these; this module never
imports agent.tui*):

    from agent.llm.usage import UsageLog, format_model_stats

    usage = UsageLog(workspace_root)            # <workspace>/.agnostic/usage.jsonl

    # --- agent/llm/client.py, around LLMClient.chat_completion -------------
    t0 = time.monotonic()
    try:
        response = ...                          # the real call
    except Exception as e:
        usage.record_response(preset_key, self.config, None,
                              time.monotonic() - t0, ok=False, error=str(e))
        raise
    usage.record_response(preset_key, self.config, response,
                          time.monotonic() - t0)

    `record_response(preset_key, config, response, latency_s, ok=True, error=None)`
    is the ONLY hook needed: it reads config.provider / .model / .sub_model and
    pulls `response.usage.prompt_tokens` / `.completion_tokens` (attribute- or
    dict-shaped, missing `usage` tolerated -> zeros).

    # --- status bar --------------------------------------------------------
    usage.today_cost()                          -> float (known costs only)

    # --- /model table (availability column) --------------------------------
    summary = usage.summarize(days=1)
    format_model_stats(summary, model_id)       -> "p50 12.3s | $0.42 today"
    usage.last_latency(model_id)                -> float | None

Pricing lives in agent/llm/pricing.json (ships with every price null — the user
fills it in) and may be overridden per-user from ~/.agnostic/pricing.json.
Unknown price -> cost_usd is null and the summary carries a `cost_unknown` flag.
Subscription providers (`*-sub`) and `local` always cost 0.0.
"""

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

# Rotate at 5 MB, keeping exactly one previous generation (usage.jsonl.1).
# Module-level so tests can monkeypatch it down to a few bytes.
MAX_BYTES = 5 * 1024 * 1024

PRICING_PATH = Path(__file__).with_name("pricing.json")
USER_PRICING_PATH = Path.home() / ".agnostic" / "pricing.json"


# --- pricing --------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _models_of(path: Path) -> Dict[str, Dict[str, Any]]:
    """Model->entry mapping from a pricing file. Both {"models": {...}} and a
    bare {model: {...}} shape are accepted; anything unreadable reads as empty."""
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    models = data.get("models") if isinstance(data.get("models"), dict) else data
    return {str(m): e for m, e in models.items() if isinstance(e, dict)}


# The shipped table is a static repo asset, so the first successful read wins
# forever: re-reading it per call let one transient file lock (Windows indexer,
# an editor's atomic save) silently blank every price for that call.
_SHIPPED_PRICING: Optional[Dict[str, Dict[str, Any]]] = None


def load_pricing() -> Dict[str, Dict[str, Any]]:
    """Shipped pricing table, with ~/.agnostic/pricing.json merged over it.

    A user entry replaces the shipped entry for that model outright."""
    global _SHIPPED_PRICING
    if not _SHIPPED_PRICING:
        _SHIPPED_PRICING = _models_of(PRICING_PATH)
    table = dict(_SHIPPED_PRICING)
    table.update(_models_of(USER_PRICING_PATH))
    return table


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    """USD for one call, or None when this model has no price on file."""
    entry = load_pricing().get(model)
    if not entry:
        return None
    inp = entry.get("input_per_mtok")
    out = entry.get("output_per_mtok")
    if inp is None or out is None:
        return None
    try:
        return (prompt_tokens / 1_000_000) * float(inp) + (completion_tokens / 1_000_000) * float(
            out
        )
    except (TypeError, ValueError):
        return None


def cost_for(
    provider: str, model: str, prompt_tokens: int, completion_tokens: int
) -> Optional[float]:
    """Cost of one call. Subscriptions and local models are free by definition."""
    if provider.endswith("-sub") or provider == "local":
        return 0.0
    return estimate_cost(model, prompt_tokens, completion_tokens)


# --- helpers --------------------------------------------------------------


def model_key(provider: str, model: str, sub_model: Optional[str] = None) -> str:
    """Aggregation key: the model actually executed, scoped by provider."""
    return f"{provider}/{sub_model or model}"


def _field(obj: Any, name: str) -> Any:
    """Attribute or dict lookup — response objects come in both shapes."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _percentile(values: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile: p50 of [1,2,3,4] is 2, p95 of it is 4."""
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[min(idx, len(ordered) - 1)]


def _parse_ts(raw: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def _blank_bucket() -> Dict[str, Any]:
    return {
        "calls": 0,
        "errors": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_known_usd": 0.0,
        "cost_unknown": False,
        "latencies": [],
    }


def _add(bucket: Dict[str, Any], entry: Dict[str, Any]) -> None:
    bucket["calls"] += 1
    if not entry.get("ok", True):
        bucket["errors"] += 1
    bucket["prompt_tokens"] += _int(entry.get("prompt_tokens"))
    bucket["completion_tokens"] += _int(entry.get("completion_tokens"))
    bucket["total_tokens"] = bucket["prompt_tokens"] + bucket["completion_tokens"]
    cost = entry.get("cost_usd")
    if cost is None:
        bucket["cost_unknown"] = True
    else:
        bucket["cost_known_usd"] += float(cost)
    latency = entry.get("latency_s")
    if isinstance(latency, (int, float)):
        bucket["latencies"].append(float(latency))


def _finish(bucket: Dict[str, Any]) -> Dict[str, Any]:
    bucket["p50"] = _percentile(bucket["latencies"], 50)
    bucket["p95"] = _percentile(bucket["latencies"], 95)
    # cost_usd is the honest total: None as soon as one call had no price.
    bucket["cost_usd"] = None if bucket["cost_unknown"] else bucket["cost_known_usd"]
    return bucket


def _merge(buckets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not buckets:
        return None
    if len(buckets) == 1:
        return buckets[0]
    merged = _blank_bucket()
    for b in buckets:
        merged["calls"] += b["calls"]
        merged["errors"] += b["errors"]
        merged["prompt_tokens"] += b["prompt_tokens"]
        merged["completion_tokens"] += b["completion_tokens"]
        merged["cost_known_usd"] += b["cost_known_usd"]
        merged["cost_unknown"] = merged["cost_unknown"] or b["cost_unknown"]
        merged["latencies"].extend(b["latencies"])
    merged["total_tokens"] = merged["prompt_tokens"] + merged["completion_tokens"]
    return _finish(merged)


def format_model_stats(summary: Dict[str, Any], model: str) -> str:
    """Short availability-column string for the /model picker.

    "p50 12.3s | $0.42 today" when the price is known, "p50 12.3s | cost n/a"
    when it is not, "" when this model has no calls in the window. Assumes the
    summary came from summarize(days=1) — that is where "today" comes from."""
    models = summary.get("models") or {}
    matches = [
        bucket for key, bucket in models.items() if key == model or key.split("/", 1)[-1] == model
    ]
    bucket = _merge(matches)
    if not bucket:
        return ""
    p50 = bucket.get("p50")
    latency = f"p50 {p50:.1f}s" if p50 is not None else "p50 n/a"
    cost = bucket.get("cost_usd")
    money = "cost n/a" if cost is None else f"${cost:.2f} today"
    return f"{latency} | {money}"


# --- the log --------------------------------------------------------------


class UsageLog:
    """Append-only usage/cost/latency journal at <workspace>/.agnostic/usage.jsonl."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or ".").resolve()
        self.path = self.workspace_root / ".agnostic" / "usage.jsonl"

    # -- writing --

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.stat().st_size > MAX_BYTES:
                os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        except OSError:
            pass  # never let bookkeeping break a turn

    def record(
        self,
        preset_key: Optional[str],
        provider: str,
        model: str,
        sub_model: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_s: float = 0.0,
        ok: bool = True,
        error: Optional[str] = None,
        cost_usd: Any = "auto",
    ) -> Dict[str, Any]:
        """Append one call to the journal and return the entry that was written.

        cost_usd defaults to "auto" — priced from pricing.json / the provider."""
        prompt_tokens = _int(prompt_tokens)
        completion_tokens = _int(completion_tokens)
        if cost_usd == "auto":
            cost_usd = cost_for(provider, sub_model or model, prompt_tokens, completion_tokens)
        entry = {
            "ts": datetime.now().astimezone().isoformat(),
            "preset_key": preset_key,
            "provider": provider,
            "model": model,
            "sub_model": sub_model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_s": round(float(latency_s), 3),
            "cost_usd": cost_usd,
            "ok": bool(ok),
            "error": error,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                fh.flush()
        except OSError:
            pass  # a read-only workspace must not kill the turn
        return entry

    def record_response(
        self,
        preset_key: Optional[str],
        config: Any,
        response: Any,
        latency_s: float,
        ok: bool = True,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """The one-call hook for agent/llm/client.py.

        Reads provider/model/sub_model off an LLMConfig and token counts off an
        OpenAI-style response. A response with no `.usage` (subscription CLI
        bridge, streamed SimpleNamespace) records zero tokens rather than fail."""
        usage = _field(response, "usage") if response is not None else None
        return self.record(
            preset_key=preset_key,
            provider=str(_field(config, "provider") or ""),
            model=str(_field(config, "model") or ""),
            sub_model=_field(config, "sub_model"),
            prompt_tokens=_int(_field(usage, "prompt_tokens")),
            completion_tokens=_int(_field(usage, "completion_tokens")),
            latency_s=latency_s,
            ok=ok,
            error=error,
        )

    # -- reading --

    def entries(self) -> Iterator[Dict[str, Any]]:
        """Every well-formed entry, oldest first. Corrupt lines are skipped."""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(entry, dict):
                        yield entry
        except OSError:
            return

    def summarize(self, days: int = 1) -> Dict[str, Any]:
        """Aggregate the last `days` days by provider/model and by preset key.

        Returns {"since": iso, "models": {key: bucket}, "presets": {key: bucket},
        "totals": bucket}. Every bucket has calls, errors, p50, p95, token
        counts, cost_usd (None when any call had no price), cost_known_usd and
        cost_unknown."""
        since = datetime.now().astimezone() - timedelta(days=days)
        models: Dict[str, Dict[str, Any]] = {}
        presets: Dict[str, Dict[str, Any]] = {}
        totals = _blank_bucket()
        for entry in self.entries():
            ts = _parse_ts(entry.get("ts"))
            if ts is None or ts < since:
                continue
            key = model_key(
                str(entry.get("provider") or ""),
                str(entry.get("model") or ""),
                entry.get("sub_model"),
            )
            _add(models.setdefault(key, _blank_bucket()), entry)
            _add(presets.setdefault(str(entry.get("preset_key")), _blank_bucket()), entry)
            _add(totals, entry)
        return {
            "since": since.isoformat(),
            "models": {k: _finish(v) for k, v in models.items()},
            "presets": {k: _finish(v) for k, v in presets.items()},
            "totals": _finish(totals),
        }

    def today_cost(self) -> float:
        """Known spend since local midnight. Unpriced calls count as 0.0 —
        pair with summarize()['totals']['cost_unknown'] if you need the caveat."""
        today = datetime.now().astimezone().date()
        total = 0.0
        for entry in self.entries():
            ts = _parse_ts(entry.get("ts"))
            cost = entry.get("cost_usd")
            if ts is not None and ts.date() == today and cost is not None:
                total += float(cost)
        return total

    def last_latency(self, model: str) -> Optional[float]:
        """Latency of the most recent call to `model` (matches sub_model too)."""
        latest = None
        for entry in self.entries():
            key = model_key(
                str(entry.get("provider") or ""),
                str(entry.get("model") or ""),
                entry.get("sub_model"),
            )
            if model not in (key, key.split("/", 1)[-1]):
                continue
            latency = entry.get("latency_s")
            if isinstance(latency, (int, float)):
                latest = float(latency)
        return latest
