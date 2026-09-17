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

---

## Cut on 2026-09-17 (second token pass, 28.3KB → ~20KB)

Evidence and attributions removed from the loaded file; every directive stayed.

- **Non-negotiables:** the trifecta rule was adopted from JDE Projects, 2026-09-03.
- **Core Philosophy 7:** written by Wes 2026-09-03 after an unlabeled storyboard tile and two targets asserted from memory that he had to correct.
- **How to Work, declick:** rule dated Wes 2026-09-03; `declick-nudge` reminds once per session when an MCP, WebFetch or Chrome read has an adapter; `declick add` lands the skill in every client. The fix-loop-never-edits-tests rule is dated 2026-09-03.
- **Delegation, fable-delegate-guard:** 2026-09-03, three delegated fix passes cost 3.7M tokens and two hours on defects a 40-minute hand pass closed, and the 8-edit budget fought that hand pass; 2026-09-06, the guard's own log held 1,046 events, 714 of them `# FABLE_OK` overrides, 266 shell denials (among them `npm test`, a heredoc commit message, a read-only grep) and edit denials retried five to seven times on the same file, because a model treats a deny like a transient error and retries the next queued edit. A hard block in a PreToolUse hook produces probing and half-applied changes; the briefing was the part that informed the routing decision.
- **Delegation, advisor:** consultations uncapped and always one rung above the caller, both Wes 2026-09-03; a blocked consultation becomes a guess, and a guess in a fix pass costs more tokens than the advice. Anthropic's native advisor: one global model, no per-caller escalation, no cap, reads the full transcript, skipped when weaker than the caller.
- **Delegation, budget guard constants:** three independent measurements: 15,746 weighted tokens median across 21 startup-only lean spawns recounted from raw transcripts, ~17k measured 2026-09-02, 18,664 observed live 2026-09-15 from a `haiku-scout` that made zero tool calls. Per-call cost is superlinear, so the shipped 2k per call is a floor that biases the guard toward allowing. Rule dated Wes 2026-09-15, after a one-line edit delegated to a subagent cost 77,000 tokens. The once-per-session denial exists because the fable-delegate-guard log showed a hard wall produces retries, not better routing.
- **Delegation, lean types:** measured 2026-09-02: lean ~17k per spawn, general-purpose ~60k, the default agentType ~24k more per spawn than a lean one.
- **Setup:** "push everything means all of them" is Wes, 2026-09-03.
- **Communication:** "decide, don't menu" promoted 2026-09-02 after 3 corrections; wes-voice rule Wes 2026-09-04 after a Reddit launch post had to be rewritten; platform ranking signals (X Phoenix weights, LinkedIn dwell and first-comment link, Reddit story-not-pitch, HN) Wes 2026-09-06: "did you do research on the algorithm or did you just wing it?".
- **ADHD section:** precedence paragraph Wes 2026-09-08; the skill's upstream is https://github.com/ayghri/i-have-adhd and the plugin is installed for Claude Code, Codex, Gemini, agy and Copilot.
- **Memory:** layout and tiers Wes 2026-09-11. Tier names: ROM = MEMORY.md (Claude Code loads only the first 200 lines or 25KB), RAM = context/ and daily notes, Disk = people/projects/decisions (tagged lines, struck lines never deleted), Tape = archive/ (documents enter whole). The recurrence gate's rationale: a hostile input can suggest a rule once, and once is never enough.
- **Learned Rules:** the promotion gate is dated 2026-09-01.
