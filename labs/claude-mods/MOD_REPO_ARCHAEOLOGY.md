# MOD_REPO_ARCHAEOLOGY — what the portfolio already contains, re-read through function hooks

Synthesised from seven parallel read-only archaeology passes over 111 local directories and 169 GitHub
repositories (`archaeology/A..G-*.md`, ~6,700 lines, every claim there cites a file and line). Ground
truth for "what a Mod can do" is `MOD_CAPABILITY_MAP.md` §20. Corrections to assumptions in the brief
are listed first because they change verdicts.

## Corrections to the brief's premises (verified by the agents)

| Assumption | Reality | Evidence |
|---|---|---|
| `rewind` = session replay / checkpoints | A Halo Infinite OBS instant-replay booth. Contains one transferable primitive (the **air gate**), no agent code. | `rewind/README.md:1-8`, modules `airgate, obs, editor, capture` |
| `codex-runtime-rnd` exists | Empty: no commits, only a DashClaw `state.json` written today | `git log` → "does not have any commits yet" |
| `C:\Projects\audit` = claude-code-audit | It is **receipt-recon** (expense auditor); claude-code-audit is a private GitHub repo (cloned) | `git remote -v` |
| `phone-claude` is its own project | It **is** SideTap (same remote) | `git remote -v` |
| `zentty`, `supergoal`, `nanoclaw-v2`, `picoclaw`, `orbit`, `archify` are Wes's | All forks/clones of other people's work | `gh api …/parent.full_name`, `git log --format=%an` |
| `claude-config` at `C:\Projects\claude-config` | The live harness is `C:\Users\sandm\.claude`; `claude-harness` is its public mirror | agent A |
| `discovery-loop-cvrp/-miplib-open` are repos | git **worktrees** of discovery-loop pinned 12 days back | `git worktree list` |

## The one sentence the whole portfolio keeps saying

Seven of the nine repos in cluster C, all 49 hooks in cluster A, all four cost tools in cluster D and both
governance transports in cluster B are **the same workaround: attack the session from outside because
nothing inside would answer.** Leg polls an OAuth usage endpoint with a token read off disk; the handoff CLI
says "the CLI cannot see the conversation — only you can"; `context-monitor.mjs` takes the context size as
`process.argv[2]`; the statusline writes a context percentage to `%TEMP%` so a Python hook can read it; four
transcript parsers recompute the same cumulative-usage dedupe; DashClaw holds a tool call hostage in a Python
subprocess for up to 3,660 s to wait for a human. What survives in every case is the **policy** (the 85 %
warn threshold, the promotion gate, the five-state anchor verdict, the 50 % instruction-distance rule, the
two-phase consent, the monitor→alert→block ladder). The plumbing is what function hooks delete.

Second recurring shape, arrived at independently in Python, Go, JS and Rust: **reserve-before / settle-after
ledgers** (`discovery-loop research_state.py`, `mole ledger.go`, `budget-aware cost-tracker.mjs`) and **a check
whose mechanism differs from the thing it checks** (`verification_contract.py`, `mole quote.go`, `solver br.rs`,
`guard-canary.ps1`, `enforcement_liveness_probe.py`). Both are exactly what a Mod needs and neither needs inventing.

---

## FORGOTTEN GEMS

The success criterion asked for at least three discoveries from repositories the brief did not name. There are
more than three; the strongest six, in the required form:

1. **AgentLens** (`ucsandman/AgentLens`, private, archived 2026-05). I found a **confidence-graded repeated-run
   detector** (`src/repeated-runs.js`: `high` = same target across ≥3 model requests, `low` = "inside one request, a
   batch not a loop") **plus five waste rules the surviving cost tool never absorbed** (`CONTEXT_GAPS_DETECTED`,
   `MODEL_DOWNSHIFT`, `CACHE_WRITE_BLOAT`, `SUBAGENT_PROMPT_BLOAT`, `REPEATED_READ_CYCLES`) and a subagent-ROI
   keep/trim/drop model. It originally solved "which repeated tool calls are a stuck loop and which a harmless
   batch" from a post-hoc SQLite ingest where the request boundary had to be guessed. Function Hooks change the
   equation because `tool.call` delivers the request boundary as an event (the grade becomes a fact) and
   `agent.spawn` delivers the whole subagent prompt (the bloat rule measures instead of estimating 200-char
   previews). Combined with **costclaw**, this becomes the day-one rule set of CostClaw LIVE, with costclaw's
   empirical 60 %/25 % share gates deleted because the hook no longer needs them.

