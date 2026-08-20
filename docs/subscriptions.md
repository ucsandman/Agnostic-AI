# Subscription bridges

Three presets in `/model` run on a CLI you are already logged into instead of an
API key: `sub-google-antigravity` (`agy`), `sub-claude-code` (`claude`) and
`sub-openai-codex` (`codex`). `LLMClient.chat_completion` sees a provider ending
in `-sub` and hands the turn to `SubprocessSubscriptionBridge.execute_turn`,
which spawns the CLI, reads its stdout (stderr merged in, so a chatty CLI cannot
deadlock the pipe) and returns the same
`SimpleNamespace(choices=[...])` shape the OpenAI SDK does. A turn that produces
nothing within `timeout` seconds (default 180) kills the child and raises.

## Session continuity

A bridge turn used to flatten the entire conversation into one prompt and spawn a
brand-new process, so turn 20 re-sent turns 1-19 and paid for them again. The
client now keeps one `BridgeSession` (`LLMClient.bridge_session`) holding the
CLI's session id and how many messages it has already been given, and sends only
the new ones.

| CLI | First turn | Later turns | Notes |
|---|---|---|---|
| `claude` (anthropic-sub) | `claude -p <transcript> --output-format json --session-id <uuid4>` | `claude -p <new messages> --output-format json --resume <id>` | The id comes back in the result JSON and is preferred over the uuid we generated. |
| `codex` (openai-sub) | `codex exec <transcript> --dangerously-bypass-approvals-and-sandbox` | `codex exec resume <id> <new messages> ...` | Only when `codex exec --help` advertises a `resume` subcommand (parsed once per process) **and** the id was scraped from the `session id: <uuid>` header. Otherwise the full transcript is re-sent. |
| `agy` (google-sub) | `agy --print <transcript> ...` | identical, full transcript | `agy --print` is one-shot: it exposes no session or resume flag, so there is nothing to continue. |

A resumed prompt carries only the messages the CLI has not seen, minus a leading
assistant message (it wrote that itself), plus a one-line reminder that the tool
list and the JSON tool-call format from the first turn still apply.

### What resets a session

The session drops back to a full transcript under a fresh id when:

- the provider or the pinned `sub_model` changes (a `/model` switch);
- the history got shorter than what was already delivered (`/rewind`, `/compact`);
- the last delivered message no longer matches what was delivered (compaction
  rewriting the transcript without shortening it);
- there is nothing new to send.

Nothing else invalidates it. A CLI session that expires or is deleted on disk
surfaces as a failed turn rather than a silent re-flatten.

## Structured output and usage

`claude -p --output-format json` returns an envelope with `result`, `session_id`
and `usage`. The bridge parses it (retrying on the outermost `{...}` so a startup
banner above the payload does not lose it) and uses `result` as the message
content; if the output will not parse at all the raw text is used exactly as
before. In JSON mode the live stream callback receives the parsed answer once
instead of the raw envelope.

When the envelope carries token or cost fields, the response gets a
`.usage` with `prompt_tokens` / `completion_tokens` / `total_tokens` (and
`cost_usd` when reported) — the shape `UsageLog.record_response` already reads,
so subscription turns land in `.agnostic/usage.jsonl` like API turns. `codex` and
`agy` report nothing parseable, so their turns record zero tokens.

## Tool calls

The CLIs have no tool-calling API, so the prompt asks for fenced blocks:

````
```json
{"name": "read_file", "arguments": {"path": "a.py"}}
```
````

**Every** such block in a reply becomes its own tool call, in order, with ids
`call_sub_<pid>_<n>`; prose before, between and after them is ignored, and a
fenced block that is not a `{name, arguments}` object stays prose. (Only the
first block used to be parsed, so a CLI that batched two calls silently lost
the second.)

## Pinning the model

Subscription presets run their vendor's API-key presets as concrete models:
`/model 2 claude-fable-5 high`, or pick one in the model picker. The choice is
stored on `LLMConfig.sub_model`, shown as `claude-code-subscription/claude-fable-5`,
and passed to the CLI as the last argument pair — `--model` for `claude` and
`agy`, `-m` for `codex`. Without a pin the CLI's own default model is used.

## Limits

- The bridge is not token-streamed: `claude` in JSON mode emits one blob, so the
  UI gets the answer in one piece.
- `reasoning_effort` only reaches `agy` (`--effort`); `claude` and `codex` use
  whatever their own config says (`LLMClient.effort_supported` reports this).
- Continuity lives in memory. Restarting the agent (or `/rewind`) starts a new
  CLI session; the CLI's own transcript files are not reused.
