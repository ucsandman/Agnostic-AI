---
name: context-graph
description: How dependency-aware context loading is wired into this harness: the hook, its four events, the roots, the budgets, the ledger, and how to add or debug a module
context:
  triggers:
    keywords: [context graph, context module, context-graph, "why did that load", "loaded on demand", semdag, dependency-aware context, module frontmatter]
    paths: ["~/.claude/hooks/context-graph.*", "C:/Projects/agnostic-ai/engine/context/**", "C:/Projects/agnostic-ai/core/rules/modules/**"]
  priority: 70
---
# Context graph

Situational context is a module, not standing text. `hooks/context-graph.cjs`
selects modules from the prompt, the working directory and the file being
edited, resolves their dependency closure in prerequisite order, and injects
the bundle under a hard budget, each module naming the reason it loaded.
Engine and contract: `C:/Projects/agnostic-ai/engine/context/README.md`.

## Events

| Event | Signal | Budget | Effect |
|---|---|---|---|
| `UserPromptSubmit` (source user/sdk only) | prompt text, cwd, files touched this session (transcript tail) | `turnTokens` 2,500, `sessionTokens` 12,000 | inject, remember what is in context |
| `PreToolUse` Edit/Write/MultiEdit/NotebookEdit | the file path only | same session cap | a module whose `triggers.paths` matches loads before the write, once per session |
| `PreToolUse` Agent/Task | the brief (type + prompt) | none | stashed for the child |
| `SubagentStart` | agent type + the stashed brief | `subagentTokens` 1,200 | the child gets its own bundle |
| `SessionStart` compact | the session's loaded set | `turnTokens` | required modules re-injected after the summary pass |
| `SessionStart` clear | | | loaded set forgotten |

Slash commands, prompts under 12 characters and machine turns (`loop_wakeup`,
`schedule_wakeup`, `system`, `poll_event`) never trigger a load.

## Roots (the trust allowlist)

`hooks/context-graph.json`:

| id | path | trust | what makes a file a module |
|---|---|---|---|
| `rules` | `C:/Projects/agnostic-ai/core/rules/modules` | harness | sections moved out of `global-rules.md` |
| `harness-docs` | `docs/` | harness | a `context:` frontmatter block (14 docs carry one) |
| `memory` | the hierarchical memory store (`people/`, `projects/`, `decisions/`) | user | every file; `MEMORY.md`'s triggers column selects, `[[links]]` are soft edges, `context:` refines |
| `repo-memory` | `projects/{slug}/memory` for the cwd | user | same; repo-scoped, invisible from another repo |
| `repo-tree` | `<cwd>/.agents/memory` | repo | **off**; opt in per repo. No edges out of its root, private modules never join its bundle, content bannered as data |

## Reading the injection

```
[context-graph] 2 modules for this turn (est 842 tokens; session 842/12,000). Prerequisites first; each says why it is here.
▸ harness-guards  (harness/harness · 2026-09-19 · 697 tok)
  why: path "~/.claude/hooks/**"
...
[context-graph] already in context (skipped): harness-push-destinations. over budget (not loaded): browser-qa 1,601 tok. Load one by name: node C:/Projects/agnostic-ai/engine/context/cli.cjs show <name>
```

`STALE 140d` on a module means it is past its `stale_after`: verify before
relying on it. `required dependency missing: x` means the module's declared
prerequisite does not exist; fix the frontmatter.

## Accounting

`logs/context-graph.jsonl` holds one row per event (targets, loaded, deduped,
rejected with reason, tokens, wall time). `node hooks/context-graph.cjs --report`
summarises a window: loads per module, duplicate context avoided, rejections
by reason, modules never loaded, and the eager baseline every session pays
regardless (`eagerBaseline` in the config). Replay real prompts without side
effects: `node tools/tokflow/context-graph-bench.cjs --days 14`.

## Adding, tuning, debugging

- New module: give the file a `name`, a `description` and a `context:` block
  (schema in the engine README). Keyword triggers are matched whole-word,
  case-insensitive; keep them specific (`cd` matched every pasted command,
  which is why index triggers under 4 letters are ignored).
- `node C:/Projects/agnostic-ai/engine/context/cli.cjs graph` lints: cycles,
  orphans (no trigger, no dependent), missing dependencies, oversized modules
  (over 1,500 tok: set `section:` or split), fanout, stale.
- `explain <name>` shows the closure with reasons; `impact <name>` lists what
  depends on a module before you change it; `select --prompt "..."` shows the
  points per signal for a prompt that loaded the wrong thing.
- Off for one session: remove the entries from `settings.json`, or point
  `CONTEXT_GRAPH_CONFIG` at a config with no roots. The hook is fail-open:
  any error exits 0 with no output and one ledger row.
- Probe: `node hooks/tests/context-graph-probe.cjs` (16 cases, every event,
  negative controls included).

## Other clients

The hook is in `settings.json`, so `npm run port` in agnostic-ai carries it to
Codex (`~/.codex/config.toml`), Gemini and Cursor through the same shim as the
other guards; the client is inferred from the transcript path (`--client` or
`CONTEXT_GRAPH_CLIENT` overrides). A module's `clients:` list narrows where it
applies; the four rules modules are client-neutral except
`delegation-and-model-routing` (Claude only, since the port already drops that
section for other clients).
