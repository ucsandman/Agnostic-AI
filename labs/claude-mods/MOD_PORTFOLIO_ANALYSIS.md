# MOD_PORTFOLIO_ANALYSIS: what function hooks do to each project

Phase 4. Sources: `MOD_CAPABILITY_MAP.md` (build 2.1.273, verified ground truth), `MOD_REPO_ARCHAEOLOGY.md`, the
seven cluster reports `archaeology/A-*.md` … `G-*.md`, and `lab/README.md`. No repository was re-read for this
document; every file path below is quoted from a report that cites it.

## How to read the status tags

| Tag | Meaning | Source |
|---|---|---|
| (CONFIRMED) | observed in a live run this sprint | §20 "CONFIRMED WORKING [RUN]" |
| (EXPERIMENTAL) | declared in `claude-code.d.ts` or the loader, not exercised | §20 "PRESENT BUT EXPERIMENTAL" / "INCOMPLETE" |
| (NOT POSSIBLE) | refused, withheld on this machine, or absent | §20 "NOT CURRENTLY POSSIBLE" |

Three conventions follow from §20 and apply throughout. **`$.store` and `$.clock.every` are (EXPERIMENTAL)**, so
cross-session state is written with `$.fs.write` (CONFIRMED) and cadence hangs off `turn.complete` (CONFIRMED).
**`$.fs.write` is (CONFIRMED) but `$.fs.read` is not** (§2c names `fs.write` among the op events seen live, not
`fs.read`), so session-start file reads use `$.process.run` (CONFIRMED). **`$.model.classify` is (CONFIRMED);
`$.model.complete` and `$.model.fork` are not.**

**Two source conflicts, reported and not resolved.** `lab/README.md` exercises two capabilities §20 still lists
as [DECL]: `$.ui.ask` (§10 records it rejecting in `-p`; the MATRIX demo reports it opening the engine's
AskUserQuestion dialog with on-screen proof, `⏸ FROZEN #1 … ▶ released after 28321ms`) and `$.store` (the X-RAY
plugin reports `/xray` filter state persisted across sessions). Probably the map lagging the lab, but the map is
the stated ground truth, so both are tagged (EXPERIMENTAL) here and neither appears in any demo below. §10 and
§20 should be reconciled against the Phase 3 payloads before anything ships depending on either.

---

## claude-harness (the live `~/.claude` harness)

### CURRENT ARCHITECTURE

A policy engine assembled from 49 stateless subprocess invocations across 10 lifecycle events
(`A-harness-agnostic.md` §1: PreToolUse 19, PostToolUse 6, PostToolUseFailure 1, Stop 6, SessionStart 7,
UserPromptSubmit 6, MessageDisplay 1, SubagentStart 1, SubagentStop 1, PreCompact 1), wired in
`C:\Users\sandm\.claude\settings.json`. 26 guards in `hooks/*.cjs`, two of which (`fable-delegate-guard.cjs`,
`capability-graph-guard.cjs`) live in `C:\Projects\agnostic-ai\engine\hooks\` and are loaded by absolute path.
21 instruments in `tools/`, 6 agent types, 4 workflow scripts. `statusline.ps1` is the only component the host
hands `context_window.used_percentage`, `rate_limits.*` and `cost.total_cost_usd` (`statusline.ps1:112-145`).

### CURRENT LIMITATION

| Property | Consequence |
|---|---|
| Stateless per event | nine side files fake memory: `.fable-spawn-counts.json`, `.subagent-budget-{denials,spawns}.json`, `corrections.jsonl`, `logs/batch-guard.log`, `%TEMP%\claude-repeat-guard\`, `~/.declick/hooks/nudge-stats.json`, `opus-handoff-injected/<session>` |
| The model is invisible | four reimplementations of one four-step model ladder (`agent-model-guard`, `fable-delegate-guard`, `capability-graph-guard`, `opus-handoff-inject`); the last reads 256 KB of transcript by fd on every UserPromptSubmit |
| Context and cost are invisible | `statusline.ps1:215` writes `%TEMP%\claude_ctx_<session_id>.txt` so `hooks/context-nudge.py` can read a number the hook API never gives it; 90 such files exist, 5 written today |

Measured price: core median **1,099 ms** for a whole `tool.call` on `echo` (min 808, max 4,556) where the echo is
~50 ms; the same event from a function hook is **+0.1 ms** (§21).

### WHAT MODS CHANGE

| Guard | Event | Change | Status |
|---|---|---|---|
| `agent-model-guard`, `capability-graph-guard` | `agent.spawn` | stop denying, start rewriting the model | rewrite CONFIRMED (forced to haiku, `agentId` returned) |
| `subagent-budget-guard` | `agent.spawn` + `turn.complete` | the declared `# EST:` becomes a measurement | `agentId` on `turn.complete` with usage CONFIRMED |
| `tool-output-secret-watch`, `output-secret-watch` | `tool.call` | detection becomes redaction | result replacement after `next` CONFIRMED |
| `batch-guard`, `repeat-tool-guard`, `scope-lock` | `tool.call` | streak counters become variables | in-memory state across events CONFIRMED (306 events) |
| `context-nudge.py`, `session-count.cjs`, `statusline.ps1` | `session.start` + `ui.render` | one call replaces the `%TEMP%` channel | `$.session.usage()` CONFIRMED (7 % ctx, 11 % 5h, $0.31) |
| `process-kill-guard` | `tool.call` | rewrite a name-based kill into the PID form instead of denying | argument rewrite CONFIRMED |
| eleven override markers (`RM_OK`, `SEQ`, `GATE_OK`…) | `$.command.register` | magic comment strings become logged commands | CONFIRMED |

### WHAT MODS DO NOT CHANGE

The 49 rules. Every one is a dated incident and none expire; the mechanism expires, not the policy. The outer
verification ring stays classic and stays outside anything it verifies: `hooks/gate-freeze.cjs`,
`hooks/guard-canary.ps1`, `hooks/creds-resolve.cjs` (touches secrets, belongs outside the sandbox) and
`C:\Projects\DashClaw\hooks\enforcement_liveness_probe.py`. `secret-guard.cjs`'s patterns,
`slopsquat-guard.cjs`'s `INSTALLERS` table and `rm-guard.cjs`'s `segments()`/`stripWrappers()` command-position
parsing are the assets; the dispatch is not.

### WHAT BECOMES OBSOLETE

`context-nudge.py` and the `%TEMP%\claude_ctx_*` IPC channel; `session-count.cjs` (walks
`~/.claude/projects/**/*.jsonl` mtimes to approximate a rate limit `$.session.usage()` returns);
`skill-telemetry.py` and its byte-offset transcript cursor; `opus-handoff-inject.cjs`'s whole detection stack;
`batch-guard.cjs`'s 128 KB transcript re-read per call; the PowerShell `SoundPlayer` turn-end ping.
`hooks-gen`-style generators of classic hooks are dead for user plugins here: hooking `classic.*` from the user
tier on a managed-settings machine is (NOT POSSIBLE).

### WHAT BECOMES SIMPLER

Model resolution collapses to `$.session.model()` plus `turn.step`'s per-request `model` (CONFIRMED).
`scope-lock`'s two halves become one object because the prompt handler and the tool handler share memory.
`dev-server-guard`'s real failure (663 orphaned tsserver children) becomes a teardown at session end rather than
a reminder. `slopsquat-guard`'s 4 s blocking registry lookup becomes an in-process `$.http.fetch` with a
pre-warmed cache.

### NEW PRODUCT CAPABILITIES

1. Redaction where there was only detection. `tool-output-secret-watch.cjs`'s header says "by the time
   PostToolUse fires, the result is already in the transcript"; `tool.call` replaces the result the model
   receives after the real tool ran (CONFIRMED; it even replaced an error result).
2. `forced-verify-stop-gate.cjs` becomes real. Today it greps one message for the word "verification" and only
   under `STOP_GATE_MODE=enforce`; with the session's tool-call history in memory, "did a test actually run since
   the last edit" is an exact question (CONFIRMED).
3. `dynamic-recall.cjs` stops being a three-regex table. It is three rules because a bigger one costs a process
   per edit; in-process it becomes retrieval with `$.model.classify` (CONFIRMED) choosing the rule.
4. `next.trace` (CONFIRMED) makes the guard chain observable per link with ms and outcome. No classic hook can
   see another hook at all.

### LONG TERM ARCHITECTURE

One runtime-adapter Mod holding the guards as pure functions over one event chain, with the policy files
(`hooks/security-tiers.json`, `tools/gates/gate-manifest.json`) unchanged; the classic layer retained only for
the ring that must survive a compromised plugin layer; the statusline and every cost instrument replaced by one
`ui.render` band fed by one accumulator.

### COMPATIBILITY RISKS

- The API is early access and undocumented; `hooks.json.surface` was already replaced once by `Client({module})`,
  so this surface has had at least one breaking revision (§19).
- `classic.*`, `prompt.section`, `prompt.context`, `skill.prompt`, `attribution.text` and `settings.read` hooks
  are withheld from the user tier here because `C:\Program Files\ClaudeCode\managed-settings.json` exists and
  `sec-default@builtin` does `next.to(e,"append")` (NOT POSSIBLE). A Mod cannot wrap the 49 entries; it must
  reimplement them, so during migration both layers run and both costs are paid.
- The permission dialog cannot be drawn (NOT POSSIBLE): `$.ui.notice` adds a line under it, and that is all.
  Registered-tool results must be `string | content-block[] | undefined` (§8). One hooks module per plugin.
- Project-specific: `guard-canary.ps1` needs a Mods leg **before** any guard moves or the migration is verified
  by assertion; the statusline's wiring point was not found in any settings file (`A-*.md` §1) and must be
  located before `statusline.ps1` is removed.

### ONE "HOLY SHIT" DEMO

Run `env | grep -i "^ANTHROPIC"`. The command runs for real, a dim line reads `⟦redact⟧ 1 secret replaced in Bash
result`, and the model's next message quotes `ANTHROPIC_API_KEY=<redacted by hook>` because that is all it
received. The key never enters the transcript, which is the exact 2026-09-06 incident today's guard can only
report after the fact. (CONFIRMED: `tool.call` result replacement, `$.ui.log`.)

### ONE PRACTICAL NEAR TERM FEATURE

One `ui.render` band on `AbovePrompt` (CONFIRMED) carrying context %, five-hour and seven-day rate-limit %, cost
USD and turn count from `$.session.usage()` (CONFIRMED). It subsumes `statusline.ps1`, `statusline-combined.ps1`,
`context-nudge.py` and `session-count.cjs`, and deletes the `%TEMP%` IPC channel in the same change.

### ONE SPECULATIVE FUTURE FEATURE

Close the `corrections.jsonl` loop. The tracker records what Wes said but not what the agent did to earn it; with
`$.session.messages()` (CONFIRMED) the preceding assistant turn joins the record, and the harness gains its first
instrument that can say which rule stopped a bucket accruing.

---

## Agnostic AI

### CURRENT ARCHITECTURE

A client-neutral harness bundle plus a per-client renderer. `core/templates/targets.json` registers 20 clients;
`engine/harness/{capture,apply,bundle,status}.cjs` do capture → bundle → apply → report;
`engine/harness/targets/{claude,codex,gemini,agy,cursor,generic}.cjs` are the six renderers (14 targets fall
through to `generic`); `engine/hooks/shim.cjs` (16.5 KB) runs an unmodified Claude Code hook under
cursor/gemini/agy by translating the payload in and the decision back; `engine/hooks/universal-adapter.cjs`
normalises 10+ client payloads into `{client, event, toolName, command, targetFile, args, raw}` with a four-verb
event vocabulary (`universal-adapter.cjs:4-14`).

### CURRENT LIMITATION

There is no runtime-capability contract. A target is a path map plus a dialect name; capability is encoded three
ways, all implicit (field presence, `adapter`, `dialect`), and nothing checks the three agree. Exactly 5 of 20
targets have any hook surface. The four flags that matter most for a governed harness,
`supports.resultMutation`, `supports.uiInjection`, `supports.contextSignals`, `supports.usageSignals`, are
**false for every target today** (`A-*.md` §3). The system discovers a gap by attempting the write and recording
the failure (`apply.cjs:209`, `GLYPH.unsupported = '-'`). That is a report, not a contract.

### WHAT MODS CHANGE

