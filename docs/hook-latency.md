---
name: hook-latency
description: "Measured per-event hook timing: hooks per event cost their slowest member, and what to keep synchronous"
context:
  triggers:
    keywords: ["hook latency", "slow hook", "hook timing", "pretooluse slow", "async hook"]
  requires: ["harness-guards"]
  priority: 40
---
# Hook latency

What each registered hook costs per event, measured, and what was done about it.
Guard behavior and overrides: [guards.md](guards.md).

## The standing rules

- Hooks for one event run in parallel, so the event costs its slowest hook, not
  the sum. Cut the slowest member first, then the count.
- A hook that can deny or inject stays synchronous. A hook that only records
  runs `"async": true`: exit 0, no stdout, no decision. Async hooks still
  spawn a process and still load the machine.
- Every hook is a process spawn, and Claude Code runs each through `bash -c`
  first. Time one spawn and one empty login shell on the machine before adding
  a hook; a verdict about hook cost is only as durable as the spawn cost it
  was measured on.
- Measure with `tools/hook-latency/`: its README gives the healthy numbers and
  the reading order.

## Passes

- [2026-09-19](hook-latency-2026-09-19.md): sessions were slow because process
  spawn on the machine was 10 to 30x slow and every Bash tool call paid a 5 to
  14 s Git Bash login shell. Shim, plugin off, orphans, the measurements.
- [2026-09-06](hook-latency-2026-09-06.md): two hooks ported from pwsh and
  python to node, a dead rewrite removed, the DashClaw round trip collapsed from
  two requests to one, four recording hooks made async.
