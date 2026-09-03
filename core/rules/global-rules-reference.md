# Global Rules — Rationale and Incident History

Companion to `core/rules/global-rules.md`. **Not loaded into sessions.** Everything here was cut from the
loaded file on 2026-09-02 to reduce per-session token cost: rationale paragraphs, worked examples, anecdotes,
dated incidents, and implementation trivia. No rule lives only here — every directive stayed in the loaded
file. Sections mirror the loaded file's headings.

---

## Global Working Agreement (framing)

Original opening: "How I want you to work across all projects. You operate inside production codebases.
Produce **clean, correct, shippable, minimal changes** that run locally and do not create cleanup work."
And: "A project's own rules and my explicit instructions override this file. Bias toward caution over speed.
For trivial tasks, use judgment."

---

## Non-Negotiables

- Why secret env files are never opened: "It is where credentials live for Stripe, Google auth, and similar.
  Wire tools to read it; never read it yourself."
- Hard stops originally carried the framing "Get explicit in-session confirmation before any of these. State
  the exact action, affected environment, expected side effects, and rollback path first."

---

## Core Philosophy

### 1. Think before coding
- Rationale: "Wrong assumptions run unchecked are the most common failure mode."
- Worked example of a STOP on disagreeing sources: "I see X in file A but Y in file B, which takes precedence?"
- Original wording of the multi-interpretation exception: "The one exception: when every reading produces the
  same files and the same user-visible behavior, name your reading in the ASSUMPTIONS block and proceed."

### 2. Simplicity first
- Rationale: "Your natural tendency is to overcomplicate. Actively resist it."
- Cut self-check: "Would a senior engineer say 'why didn't you just...'?"
- Closing line: "Cleverness is expensive."

### 3. Surgical changes
- Original framing of the broken/imperfect split: "Boundary with the fix-on-the-spot rule below: fix anything
  **broken** that you touch or that blocks verification... Leave anything merely **imperfect**... Broken gets
  fixed and reported. Imperfect gets mentioned and left."

### 4. Push back when warranted
- Rationale: "'Of course!' followed by implementing a bad idea helps no one."

### 5. Build for human eyes, not terminals
- Rationale: "Your systematic bias: you build for what you know (CLIs, JSON, terminals, GitHub) and forget the
  operator is a visual human."
- Test 6 rationale: "Tests prove data exists; only a rendered page proves a human can use it."
- Test 1 original: "a stranger looking at the surface for 10 seconds can say what it does. If understanding
  needs a README, spec, or workflow file, it fails."

### 6. Goal-driven execution
- Original phrasing of the naive-then-optimize rule: "For algorithmic or data-processing work,
  naive-then-optimize: implement the obviously correct naive version, verify correctness, then optimize while
  preserving behavior. Never skip step 1."

---

## How to Work

### Batching (profiling data, 2026-09-01)
- Every tool call costs a model round-trip (median 9s) plus ~2s of hooks.
- Profiled across 8 sessions / 27 active hours: **70% of tool turns made exactly one call**, and that serial
  pattern was the single largest cost driver.
- Guard path: `~/.claude/hooks/batch-guard.cjs`. `node ~/.claude/hooks/batch-guard.cjs --report` shows denials
  and overrides per day.
- `slow-command-guard` exists because recursive grep/rg/find rooted at `C:\Projects`, the home dir, or a drive
  costs 120-180s each.
- The saved Workflow shapes under `~/.claude/workflows/` are `adversarial-review`, `tournament`, `understand`,
  `fix-findings`. Rationale for reusing them: "do not regenerate a 10-20k-token script for a shape that already
  exists there."

### creds / blockers
- `creds resolve` fills `.env` from `.env.example` using every key already on this machine; the SessionStart
  hook runs it too.
- `creds mint <provider|KEY>` prints the exact page, scopes, and CLI shortcut; `--open` drives the browser; a
  pasted value lands in `~/.creds/vault.env`.
- **Incident 2026-09-01:** told Wes to fund a wallet and get Coinbase CDP keys. The funded wallet was already in
  `~/.agentcash/wallet.json` and the PayAI facilitator settles Base mainnet with no keys. This is why the
  three-step blocker proof exists.

---

## Delegation and Model Routing

- `fable-delegate-guard` and `capability-graph-guard` both live in `engine/hooks` and are installed by
  first-run.
- `capability-graph-guard` learns each subagent's model from `SubagentStart` and denies the Agent/Task/Workflow
  call that would cross an edge the graph does not have.
- Advisor pattern: "This subagent form is our own, capped and logged by capability-graph-guard." Anthropic's
  native advisor is documented at https://code.claude.com/docs/en/advisor. Anthropic documents the pattern
  (Sonnet plus Opus or Fable) as the way to use a stronger model cheaply.
- **Delegation economics, measured 2026-09-02:** the ~60k input tokens a subagent costs before its first tool
  call is the harness prompt plus the skill and tool catalogs. A one-line edit delegated to Sonnet cost 77k.
- **Incident 2026-06-12:** bare `agent()` calls inherit the main-loop model (Fable), which is how 110 Fable
  agents burned a 5h window. That is why every dispatch must name its model explicitly.
- Nesting rationale: "Reading a few files is not that; sweeping a repo or running a suite is." Depth two
  (Fable -> Opus -> Haiku) is the practical ceiling.

---

## Learned Rules

- The promotion gate was added 2026-09-01. Full original wording: "a candidate becomes an L-rule only after at
  least 3 signals across at least 2 distinct sessions, with signals older than 30 days counting half. One
  contradiction records; two clear contradictions demote. Each L-rule keeps its dated trail. Lessons from
  failures are stated as evidence ('when X broke, Y fixed it'), not as commands, so a hostile input cannot
  become a standing rule through a single session."
- L1 (2026-08-13) and L2 (2026-08-20) remain verbatim in the loaded file.
