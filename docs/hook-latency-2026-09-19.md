---
name: hook-latency-2026-09-19
description: "The 2026-09-19 pass: slow sessions were process spawn cost and the Bash tool's login shell, not hooks or the model"
context:
  triggers:
    keywords: ["slow session", "spawn cost", "login shell", "bash-noprofile", "tsserver memory", "snapshot timeout"]
  requires: ["hook-latency"]
  priority: 30
---
# Hook latency pass of 2026-09-19

Sessions had become "incredibly slow". Measured with `tools/hook-latency/`;
the raw numbers are in memory `harness-hook-overhead-measured`.

| measure | this pass | 2026-09-06 pass | healthy |
|---|---|---|---|
| PreToolUse/Bash, 15 hooks in parallel | 5.8 to 11.5 s | ~0.5 s | under 1 s |
| PostToolUse/Bash, the 2 blocking hooks, real session | 4.3 s | n/a | under 0.3 s |
| `node -e 0` | 0.1 to 3.1 s | ~0.05 s | 0.05 s |
| `cmd /c ver` | 0.03 to 1.1 s | n/a | 0.03 s |
| Git Bash login shell, `bash -l -c true` | 5 to 14 s | never measured | under 0.3 s |
| Bash tool call in a fresh session, one `echo` | 31.6 s | n/a | under 2 s |
| RAM free | 0.77 GB of 32 | n/a | |

## What it meant

- **Process creation was 10 to 30x slow and erratic**, and every layer of the
  harness is a spawn: 56 hook commands, each run through `bash -c`, then the
  hook's own node or python. The 2026-09-06 verdict "a dispatcher buys nothing"
  was made on a fast machine; on a slow one the count is the cost. The
  `"async": true` hooks (the context-handoff checkpoint, the DashClaw post-tool
  and Stop hooks) do not block a turn, but they still spawn and still load the
  box.
- **Every Bash tool call ran `bash -c -l`**, and Git for Windows' `/etc/profile`
  forks about 14 times. That alone was 5 to 14 s per call, invisible because
  nobody had timed an empty login shell.
- **RAM**: the typescript-lsp plugin spawned one tsserver per session that
  indexed all of `C:\Projects` (2.2 GB, 1.6 GB, 0.7 GB); four orphan
  `node -e "setInterval(...)"` sentinels and a hung test runner sat behind gone
  parents. Freeing 5.3 GB did not make spawn fast again: RAM was a contributor,
  not the cause.
- **Prompt caching was fine**: 0 prefix losses in-session, 1 in 148 calls over
  a long session (the post-compaction restart). Fixed context is 69k tokens per
  session here (94 to 102k in other projects): the skill catalog, deferred MCP
  tool names, MCP instructions, the CLAUDE.md chain.
- Claude Code's shell snapshot has a hard 10 s timeout and no knob; the
  snapshot script forks ~30 times and took 14 to 36 s here, so sessions ran
  without one. The Bash tool still works without a snapshot.

## What changed

- `tools/bash-noprofile/`: a `bash.exe` shim (`--noprofile --norc`, explicit
  std handles, kill-on-close job) wired through `CLAUDE_CODE_GIT_BASH_PATH`.
  Bash tool call in a fresh session: 31.6 s to 1.7 to 4.2 s. Verified with a
  haiku `claude -p` probe; the README there has the command. Three probes were
  lost to a first version that inherited handles instead of passing them:
  Claude Code spawns the shell detached, so the child wrote to a console nobody
  read and the tool said "(Bash completed with no output)".
- typescript-lsp plugin disabled in settings.json; sessions started before
  that regrow their tsserver until restarted.
- `~/.bashrc`: the openclaw completion file (150 KB) loads only in interactive
  shells.
- `tools/hook-latency/`: the four measurements, so the next "it feels slow"
  starts with numbers.

## Not fixed

Why process creation is slow on this machine (kernel time 18%, 115k context
switches/s, Defender on, no Smart App Control or AppLocker) needs an elevated
shell: `fltmc filters` for third-party filter drivers, then Defender exclusions
for node, python, bash, `C:\Projects` and `~/.claude`.

## Next cuts, in payoff order, once spawn cost is known

1. Fold the 13 node PreToolUse guards into one dispatcher, or into a
   function-hook module (`CLAUDE_CODE_ENABLE_FUNCTION_HOOKS` is already on):
   15 spawns per Bash call become 1 or 0 with the same policy.
2. Make `dashclaw_pretool.py` skip its remote TCP preflight on read-only tools.
3. Move the two blocking PostToolUse hooks (`tool-output-secret-watch`,
   `repeat-tool-guard`) into the same dispatcher.

Lesson: before adding any hook or shell layer, time one process spawn and one
empty login shell on the machine. A verdict about hook cost is only as durable
as the spawn cost it was measured on.
