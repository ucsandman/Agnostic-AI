# Memory

Persistent auto-memory for the coding agent: the durable facts a session learns
(a preference, a correction, a project gotcha) survive the session that learned
them, and come back as an index in the next system prompt.

Implemented in `agent/governance/memory.py` (`MemoryStore`), stdlib only — no
embeddings, no database, no extra dependency.

## Where it lives

Workspace-local, next to the rest of the agent's state:

```
<workspace>/.agnostic/memory/
  MEMORY.md              # one line per memory: the index
  dashboard-port.md      # one file per memory
  ruff-line-length.md
```

Nothing is written outside the workspace, and nothing is written until the first
memory is saved.

## File format

A memory file is frontmatter plus a markdown body:

```markdown
---
name: Dashboard port
description: the command center binds 7843+ here
type: project
created: 2026-08-20
---

Port 7842 is taken by another local service, so the dashboard picks the next
free port. Read the URL it prints instead of assuming 7842.
```

- `name` — the title. It is slug-normalised (`Dashboard port` →
  `dashboard-port.md`), so re-saving the same name updates that memory in place.
- `description` — one line; this is what the index shows and what the model
  reads on every turn.
- `type` — one of `user` (a preference), `feedback` (a correction),
  `project` (a durable project fact), `reference` (a lookup note).
- `created` — ISO date, stamped at first save and preserved by later upserts.

`MEMORY.md` is regenerated on every save and delete:

```markdown
# Memory index

- [Dashboard port](dashboard-port.md) — the command center binds 7843+ here
```

Limits, enforced with a clear error rather than a truncation: 8 KB per body,
200 memories per workspace, no path separators or dots-only names. Files are
written to a `.tmp` sibling and `os.replace`d into place, so a crash mid-write
never leaves a half-written memory.

## The two tools

Registered on the agent's tool registry in `AgentLoop._register_memory_tools`:

- **`save_memory(name, description, body, type)`** — save when the user states a
  preference, corrects the agent, or reveals a durable project fact. Not for
  transient task state, and never for secrets, tokens or keys.
- **`recall_memory(query)`** — keyword search returning the full text of the best
  matches. Scoring is case-insensitive token overlap over name, description and
  body (name and description count double); no embeddings are involved.

## How it is injected

`AgentLoop._load_harness_system_prompt` appends, after the compiled harness
rules and the project agreement:

```
## Memory (auto-recalled)
- [Dashboard port](dashboard-port.md) — the command center binds 7843+ here
```

Only the index goes into the prompt — bodies are fetched on demand with
`recall_memory`. The index is capped at 4000 characters and drops the oldest
whole lines first, and the section is skipped entirely in compact mode when the
prompt is already near its small-context budget. A corrupt or unparsable file is
skipped and reported as an `- [!] …` issue line; `index_text()` never raises, so
a damaged store cannot break a session.

## Slash command (UI phase)

`/memory` is wired in the UI phase and should call `MemoryStore` directly —
there is no other API:

| Command | Call |
| --- | --- |
| `/memory` or `/memory list` | `MemoryStore(workspace_root).list()` → `Memory(slug, name, description, type, created, body)` |
| `/memory show <name>` | `MemoryStore(workspace_root).get(name)` → `Memory` or `None` |
| `/memory save <name>` | `MemoryStore(workspace_root).save(name, description, body, type)` → the saved `Memory`; raises `ValueError` with a user-facing message |
| `/memory forget <name>` | `MemoryStore(workspace_root).delete(name)` → `True`, or `False` when there was no such memory |

Saving or deleting from the UI takes effect on the next
`_load_harness_system_prompt()`; the running turn keeps the prompt it started with.
