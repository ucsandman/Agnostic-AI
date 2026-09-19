# hook-latency

Four read-only measurements that say why a Claude Code session is slow or
token-hungry on this machine. Run them before adding a hook, and whenever a
session "feels slow". Results and the history of what they found:
[docs/hook-latency.md](../../docs/hook-latency.md).

| script | question it answers | healthy | run |
|---|---|---|---|
| `hookpar.cjs` | wall clock of one event, all its hooks in parallel (what a tool call really pays) | PreToolUse/Bash under 1 s | `node tools/hook-latency/hookpar.cjs PreToolUse Bash 2` |
| `hooktime.cjs` | each hook alone: ms, exit code, bytes it injects | node hook under 150 ms, python under 400 ms | `node tools/hook-latency/hooktime.cjs` |
| `usage.cjs` | fixed context per session, cache hit rate, injected volume | fixed context under 50k tok; prefix losses only after compaction | `node tools/hook-latency/usage.cjs --recent 5` |
| `cachetrace.cjs` | which call lost the prompt cache and what preceded it | same | `node tools/hook-latency/cachetrace.cjs <transcript.jsonl> all` |
| `memmap.ps1` | who holds the RAM, spawn latency, per-session process trees, orphans (Windows) | `cmd /c ver` under 100 ms | `powershell -NoProfile -ExecutionPolicy Bypass -File tools/hook-latency/memmap.ps1` |

Reading order when a session is slow:

1. `memmap.ps1`: if `cmd /c ver` takes hundreds of ms, the machine is the
   problem and every hook multiplies it. Free RAM, kill orphans, find the
   language server that indexed the whole drive. Stop here until spawn is fast.
2. `hookpar.cjs PreToolUse Bash`: the event costs its slowest hook under
   contention, so the number to cut is the slowest member, then the count.
3. `usage.cjs --recent 5`: a fixed context over ~70k tokens means the skill
   catalog, MCP tool list or CLAUDE.md chain is the cost, not the conversation.
   A prefix loss on a call that is not the post-compaction one means something
   changed early in the prompt (a catalog, a tools list) mid-session.

The transcript scripts read `~/.claude/projects/<slug>/<session>.jsonl`. The
hook scripts read `~/.claude/settings.json` and give hooks a fake session id, so
a guard that needs a transcript sees "none" and should exit fast.