2. **agent-pit** (`C:\Projects\agent-pit`, 163 commits, untouched since July). I found a **versioned
   event-stream replay format with a working dual-format playback controller** (`src/lib/replay-utils.ts`,
   `src/lib/replay-controller.ts`, 363 lines: play/pause/seek/speed), a 12-line seeded PRNG, a 300-match self-play
   **dominance gate** that exits 1 if any policy dominates, and a one-shot authenticated **coaching window** into a
   running agent's system prompt. It originally solved "prove the fight resolver has no solvable line before real
   money flows, and let spectators scrub a finished match". Function Hooks change the equation because
   `tool.call`, `turn.step` and `agent.spawn` emit exactly the frame-stamped event stream that format was designed
   to hold, so recording a Claude Code session into `EventStreamReplay` is a mapping, not a build. Combined with
   **Agent-Task-Router**, this becomes an arena that scores subagent configurations offline and feeds the
   dispatcher's `agent_metrics` table — routing by measured Elo instead of a model name typed into a prompt.

3. **Agent-Task-Router** (`ucsandman/Agent-Task-Router`). I found a **complete fleet dispatcher** — four-axis
   scoring (capability 40, free capacity 20, per-skill history 25, priority 15) with human-readable `reasons[]`,
   retry → timeout → escalate transitions, and a `routing_log` audit table — in 900 lines with no framework. It
   originally solved dispatch for a fleet of HTTP-addressable agents that never materialised. Function Hooks change
   the equation because `agent.spawn` can rewrite a subagent's model/prompt/type before launch and `turn.complete`
   reports duration, tokens and model per `agentId`: the two halves it was starved of (a dispatch it controls, a
   feedback signal it learns from) are both hook payloads. Combined with the live harness's four routing guards
   (`agent-model`, `subagent-budget`, `capability-graph`, `fable-delegate`), this becomes one routing Mod with a
   readable log instead of four guards reconstructing "who is calling, on what model" from transcript tails.

4. **clawd `hooks/`** (`ucsandman/clawd`, private, 75,005 files). I found **two finished hook implementations
   written two runtimes too early**: a budget-aware model router with four bands (normal / ≤30 % warn / ≤20 % Opus
   blocked / ≤15 % force-Sonnet) and exponential backoff with jitter (`hooks/smart-model-router/handler.ts` +
   `budget.ts`, 2026-02-05), and a sub-300 ms vector-memory prompt injector (`hooks/memory-injection/handler.js`,
   2026-02-08), both against `clawdbot`, plus a prose protocol that spends ~500 tokens every 5 messages polling
   context size. They originally solved "stop Opus burning the weekly budget on a status check" and "put the right
   memory in front of the model unasked". Function Hooks change the equation because `turn.step` rewrites model and
   effort **per request** and `$.session.usage()` returns context %, five-hour/seven-day % and cost USD natively,
   deleting `budget.ts`, its `capture.py` dependency and the 500-token poll. Combined with **Agent-Task-Router**,
   this becomes one router that picks the model by measured performance and refuses to spend above a band.

5. **context-health-bar** (`ucsandman/context-health-bar`, Chrome extension). I found an **instruction-distance
   drift model** (`calculateHealth()`: penalise when >50 % of the conversation sits after the last
   instruction-bearing message, `(distanceRatio − 0.5) × 80`, tiers stable/degrading/unreliable/critical) plus a
   salience-scored handoff packet. It originally solved "tell me when Claude has drifted, from outside, with nothing
   but the DOM". Function Hooks change the equation because `$.session.usage()` makes the length half exact and
   `$.session.messages()` makes the instruction half first-class, while `tool.call` adds the noise term the DOM
   could never see (a 4,000-line test dump displaces instructions harder than prose). Combined with **LegCli**, whose
   `chooseNext()` fires only on quota ≥85 %, this becomes a *quality*-triggered handoff: switch agents because the
   session drifted, a reason Leg's machinery is built for and has never had.

