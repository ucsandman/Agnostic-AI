# engine/context — the semantic context graph

Durable context (rules, reference docs, memory) as modules with declared
dependencies, resolved into the smallest useful bundle for the task at hand.
Zero dependencies. Client-neutral: the engine reads markdown files and a
config; a client's hook decides when to call it and what to do with the text.

```
select (may be heuristic)  ->  resolve (never heuristic)  ->  pack (budget)  ->  render (explain)
prompt / cwd / files /         dependency closure,           required first,      every module says
agent type / client            cycles, topological order     then optional        why it is here
```

## A module

Any `.md` file under a configured root whose frontmatter carries a `name`
(memory files already do), or that the root's index lists. The optional
`context:` block declares edges and selection signals:

```yaml
---
name: billing
description: billing domain rules
context:
  requires: [company, architecture, database]   # hard prerequisites, loaded first
  suggests: [customer-model]                     # soft, budget permitting
  triggers:
    keywords: [billing, invoice, "price hike"]   # +2 each on the prompt (cap 6)
    paths: ["C:/Projects/billing/**"]            # +3 on cwd or a touched file
    repos: [billing]                             # +3 on the repo id
    tools: [Bash]                                # +2 in PreToolUse mode
    agents: [opus-owner]                         # +3 on the subagent type
  scope: user            # harness | user | repo (default: the root's)
  clients: [claude]      # applicability; default all
  priority: 70           # tie-break inside the budget, 0-100
  stale_after: 90d       # flags STALE in the bundle past this age
  sensitivity: private   # never joins a bundle with a repo-trust target
  section: "## Rules"    # inject one heading only (prefix match)
---
```

`[[wikilinks]]` in the body are implicit `suggests`, so a memory store that
already links related notes is a graph before anyone writes a `context:` block.
An index table (`| name | file | triggers | hook |`, the MEMORY.md routing
format) supplies weaker triggers (+1 each, cap 3, entries under 4 letters
ignored).

## Resolution guarantees

- **Deterministic.** Same files, same targets, same order; root order does not
  matter; ties break by name.
- **Prerequisites first.** Kahn over dependency-to-dependent edges. A required
  prerequisite that does not fit the budget sinks its dependents
  (`prerequisite-rejected`), never the other way round.
- **Cycles are detected** (Tarjan) and reported; ordering breaks the edge into
  the cycle's smallest member so every module still appears once. `graph`
  (lint) fails on a cycle; `resolve` exits 1.
- **Missing required dependency** flags the dependent `degraded` and the render
  says which prerequisite is absent; a missing optional one only warns.
- **Bounded.** `maxDepth`, `maxClosure` (truncated, reported), `maxModules`,
  a per-turn token budget and a per-session cap the hook passes in.
- **Dedup by hash.** A module already in the session with the same content
  hash is skipped and counted as duplicate context avoided; a changed hash
  reloads as `refreshed`.

## Trust boundary

Context is instruction material. Roots are the allowlist; each carries a
`trust` (`harness`, `user`, `repo`).

- A file that resolves outside its root (symlink) is excluded, reason recorded.
- A repo-trust module's edges cannot leave its root (`cross-root-edge-from-repo-trust`):
  content that arrived with a repository never pulls harness or user context along.
- When any target is repo-trust, `sensitivity: private` modules are dropped
  (`private-in-repo-bundle`) and repo content is bannered as data, not instructions.
- `findSecrets` (the caller's own pattern set) runs on every body; a hit drops
  the module and reports kind and length only.

## CLI

```
node engine/context/cli.cjs resolve <name...>    closure in load order, why each is there
node engine/context/cli.cjs explain <name>       the tree with reasons
node engine/context/cli.cjs impact <name>        reverse dependencies (what a change here touches)
node engine/context/cli.cjs graph                lint: cycles, orphans, missing, oversized, fanout, stale, similar names
node engine/context/cli.cjs select --prompt ".." what the selector would pick, with the points per signal
node engine/context/cli.cjs bundle --prompt ".." select + resolve + pack + render (what a hook injects)
node engine/context/cli.cjs show <name>          one module's bundle, by name
node engine/context/cli.cjs list                 every module, root, tokens, triggers
node engine/context/cli.cjs report [--days N]    the ledger: loaded / deduped / rejected, never-loaded, eager baseline
```

`--config` defaults to `$CONTEXT_GRAPH_CONFIG` or `~/.claude/hooks/context-graph.json`
(`config.cjs` documents the shape; `perRepo` roots expand `{slug}` / `{cwd}`
from the working directory).

## Library

```js
const ctx = require('agnostic-ai/engine/context/index.cjs');
const r = ctx.bundle({ cfg, signals: { prompt, cwd, client }, already, sessionUsed, findSecrets, cli });
r.text          // '' or the bundle; r.packed.{loaded,deduped,rejected,tokens}; r.resolved.{order,cycles,degraded}
```

Tests: `engine/tests/reg-context.cjs` (part of `npm test`). `--break`
sabotages the chain fixture so the first check fails: a green run under
`--break` means the suite stopped looking.

Claude Code wiring, budgets and the ledger: `~/.claude/docs/context-graph.md`
in the harness (`docs/context-graph.md` in this repository).
