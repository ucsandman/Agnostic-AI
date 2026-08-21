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

## How it is wired

The client records; the UI only reads.

`LLMClient` owns one `UsageLog()` (`self.usage`, resolved against the cwd, which
is the workspace root for both entrypoints) and every path through
`chat_completion` writes exactly one entry through a single `_record` helper:
the subscription bridge, the streaming call and the plain call, on success and
on failure alike. Latency is `time.monotonic()`; a failure records
`ok: false` with the first 200 characters of the exception and then re-raises.
Journalling is wrapped in `try/except` throughout — bookkeeping never kills a
turn.

Two details worth knowing:

- The streaming path asks for `stream_options={"include_usage": True}` on every
  provider **except `local`** (LM Studio / Ollama builds reject unknown request
  fields). The usage chunk that comes back carries an **empty `choices` list**,
  so it is read before the empty-choices guard that skips content-less chunks —
  otherwise a streamed turn records zero tokens.
- `record_response` tolerates a response with no `.usage` (an older CLI envelope,
  a server that sends no usage chunk) and records zero tokens rather than failing
  a turn. Token counts and dict-shaped usage payloads are both read.

`LLMConfig.preset_key` carries the preset a config came from, so the `presets`
buckets are filled in; switching by bare model id clears it.

### Where it shows up

- **TUI status bar:** a dim `$ 0.42 - p50 12.3s` segment after the context gauge,
  from `ui_common.usage_segment(summary, model)`. It renders nothing at all until
  something has been recorded, and drops the money half when the window's known
  spend is `0.00` but some call had no price — an unpriced model must not claim
  `$0.00` of spend. `AgnosticTUI._refresh_usage_bg` recomputes it every 10s on a
  worker thread; `summarize()` reads the whole journal and must never run on a
  repaint.
- **`/model` picker:** `UsageLog().summarize(days=1)` once for the whole list,
  then `format_model_stats(summary, preset["model"])` per row, appended as a dim
  `p50 12.3s | $0.42 today` after the availability column. The literal "today" in
  that string assumes `days=1`.
