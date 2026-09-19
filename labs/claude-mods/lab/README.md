# Mod laboratory (isolated; never touches `~/.claude`)

Every plugin here loads only when you pass `--plugin-dir`. Nothing is installed, nothing in the
production harness is modified. Build 2.1.273; the API is early access and may change (see
`../MOD_CAPABILITY_MAP.md` and `../snapshot/`).

## Run the X-RAY (Phase 2)

```
claude --plugin-dir C:\Projects\claude-mods-rnd\lab\xray
```

What you get:
- A magenta **CLAUDE RUNTIME X-RAY** band above the prompt: event count, errors, subagents,
  unknown events, live context %, five-hour / seven-day rate-limit %, session cost; the last five
  events with their result and latency.
- Transcript lines `⟦xray⟧ <event> <what> <result> ·ms · from <plugin>/<tier>` followed by the
  **pipeline** the call took (`Claude → [xray] → tunnel-cost/user 1ms → … → engine 2546ms`) and the
  interception capabilities that exist for that event (only real ones are listed).
- `/xray tools|subagents|session|usage|ui|errors|unknown|all|off` switches the filter (persisted in
  `$.store` across sessions); `/xray status` prints counts per event, subagents seen, usage, and the
  timeline path.
- Black-box file: `lab/xray/timeline/<sessionId>.jsonl`, one JSON object per event with `e`, `r`,
  `origin`, `agentId`, `ms`, `trace`.

Dogfood evidence (2026-09-16): 1,240 events in a four-prompt session; `../snapshot/2.1.273/payloads/xray-timeline-demo-session.jsonl`.

## Phase 3 demonstrations (load several at once; order matters, first is outermost)

```
claude --plugin-dir lab\xray --plugin-dir lab\demos\matrix --plugin-dir lab\demos\bender ^
       --plugin-dir lab\demos\guardian --plugin-dir lab\demos\blackbox ^
       --plugin-dir lab\demos\tunnel\observer --plugin-dir lab\demos\tunnel\cost ^
       --plugin-dir lab\demos\tunnel\policy --plugin-dir lab\demos\tunnel\telemetry
```

| Demo | Ask Claude | What the runtime does | Proof on screen |
|---|---|---|---|
| **MATRIX** | `Run the Bash command: echo enter the matrix` | `tool.call` hook holds the call open, prints what Claude intended, opens the engine's own AskUserQuestion dialog (`$.ui.ask`); Continue / Deny / Rewrite | `⟦matrix⟧ ⏸ FROZEN #1 … ▶ released after 28321ms (Continue)`; the Bash row shows 30,315 ms |
| **REALITY BENDER** | `Run the Bash command: echo hello bend` | tool runs for real; hook returns its own `{result}`; Claude reads the altered text plus a hidden context note | `REAL TOOL RESULT: hello bend` / `CLAUDE RECEIVED: DNEB OLLEH` |
| **GUARDIAN** | `Use the Edit tool to append a line to lab/demos/protected/DO_NOT_EDIT.txt` | `{deny}` on `tool.call` for Write/Edit/NotebookEdit/Bash-redirect into `protected/**`, plus a `tool.check` deny as belt-and-braces | `✖ BLOCKED #1: Edit …`, toast, Claude quotes the refusal; file unchanged |
| **MIDDLEWARE TUNNEL** | `Run the Bash command: echo through the tunnel` | four plugins each print `↓ enter` / `↑ leave`; the outermost prints `next.trace` | nested order observer→cost→policy→telemetry→tool→telemetry→policy→cost→observer, each leaving after ~2,546 ms |
| **BLACK BOX** | `/blackbox` | per-session JSONL of prompts, model steps (with usage), tool calls (ms, agentId), spawns, denials | timeline table with seconds offsets |

Lesson observed while dogfooding: **a recorder must sit outermost.** `blackbox` was loaded after
`guardian`, so the denied Edit never reached it (guardian answered without calling `next`), and its
summary said "0 denied" while `xray` (loaded first) saw the denial. Order of `--plugin-dir` = order in
the chain within the user tier.

## Headless probes (Phase 1)

`probe`, `probe2`, `probe3`, `probe-ui`, `bench` — see `../snapshot/2.1.273/README.md`. Run any with
`claude --plugin-dir <dir> -p "..." --model haiku --allowedTools "Bash,Read"`; append `# SEQ: probe` to
Bash commands so the production batch-guard lets single commands through.

## Driving a real interactive session from a script

`python tools/pty_drive.py <out.txt> 25 "<dir>,<dir>" "<prompt>|||KEYS:1|||WAIT:10|||KEYS:/xray status\r" 30 "" --debug`
(pywinpty + pyte; 150×45 cells; snapshots every 5 s). Never kill `claude.exe` by image name from
inside a Claude session.
