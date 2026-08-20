# Capabilities roadmap — 2026-08-20

Origin: after the TUI UX tournament (see 2026-08-20-tui-ux-tournament.md) Wes asked for every
remaining glaring weakness to be built, parallel where file ownership allows, sequential otherwise.

## Running in parallel (Phase 1, disjoint files)
| key | files | what |
|---|---|---|
| harness-health | ~/.claude/scripts/harness-health.ps1, both SKILL.md copies | ~/.claude.json + .mcp.json scan, -Probe dry-run of hooks, duplicate-hook detection, diff vs last run (state json), -IfChanged + wiring snippets |
| memory | agent/governance/memory.py, agent/loop.py | .agnostic/memory/ store (MEMORY.md index + per-memory md), injected as "## Memory (auto-recalled)", tools save_memory / recall_memory |
| mcp | agent/tools/mcp.py, agent/tools/registry.py | zero-dep stdio MCP client, .agnostic/mcp.json / .mcp.json / ~/.agnostic/mcp.json, tools registered as mcp__<server>__<tool>, registry.mcp_status() |
| bridge | agent/llm/client.py | multi tool-call parsing, claude --session-id/--resume delta sends, --output-format json, codex resume when supported, .usage surfaced |
| usage | agent/llm/usage.py, agent/llm/pricing.json | .agnostic/usage.jsonl, summarize p50/p95/cost, pricing.json with explicit nulls (no invented prices), record_response hook contract |

Also running: TUI tournament winners 1-9 (wf_4c8e6487-cbb), sequential.

## Queued (Phase 2, sequential — all touch tui.py / tui_commands.py / ui_common.py)
1. Usage wiring into chat_completion + /model picker stats + status-bar cost fragment
2. /memory command + picker
3. /mcp command + status glyph
4. /diff turn browser over _turn_marks (needs winner 8)
5. Turn-done notifications (bell + toast, /notify on|off)
6. Multi-line TextArea composer (Shift/Alt+Enter newline, paste as block)
7. Headless `agnostic -p` mode (agent/headless.py, --output-format text|json)

Specs for Phase 2 are written by the last agent of Phase 1 to the session scratchpad
(phase2-specs.json) and should be copied here when Phase 2 launches.

## Deliberately not doing
Image paste (no vision path in the bridges yet), /theme live preview (Textual chrome does not repaint),
any `end`/`ctrl+u` binding without priority=True.