Mods flip all four flags for exactly one client: `resultMutation` via `tool.call` result replacement
(CONFIRMED), `uiInjection` via `ui.render` on 10 observed components (CONFIRMED), `contextSignals` and
`usageSignals` via `$.session.usage()` (CONFIRMED). This repo is the only place in the estate that can represent
that asymmetry instead of hiding it: a `supports` object in `targets.json`, a row in
`engine/harness/README.md`'s field table, and `capabilitiesOf(client)` beside `detectClient()`.

### WHAT MODS DO NOT CHANGE

Mods are a Claude Code feature and cannot be ported, which is the opposite of this repo's purpose. The 15
rules-file-only targets stay rules-file-only. `shim.cjs`'s hard-won facts survive verbatim: Gemini and agy merge
every hook result for one event and **the last reason wins**, so all guards for one `(event, matcher)` pair chain
in one entry with `++`; Gemini's `BeforeTool` has no "ask" at all (`shim.cjs:337`). `targets/codex.cjs`'s
`selfTestTrustHash()`, which reproduces Codex's own `trusted_hash` so a ported hook is live on the next run, is
unaffected.

### WHAT BECOMES OBSOLETE

Nothing in the porter. For the Claude target only, the shim's pre-tool/post-tool translation stops being the
delivery path once a Mod variant of a guard exists, but the shim stays for the other four hook-capable clients.
It becomes a second rendering, not a replacement.

### WHAT BECOMES SIMPLER

`universal-adapter.cjs` is already where any client's payload becomes one object, so it is the natural home for a
`model` field every guard reads instead of deriving. The Claude branch of that resolver becomes
`$.session.model()` while Codex/Gemini/agy keep their measured payload archaeology: one change that removes the
four duplicate ladders in the live harness and gives three other clients the same field for free.

### NEW PRODUCT CAPABILITIES

One capture, two renderings, one recorded reason per drop: `apply.cjs` checks `supports.*` **before** writing and
drops with a declared reason instead of discovering the gap, and `status.cjs` renders negotiated-versus-achieved.
The porter becomes honest about a gap it currently cannot express.

### LONG TERM ARCHITECTURE

`capabilitiesOf(client)` as the single declaration, consumed by `apply.cjs`, `status.cjs` and `shim.cjs`; a guard
authored once in the Claude dialect and compiled to a Mod for Claude Code and to a shim invocation elsewhere;
`engine/harness/README.md`'s bundle shape (`manifest.json`, `rules.md`, `hooks.json`, `mcp.json`, `agents/*.md`,
`commands/*.md`, `skills.json`, `permissions.json`) as the neutral IR.

### COMPATIBILITY RISKS

- Early access and undocumented; a `supports` contract written against it needs re-verification per build.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here), so the Claude rendering cannot assume the classic dialect it captures from.
- The permission dialog cannot be drawn (NOT POSSIBLE), so `supports.dynamicPermissions` for Claude stays partial
  even under Mods. Registered-tool results must be `string | content-block[] | undefined`; one hooks module per
  plugin.
- Project-specific: `fable-delegate-guard.cjs` and `capability-graph-guard.cjs` are authored here and loaded by
  the live harness by absolute path, so agnostic-ai is a hard runtime dependency of the harness while presenting
  itself as a porter. Migrating either is a cross-repo change.

### ONE "HOLY SHIT" DEMO

Type `/supports`. A registered command prints the target table with the Claude row filled in from the running
engine rather than the registry: `resultMutation true (measured)`, `usageSignals true (ctx 7 %, 5h 11 %, $0.31)`,
each line carrying the event that proved it. The porter's claims are being read off the client instead of
asserted about it. (CONFIRMED: `$.command.register`, `command.run` on a registered command, `$.session.usage()`,
`tool.call` observation.)

### ONE PRACTICAL NEAR TERM FEATURE

Add `supports: {}` to all 20 entries in `core/templates/targets.json`, document it in the README field table in
the same change, and have `apply.cjs` drop with a declared reason. No Mod code required; it is the prerequisite
for everything else here.

### ONE SPECULATIVE FUTURE FEATURE

Capability negotiation at runtime: the Claude adapter declares the four flags true only when the Mods plugin is
installed and loaded, verified by a probe rather than by configuration, so a harness that silently lost its
plugin reports as a lesser target instead of pretending.

---

## DashClaw

### CURRENT ARCHITECTURE

A multi-tenant policy decision point returning one of five verdicts (`allow` / `warn` / `allow_contained` /
`require_approval` / `block`) with a risk derivation ledger. Three separable layers:
`app/lib/guard/evaluate.ts:59` `evaluateGuard` (needs Postgres and an `orgId`), `app/lib/guard/policy.ts:300`
`POLICY_EVALUATORS` (20 types, **15 pure synchronous functions**), and `app/lib/guard/evidence.ts` (858 lines,
**zero imports**, `classifyAct` over `shell|http|sql|file`). Two Claude Code surfaces run at once: a plugin with
classic shell hooks (PreToolUse timeout **3660 s**) and an MCP server with 17 tools whose own description calls
the flow "cooperative policy and audit".

### CURRENT LIMITATION

Every governed tool call pays a Node launcher that probes for `python3` vs `python` (cached a day in a temp file
because the probe was "a whole extra process per tool call"), then a Python process parsing a 2,625-line script
plus a 42 KB bash classifier, then one or two HTTPS round trips. Verdicts travel as exit codes.
`require_approval` polls `GET /api/actions/<id>` every 3 s **inside the blocked hook subprocess**, which is why
the timeout is an hour. `dashclaw_scope_sync.py` mutates `.claude/settings.local.json` at SessionStart and cannot
express allowlists. Pre/post hooks talk through `%TEMP%/…<tool_use_id>.json`. And the MCP path is advisory: a
model that skips the tool is ungoverned.

### WHAT MODS CHANGE

| Today | Under Mods | Status |
|---|---|---|
| Python subprocess builds the `act` | build it from the call: `Bash.command` → `{kind:'shell'}`, `Write/Edit.file_path` → `{kind:'file'}`, `mcp__*` → `{kind:'http'}` | `tool.call` observe + deny CONFIRMED |
| exit 2 blocks | `{deny}` with the reason reaching the model as an error result | CONFIRMED ("resolved by a hooks module (deny: …)") |
| contained allow via stdout JSON + temp-file handshake | argument rewrite, staging map in session memory | `next({...e, command})` CONFIRMED (tool ran the rewrite) |
| `delegation_constraint` inferred from Task arguments | `agent.spawn` carries the parent and the spawn parameters | spawn rewrite + `agentId` CONFIRMED |
| declared `cost_estimate`, caller-asserted model | observed per-request and per-turn `usage` | `turn.step` / `turn.complete` usage CONFIRMED |

### WHAT MODS DO NOT CHANGE

The engine is inseparable from Postgres and a tenant id. The org kill switch, the approvals inbox, cross-session
rate limits, the `guard_decisions` row and the Ed25519 receipts all still want a server, and
`app/lib/integrity/sign.ts` imports `node:crypto`, which a Mod module cannot (NOT POSSIBLE): signing stays
server-side or goes over `$.http.fetch`. The 20 YAML packs in `app/lib/guardrails/packs/*/policies.yml` and the
`RiskBreakdown` explainability shape are unaffected.

### WHAT BECOMES OBSOLETE

`plugins/dashclaw/hooks/hooks.json` + `hooks/run_hook.cjs` with its interpreter probe and day-long temp cache;
exit-code signalling; `hooks/dashclaw_agent_intel/written_paths_ledger.py`, `session_tracker.py`,
`mcp_monitor.py` and `_write_containment_action_state`, all of which exist only because PreToolUse and
PostToolUse are separate processes; `dashclaw_scope_sync.py`'s settings-file mutation and its
`.dashclaw-scope.json` cleanup; and the 42 KB Python bash classifier, a second implementation of `evidence.ts`
that has to be kept in step.

### WHAT BECOMES SIMPLER

Containment: "rewrite the tool's arguments" is exactly `updatedInput` without the stdout protocol, with
`containment.ts`'s `isContainableAct` unchanged. The interruption budget (`evaluate.grants.ts:268`) counts
`commandShapeKey` occurrences locally instead of over a 7-day SQL window. Script-then-execute detection becomes
trivial when both calls sit in one closure.

### NEW PRODUCT CAPABILITIES

1. Subagent governance that is real rather than inferred: deny a `deploy` action type inside a research subagent,
   cap `max_depth` per branch (`agent.spawn` deny is EXPERIMENTAL; spawn **rewrite** is CONFIRMED, so today's
   enforceable form is a downgrade, not a refusal).
2. Attested spend per subagent, which the schema has fields for (`tokens_in/out`, `cost_estimate`) and no way to
   enforce.
3. Governance a model cannot skip. `tool.call` is the single point every cooperative surface in this cluster
   converges on.

### LONG TERM ARCHITECTURE

A local policy decision point in-process (ported `classifyAct` + `serverRiskTerms` + the 15 pure evaluators +
`riskTemplates.ts` + `protected-path.ts`, all zero- or near-zero-import) with the HTTP call reserved for
approvals, cross-session rate limits, the ledger and the receipt. That is the two-tier design
`offlocalai-mcp/src/dashclaw/guard.ts` already implements (`localPolicyPreview()` then `guardWithDashclaw()`,
with the preview riding along in `metadata`).

### COMPATIBILITY RISKS

- Early access and undocumented; the wire schema in `app/lib/validate.js:289` is stable but the event surface is
  not.
- `classic.*` (and `prompt.section`/`prompt.context`) are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here), so a Mod adapter is a **replacement** for the shell hooks, not an addition. Both must not
  run at once or every governed call produces two decisions and two action rows.
- The permission dialog cannot be drawn (NOT POSSIBLE), so `require_approval` has no native surface: the pause
  must be built (see `leg-alexa-mcp/src/confirm.ts`) and `$.ui.ask` is (EXPERIMENTAL). Registered-tool result
  shape applies; one hooks module per plugin.
- Project-specific: a Mod governs one session on one machine and has no tenancy model; `node:crypto` is out of
  reach; `sec-default` denies user-tier `$.tool.register` when managed policy sets `allowedMcpServers`.

### ONE "HOLY SHIT" DEMO

Ask for a schema migration against the production database. The Bash row shows the command that actually executed
as `… --database dashclaw-contained-a1b2`, the model's result says the migration ran, and a line above the prompt
reads `⟦contained⟧ 1 act staged · promote or discard`. Nothing was denied and nothing touched production.
(CONFIRMED: `tool.call` argument rewrite, `ui.render` on AbovePrompt, `$.process.run` to create the branch.)

### ONE PRACTICAL NEAR TERM FEATURE

`HOOK_MODE=observe` as a Mod: port `evidence.ts` verbatim, classify every `tool.call`, write one JSONL line per
decision with `$.fs.write` (CONFIRMED), enforce nothing. Microseconds against today's node-probe plus
Python-parse plus two HTTPS round trips, and it produces the local evidence needed to tune before anything
blocks: the log-only posture four separate repos in this portfolio converged on independently.

### ONE SPECULATIVE FUTURE FEATURE

Containment by default: every provably file-scoped act runs against a worktree until a human promotes it, with
the staged set rendered and promote/discard as controls. That is a different product from "governance that says
no", and the primitive already exists in `containment.ts`.

---

## LegCli

### CURRENT ARCHITECTURE