6. **leg-alexa-mcp `src/confirm.ts`** (`C:\Projects\leg-alexa-mcp`, hackathon scaffold). I found a **45-line
   server-enforced two-phase consent token** (preview + single-use 32-byte token, 5-minute TTL, bound to one
   session, invalidated by restart, "the server, not convention, enforces the pause"). It originally solved "a voice
   assistant must never kill a running coding agent on one misheard sentence". Function Hooks change the equation
   because a plugin **cannot draw the permission dialog**, so every Mod that flips an `ask` to `allow` on `tool.check`
   or performs an irreversible `$.fs`/`$.process` act must build its own pause — and this is that pause, already
   fail-closed, needing `$.store` for `Map` and `$.ui.ask` for the second call. Combined with
   **markdown-agent-memory**, whose promotion step is deliberately editorial and has no interface, this becomes the
   clickable gate for memory promotion.

Also gems, shorter: **2-part-memory-system** (a 45 %-of-window consolidation trigger whose only input was
`process.argv[2]` — the missing "moment" for markdown-agent-memory's unwatched 30,000-char RAM cap);
**spendwall `policy.ts`** (pure `evaluatePolicies` → allow/flag/needs_approval/block with a monitor→alert→block
ladder — the decision layer costclaw never had); **GroundLock TrueName** (DNSSEC-TXT split receipts, no server);
**AI-Agent-Governance-Compliance-Kit** (a working 666-line SOC2/ISO/GDPR/NIST mapper whose own README shows it
unbuilt); **vibes-governance-starter** (two independent human-flipped gates, `ENFORCEMENT_LIVE` + `OUTBOUND_MODE`,
both off by default — the rollout template for any governance Mod); **Agent-Reputation-Oracle** (a decayed,
confidence-weighted reputation engine whose event model maps 1:1 onto `agent.spawn` + `turn.complete`);
**stream/Railbird** (priority arbiter + exponential-decay attention heat + clock-scaled JSONL replay — the answer
to "many parallel subagents, one human, one pane"); **auto-docs** (a hash-keyed doc-staleness registry shipped with
an empty `registry.json`, installed and never run); **agnostic-agent `undo.py`** (named working-tree checkpoints
with rollback — Claude Code has no checkpoint primitive, which is why `git-tree-guard` must deny `git stash` and
talk the model through copying files by hand); **discovery-loop `verification_contract.py`** (24 hours old, three
verdicts, sticky FLAG, missing verdict ≠ pass — not forgotten, but not yet applied anywhere else).

---

## DIRECT MOD OPPORTUNITIES (concrete: event → hook → what changes)

Ranked by (evidence that the limitation is real) × (how much of the code already exists).

| # | Opportunity | Events | Existing code reused | Evidence the limitation is real |
|---|---|---|---|---|
| 1 | **Routing + budget as one Mod** replacing four guards; declared `# EST:` becomes measured; deny becomes rewrite | `agent.spawn`, `turn.complete`(agentId), `$.session.usage()`, `$.store` | `subagent-budget/calibrate.cjs` fitting; Agent-Task-Router `matcher.js`; clawd `budget.ts` bands; `budget-aware makeDecision` reason codes | `fable-delegate-guard` log: 1,046 events, 714 overrides, edit denials retried 5–7× ("a model treats a deny like a transient error"); `capability-graph-guard` keeps an `agent_id→model` registry because SubagentStart carries `subagent_config: null` |
| 2 | **Detection → redaction** for secrets in tool results and streamed text | `tool.call` result replacement, `turn.step` text chunks | `secret-guard.cjs` patterns; `capsule.mjs scanForSecrets`; `offlocal sanitizeDashclawText` | both watchers' headers: "This DETECTS, it does not redact… by the time PostToolUse fires the result is already in the transcript"; 2026-09-06 `env \| grep ANTHROPIC` incident |
| 3 | **CostClaw LIVE** plugged in at `rebuildSessionUsage()` (already exported); 6 of 8 rules live; `windows.ts` deleted; thrash interceptor answers the 11th identical Read from cache | `turn.step` usage, `tool.call`, `agent.spawn`, `$.session.usage()` | costclaw `pricing.ts` (zero changes), `parser.ts:210`, AgentLens `repeated-runs.js`, spendwall `policy.ts` | four independent JSONL parsers on one machine; `calibrate.cjs` admits mirroring `read-sessions.ts`; $227 + $95 incidents with "zero cost visibility" |
| 4 | **DashClaw native adapter**: `tool.call` → ported `classifyAct` + 15 pure evaluators → deny; `tool.check` as the approval seam; subagent `delegation_constraint` made real | `tool.call`, `tool.check`, `agent.spawn`, `$.clock.every`, `$.prompt.submit` | `app/lib/guard/evidence.ts` (858 lines, zero imports), `risk.ts`, `containment.ts`, 15 evaluators, 20 policy packs | today: Node probe + 2,625-line Python parse + 2 HTTPS round trips per governed call; 3,660 s hook timeout; temp-file IPC between pre/post hooks; settings.local.json mutated at SessionStart |
| 5 | **"Is this production?" before every Bash** = offlocal `evaluatePolicy` × DashClaw `classifyAct` | `tool.call`, `prompt.submit` banner, `ui.render` footer | `offlocalai-mcp/src/policy.ts` (pure, 60 lines), `dashclaw/guard.ts` mapping | offlocal has **zero** matches for `--prod`, `wrangler`, `git push`: it governs only its own 124 MCP tools |
| 6 | **Safe-boundary handoff** in Leg: warn at ≥85 %, act at `turn.complete`, `$.turn.abort()` instead of `killTree()`; Leg finally sees subagents | `turn.complete`, `$.session.usage()`, `agent.spawn` | `leg/src/usage.mjs` (lock-safe limit state), `resume.mjs`, `synthesis.mjs`; a sixth tap `src/taps/mod.mjs` through the existing `recordUsage/markLimited/updateSession/appendEvent` | `attach.mjs` kills mid-edit; `claude.mjs:72 if (j.isSidechain) continue` discards every subagent line; OAuth token read off disk to poll usage |
| 7 | **Flight-recorder handoff bundle**: anchors + line ranges + hashes captured at read/write time; one small-model finding per turn; bundle survives a crashed session | `tool.call`, `turn.complete`, `$.model.complete`, `$.session.repo()`, `$.clock.every` | context-handoff-bundle `anchors.py` (`hash_anchor_content`, `link_evidence`), `drift.py`, `resume.py`; Leg's `handoff.mjs` seam | `commands/handoff-save.md`: "The CLI cannot see the conversation — only you can"; the 3 % token claim is a `chars/4` size ratio, never measured |
| 8 | **Memory candidate feed** into the RAM tier only, `[observed]` only, `[stated]` only from `prompt.submit origin=composer`; consolidation triggered at 45 % of window before compaction | `tool.call`, `turn.complete`, `prompt.submit`, `$.session.compact()` | markdown-agent-memory lint (unchanged), 2-part-memory-system trigger policy, leg-alexa `confirm.ts` for the promote button | RAM cap of 30,000 chars "that no process watches"; promotion gate is prompt-injection defence and must stay editorial |
| 9 | **giti at the edit**: fragility + coupling as hidden context on Edit/Write; `ask` above a regression threshold; `_dead_ends.json` on `prompt.submit` | `tool.call`, `tool.check`, `prompt.submit`, `$.process.run("git log")` once per session | `file-analyzer.ts` (`getHotspots`, `getFileCouplings`), `fts.ts` (dependency-free TF-IDF), `curator.ts` thresholds | giti has no MCP server; knowledge answers only when a human types `giti hotspots`; `organism.json` forbids touching the target repo |
| 10 | **declick as enforcement, not nudge**: answer `mcp__*` calls with the declick envelope without `next`; `capData()` on every tool result; `policy.json` on `tool.check`; register one `declick` tool from manifests | `tool.call`, `tool.check`, `tool.describe`, `$.tool.register`, `$.process.run` | `src/output.mjs` (251 lines, zero imports), `describe.mjs`, `policy.mjs`, `guard.mjs derivedMutating` | `~/.declick/hooks/nudge-stats.json`: **36 nudges, 2 followed, 34 ignored (5.6 %)**; `web` fired 23×, followed 0× |
| 11 | **Discovery Loop observations from runtime events** (not confirmations): field map onto `research_memory._development_entry`; `family` = intervention class; `BudgetLedger` reserve/settle on `agent.spawn`/`turn.complete`; `RoutingJournal` breakers on `turn.step` | `tool.call`, `agent.spawn`, `turn.step`, `session.*` | `research_memory.py`, `research_state.py:114`, `routing.py`, `verification_contract.py` | `compare_paired` needs ≥3 seeds on a rectangular matrix: a live session has no seed and no incumbent arm — runtime events are observations, never confirmations, without a replay harness |
| 12 | **Git-for-agent-execution (honest scope)**: record + replay-against-recorded-results + compare + debug + file-restore; never transcript restore or deterministic model re-run | `on("*")`, `tool.call` answer-without-next, `next.trace`, `$.fs.*` | agent-pit `replay-*.ts`, agnostic-agent `undo.py`/`watchdog.py`, mole `crossing.go` record shape | see the six-row table in `archaeology/F-*.md §2` |
| 13 | **Capsule doctor continuous** + live secret tripwire on Write | `$.clock.every`, `tool.call` | `capsule.mjs runDoctor` (prints N/M), `scanForSecrets` | pack-time scan fires hours after the key was written |
| 14 | **Agent-comms delivery + wake**: attach unread mail at `prompt.submit` (only on a hit, with count); `$.prompt.submit()` on `[URGENT]` | `prompt.submit`, `$.clock.every`, `$.prompt.submit` | `inbox.mjs` | the rule "check the inbox at session start" is a rule the model can forget; HEARTBEAT.md has never had an event source |
| 15 | **mole toolkit without prompts**: `$.mcp.call("mole.verify_quote")` on claim-shaped results; deny Read/Bash on connector paths and route to `mole.aggregate` | `tool.call`, `$.mcp.call`, `ui.render` crossing pane | mole toolkit (14 tools), `crossing.go` record shape | the only mechanism found that **enforces** the trifecta rule instead of asking an agent to remember it |

---

## IDEAS WORTH STEALING (policy and shapes, independent of code)

- **Fail-closed vs fail-open, kept explicit.** agnostic-agent's `guards.json` fails closed (a vanished policy file is an attack); the Claude harness guards fail open (a crashed regex is a bug). Both are right; a Mod must state which it is. (A)
- **The air gate** (`rewind/airgate.py`, 74 lines, clock-injected, tested): hold a notice until a quiet moment, force on a hard signal, degrade to picture-in-picture instead of dropping when the hold expires. Every Mod nag (context 80 %, budget low, guard fired) should go through it. (F)
- **Containment instead of denial** (DashClaw `containment.ts`): a provably file-/db-scoped act is redirected into a worktree or ephemeral branch; a human promotes or discards later. `tool.call` argument rewrite is exactly `updatedInput` without the stdout JSON protocol. (B)
- **Two independent human-flipped gates, both off by default** (vibes-governance-starter, DashClaw `HOOK_MODE=observe`, offlocal, Off Localhost's headline promise): the default mode of every governance Mod. (B)
- **Escrow** (mole `escrowFor`): reserve part of the five-hour window for the turn that writes the answer; start denying spawns and downshifting models when the unreserved part is gone. (E)
- **Reserve-before / settle-after / charge the full reservation when cost is unknown** (discovery-loop, mole): a failed subagent that burned 40k tokens and returned nothing charges 40k. (E)
- **Three verdicts, sticky FLAG, missing verdict ≠ pass** (`verification_contract.py`): use verbatim in any Mod that asks `$.model.complete` to judge anything. (E)
- **A check whose mechanism differs from what it checks** (solver `br.rs`, `guard-canary.ps1`, `enforcement_liveness_probe.py`): a Mod claiming a saving measures it from `$.session.usage()` deltas, never from its own count of what it suppressed; a Mods leg for the canary must exist **before** any guard moves. (A, E)
- **Print the denominator** (`runDoctor` "N/M pass", `gitradar` loud ERROR rows instead of zeros, memory-lint volumes): `$0.00 spent` and `the usage call failed` must not look alike. (D, F)
- **Confidence-graded evidence** (AgentLens): only `high` may produce a dollar figure. (D)
- **Reason codes shipped with every automatic decision** (budget-aware `makeDecision`, Task-Router `reasons[]`, DashClaw `RiskBreakdown`): a downshift the user cannot see the reason for is worse than none; render in the footer. (E, F)
- **Derived-only persistence** (claude-code-audit `store.ts`): `$.store` holds metrics and prose, never transcript text. (D)
- **Audit rows that never contain the sensitive value** (mole `crossing.go`, envdoctor, declick `redactArgs`, capsule bundles carry key names never values). (E, G)
- **Smooth small drift, snap past a threshold, hold the seat on disconnect** (husky-raid) for any Mod keeping derived state over `$.session.messages()` across a compaction. (G)
- **Arbiter + heat + replay** (Railbird) for which subagent gets the human's one pane. (G)
- **One git worktree per concurrent long job** (discovery-loop's three worktrees) so champions cannot clobber each other. (E)
- **Preflight before you gate** (sentinel-api `/health` before payment): verify the precondition before returning `allow`, hide a capability whose precondition is unmet (`agent.offer`). (G)

---

## PROJECTS THAT SHOULD MERGE (under Mods)

| Merge | Into | Why |
|---|---|---|
| `spend.cjs`, `subagent-budget/calibrate.cjs`, `tokflow/*` (session-scoped half of `~/.claude/tools`) + AgentLens's five rules + spendwall `policy.ts` | **CostClaw LIVE** | four parsers of one JSONL become four *views* of one `turn.step` accumulator; costclaw computes, spendwall decides, AgentLens grades |
| `agent-model-guard`, `subagent-budget-guard`, `capability-graph-guard`, `fable-delegate-guard` + Agent-Task-Router scorer + clawd router bands + budget-aware reason codes | **one routing Mod** (part of the shared runtime adapter) | all reconstruct the same two invisible facts; `agent.spawn` carries both and lets them be rewritten |
| `context-nudge.py`, `session-count.cjs`, `skill-telemetry.py`, `statusline.ps1` + `%TEMP%` IPC, `opus-handoff-inject.cjs` | **`$.session.usage()` + one `ui.render` footer** | every field they smuggle is a call away |
| `batch-guard`, `repeat-tool-guard` (three wirings), `scope-lock` (two halves) | **in-memory streak counters in one Mod** | they exist because a subprocess has no memory |
| claude-commands `/handoff-*` | **context-handoff-bundle** (or a Mod that registers them) | thin shells over one CLI |
| 2-part-memory-system's trigger | **markdown-agent-memory** | the policy has no moment; the trigger has no policy |
| tokentrail, claude-code-audit engine | already merged into costclaw; retire the copies | lineage recorded in `optimizer.ts:1-7` |
| DashClaw's 42 KB Python bash classifier | retire in favour of `evidence.ts` | two copies of one risk model |
| `dashclaw-guardrails` evaluator, Compliance Kit mapper, vibes-governance gates | **DashClaw Mod adapter** as its rollout posture and evidence layer | already absorbed once (`guardrails/evaluator.ts` header) |
| agnostic-agent `governance/` (undo, watchdog, interceptor, guards.json, READ_ONLY_ROLES) | **the Mods layer** (keep the Python agent) | five primitives Claude Code lacks |

## PROJECTS THAT SHOULD STAY INDEPENDENT

`claude-harness` mirror (publication, not runtime); `markdown-agent-memory` (editorial policy Mods must not automate — gains one narrow feed); `context-engine` (5 days old, gated commercial service, recall unmeasured); `mole`, `x402watch`, `sentinel-api`, `spendwall`, `offlocalhost`, `solver` (live products / other rails / different runtimes); the machine-scoped harness tools (`gitradar`, `cronwatch`, `envdoctor`, `recall`, `procledger`); `gate-freeze`, `guard-canary`, `creds-resolve`, `enforcement_liveness_probe` (the ring that verifies everything else must sit outside the layer it verifies); `agent-capsule` as a CLI (Mods only make its checks continuous); `leg-alexa-mcp`'s transport; `discovery-loop`'s Docker/seeded experiment machinery; `clawd` workspace (personal store).

## PROJECTS MODS MAKE LESS RELEVANT

`DashClaw-astra-audit` (stale working copy); `claude-code-audit`, `tokentrail` (superseded by costclaw twice); `PulseGate`, `recall-sweep` (name collisions, consumer products); `dashclaw-agent` (an agent nagging an agent to self-police is the workaround hooks remove); `nanoclaw-v2`, `picoclaw` (forks; compensate for SDK blindness a Mod host does not have); `codex-runtime-rnd` (empty); `rewind` as a repo; `ufo` in its current Managed-Agents form; `claude-code-capability-primer`'s current *content* (documents the surface Mods supersede) though its mission gains; costclaw's `windows.ts` rate-window inference and `read-sessions.ts` (deleted, not ported); every `hooks-gen`-style generator of classic hooks (blocked for user plugins on this machine).

## PROJECTS MODS MAKE MORE IMPORTANT

**Live harness** (49 incident-born rules survive; 1,099 ms/`echo` of mechanism does not), **agnostic-ai** (the only place that can declare the capability asymmetry Mods create — `supports.*` is missing from all 20 targets today; the four flags that matter most are false everywhere and Mods flip them for one client), **DashClaw** (policy engine gains a real enforcement point; transport deleted), **offlocalai-mcp** (pure policy extends over the 90 % of production acts that never touch an MCP tool), **LegCli** (owns the launch; gains subagents and safe boundaries), **context-handoff-bundle** (its limiting sentence is repealed; schema/drift survive), **costclaw** (engine already pure; polling deleted), **AgentLens** (revive), **Agent-Task-Router** (revive), **agent-pit** core (revive), **giti** analyzers + memory (revive; organism less relevant), **agent-comms**, **agent-capsule**, **declick** (compiler stays; the Mod is its enforcement arm), **creds** (ambient resolution on `tool.call` retry), **frontend-verify** (result replacement makes "done" unclaimable over a broken route), **context-health-bar** (revive as a Mod, keep the extension), **mole** toolkit mode, **discovery-loop** judgment layer, **auto-docs** (revive as a Mod), **dashclaw-guardrails**, **Compliance Kit**, **vibes-governance-starter**, **Agent-Reputation-Oracle** (as a reference implementation), **stream/Railbird** triad, **supergoal** (fork, but its prose loop is `turn.complete` + `$.store` + `$.prompt.submit` faked).

---

## Cross-cluster combinations the agents found (feeding PORTFOLIO_RUNTIME_MAP.md)

- DashClaw `evidence.ts` × offlocal `evaluatePolicy` → production awareness of shell commands (neither project wired this; the only link today is offlocal sending its own tool calls to DashClaw).
- Three receipt anchors (DashClaw Ed25519 JSON, GroundLock DNS-TXT, TreasuryClaw calldata) → one canonical decision object anchored wherever the operator turns on.
- `guard-canary.ps1` × `enforcement_liveness_probe.py` × `$.clock.every` × `next.trace` → a self-verifying policy layer with a visible "enforcement is live" badge.
- Leg × context-health-bar → quality-triggered handoff; Leg × synthesis × markdown-agent-memory → "ruled out" as the memory folder's intake pipe.
- context-handoff-bundle × context-engine → every saved bundle is a free labelled relevance set (recall@k that the SPIKE-REPORT lists as unbuilt).
- agent-pit × Agent-Task-Router → offline Elo feeding a live dispatcher; × agent-capsule → a dominance gate for harness configurations ("did that new hook actually help?").
- giti couplings × discovery-loop `_dead_ends.json` → the two facts a fresh session always re-derives, delivered at the edit.
- mole `crossing` × giti hotspots → one pane answering "what did you break" and "what did you send".
- declick audit bytes × `$.session.usage()` → tighten `--max-bytes`/`--limit` as context fills.
- costclaw × spendwall → a number becomes a verdict; × `subagent-budget` → the guard gets an enforcement ladder and a `needs_approval` tier.
- `undo.py` × `git-tree-guard` → deny the stash, offer `/checkpoint`.
- AirGate × sidelook/agent-comms → approvals and mail that never interrupt a thought and never rot.

## Findings for Wes, not acted on

- `C:\Projects\git-intelligence\.env` (877 B) is checked into the repo root (not opened).
- `Agent-Reputation-Oracle/README.md` contradicts itself ("not deployed" vs a live Railway instance on Base mainnet).
- The statusline's wiring point (`statusline-combined.ps1`) was not found in any settings file; it is the managed `C:\Program Files\ClaudeCode\managed-settings.json` (found in Phase 1) — and that same file is why `sec-default` withholds `classic.*` from user plugins.
- `precompact-extract.cjs` reads `evt.transcript || evt.content`; whether PreCompact carries either is unverified (L2 risk).
- `codex-runtime-rnd` and `hoop` are empty directories.
