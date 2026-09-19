---
name: delegation-and-model-routing
description: The full delegation contract: Fable escalations, the capability graph, the advisor pattern, spawn economics, the EST declaration, nesting, lean agent types, task routing and the model literal rule. Loads when a prompt or tool call is about spawning agents.
context:
  triggers:
    keywords: [subagent, subagents, spawn, delegate, delegation, workflow, agent tool, opus-owner, sonnet-implementer, haiku-scout, advisor, fan out, fan-out, orchestrat]
    tools: [Agent, Task, Workflow]
    agents: [opus-owner]
  clients: [claude]
  priority: 80
  stale_after: 180d
---
# Delegation and model routing (loaded on demand)

The two-line summary lives in the global rules; this is the contract behind it.

- **Opus runs the main loop**: planning, orchestration, integration.
- **Fable for five escalations only:** architecture decisions; security-sensitive reviews; cross-project synthesis; root-cause after 2 failed fixes; final synthesizer/judge of a large dynamic Workflow. Max 3 Fable spawns/session.
- **A Fable main loop is delegate-first by judgment, not by block** (`fable-delegate-guard` briefs once and logs; it denies nothing). Plan the tree first; decisions, review and synthesis stay in the main loop; a change set you start by hand gets finished by hand. Before dispatching any fix, grep for the second implementation of the same behaviour and put every site in one finding with one owner; fix at the root.
- **The capability graph** (`capability-graph-guard`): Fable → Opus/Sonnet/Haiku; Opus → Sonnet/Haiku; Sonnet → Haiku; Haiku → nobody. Downward only; a call crossing a missing edge is denied. A `fork` inherits the caller's model, so it is a peer edge from any subagent. Only Opus subagents may run a Workflow, and every `model:` literal in it must rank below the caller.
- **Upward consultation is the advisor pattern:** a Sonnet or Opus agent spawns subagent_type `advisor` (read-only, guidance only) for one focused architecture, security or after-2-failures decision, and keeps ownership. Consultations are never capped and do not count against the Fable cap. The guard ignores any `model:` passed and injects one rung above the caller (Sonnet → Opus, Opus → Fable, Fable → Fable). Anthropic's native advisor (advisorModel) is separate, server-side and set to Opus: right for Sonnet and Haiku workers; Opus agents and an Opus main loop spawn `advisor` instead.
- **Delegation economics:** a subagent costs ~60k input tokens before its first tool call (~17k for a lean type), then 2-4k per call. Under ~10 tool calls or ~80 edited lines, stay in the main loop. Delegate when work is large (many files, a test suite, long tool output) or when independent pieces run in parallel.
- **Every Agent dispatch declares its scope** (`subagent-budget-guard`): `# EST: <n> calls, <n> files` in the prompt. The hook prices it against inline work and denies a spawn that does not pay for its overhead, showing the arithmetic (the identical dispatch is denied at most once per session). Unknowable scope says `# SPAWN_OK: <why>`; that is an allowed answer, and it is logged. Break-even: ~5 tool calls for a lean type, ~15 for `general-purpose`; re-fit with `node ~/.claude/tools/subagent-budget/calibrate.cjs`.
- **Nesting guide:** nest only when a sub-task briefs in one paragraph, is independent, and its output would flood the parent's context (a repo sweep or a test suite, not a few file reads). Depth two (Fable → Opus → Haiku) is the ceiling. Fan out from the highest level that can already write the brief: knowing the five files, spawn five Haiku workers, not one Opus that re-derives them. Never nest for an answer one Grep or Read gives.
- **Lean agent types by default:** `opus-owner`, `sonnet-implementer`, `haiku-scout` (no skills, MCP, or Artifact). `general-purpose` costs ~3x and is used only when the worker genuinely needs a skill, an MCP tool, or Artifact; a lean worker reaches every MCP server with a declick adapter from Bash, and its brief carries the DECLICK-FIRST block from `dispatch-blocks`.
- **Route by task:** searches/formatting/mechanical edits → Haiku; implementation/exploration → Sonnet; architecture/final review/hard debugging → Opus. Codex = external executor for heavy implementation, debugging, test fixing, multi-file edits.
- **Every dispatch names its model.** Each `agent()` in a Workflow script and each Agent call carries its own inline `model:` literal (`opus`/`sonnet`/`haiku`); a shared opts variable doesn't count, one bare `agent()` BLOCKS the script (`agent-model-guard`). Split: finders/reviewers → Opus, per-finding skeptics → Sonnet, mechanical lookups → Haiku, final synthesizer → Fable as a module-top-level `await agent(..., {model: 'fable'})` after the fan-out (never inside one or in a helper; max 3/script). Pair a lean `agentType` with the model unless the stage needs WebFetch, MCP, Skill or Artifact.
- Per-session off switches: `FABLE_DELEGATE_GUARD=off`, `CAPABILITY_GRAPH_GUARD=off`.