A supervisor that can only see a coding-agent CLI from outside it, reconstructing runtime state from four kinds
of exhaust: OS process state, git, the agent's own log files, and (for Claude only) an injected `--settings` file
carrying classic hooks. `src/attach.mjs` is the loop (`POLL_MS=2000`, `GIT_EVERY=3`, `USAGE_MS=60000`).
`src/taps/claude-usage.mjs` reads `~/.claude/.credentials.json`, extracts the OAuth token and polls
`api.anthropic.com/api/oauth/usage` every 60 s because Claude Code 2.1.268 does not run a custom `statusLine`
passed via `--settings` (verified 2026-09-11 in that file's own comment).

### CURRENT LIMITATION

Three, all structural (`C-legcli-handoff-memory.md` §1). **No context signal at all**: Leg's only pressure
numbers are the 5h/7d subscription windows. **Subagents are discarded**: `src/taps/claude.mjs`'s
`transcriptTail()` contains `if (j.isSidechain) continue`. **The handoff is destructive and unbounded**:
`killTree(child.pid)` at whatever instant the limit arrives, with mid-turn, mid-edit and mid-`npm test` identical
to it. Plus one `node src/hook.mjs` process per Edit/Write/MultiEdit/NotebookEdit for `files_touched`.

### WHAT MODS CHANGE

| Signal Leg lacks | Mod source | Status |
|---|---|---|
| context % | `$.session.usage()` | CONFIRMED |
| rate-limit % without credentials | `$.session.usage()` `rateLimits[]` | CONFIRMED |
| activity phase | `turn.step` chunk kinds, `tool.call` name | CONFIRMED |
| safe boundary | `turn.complete` | CONFIRMED (incl. subagent turns) |
| tests running | `tool.call` on Bash plus its result | CONFIRMED |
| subagent working | `agent.spawn` + `agentId` on child `turn.step`/`tool.call`/`turn.complete` | CONFIRMED |
| files touched, in-process | `tool.call` | CONFIRMED |

The integration point exists already: a sixth tap, `src/taps/mod.mjs`, calling the same four lock-safe functions
the classic hooks call today (`recordUsage`, `markLimited`, `updateSession`, `appendEvent`), all of which already
take a `source` string.

### WHAT MODS DO NOT CHANGE

Three of Leg's five taps are log-scraping for Codex, agy and grok and gain nothing. `reapLost()` (runner-pid
liveness) is still required because a Mod dies with the session. The merge queue (`src/mergequeue.mjs`,
per-canonical-root FIFO, five named bounces), the worktree model, `assertAllowed()`'s forbidden-flag check at
spawn time and `src/limits.mjs`'s fixture-driven classifier with `observed-live` vs `docs-only` provenance are
untouched. Leg keeps owning the launch, which is exactly why it is the natural host for a Mod.

### WHAT BECOMES OBSOLETE

`src/taps/claude-usage.mjs` entirely, and with it the practice of reading an OAuth token off disk. The
`PostToolUse` entry in `settingsFor()` and the per-edit `node src/hook.mjs` spawn. `handleStatusline()`, which
exists to print one line that on 2.1.268 never runs.

### WHAT BECOMES SIMPLER

`files_touched` becomes an **attention** map rather than an edit map, because `tool.call` also sees Read, Grep
and Glob. That upgrades `overlaps()` in `src/sessions.mjs` from "both wrote it" to "one is reading what the other
is writing". `src/usage.mjs`'s lock-safe limit state keeps its documented race fix and simply gains a better
feed.

### NEW PRODUCT CAPABILITIES

1. **Safe-boundary handoff**: set a flag at `WARN_PCT`, act at the next `turn.complete` (CONFIRMED). Today a
   handoff can land mid-edit and the next agent inherits a half-written tree.
2. **A board that sees the tree**: one row per terminal becomes a tree with per-subagent token cost;
   `appendEvent(sid, {type, summary})` already takes arbitrary event types.
3. **Quality-triggered handoff**: port `calculateHealth()` from context-health-bar and hand off because the
   session drifted, not because the account ran out. `chooseNext()` is built for it and has never had the signal.
4. **`SYNTHESIS-<id>.md` written for the agent rather than by it**, from `turn.step` text chunks (CONFIRMED read)
   plus `$.model.classify` (CONFIRMED), with `validateSynthesis()` already checking the result.

### LONG TERM ARCHITECTURE

Leg ships its own plugin folder and appends `--plugin-dir` in `src/adapters/claude.mjs argv()`; the Mod pushes
state to the board instead of the board polling for it; `attach.mjs`'s interval survives for git and process
liveness only; the handoff trigger gains a second, better condition (warning **and** turn boundary).

### COMPATIBILITY RISKS

- Early access and undocumented; `--settings` merging is already version-sensitive (2.1.268 broke `statusLine`
  there), so two version-sensitive mechanisms now exist.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here). This does not block Leg, which is the launching process rather than a user plugin, but the
  Mod and the `--settings` hooks must not double-count `files_touched`: remove `PostToolUse` from `settingsFor()`
  in the same change that adds the Mod.
- The permission dialog cannot be drawn (NOT POSSIBLE), so an approval lives in a band or the browser board.
  Registered-tool result shape applies; one hooks module per plugin.
- Project-specific: `$.turn.abort()` is (EXPERIMENTAL), so the graceful stop today is "signal Leg at
  `turn.complete` and let Leg do the killing", not an in-session abort. A Mod cannot see Codex, agy or grok, so
  the architecture gains surface rather than losing it.

### ONE "HOLY SHIT" DEMO

Watch a session cross 85 % of its five-hour window in the middle of a four-file edit. The band turns amber and
reads `handoff armed · waiting for turn boundary`, the edits finish, and the moment the turn ends a line appears:
`⟦leg⟧ bundle saved (14 anchors) · next: claude/account-2`. The tree is clean, which is the one thing
`killTree()` can never promise. (CONFIRMED: `$.session.usage()`, `ui.render` on AbovePrompt, `turn.complete`,
`$.process.run` for the bundle save, `$.ui.log`.)

### ONE PRACTICAL NEAR TERM FEATURE

`src/taps/mod.mjs` plus a Mod writing `$LEG_HOME/sessions/<id>/runtime.json` at every `turn.complete` with
context %, both rate-limit percentages, cost USD and the live `agentId` roster. Zero changes downstream;
`recordUsage(agent, account, windows, 'mod')` already exists.

### ONE SPECULATIVE FUTURE FEATURE

Leg hands off on drift: `calculateHealth()` over `$.session.messages()` plus the tool-output noise term only
`tool.call` can see, feeding `pressure()`, so a session with 60 % of its quota left is retired because a fresh
one starting from the bundle will do better work.

---

## context-handoff-bundle

### CURRENT ARCHITECTURE

A Python CLI, zero runtime deps, 3,662 lines across 12 modules. Its primitive is a content-hashed evidence anchor
with a five-state verdict: at save time the referenced line range is sha256'd (16 hex), at load time re-checked
into `verified | ok | changed | gone | n/a`, and `link_evidence(finding, anchors)` flags a finding only when it
cites a moved anchor. Eight bundle files per save; quality scoring weighted toward trust
(`evidence_coverage 3.0`, `open_question_honesty 2.5`). Zero LLM calls on the load path.

### CURRENT LIMITATION

One sentence, in the project's own words (`commands/handoff-save.md`): **"The CLI cannot see the conversation."** So the agent must be instructed by a slash command to hand-author a structured notes file, and
the fallback (`autocontext.gather_repo_context()`, 463 lines) is called a useless stub by the project's own docs.
The headline "~3 % of the tokens" is `CHARS_PER_TOKEN = 4` over `path.stat().st_size`: a size ratio, not an
experiment; 0 of 5 test files measure a real session's cold-start cost. A session that dies before someone runs
`/handoff-save` produces nothing.

### WHAT MODS CHANGE

| Bundle field | Live source | LLM needed |
|---|---|---|
| `evidence_index[].path` | `tool.call` on Read/Edit/Write/Grep/Glob (CONFIRMED) | no |
| `line_start` / `line_end` | tool arguments: Read `offset`/`limit`, Edit `old_string` position (CONFIRMED) | no |
| `content_hash` | hashed at the moment of the call | no |
| `role` (`primary`/`reference`) | written ⇒ primary, read-only ⇒ reference | no |
| `scope.repos`, `branch`, `head_commit`, `dirty` | `$.session.repo()` (CONFIRMED) | no |
| `findings[].evidence[]` | the anchors touched during the turn that produced the finding | no |
| `token_estimates.*` | `$.session.usage()` (CONFIRMED) | no |
| `findings[].summary` / `confidence` | `turn.step` text and thinking chunks | **yes** |

The causal link `link_evidence()` reconstructs by string matching is something the recorder simply knows.

### WHAT MODS DO NOT CHANGE

Cross-session drift. `drift.analyze_drift()` covers the window where no hook was running (another terminal, a
teammate, a `git pull`, a rebase), including the git-rename following added in commit `40cef52`. That half is
unchanged and still essential. Findings, confidence and implications still need a model. The Python CLI stays the
only writer of bundle files, which is the invariant `C:\Projects\leg\src\handoff.mjs` depends on ("Leg never
re-implements the bundle format").

### WHAT BECOMES OBSOLETE

`anchors.parse_anchor()` (259 lines of heuristics for em dashes, Windows drive colons, label prefixes and bare
commits) for anything the recorder saw; it survives only for anchors a human typed. `autocontext.py` entirely.
`tokens.py`'s `chars/4` estimate. The manual authoring step that makes `handoff-save.md` an 86-line instruction.

### WHAT BECOMES SIMPLER

Intra-session drift collapses to a recorded fact: the recorder saw both the read and the write and knows the
order, so `_anchor_status()`'s `changed` state for same-session anchors is free. `entities[]` come from path
prefixes rather than `autocontext._detect_projects` guessing from `packages/`, `apps/`, `services/`.

### NEW PRODUCT CAPABILITIES

1. A bundle for sessions that die. The recorder writes as it goes, so a crash, a rate limit or a closed terminal
   no longer costs the whole session.
2. A measurable token claim: record actual input tokens at turn 1 of a fresh session and the denominator stops
   being a guess about behaviour. The cheapest credibility upgrade in the repo.
3. Anchors more accurate than a human can write, because `Read offset/limit` is exact where `:40-62` is
   remembered.

### LONG TERM ARCHITECTURE

A continuous flight recorder feeding the existing CLI: `tool.call` appends to an evidence ledger,
`turn.complete` produces at most one finding linked to that turn's anchors, the CLI writes the files through
`$.process.run`, and `drift.py` runs unchanged at load. `resume.py`'s `compose_resume()` layout (State /
Pressure / Drift / Open First / Must reverify / Next moves) becomes the shape of a hidden context block.

### COMPATIBILITY RISKS

