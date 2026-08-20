# Usage, cost and latency

Every LLM call the agent makes is appended to `<workspace>/.agnostic/usage.jsonl`
by `agent/llm/usage.py`. That file is the only source for the spend shown in the
status bar and the latency column in `/model`. It is stdlib-only, workspace-local
and never leaves the machine.

## The journal

One JSON object per line, append-only:

```json
{"ts": "2026-08-20T16:14:02.913-04:00", "preset_key": "codex-o4-mini",
 "provider": "openai", "model": "o4-mini", "sub_model": null,
 "prompt_tokens": 1200, "completion_tokens": 340, "latency_s": 12.34,
 "cost_usd": null, "ok": true, "error": null}
```

- `cost_usd` is `null` when the model has no price on file (see below), `0.0`
  for subscription providers (`*-sub`) and `local`.
- `sub_model` is the concrete model a subscription CLI ran (`--model`), e.g.
  `claude-fable-5` under `sub-claude-code`. Aggregation keys on it.
- A failed call is still recorded, with `ok: false` and `error` set.
- The file rotates to `usage.jsonl.1` (exactly one generation kept) once it
  passes 5 MB. Corrupt lines are skipped, never raised — a half-written line
  after a crash costs you one record, not the log.

## Prices

`agent/llm/pricing.json` maps model id to
`{input_per_mtok, output_per_mtok, currency, source, as_of}`. **It ships with
every API model priced `null` on purpose** — a wrong price is worse than no
price. Until you fill it in, `cost_usd` is `null` and summaries report
`cost_unknown: true` alongside the subtotal they *do* know.

Fill in the numbers from your provider's pricing page (USD per 1,000,000
tokens), or keep them out of the repo entirely in `~/.agnostic/pricing.json` —
same shape, merged over the shipped table per model:

```json
{"models": {"claude-opus-5": {"input_per_mtok": 15.0, "output_per_mtok": 75.0,
                              "currency": "USD", "source": "anthropic.com/pricing",
                              "as_of": "2026-08-20"}}}
```

## API

```python
from agent.llm.usage import UsageLog, format_model_stats, estimate_cost, load_pricing

usage = UsageLog(workspace_root)
```

| Call | Returns |
|---|---|
| `record_response(preset_key, config, response, latency_s, ok=True, error=None)` | The entry written. **The single hook `agent/llm/client.py` needs.** |
| `record(preset_key, provider, model, sub_model=None, prompt_tokens=0, completion_tokens=0, latency_s=0.0, ok=True, error=None, cost_usd="auto")` | The entry written. Low-level; prices the call itself unless `cost_usd` is given. |
| `summarize(days=1)` | `{"since", "models", "presets", "totals"}` — see below. |
| `today_cost()` | `float` — known spend since local midnight. |
| `last_latency(model)` | `float \| None` — most recent call to that model. |
| `entries()` | Iterator over well-formed entries, oldest first. |
| `estimate_cost(model, prompt_tokens, completion_tokens)` | `float \| None`. |
| `cost_for(provider, model, prompt_tokens, completion_tokens)` | as above, but `0.0` for `*-sub` / `local`. |
| `load_pricing()` | Shipped table with the user override merged in. |
| `format_model_stats(summary, model)` | `"p50 12.3s \| $0.42 today"`, `"p50 12.3s \| cost n/a"`, or `""`. |

`summarize()` buckets are keyed `"<provider>/<sub_model or model>"` under
`models` and by `preset_key` under `presets`; `totals` is the same shape for the
whole window. Each bucket carries `calls`, `errors`, `p50`, `p95` (nearest-rank
percentiles of `latency_s`), `prompt_tokens`, `completion_tokens`,
`total_tokens`, `cost_known_usd`, `cost_unknown` and `cost_usd` (`None` as soon
as one call in the bucket had no price).

## Wiring it up

The client records; the UI only reads.

```python
# agent/llm/client.py — around the real call in LLMClient.chat_completion
t0 = time.monotonic()
try:
    response = ...
except Exception as e:
    self.usage.record_response(preset_key, self.config, None,
                               time.monotonic() - t0, ok=False, error=str(e))
    raise
self.usage.record_response(preset_key, self.config, response, time.monotonic() - t0)
```

`record_response` tolerates a response with no `.usage` (the subscription CLI
bridge and the streaming path both return bare `SimpleNamespace` objects) and
records zero tokens rather than failing a turn. Token counts and dict-shaped
usage payloads are both read.

- **Status bar:** `f"${usage.today_cost():.2f}"`.
- **`/model` availability column:** `summary = usage.summarize(days=1)` once,
  then `format_model_stats(summary, preset["model"])` per row. The literal
  "today" in that string assumes `days=1`.
