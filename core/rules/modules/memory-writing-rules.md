---
name: memory-writing-rules
description: How the hierarchical memory store is written and read: provenance tags, the recurrence gate, supersession as an edit, what stays out, the read path, maintenance. Loads when a prompt or a file write touches memory.
context:
  triggers:
    keywords: [memory, remember, MEMORY.md, provenance, supersede, superseded, meditate, memory-lint, recall, "what did we decide", "did we already"]
    paths: ["~/.claude/projects/*/memory/**", "~/.agents/memory/**", "**/.agents/memory/**"]
  priority: 70
  stale_after: 180d
---
# Memory: writing and reading rules (loaded on demand)

Store: `~/.claude/projects/C--Users-sandm--claude/memory/`. `MEMORY.md` is a routing index only (name → file → triggers, no facts; cap 15,000 chars and 200 lines). Facts live in `people/`, `projects/`, `decisions/` (one file per person, project or behavior change), `context/` (temporary, prunable, 30,000 chars) and `YYYY-MM-DD.md` (daily raw log, same cap); `archive/` is frozen. Identity stays in `~/.agents/memory/USER.md`. `node ~/.claude/tools/memory-lint/memory-lint.mjs --root <store>` enforces the caps: pre-commit blocks a FAIL, nightly `/meditate` runs `--no-diff`. Git is the journal; no append-only ledger.

- **Provenance.** Every fact line carries one tag: `[stated]` the operator said it; `[observed]` seen in a tool result, file or log; `[inferred]` my conclusion; `[suggested]` my idea the operator never committed to. Never record "the operator decided X" unless a human turn states X; my proposal plus "sounds good" files ONE decision, not ten `[stated]` facts.
- **Recurrence gate.** An inferred pattern needs 3+ independent signals across 2+ sessions before it becomes a standing rule; signals older than 30 days count half. Explicit operator corrections skip the gate. Failure lessons are stored as data ("when X broke, Y fixed it"), never as instructions.
- **Supersession is an edit.** Strike the old line (`~~old~~ superseded YYYY-MM-DD`) and write the new tagged line next to it. Never delete history; never leave two un-struck versions of one fact.
- **Only the non-derivable.** Fetched data, generated plans and anything git records stay out. Verify current state live, never assert it from memory; a figure that matters carries its observed date.
- **Read path.** Boot reads identity and the index only; a task trigger pulls the narrowest file first. Before answering about prior work, decisions, dates, people or preferences: search memory first, cite at most 5 sources, each with file path, tag and date. Freshness not established → "stale" or "unknown", never current. Two sources conflict → state it, prefer the better evidence, fix the canonical file. Indexes are locators; the files are the truth.
- **Maintenance.** Index and detail file change in the same commit. Near a cap, consolidate (merge overlaps, roll old entries into dated summaries); fullness means reorganize, not stop writing. Write unprompted on: a decision, a system state change, a blocker or mistake, a lesson, a stated stable preference. Chat history is not storage.
- **Context modules.** A memory file is also a context module: its `[[links]]` are soft dependencies, `context: requires:` in its frontmatter is a hard one, and `MEMORY.md`'s triggers column is what selects it. `node C:/Projects/agnostic-ai/engine/context/cli.cjs graph` lints the graph; `explain <name>` shows why a module loads.