- Early access and undocumented.
- `classic.*`, `prompt.section` and `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here), so the load path uses `prompt.submit` hidden context (CONFIRMED), not a context-block
  rewrite.
- The permission dialog cannot be drawn (NOT POSSIBLE); a bundle browser needs a Pane, and `$.ui.open` "waits
  unplaced" below 144 columns. Registered-tool result shape applies; one hooks module per plugin.
- Project-specific: the recorder produces far more raw material than a bundle should contain (every Read of every
  file), so a salience filter is mandatory or `evidence_index.json` becomes a log. Per-turn findings want
  `$.model.complete`, which is (EXPERIMENTAL): only `$.model.classify` is confirmed. A cross-session buffer
  wants `$.store` (EXPERIMENTAL); use `$.fs.write` (CONFIRMED).

### ONE "HOLY SHIT" DEMO

Work for twenty minutes, then close the terminal without saving anything. Open a new session, run the registered
`/handoff-load`, and the resume block lists 14 evidence anchors with exact line ranges and content hashes
captured at the moment each file was read, three already marked `changed`. Nobody typed a notes file and nobody
ran a save. (CONFIRMED: `tool.call` observation, `$.fs.write`, `$.command.register`, `prompt.submit` hidden
context, `$.process.run` for the drift check.)

### ONE PRACTICAL NEAR TERM FEATURE

A `tool.call` recorder appending `{path, line_start, line_end, hash, role, turn}` to
`.context-handoffs/live-<session>.jsonl` via `$.fs.write`, consumed by `save --notes` unchanged. It removes the
authoring step without touching the format, the schema or the CLI.

### ONE SPECULATIVE FUTURE FEATURE

Every saved bundle becomes a free labelled relevance set ("what was this session about" → "these anchored
files"), which is exactly the recall@k evaluation data `context-engine`'s SPIKE-REPORT lists as unbuilt manual
work. A flight recorder produces them continuously.

---

## CostClaw (+ claude-code-audit lineage)

### CURRENT ARCHITECTURE

A pure deterministic cost-and-waste engine with a hard separation between parsing the world and reasoning about
it: `packages/engine` has no clock, no filesystem and no network; `apps/cli` is the only thing touching disk.
Three primitives: billing-accurate usage reconstruction (`parser.ts:180-207`
`growsFrom`/`sameCandidate`/`preferredCandidate`, because naive summing overcounts 3-4x), a cost model separating
waste from working cost (`pricing.ts`, `PRICING_SNAPSHOT_DATE = "2026-09-14"`), and eight waste rules
(`optimizer.ts`). The lineage is written down: tokentrail (2026-05) → claude-code-audit (2026-08) → costclaw,
recorded at `clones/claude-code-audit/src/lib/cost-engine/optimizer.ts:1-7`.

### CURRENT LIMITATION

Nothing in it can see a session while it runs, so every remedy is advice for next time. `windows.ts:27-78` infers
five-hour window boundaries from 15-minute cost buckets because it cannot see the real limits. Subagent
attribution comes from **directory nesting** (`read-sessions.ts` `classify()`). The privacy invariant (no target
values in output, with a tripwire test) exists because the record was designed to be uploadable, and it makes
every loop finding vague. And it is the fourth parser of the same JSONL on this machine, alongside `spend.cjs`,
`subagent-budget/calibrate.cjs` and `tokflow/*.cjs`.

### WHAT MODS CHANGE

The seam is one function below `buildAudit()` and already exported: `packages/engine/src/parser.ts:210`
`rebuildSessionUsage(session, fragments, extraWarnings)`: pure, idempotent, the only mutation point.

| Rule | Live? | Note |
|---|---|---|
| `HEAVY_TOOL_LOOPS` | fully live | two counters over `tool.call` (CONFIRMED) |
| `REDUNDANT_TARGET_THRASH` | fully live | the 11th identical Read can be answered from cache (CONFIRMED) |
| `MARATHON_SESSION` | fully live | `turn.step.usage` gives `{read, miss}` per request (CONFIRMED) |
| `SHORT_SESSION_BLOAT` | live | `$.session.usage().cost` plus wall clock (CONFIRMED) |
| `MODEL_MISROUTE` | inverts | becomes a prior on `agent.spawn` (model rewrite CONFIRMED); per-request rewrite on `turn.step` is (EXPERIMENTAL), effect UNKNOWN |
| `WORKFLOW_COST` | live and better | real parent/child edge from `agent.spawn` + `agentId` (CONFIRMED) |
| `BAD_CACHE_HIT`, `HOT_PROJECT` | need history | live from session 4 onward with persistence |

`pricing.ts` `normalizeUsage()` takes the raw `usage` object `turn.step` carries, including the
`cache_creation.ephemeral_5m/1h` TTL split, with **zero changes**.

### WHAT MODS DO NOT CHANGE

The pricing engine, the rate-card discipline and the "not an invoice reconciliation" caveat. `burnClock` is
genuinely a long-window statistic (gated at ≥7 active days). The npm CLI stays as the portable path because
costclaw ships to machines with no Mods. `scoring.ts:28 makeCheck()`'s not-assessed discipline (a check with no
evidence scores `null` and is excluded rather than defaulted) is required on day one live, because early in a
session almost nothing is assessable.

### WHAT BECOMES OBSOLETE

`packages/engine/src/windows.ts:27-78` is deleted rather than ported: `$.session.usage()` returns five-hour and
seven-day percentages directly (CONFIRMED). `apps/cli/src/read-sessions.ts` goes wholesale: `$.session.repo()`
replaces `repoRootFor` + `projectNameFromLogs`, `agentId` replaces `classify()`. `apps/cli/src/serve.ts` (373
lines, loopback HTTP server, idle timeout, CSRF token, network allowlist entry) and the HTML renderers.
`parser.ts`'s cumulative-snapshot reconciliation is dead weight live, because `turn.step` delivers one
authoritative usage object per request. `claude-code-audit` is superseded on every axis; its value is
archaeological.

### WHAT BECOMES SIMPLER

`PromptSignals` stop being `CORRECTION_RE` / `INTERRUPT_MARK` / `SLASH_PREFIXES` regexes over user rows and
become the real event (`prompt.submit`, CONFIRMED). Exactly one private function blocks the adapter:
`parser.ts:79 targetFor(name, input)`, whose signature is *already* the `tool.call` shape. Export it and
`commandTarget()` with it; its `cd X &&` hop-stripping exists for a dated reason and should not be rewritten.

### NEW PRODUCT CAPABILITIES

1. **The thrash interceptor.** At `REDUNDANT_TARGET_MIN_FIRES` (10), stop reporting and answer the 11th identical
   Read from the hook's own cache with a transcript line saying so (CONFIRMED). The only signal in the repo whose
   fix is free.
2. **Named files in findings.** The privacy invariant existed because the record was uploadable; a Mod uploads
   nothing, so "Repeated Read calls on the same file" becomes "`src/api/handler.ts` read 14 times".
3. **AgentLens's confidence grading with certainty.** `classifyRun()`'s `low` bucket ("inside one request, a
   batch not a loop") is a heuristic post-hoc and a fact under `tool.call`, which lets costclaw's empirical share
   gates (`HEAVY_TOOL_MIN_SHARE = 0.6`, `REDUNDANT_TARGET_MIN_SHARE = 0.25`) be deleted and recovers the real
   loops those gates suppressed.
4. **A verdict, not a number**: spendwall's `evaluatePolicies` turns the dollar into
   `allow | flag | needs_approval | block` on a `monitor → alert → block` ladder.

### LONG TERM ARCHITECTURE

One `turn.step` accumulator producing `UsageFragment`s once; `rebuildSessionUsage()` turning them into
`SessionMetrics`; four existing tools becoming four views of it: `spend`'s burn arithmetic reading
`session.costBuckets` (already 15-minute grain), `calibrate.cjs`'s counters coming off `agent.spawn` + `agentId`,
`tokflow` retired, the optimizer running every N turns. One derived `AuditRecord` at session end so the batch CLI
and the live Mod produce interchangeable records.

### COMPATIBILITY RISKS

- Early access and undocumented; costclaw ships to npm for machines that have no Mods, so the JSONL reader stays
  the portable fallback and the Mod can never be the only path.
- `classic.*` and `prompt.context` are withheld from user plugins on managed-settings machines (NOT POSSIBLE
  here), so `PreModelSwitch`/`PostModelSwitch` with `estimated_cache_write_usd` and `prompt_cache_warm` are
  unavailable to this Mod.
- The permission dialog cannot be drawn (NOT POSSIBLE), so a `needs_approval` verdict renders in a band and
  `$.ui.ask` is (EXPERIMENTAL). Registered-tool result shape applies; one hooks module per plugin.
- Project-specific: a Mod sees this session plus whatever it persisted, not the 2.2 GB of history that makes
  `HOT_PROJECT`, `burnClock` and a 3-session `BAD_CACHE_HIT` streak meaningful; live and batch are complements.
  Cross-session state wants `$.store` (EXPERIMENTAL); `$.fs.write` (CONFIRMED) is the shippable substitute. Per
  L2, `$0.00 spent` and `the usage call failed` must not look alike.

### ONE "HOLY SHIT" DEMO

On turn four of an ordinary session the band already reads `$0.31 · ctx 7 % · 5h 11 % · 7d 3 %`. Ask the model to
re-check a file it has already read ten times and the Read returns instantly with a dim line `⟦costclaw⟧ served
from session cache · 11th identical Read · ~4.2k tokens not spent`. The number that used to arrive with the bill
is on screen while the money is still being decided. (CONFIRMED: `$.session.usage()`, `ui.render` on AbovePrompt,
`tool.call` answer-without-`next`, `$.ui.log`.)

### ONE PRACTICAL NEAR TERM FEATURE

Export `targetFor` and `commandTarget`, then ship a `turn.step` + `tool.call` accumulator that calls
`rebuildSessionUsage()` and renders the headline. Six of eight rules run with no history and `pricing.ts` needs
zero adaptation.

### ONE SPECULATIVE FUTURE FEATURE

Escrow, from mole's `escrowFor(budget)`: reserve a slice of the five-hour window for the turn that writes the
answer and start downgrading `agent.spawn` models once the unreserved part is gone, instead of discovering at
94 % context that there is no room left to summarise.

---

## Discovery Loop

### CURRENT ARCHITECTURE

A confirmation pipeline in which the thing that decides is never the thing that proposed. Five reusable
mechanisms: a reserve/settle allowance ledger (`research_state.py:114` `BudgetLedger`, which charges the **full
reservation** when the real cost is unknown, so a failed call still spends); durable routing with circuit
breakers partitioned into `RETRYABLE` / `MODEL_BREAKERS` / `FAMILY_BREAKERS` (`routing.py:72`); disposable
network-disabled Docker execution (`isolation.py:424`); a paired-matrix statistical gate (`evaluation.py:206`);
and exogenous edge tagging for review (`verification_contract.py`, 180 lines, zero dependencies, three verdicts,
**FLAG is sticky**, a missing verdict is not a pass). Four gates in order, the fourth human (`dashboard.py:520`
returns "Approval queued locally. No publication occurred.").

### CURRENT LIMITATION

`compare_paired` refuses loudly rather than degrading: a non-rectangular target×seed matrix raises, and it
requires ≥3 distinct seeds per target with zero candidate failures. A live Claude Code session has **no seed and
no incumbent arm**: you cannot re-run yesterday's session with the Mod off. `loop.py` is 2,273 lines with a
700-line procedural research function, so the primitives are excellent and unpackaged.

### WHAT MODS CHANGE

Only the observation half, and cleanly. The field map onto `research_memory._development_entry` is mechanical:
`run_id` ← session id, `iteration` ← `turn.step.messageCount`, `provider`/`actual_model` ← `turn.step`'s
per-request `model`, `role` ← main loop or `agentId`, `cost_usd` ← `$.session.usage().cost` delta, `critique` ←
`$.model.classify`, all (CONFIRMED). `family` stays a policy choice (the intervention class, not the instance),
and `fingerprint` becomes the sha256 of the Mod's normalized policy object rather than an AST hash.
`summarize_development` and `retro.py` then work unchanged, and the recurring-failed-approach rollup (bounded
20-row window, **unbounded** family rollup) comes free.

### WHAT MODS DO NOT CHANGE

The confirmation gate, and the honest reason: runtime events are observations, never confirmations, without a
replay harness. `isolation.py`'s boundary has no Mod equivalent: `$.process.run` (CONFIRMED) gives no
network-disabled, output-capped, container-removed execution, so a Mod that runs model-written code is strictly
weaker than the Python loop it borrows from. The four-gate promotion structure, the hash-bound promotion with its
TOCTOU check, and the human publication gate stay exactly as they are.

### WHAT BECOMES OBSOLETE

Nothing in this repository. Stated plainly because the temptation is to claim otherwise: master was committed the
day before the archaeology, the experiment machinery is the point, and Mods supply none of it. What changes is
where the loop's *judgment* layer gets reused.

### WHAT BECOMES SIMPLER

Delivering `problems/_dead_ends.json` to a session. It is a list of `{id, problem, approach, why_failed,
evidence, tags, date}` and its contents are exactly what a fresh session re-derives at full cost: `de-001`'s
`why_failed` reads "Timeout at 120s and 600s on 2,091,510 clauses. …This is a timeout, NOT UNSAT". As hidden
context on `prompt.submit` (CONFIRMED) it becomes a property of the session rather than of whether the model read
a notes file.

### NEW PRODUCT CAPABILITIES

1. `verification_contract.py` used verbatim by any Mod that asks a model to judge anything: three verdicts,
   sticky FLAG, missing verdict ≠ pass. 180 lines of pure logic, no imports, and the best single idea in the
   repository.
2. `BudgetLedger` semantics on spawns: reserve from the declared `# EST:`, settle from the subagent's
   `turn.complete` usage (CONFIRMED), charge the full reservation on failure. A failed subagent that burned 40k
   tokens and returned nothing charges 40k, which is what a naive counter gets wrong.
3. `RoutingJournal`'s three-way error partition applied to a session: a `usage_limit` takes one model out of
   rotation, an `authentication` failure takes a family out.

### LONG TERM ARCHITECTURE

The only route to a *confirmed* claim about a Mod is a problem plugin whose target is a task fixture (a repo
snapshot plus a prompt), whose seed is a repetition index, and whose solver is `claude -p --plugin-dir <mod>`
running inside `isolation.run_solver`. `providers.py:120-146` already has the exact flag set for driving
`claude -p` as a scrubbed, killable completion endpoint. Everything short of that is an observation, and the
repo's own vocabulary says so.

### COMPATIBILITY RISKS

- Early access and undocumented, which matters more here: an experiment whose treatment is a Mod is invalidated
  by a build that changes the event surface mid-run.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here), so dead-end delivery uses `prompt.submit` hidden context.
- The permission dialog cannot be drawn (NOT POSSIBLE). Registered-tool result shape applies; one hooks module
  per plugin.
- Project-specific: `$.process.run` has no shell, a 30 s default and a 10 min ceiling, so it cannot host a
  nightly run. No seed is exposed by `turn.step`, so a deterministic model re-run is (NOT POSSIBLE) at any price;
  the confirmation arm must come from repeated fresh runs, not from replay. `$.clock.every` (EXPERIMENTAL)
  cannot be assumed for the nightly lane.

### ONE "HOLY SHIT" DEMO

In the discovery-loop repo, ask for a new approach to the CVRP solver. Before the model touches a file its first
line is "de-001 already rules that out: that was a timeout at 2,091,510 clauses, not UNSAT", because the matching
dead-ends arrived as hidden context the human never pasted and the model was never told to look for. (CONFIRMED:
`prompt.submit` hidden context; the model saw it, and in the probe run Sonnet flagged it as injected.)

### ONE PRACTICAL NEAR TERM FEATURE

A dead-ends injector: match `problems/_dead_ends.json` entries against the prompt and attach only the hits, with
the count, as hidden context. Read the file with `$.process.run` (CONFIRMED) at session start and hold it in
module state.

### ONE SPECULATIVE FUTURE FEATURE

The Mod becomes the unit under test: a `problems/mods/problem.py` whose `solver_argv` is a Claude Code session
with and without the plugin, over a fixed task suite, three seeds per target, in the existing Docker worker, the
first honest answer to "did that hook actually help", scored by the same `compare_paired` gate that governs every
other claim in the repo.

---

## git-intelligence (giti)

### CURRENT ARCHITECTURE

Three separable things, and the repo's "organism" framing hides the best one.
`packages/giti/src/analyzers/file-analyzer.ts` derives fragility from git alone: `getHotspots` returns
`{filepath, changes, authors, bugFixes}` per file from one `git log --name-only` pass, and `getFileCouplings`
emits a pair only when both files have ≥5 individual changes and they co-occur in >60 % of the rarer file's
commits. `packages/giti/src/agents/memory/curator.ts` holds a recurrence gate written in code (confidence 0.5,
+0.1 per corroborating event capped at 1.0; a rejection reason becomes a lesson at 5; a tag becomes a preference
at 10). `packages/giti/src/agents/memory/fts.ts` is ~200 lines of dependency-free stemmer, inverted index and
weighted-field TF-IDF.

### CURRENT LIMITATION

There is no MCP server anywhere in the repo (`grep -rn "mcp\|MCP"` over `packages/giti/src` returns nothing). The
only doors are `giti remember query`, `giti hotspots` and `giti pulse`, each a process spawn producing
chalk-coloured text. The knowledge answers only when a human types the command, and `organism.json`'s
`boundaries.forbidden_zone` lists "modifying the target repository in any way", which is a promise kept by not
having the capability. `fragile_files` is populated only from giti's own `regression-detected` events, so on a
repo giti has not run a lifecycle against it is empty.

### WHAT MODS CHANGE

The delivery point. One `git log` per session through `$.process.run` (CONFIRMED), the map held in module state
(in-memory across events, CONFIRMED), and the lookup performed on `tool.call` for Edit/Write/NotebookEdit against
the target path in the arguments (CONFIRMED). The answer arrives as hidden `context[]` on the tool result
(CONFIRMED, capped 32k chars) at the moment the follow-up edit is being decided. `fts.ts` runs inside a Mod
module unmodified, which removes the strongest argument for putting a Mod's memory behind an MCP server.

### WHAT MODS DO NOT CHANGE

Git history is not free: `git log --name-only` over a large repo is hundreds of milliseconds, so it stays
session-scoped and cached, never per event. The coupling rule needs ≥5 changes per file, so on a young repo the
table is silent and the Mod must say "no signal" rather than "no risk" (L2: print the count beside the verdict).
`BUG_FIX_PATTERN` is commit-message matching and inherits the repo's commit hygiene. The self-evolving organism
lifecycle is unaffected and mostly irrelevant.

### WHAT BECOMES OBSOLETE

The CLI as the delivery path for `hotspots` and `remember query`. `integrations/openclaw/instrument.ts`'s
`traceAgent` wrapper, because `{agent, action, duration_ms, status}` falls out of `agent.spawn` +
`turn.complete` with `agentId`, real token usage and the real model, and covers subagents the wrapper could never
see. `giti-observatory` for this purpose; it remains a visualisation product.

### WHAT BECOMES SIMPLER

`getHotspots` and `getFileCouplings` each run their own `git log` over the same range today; one session-scoped
pass feeds both. `curator.ts`'s thresholds become a Mod's promotion gate directly, already written and tested.

### NEW PRODUCT CAPABILITIES

1. Knowledge at the moment of the edit rather than on request, the capability the CLI never had because nothing
   was watching.
2. The coupling fact, which is the highest-value payload: "you changed A, history says B changes with it 87 % of
   the time, you have not opened B."
3. A retrieval layer for any Mod's memory with no server and no network (`fts.ts` plus `query.ts`'s field weights
   and recency tie-break).

### LONG TERM ARCHITECTURE

One "what you don't know about this file" Mod holding two tables keyed on path and repo identity: giti's
couplings and fragility, and discovery-loop's `_dead_ends.json`. Both are knowledge a fresh session re-derives at
full cost, both are cheap lookups, and neither can reach a model at the moment it matters today.

### COMPATIBILITY RISKS

- Early access and undocumented.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here); session-start injection uses `prompt.submit` hidden context (CONFIRMED) instead.
- The permission dialog cannot be drawn (NOT POSSIBLE), and escalating a fragile edit from `allow` to `ask` on
  `tool.check` is **not** in the confirmed set: only `ask → allow` was exercised (§15), so escalation is
  (EXPERIMENTAL) and the shippable form is hidden context plus `$.ui.status` (CONFIRMED). Registered-tool result
  shape applies; one hooks module per plugin.
- Project-specific: `C:\Projects\git-intelligence\.env` (877 B) is checked into the repo root and was not opened;
  flagged for Wes. The Anthropic SDK path needs a paid key, irrelevant to the two analyzers but relevant to
  anyone reviving the organism.

### ONE "HOLY SHIT" DEMO

Edit `src/api/handler.ts`. The edit succeeds, and the result the model reads carries a block the human never sees
in the diff: "3 recorded regressions, last 2026-08-02; co-changes with `src/api/router.ts` in 87 % of its commits
(13 of 15); you have not opened that file." The model's next tool call is a Read of `router.ts`. (CONFIRMED:
`tool.call` hidden `context[]` on the result, `$.process.run` for the one git pass.)

### ONE PRACTICAL NEAR TERM FEATURE

A session-scoped coupling map: one `git log --name-only` at `session.start` (CONFIRMED, awaited before the first
prompt), `getFileCouplings` ported as-is, and hidden context on every Edit result naming an untouched coupled
sibling, with the commit counts printed beside the claim.

### ONE SPECULATIVE FUTURE FEATURE

Fragility as a routing signal: a file with recorded regressions above a threshold forces the edit onto a stronger
model at `agent.spawn` (rewrite CONFIRMED) and requires a verification run before the turn can claim done, so the
repo's own history decides how much care an edit gets.

---

## budget-aware-research-agent

### CURRENT ARCHITECTURE

A transparent expected-value router in 115 lines with no model call in it: `run-prototype.mjs:97`
`makeDecision(request, rewrite, freePass)` sums named additive gains (`time_sensitive +0.25`,
`niche_topic +0.25`, `thin_free_results +0.20`, `stale_free_results +0.18`, `must_be_current +0.15`,
`insufficient_specificity +0.12`, `insufficient_depth +0.12`, `rewrite_sharpens_paid +0.05`), applies four
stay-free overrides that short-circuit before the threshold (`budget_too_low`, `scope_too_vague`,
`strategic_reasoning_better_fit`, `conceptual_answer_sufficient`), compares to one published threshold
(`escalationThreshold = 0.30`), and returns `{decision, reasonCodes, estimatedValueGain, estimatedCostUsd,
budgetCheck}`. Plus an intent→provider registry carrying `whenToUse` **and `whenNotToUse`**, and a JSONL ledger
splitting `searchCostUsd` from `synthesisCostUsd`.

### CURRENT LIMITATION

Every signal is an English regex over a query string, and the weights are hand-set with no calibration script and
no outcome feedback, so `+0.25` for niche is an assertion. `estimatedPaidCostUsd` is hardcoded to `0.01` in both
branches. `logCost` is fire-and-forget `appendFileSync` with no reserve step: a record of spend, not a cap on it,
the opposite of discovery-loop's and mole's ledgers. Nine commits, dead since mid-August.

### WHAT MODS CHANGE

| Guessed from a query string | Measured under Mods | Status |
|---|---|---|
| freshness, specificity, depth scores | context %, five-hour and seven-day %, cost USD | `$.session.usage()` CONFIRMED |
| nothing about the session | `messageCount`, per-request usage, this session's tool-failure count | `turn.step` CONFIRMED |
| "choose a provider" | rewrite a subagent's model before its first token | `agent.spawn` rewrite CONFIRMED |
| reason codes discarded | reason codes rendered where the human sees them | `ui.render` CONFIRMED |

### WHAT MODS DO NOT CHANGE

A routing decision made before a turn's outcome is known cannot be validated in the same event, so the
expected-value estimate still needs a per-session outcome record and a fit, work this repo never did either. The
search-specific half (`free-provider-registry.json`, `provider-discovery.mjs`, the 402 Index lookup) has nothing
to do with Claude Code and stays where it is.

### WHAT BECOMES OBSOLETE

The query-string classifiers, including the author's own niche list (`/\b(402 index|agentcash|x402)\b/i`). The
hardcoded `0.01` cost, which `$.session.usage()` replaces with a real figure. The provider half of the repo, for
this purpose.

### WHAT BECOMES SIMPLER

The decision shape survives untouched and only the signal set is swapped: named additive gains → stay-cheap
overrides → one threshold → reason codes. `conceptual_answer_sufficient` has an exact analogue
(`mechanical_turn_sufficient`: only Read/Grep since the last user message), computable from `tool.call`
(CONFIRMED) rather than from a phrase match.

### NEW PRODUCT CAPABILITIES

1. An auditable automatic downshift. The output already ships the reason codes that produced it, which is what
   makes a routing decision arguable instead of magic; `ui.render` (CONFIRMED) puts it on screen.
2. A decision that acts. The repo could only pick a provider; `agent.spawn` rewrites the model (CONFIRMED), so
   "stay free" becomes "spawn, but on haiku", which `subagent-budget-guard` cannot express at all.
3. `whenNotToUse` as a live field: rewrite a tool's description with this session's observed failures ("returned
   an error the last 3 times on a path under `node_modules`"). `tool.describe` **fires** (CONFIRMED) but the
   rewrite is (EXPERIMENTAL) and cached per session.

### LONG TERM ARCHITECTURE

The router's reason codes become discovery-loop's `family` key and the outcome becomes `development_status` /
`negative_result`, so after thirty sessions `low_context_remaining` carries a measured success rate instead of a
hardcoded `+0.25`. One repo has the decisions with no memory, the other the memory with nothing to decide.

### COMPATIBILITY RISKS

- Early access and undocumented.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here).
- The permission dialog cannot be drawn (NOT POSSIBLE), so a `needs_approval` tier renders in a band.
  Registered-tool result shape applies; one hooks module per plugin.
- Project-specific: per-request `model`/`effort` rewriting on `turn.step` is (EXPERIMENTAL) and §20 records the
  effect as UNKNOWN (accepted without error, not proven), so today's enforceable routing point is `agent.spawn`,
  not the model request. Fitting the weights needs persistence, and `$.store` is (EXPERIMENTAL); use
  `$.fs.write` (CONFIRMED). An automatic downshift the user cannot see the reason for is worse than none.

### ONE "HOLY SHIT" DEMO

Dispatch a subagent to grep a directory. The band shows `route: haiku · gain 0.08 < 0.30 ·
mechanical_turn_sufficient, budget_band_warn`, and the subagent's completion line reports `claude-haiku-4-5 ·
4 requests · 2,118 tokens` even though the prompt asked for the default model. The arithmetic that chose it is on
screen in the same frame as the result. (CONFIRMED: `agent.spawn` model rewrite with `agentId` returned,
`turn.complete` usage per `agentId`, `ui.render` on AbovePrompt.)

### ONE PRACTICAL NEAR TERM FEATURE

A reason-coded spawn router on `agent.spawn`: port `makeDecision`'s shape, feed it `$.session.usage()` and the
session's tool-failure count, rewrite the model, render the reason codes. It replaces a deny (which
`fable-delegate-guard`'s log shows a model retries against 5-7 times) with a rewrite, which cannot be retried.

### ONE SPECULATIVE FUTURE FEATURE

Weights fitted from the Mod's own recorded outcomes rather than asserted, re-run from the JSONL ledger the way
`tools/subagent-budget/calibrate.cjs` re-fits its constants, with the difference that the inputs are measured per
`agentId` instead of reconstructed from directory layout.

---

## offlocalai-mcp

### CURRENT ARCHITECTURE

Ambient production context resolved before an action runs: `project → environment → provider mapping → policy →
provider API → audit log`, with a pure policy function at the centre reasoning about `capability × environment
kind × provider × live-flag` rather than tool names, "so any new tool inherits safe defaults automatically"
(`src/policy.ts:9`). Production is an explicit typed field (`Environment.isProduction`), not a heuristic. The
defaults are the product (`defaultDecision`, `src/policy.ts:30`): destructive SQL and delete blocked everywhere,
purchase always `approval_required` and re-clamped after rule evaluation so an explicit allow rule cannot lower
it, any `live` write requiring approval regardless of environment.

### CURRENT LIMITATION

It governs only its own 124 MCP tools. A grep of `src/` for `--prod`, `wrangler`, `git push` and `deploy --prod`
returns **zero matches**, so `Bash("vercel deploy --prod")`, `npx wrangler publish`, `supabase db push`,
`psql $PROD_URL` and a raw `curl` to a live Stripe key are completely invisible to the system whose entire
purpose is production awareness. The model must also choose to call the tools.

### WHAT MODS CHANGE

The coverage, not the policy. `evaluatePolicy(rules, ctx)` imports nothing but types and is directly callable;
the missing half is a capability inferred from the act, which DashClaw's `classifyAct` already produces from
shell text. The three effects map onto the permission vocabulary with no translation loss: `allow → allow`,
`block → deny` (`tool.call {deny}` CONFIRMED), `approval_required → ask`. Resolution happens once per session
instead of per call, because the hook keeps project and environment in module state (CONFIRMED).

### WHAT MODS DO NOT CHANGE

`src/provider-actions.ts` is 117 KB of provider HTTP and SDK surface and cannot move into a Mod module, so the
execution half stays where it is and the Mod is the decision half. Environments still have to be registered by
hand (`add_environment`, `map_provider_resource`) and nothing detects drift between registry and reality.
`sanitizeDashclawText()`'s redaction of `*_TOKEN/SECRET/PASSWORD/API_KEY/DATABASE_URL`, `sk_/pk_live|test_…`,
`whsec_…` and database URLs stays mandatory on anything leaving the machine.

### WHAT BECOMES OBSOLETE

Nothing in the policy core. What dies is the assumption underneath the MCP surface: that governance applies to
the calls a model chose to route through it. `runGuarded`'s per-call re-resolution also becomes unnecessary.

### WHAT BECOMES SIMPLER

The `pendingApprovals` flow in `state.json` (`src/actions.ts:260-290`) no longer requires a CLI in another
window. `get_project_context`, described in the repo as "the killer tool", already renders exactly the bundle a
turn should start with: project, environment, live deployment status, and an `actionCatalog` bucketed into
allowed / blocked / approval-required by running `evaluatePolicy` in preview mode.

### NEW PRODUCT CAPABILITIES

1. The 90 % of production-touching acts that never go through an MCP tool become governable by the same rules,
   defaults and audit line.
2. An environment banner as hidden context on `prompt.submit` (CONFIRMED), so the model's plan is written with
   the environment in mind rather than corrected after the fact.
3. A footer showing project / environment / live-mode (CONFIRMED `ui.render`), the one piece of state that
   silently causes the worst mistakes.

### LONG TERM ARCHITECTURE

One decision half over every act: `classifyAct(command)` → `Capability` → `evaluatePolicy(rules, {project,
environment, provider, capability, live})` → verdict, with the two-tier pattern `src/dashclaw/guard.ts` already
implements (fast local decision, authoritative remote decision, both recorded, the local preview riding along in
`metadata.local_policy_*`).

### COMPATIBILITY RISKS

- Early access and undocumented.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here); the banner uses `prompt.submit` hidden context (CONFIRMED).
- The permission dialog cannot be drawn (NOT POSSIBLE), so `approval_required` renders in a band or becomes a
  deny carrying the approval path, and `$.ui.ask` is (EXPERIMENTAL). Registered-tool result shape applies; one
  hooks module per plugin.
- Project-specific: inferring `capability` and `provider` from a shell command is heuristic and a Mod will
  mis-classify some commands. The `purchase` and `destructive_sql` clamps make a false positive cheap and a false
  negative expensive, which is the right asymmetry but not a free one. Reading `.offlocal/state.json` at session
  start should use `$.process.run` (CONFIRMED), not `$.fs.read`, which is not in the confirmed set.

### ONE "HOLY SHIT" DEMO

Say "ship it" in a repo whose `.offlocal/state.json` marks the current environment production with Stripe in live
mode. The model composes `vercel deploy --prod`, and before the shell runs the terminal shows `✖ BLOCKED:
provider_deploy · project sentinel · environment production · live · policy: approval required`, with the model
quoting that refusal back. offlocal has never seen a shell command in its life. (CONFIRMED: `tool.call {deny}`
with the reason reaching the model, `$.ui.status`, `$.process.run` to read the registry.)

### ONE PRACTICAL NEAR TERM FEATURE

Resolve project and environment once at `session.start` (CONFIRMED, awaited before the first prompt), attach the
environment line as hidden context, and deny the nine shell shapes that map unambiguously onto `deploy` /
`env_change` / `destructive_sql` in a production environment. Everything else stays observe-only.

### ONE SPECULATIVE FUTURE FEATURE

Contained production: a production-touching act is redirected against a branch of production (DashClaw's
`containment.ts` plus offlocal's environment resolution) and promoted after one decision, so the answer to "is
this production?" stops being yes-or-no and becomes "yes, and it ran somewhere you can throw away".

---

## markdown-agent-memory

### CURRENT ARCHITECTURE

Editorial policy as the product, with a machine check for the mechanical half. Four write rules (provenance tag,
recurrence gate, supersession-as-edit, only-the-non-derivable), four tiers (ROM `MEMORY.md` ≤15,000 chars; RAM
`memory/context` + daily notes ≤30,000; disk `people`/`projects`/`decisions`; tape `archive`), and
`scripts/memory-lint.mjs` (~470 lines) enforcing precisely the subset a program can verify. The lint operates on
the **git diff**, not the working tree, so it polices new facts and leaves history alone, and each of its five
checks prints its own volume.

### CURRENT LIMITATION

Three gaps, all named by the repo or its neighbours: the RAM cap of 30,000 chars is a cap **no process watches**;
nothing anywhere says *when* consolidation runs; and promotion (the one act that must stay editorial) has no
interface, so it means opening a markdown file and typing. Whether a tag is honest is unverifiable by any
program, and the repo says so.

### WHAT MODS CHANGE

Exactly one door, and it is already the specified one. The policy names daily notes as the candidate staging area
("Until then, keep candidates in daily notes"), the lint does not police the RAM tier for provenance, and a
runtime can honestly produce only one tag: `[observed]`, because every Mod event is by definition a tool result
or a log. Four of the Capture Standard's seven triggers are observable from `tool.call` (CONFIRMED): a system
changing state is a successful Bash/Write, a blocker is a tool result that errored, a mistake is an edit
reverting an edit from the same session, a config change is a write to a config path.

### WHAT MODS DO NOT CHANGE

The promotion step, the write rules and the lint. Counting to three is mechanical; deciding that three sightings
are *the same lesson* is not. The recurrence gate's purpose is prompt-injection defence ("a hostile input can
suggest a rule once, and once is never enough"), so a Mod that automates promotion bypasses the defence rather
than implementing the policy. A machine write into `people/`, `projects/` or `decisions/` would FAIL
`checkDiskProvenance` exactly as a sloppy human write does; that boundary is already enforced in code.

### WHAT BECOMES OBSOLETE

Nothing. This is the one project in the portfolio where the correct Mod footprint is a narrow feed and a
read-only surface, and where a larger footprint is a regression.

### WHAT BECOMES SIMPLER

The missing moment. `2-part-memory-system`'s `context-monitor.mjs` is 34 lines whose entire input is
`process.argv[2]`, with a threshold of 90k of 200k = **45 % of window**; `$.session.usage()` (CONFIRMED) supplies
that number after every turn at zero cost. Wire the 45 % trigger to the unwatched RAM cap and the memory folder
gets the one thing it has never had.

### NEW PRODUCT CAPABILITIES

1. A candidate feed with honest provenance: `- [observed 2026-09-16] npm test failed on packages/x after the auth
   refactor (3 retries)`, written by the runtime that saw it.
2. Retrieval Contract enforcement: the policy caps an evidence bundle at five sources and nothing enforces it; a
   hook counting reads under `memory/` per turn can warn at six (`$.ui.toast`, CONFIRMED) and deny at ten
   (`tool.call {deny}`, CONFIRMED).
3. Boot that injects the routing index rather than the facts, matched against the prompt (`prompt.submit` hidden
   context, CONFIRMED).

### LONG TERM ARCHITECTURE

The memory folder as the terminal store of three feeds that already exist and have never been connected: Leg's
`SYNTHESIS-<id>.md` § Ruled out (the highest-value durable fact an agent can hold, and precisely an `[observed]`
one), context-handoff-bundle findings whose anchors verified across three loads in two sessions (which by
construction satisfies the 3-signals/2-sessions gate with `[observed]` provenance), and the runtime candidate
feed. Promotion stays a human act over a rendered list.

### COMPATIBILITY RISKS

- Early access and undocumented.
- `classic.*`, `prompt.section` and `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here), so instruction-file injection uses `prompt.submit` hidden context.
- The permission dialog cannot be drawn (NOT POSSIBLE), so a clickable promotion surface needs `$.ui.ask` or
  `ui.press` on a drawn element, both (EXPERIMENTAL), and `$.ui.open` waits unplaced below 144 columns; the
  CONFIRMED surface today is a registered command that prints the list. Registered-tool result shape applies; one
  hooks module per plugin.
- Project-specific: a memory-writing hook that ingests untrusted content (a fetched page, an issue comment) and
  later feeds it back into a prompt is a private-data plus untrusted-content plus persistent-influence path. The
  `[observed]` tag with a verbatim source is the mitigation and it only works if the hook never summarises what
  it ingested. `[stated]` is machine-derivable only from `prompt.submit` with `origin === 'composer'`, and the
  origin kinds are declared, not exercised (EXPERIMENTAL).

### ONE "HOLY SHIT" DEMO

Work for an hour without writing a single memory line, then type `/memory-candidates`. Today's daily note is
already 11 lines long, every line tagged `[observed]` with a timestamp and traceable to a tool result the session
actually produced, and the last line reads `RAM tier 18,204 / 30,000 chars · consolidation at 45 % window (now
31 %)`. Nothing has been promoted and nothing touched `decisions/`. (CONFIRMED: `$.command.register`, `tool.call`
observation, `$.fs.write`, `$.session.usage()`, `$.session.messages()`.)

### ONE PRACTICAL NEAR TERM FEATURE

A candidate buffer appended to `memory/YYYY-MM-DD.md` at `turn.complete`, `[observed]` only, with the write
ordered **before** any compaction and the failure case handled: a consolidation that silently failed followed by
a compaction loses the day, and a failing hook is skipped and logged.

### ONE SPECULATIVE FUTURE FEATURE

Promotion as a two-phase consent token. `C:\Projects\leg-alexa-mcp\src\confirm.ts` is 45 lines: preview plus a
single-use 32-byte token with a 5-minute TTL bound to one session, fail-closed on restart. A Mod proposes
"promote these 3 candidates", renders the diff, and requires the second token-bearing call before anything is
written to `memory/decisions/`.

---

## declick

### CURRENT ARCHITECTURE

A compiler from any callable surface to a named verb with one output envelope, plus the envelope. Ten engines
(`src/engines/index.mjs`), a compiled manifest with a `SECRETISH` scanner that refuses to save a manifest
containing something token-shaped, and `src/output.mjs` (251 lines, **zero imports**) holding the trimming
pipeline in strict order: `--where` → `--rows` → `--fields` → `--limit` → `--max-bytes` (8192 default) via
`capData()`. `capData()` is the part worth stealing: an over-cap object keeps **every key** and replaces its
biggest values with `<N bytes; add --fields or --limit>`, so the shape needed to write the next query survives
any cap. Measured (`docs/bench.md`, nine stdio MCP servers, 258 tools): raw `initialize` plus full paginated
`tools/list` = 236,818 bytes, `declick describe` = 58,309, ratio **4.1x**; `describe --verb` is 1,031-1,299 bytes
for a server with 2 tools or with 124.

### CURRENT LIMITATION

declick cannot make the model use it. Everything after the envelope (PATH install, a SKILL.md in every agent's
skills dir, a rules block pasted into CLAUDE.md, a `PreToolUse` nudge hook) is asking. The number is on disk:
`~/.declick/hooks/nudge-stats.json` since 2026-09-04 reads **36 fired, 2 followed, 34 ignored (5.6 %)**, with the
`web` key fired 23 times and followed zero times. Meanwhile `~/.declick/audit.jsonl` has 1,120 lines and 27
adapters are compiled, so the compiler works and the routing is what fails.

### WHAT MODS CHANGE

A `tool.call` hook does not ask the model to route differently; it **is** the routing.

| Move | Mechanism | Status |
|---|---|---|
| Result normalization for every tool | `await next(e)`, then return `{result: capData(shape(result))}` | result replacement CONFIRMED; `output.mjs` needs two Node touchpoints swapped (`Buffer.byteLength` → `TextEncoder`, `isTTY` passed in) |
| Answer an `mcp__*` call with declick's envelope | do not call `next`; `$.process.run(['declick','run',adapter,verb,…,'--fields','--limit','--max-bytes'])`, return stdout | answer-without-`next` CONFIRMED, `$.process.run` CONFIRMED |
| One registered `declick` tool from the manifests | `$.tool.register` at `session.start`, description from `describe(m,{verb})` | register + serve CONFIRMED, but deniable (below) |

### WHAT MODS DO NOT CHANGE

The compiler, the ten engines, the manifest model, the MCP client, the daemon, the store and the bench harness.
declick stays the CLI and the compiler; a Mod becomes its enforcement arm. The measured 4.1x is a property of
paying once for the tool surface, and `docs/bench.md` is explicit about the inverse case: for a single tiny call,
raw was 160 bytes and declick 191, because of the envelope. The win is the surface, not every call.

### WHAT BECOMES OBSOLETE

`src/hooks/declick-nudge.cjs` entirely. Roughly 60 of its 132 lines exist only because a classic hook is a
stateless subprocess: `statePath(sessionId)` under `os.tmpdir()`, a six-hour state expiry, a `pending` slot so it
can see the next tool call and score itself, and a JSON file rewritten on every event. A Mod keeps all of that in
a closure, and the 34-of-36-ignored number stops being a metric and becomes a category that no longer exists.
`RULES_BLOCK` (a fixed tax on every prompt in every session, including sessions that never touch an adapter)
becomes hidden context attached only on relevant turns.

### WHAT BECOMES SIMPLER

Per-session state, the `servers.json` lookup (`declick setup` already writes server → adapter), and the
governance path: the guard, the policy, the credential scoping and the audit line all live in `bin/run.mjs` on
this side of every engine call, so routing through the CLI brings them along for free.

### NEW PRODUCT CAPABILITIES

1. An 8 KB ceiling over `Read`, `Bash`, `Grep`, `WebFetch` and every MCP call uniformly, with
   `meta.capped = {bytes, max, hint}` telling the model exactly how to ask again. Today the ceiling protects only
   calls the model chose to route through the CLI.
2. `src/policy.mjs` (55 lines, glob rules, first match wins, fails closed) on `tool.check`, which has the **last
   word up the chain**, strictly more enforcement than declick's guard has today, since a `--dry-run` or a
   direct MCP call routes around `bin/run.mjs` entirely. The confirmed direction is `ask → allow`; a `deny`
   verdict on `tool.check` is (EXPERIMENTAL), so the enforceable block today is `tool.call {deny}`.
3. `derivedMutating()`'s floor generalised: a tool may raise its mutating flag and never lower it, which is why a
   hand-edited manifest cannot claim a delete is read-only.

### LONG TERM ARCHITECTURE

A control loop rather than a ledger. `bin/run.mjs` already records, per call, the exact quantity costclaw exists
to control (`bytes = Buffer.byteLength(out.text)` beside the governance decision, exit code and elapsed ms; 1,120
lines of it on this machine). A `tool.call` hook reading `$.session.usage()` (CONFIRMED) tightens the knobs on
the way in as context fills: `--max-bytes` from 8192 to 2048, `--limit 10`, a verb switched to `--cache 300`,
with `capData()` enforcing it without losing the key names the model needs to ask narrower.

### COMPATIBILITY RISKS

- Early access and undocumented, and this is the project most exposed to it: a Mod that reimplements declick has
  to be re-verified per Claude Code build, where the CLI does not.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here), which is exactly why the nudge hook cannot be upgraded in place: it must be replaced.
- The permission dialog cannot be drawn (NOT POSSIBLE), and `$.mcp.call` bypasses the permission prompt entirely
  (and is itself EXPERIMENTAL), which moves a real security boundary and should be moved visibly.
  Registered-tool results must be `string | content-block[] | undefined`, so the envelope goes over as a JSON
  string and declick's five exit codes have no home except inside it. One hooks module per plugin.
- Project-specific: `tool`, `tool_use_id` and `agentId` are pinned, so a true alias of one tool to another is
  (NOT POSSIBLE) and answering with `{result}` is the substitute. `sec-default` denies user-tier
  `$.tool.register` when managed policy sets `allowedMcpServers` (not set here, but the fallback must exist).
  `tool.describe` fires (CONFIRMED) but the rewrite is (EXPERIMENTAL), cached per session and needs
  `$.ui.invalidate`. `$.process.run` has no shell, 30 s default, 10 min ceiling.

### ONE "HOLY SHIT" DEMO

Ask the model to list a page snapshot through the Playwright MCP server. The result it receives is 2,048 bytes
with every key still present and the largest values replaced by `<38412 bytes; add --fields or --limit>`, and its
next call is the same tool with `--fields role,name,ref --limit 20`. Nobody typed a flag and no nudge fired.
(CONFIRMED: `tool.call` result replacement, `$.process.run`, `$.ui.log`.)

### ONE PRACTICAL NEAR TERM FEATURE

Port `src/output.mjs` into a Mod and cap every tool result in the session with a hint. Two lines of change
against 251, and the single highest-value piece of declick to move.

### ONE SPECULATIVE FUTURE FEATURE

Task-scoped tools: when a plan repeats the same three calls, compile a `compose:` chain at runtime from adapters
already built, register it for that task (CONFIRMED `$.tool.register`), and drop it at `turn.complete`.
`src/defaults.mjs` already supplies the scoping model, with values re-parsed through `parseFlags` so a default is
validated exactly like a typed flag.

---

## agent-capsule

### CURRENT ARCHITECTURE

One 861-line zero-dependency Node file (`capsule.mjs`, 41 functions) that packs `~/.claude` into a tarball,
rewrites every absolute home path to `__CAPSULE_HOME__` (`capsule.mjs:11`), follows hook commands out of the tree
to stage the external repos they call into, derives an install plan for every interpreter and binary the hooks
need (`capsule.mjs:257 deriveProvision`), and refuses to tar anything if `scanForSecrets` (`capsule.mjs:305`)
hits. Two sub-primitives matter more than the tarball: `runDoctor` (`capsule.mjs:466`) executes **every hook in
`settings.json`** with a synthetic SessionStart payload and prints `hooks: N/M pass`, and the secret scan deletes
the stage and exits 2 on a hit, so nothing is ever tarred.

### CURRENT LIMITATION

It is a file mover. It cannot move a running session, an in-flight plan, or anything the model knows but has not
written down. The doctor runs when a human types it. `scanForSecrets` fires at pack time, which is hours after
the key was written. `provision` is a static table keyed by hook binary plus a `python3 -m <module>` detector, so
a hook calling an unlisted binary provisions nothing.

### WHAT MODS CHANGE

The timing of two checks, not the tool. The secret scan moves to the moment of the write: the same regex set and
`PLACEHOLDER_RE` allowlist inside a `tool.call` hook can `{deny}` the Write that would create the secret
(CONFIRMED). That is roughly 20 lines around an existing, tested function and it is the highest-value port in the
repo. The doctor becomes continuous: run it at `session.start` and again on a cadence hung off `turn.complete`
(both CONFIRMED) through `$.process.run` (CONFIRMED), raising `$.ui.toast` (CONFIRMED) with `N/M` in the message
the moment a hook starts failing.

### WHAT MODS DO NOT CHANGE

Capsule stays a CLI. A plugin cannot install anything on a remote box, cannot drive `ssh`/`devbox` transport
decisions, and `$.process.run` on the local machine is not a substitute for the deploy path. The exclusion policy
(`history.jsonl`, session files, `projects/` except `*/memory/`) and the `apply` rule that keeps the target's own
`.credentials.json` so Claude Code stays logged in are unaffected.

### WHAT BECOMES OBSOLETE

Nothing. This is a repo Mods make *continuous* rather than replace, and saying otherwise would be wrong: the
tarball, the path tokenizer, the external-reference parser and the provision derivation have no Mod equivalent.

### WHAT BECOMES SIMPLER

The doctor's inputs. A Mod sees the session's own hook chain through `next.trace` (CONFIRMED, per-link ms and
outcome), so "did the chain run" stops being inferred from an exit code per synthetic payload.

### NEW PRODUCT CAPABILITIES

1. A secret tripwire at write time rather than at pack time.
2. Capsule provenance in the footer: stamp which capsule version this machine runs and render it (CONFIRMED
   `ui.render`), so a devbox that silently drifted is visible.
3. A capsule-aware dispatch: downgrade or refuse a subagent whose declared binaries are not on the box's PATH,
   with the doctor rows as input, instead of letting it discover that mid-task (`agent.spawn` rewrite CONFIRMED;
   deny is EXPERIMENTAL).
4. A Mod is itself a capsule payload: a folder of code with external dependencies and a `hooks.json`, exactly
   what capsule already knows how to pack, path-rewrite, secret-scan and prove working on a fresh box.

### LONG TERM ARCHITECTURE

Capsule as the unit of comparison. `capsule pack` produces a hermetic, path-rewritten snapshot of a hook set, so
two capsules are two comparable configurations; point agent-pit's `scripts/self-play.ts` dominance gate at them
over a fixed task suite and the harness gets its first honest answer to "did that new hook actually help".

### COMPATIBILITY RISKS

- Early access and undocumented; a capsule that packs a Mod packs a plugin whose API may change under it, so the
  manifest should record the build it was proven on.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here), so a capsule's doctor cannot exercise a Mod through the classic path and needs a
  function-hook leg of its own.
- The permission dialog cannot be drawn (NOT POSSIBLE). Registered-tool result shape applies; one hooks module
  per plugin.
- Project-specific: `$.process.run` has no shell, a 30 s default and a 10 min ceiling, so a full doctor over a
  large hook set must be chunked; `$.clock.every` is (EXPERIMENTAL), so the cadence hangs off `turn.complete`;
  and a Mod cannot install or verify anything on a remote box, which is half of what capsule exists for.

### ONE "HOLY SHIT" DEMO

Ask the model to write a config file containing a live-looking Stripe key. The Write never happens: the terminal
shows `✖ BLOCKED: Write src/config.ts · secret pattern stripe_live · value not echoed`, the file on disk is
unchanged, and the model quotes the refusal and asks for an env var name instead. Today the same key would sit in
the repo until the next `capsule pack` found it. (CONFIRMED: `tool.call {deny}` with the reason reaching the
model, `$.ui.toast`.)

### ONE PRACTICAL NEAR TERM FEATURE

`scanForSecrets` plus `SECRET_PATTERNS` and `PLACEHOLDER_RE` lifted as-is into a `tool.call` matcher on
`Write|Edit|MultiEdit|NotebookEdit`, denying on a hit and never echoing the value. The function is already tuned
against a real harness (it packs `token-guard.cjs` but not `*token*` data files).

### ONE SPECULATIVE FUTURE FEATURE

Harness A/B: pack two capsules, run the same task suite under each on the devbox, and report the measured diff in
tokens, wall time and guard fires, with clawd's budget bands inside the doctor, so a capsule reports not just
"your hooks execute" but "your hooks cost X USD per session".

---

## rewind

**This repository is an OBS instant-replay booth for Halo Infinite streaming.** `README.md:1-8`: "Rewind is a
local replay booth for Halo Infinite streaming. You press one button… Rewind saves the last few seconds from OBS,
edits the clip (trim, slow-mo, punch-in zoom, a REPLAY banner), and airs it on stream like a TV instant replay."
The ten Python modules are `airgate, archive, bus, capture, config, core, editor, obs, server`; the dependencies
are OBS WebSocket, ffmpeg and dxcam; all 35 commits are Halo. There is no session replay, no file checkpointing,
no undo and nothing touching a coding agent. The dispatch premise is wrong, and what follows analyses **only the
air gate**.

### CURRENT ARCHITECTURE

`rewind/airgate.py` is a 74-line clock-injected state machine, tested against an injected clock
(`tests/test_airgate.py`). Four inputs (`clip_ready(now)`, `game_signal(signal, now)`, `force(now)`, `cancel()`)
and one output, `tick(now) → NONE | AIR_FULL | AIR_PIP`. A forced clip airs immediately; a `death` or
`round_end` within `LATCH_TTL = 8.0` seconds airs full-screen; otherwise it waits for `quiet_s` seconds of no
activity; and if `hold_max_s` elapses with no safe moment it **degrades to picture-in-picture rather than
dropping or interrupting**.

### CURRENT LIMITATION

As an agent primitive it has none: the gate is 74 lines, pure, tested and clock-injected. As a repository it is
single-machine, Windows-only, OBS-coupled, and its detection half does not exist (the human is still the
trigger).

### WHAT MODS CHANGE

Every notice a Mod raises competes with what the human is reading: context at 80 %, budget low, a guard fired, a
doc gone stale. The gate's signals map onto confirmed events: `quiet` is `turn.complete` (CONFIRMED),
`round_end` is the end of a long tool run (`tool.call` result, CONFIRMED), `force` is a hard signal such as a
deny, and its three outcomes map onto confirmed surfaces: `AIR_FULL` is `$.ui.toast` (CONFIRMED dispatched) or a
full band, `AIR_PIP` is one dim line in `$.ui.status` (CONFIRMED, drawn), `NONE` is silence.

### WHAT MODS DO NOT CHANGE

A Mod cannot suppress the engine's own UI, so an air gate governs **your** notices only. The permission dialog is
not drawable (NOT POSSIBLE), so the gate cannot defer or restyle an engine-raised approval. And the repo stays a
Halo tool; the idea is the find, not the repository.

### WHAT BECOMES OBSOLETE

Nothing in the repo. What becomes obsolete is the per-Mod habit of raising a toast the instant a condition trips,
which is how a governed agent becomes one people turn off.

### WHAT BECOMES SIMPLER

One notice policy for the whole plugin stack instead of a decision at each call site. `rewind/bus.py`'s 40-line
`Bus`/`HeartbeatRegistry` pair gives the same shape for "which of my background jobs is alive, with a count", and
`rewind/core.py:56-75`'s never-strand loop (catch, publish the error, restore the safe state, continue) is the
right failure posture for a hook whose own failure must not cost the session.

### NEW PRODUCT CAPABILITIES

Notices that never interrupt a thought and never silently rot, the property agent-comms' three-message cap
exists to protect and cannot enforce, and the property that makes an approval queue survivable.

### LONG TERM ARCHITECTURE

One notice bus per Mod stack: every guard, cost warning, staleness alert and inbox delivery is queued with an
urgency, released at the next quiet boundary, and degraded to a counted footer line if it has waited too long.
The urgency ladder is the only per-source decision; timing is centralised.

### COMPATIBILITY RISKS

- Early access and undocumented.
- `classic.*` / `prompt.section` / `prompt.context` are withheld from user plugins on managed-settings machines
  (NOT POSSIBLE here), so the gate cannot take a `Notification` event as a signal; `turn.complete` is the
  substitute.
- The permission dialog cannot be drawn (NOT POSSIBLE), so an approval cannot be held by the gate; only a notice
  about one can. Registered-tool result shape applies; one hooks module per plugin.
- Project-specific: `$.clock.every` is (EXPERIMENTAL), so `hold_max_s` is evaluated on a natural event
  (`turn.complete`, CONFIRMED) rather than a wall clock, and a held notice is lost when the session closes.
  `rewind/archive.py:30 prune_raw` contains a real bug worth reading before copying anything else from the repo:
  `files[:-raw_keep]` silently keeps everything when `raw_keep == 0`.

### ONE "HOLY SHIT" DEMO

During one long turn, three separate guards fire and the screen stays completely still. The moment the turn ends,
one line appears: `⟦notices⟧ 3 held · cache decay 62 %→41 % · 2 stale docs · declick adapter available`, while a
fourth notice marked urgent (a denied write) had already appeared instantly, mid-turn. Nothing interrupted and
nothing was lost. (CONFIRMED: `tool.call` observation, `turn.complete`, `$.ui.status`, `$.ui.log`.)

### ONE PRACTICAL NEAR TERM FEATURE

Port `airgate.py` verbatim as the single exit for every `$.ui.*` call a Mod makes, with `turn.complete` as the
quiet signal and a deny as the only default force condition.

### ONE SPECULATIVE FUTURE FEATURE

Approvals and agent mail through the same gate: `[URGENT]` forces immediately, everything else waits for a quiet
window, and anything held past the limit degrades to a counted line rather than a toast: mail that never
interrupts a thought and never rots.

---

## Forgotten repos with the biggest upside

### AgentLens (`ucsandman/AgentLens`, archived 2026-05-13 "absorbed into DashClaw")

`src/repeated-runs.js` is 86 lines holding the best confidence taxonomy in the sweep: `high` = same target across
≥3 model requests, `low` = the run sits inside a single model request, "a batch, not a stuck loop", with the rule
that callers must not compute savings from low-confidence runs. Five waste rules the costclaw line never absorbed
live in `src/rules/`: `CONTEXT_GAPS_DETECTED`, `MODEL_DOWNSHIFT`, `CACHE_WRITE_BLOAT`, `SUBAGENT_PROMPT_BLOAT`,
`REPEATED_READ_CYCLES`. `tool.call` (CONFIRMED) delivers the request boundary as an event, so the grade becomes a
fact and costclaw's share gates can be deleted; `agent.spawn` (CONFIRMED) delivers the whole subagent prompt, so
the bloat rule stops estimating from 200-char previews. Do not port `src/hooks-gen.js` (it generates classic
hooks, NOT POSSIBLE here) or `src/pricing.js` (stale rate card; use costclaw's).

### agent-pit (`C:\Projects\agent-pit`, 163 commits, untouched since July)

`src/lib/replay-utils.ts` defines a versioned event-stream replay format and `src/lib/replay-controller.ts` (363
lines) plays both format versions with play/pause/seek and a speed multiplier. `tool.call`, `turn.step` and
`agent.spawn` (all CONFIRMED) emit exactly the frame-stamped, agent-attributed stream that format holds, so
recording a Claude Code session into `EventStreamReplay` is a mapping job, not a build. Also here: a 12-line
seeded PRNG, a 300-match self-play dominance gate that exits 1 if any policy dominates, and
`src/server/routes/coach.ts`, a one-shot authenticated ≤100-character steering window into a running agent's
system prompt. Honest limit: replaying recorded results proves the **tools** deterministic, not the model: no
seed is exposed by `turn.step`, so a deterministic model re-run is (NOT POSSIBLE).

### Agent-Task-Router (`ucsandman/Agent-Task-Router`)

A complete fleet dispatcher in 900 lines with no framework: `src/matcher.js` scores every candidate on four axes
with explicit budgets (capability 40, free capacity 20, per-skill history 25, priority 15) and returns
human-readable `reasons[]`; `src/router.js` has retry → timeout → escalate transitions and a `routing_log` audit
table. It was starved of the one thing it scores on (performance history) because it dispatches to
HTTP-addressable agents that report their own completion. `agent.spawn` (CONFIRMED rewrite) is a dispatch it
controls and `turn.complete` per `agentId` (CONFIRMED) is duration, tokens and model for free. One constraint:
the capability graph (Fable → Opus → Sonnet → Haiku, downward only) must filter candidates **before** scoring or
the scorer will happily propose a denied edge.

### clawd `hooks/` (`ucsandman/clawd`, private, 75,005 files)

Two finished hook implementations written two runtimes too early, buried under a generated dump.
`hooks/smart-model-router/handler.ts` + `budget.ts` (2026-02-05) classifies each message, switches the session
model, and overlays four budget bands (normal >30 % weekly, warning ≤30 %, Opus blocked ≤20 %, force-Sonnet
≤15 %) with exponential backoff and jitter; its budget data comes from shelling out to `capture.py` and parsing
the output. `$.session.usage()` (CONFIRMED) returns context %, five-hour and seven-day % and cost USD natively,
deleting `budget.ts`, its dependency and the parsing in one move. `hooks/memory-injection/handler.js`
(2026-02-08) is a sub-300 ms vector-memory prompt injector that becomes `prompt.submit` hidden context
(CONFIRMED), and `agents/smart-session-rotation.md`'s 500-tokens-every-5-messages context poll goes to zero.
Caveat: per-request model rewriting on `turn.step` is (EXPERIMENTAL); `agent.spawn` is the confirmed lever.

### context-health-bar (`ucsandman/context-health-bar`, MV3 Chrome extension)

`calculateHealth()` in `content.js` is an instruction-distance drift model, not a token gauge: penalise when more
than 50 % of the conversation sits after the last instruction-bearing message,
`instructionPenalty = (distanceRatio - 0.5) * 80`, with length terms combined by `max()` rather than summed,
tiered stable/degrading/unreliable/critical. `$.session.usage()` (CONFIRMED) makes the length half exact,
`$.session.messages()` (CONFIRMED) makes the instruction half first-class, and `tool.call` (CONFIRMED) adds the
noise term the DOM could never see: a 4,000-line test dump displaces instructions far harder than prose. Keep
the extension for claude.ai (a Mod cannot render in a browser tab); revive the model as a Mod and give Leg the
quality trigger its `chooseNext()` has never had.

### spendwall (`ucsandman/spendwall`, pushed 2026-07-09)

`packages/core/src/policy.ts` is ~150 lines, one dependency, pure: `evaluatePolicies(policies, ctx)` returns
`allow | flag | needs_approval | block` with precedence `block > needs_approval > flag > allow` and an
`enforcement: monitor | alert | block` ladder. It is the decision layer costclaw has never had: costclaw
computes a number and stops. `$.session.usage().cost` (CONFIRMED) replaces the rail importers, the AES-256-GCM
connection keys and the cron sync route for the one rail spendwall's own list never covered. Note the enforcement
asymmetry: spendwall's `freeze` is out-of-band key revocation, strictly stronger than a hook that can be disabled
by removing `--plugin-dir`, and `needs_approval` has no native surface because the permission dialog cannot be
drawn (NOT POSSIBLE) and `$.ui.ask` is (EXPERIMENTAL).

---

## What this document does not establish

- No capability here was re-verified. Every tag traces to §20, measured on build 2.1.273 on this machine with
  managed settings present. On a machine **without** managed settings the `classic.*` / `prompt.section` /
  `prompt.context` line changes and several NOT POSSIBLE entries become UNKNOWN (§20 says so).
- No cost, token or latency figure here was measured by this pass. The 1,099 ms, the 4.1x, the 5.6 % and the
  17k/60k spawn constants are quoted from the reports that measured them.
- Cross-plugin ordering between two user plugins has **not** been run (§7), which matters for every design above
  that assumes a recorder sits outermost. The one observation that exists is in `lab/README.md`: a `blackbox`
  plugin loaded after `guardian` never saw the denied Edit and reported "0 denied" while `xray`, loaded first,
  saw it. Order of `--plugin-dir` is order in the chain.
