# Sprint checkpoint (resume here if the session, usage window, or agent changes)

Repo: `C:\Projects\claude-mods-rnd` (branch master). Nothing committed yet.

## Phase 1 — DONE (2026-09-16 ~15:40)
- `MOD_CAPABILITY_MAP.md` — authoritative capability map (CONFIRMED / EXPERIMENTAL / INCOMPLETE / NOT POSSIBLE / UNKNOWN) + benchmark table.
- `snapshot/2.1.273/` — `claude-code.d.ts` (extracted from the binary), `plugin-authoring-SKILL.md`, `README.md` (build, gate, loader, failure semantics, sec-default decompile), `payloads/*.jsonl` (raw events), one full debug log.
- `lab/probe` (on("*") logger), `lab/probe2` (interception), `lab/probe3` (permission override, subagent, agent.spawn, prompt context), `lab/probe-ui` (interactive UI), `lab/bench` — all validated and run.
- `tools/pty_drive.py` — drives a real interactive `claude` session through pywinpty + pyte and snapshots the screen. Usage in file header. Needs `pip install pywinpty pyte` (done).

Key facts to carry forward:
1. Function hooks are ON for this account (GrowthBook `tengu_plugin_hooks_modules`), no env var needed. Load with `claude --plugin-dir <folder>`.
2. Module = `hooks/hooks.json {"modules":["./index.tsx"]}` + `export const register = (on, options) => {...}`. Validator is strict: `$` only as `$.noun.method()` or passed to a top-level function; `on("literal", ...)`; one registration per event without matcher; `.tsx` for JSX.
3. This machine has `C:\Program Files\ClaudeCode\managed-settings.json` → `sec-default@builtin` withholds `classic.*`, `prompt.section/context`, `skill.prompt`, `attribution.text`, `settings.read` hooks from user plugins. Build on `tool.call`, `tool.check`, `turn.*`, `agent.*`, `prompt.submit`, `ui.*`, `session.*`, op events instead.
4. Headless runs: `claude --plugin-dir X -p "..." --model haiku --allowedTools "Bash,Read"`; add `# SEQ: probe` to Bash commands and `# EST: n calls, n files # SPAWN_OK: why` to Agent prompts so the production harness guards (batch-guard, subagent-budget-guard, capability-graph-guard) let probes through. Never `taskkill /IM claude.exe` (kills this session).
5. Registered-tool results must be `string | content-block[] | undefined`.
6. Panes open unasked only at ≥144 columns; the pty driver uses 140 → use a `/command` (asked) or 150 cols.

## Phase 2/3 — DONE (~15:50)
- `lab/xray` (wildcard inspector, filters, HUD, timeline) + `lab/demos/{matrix,bender,guardian,blackbox,tunnel/*}` — all dogfooded in one real interactive session (`snapshot/2.1.273/payloads/demo-screen-snapshots.txt`). `lab/README.md` has run instructions and the ordering lesson (recorder must be outermost).

## Archaeology — DONE (~16:40)
- 7 parallel opus-owner agents → `archaeology/A..G-*.md` (6,700 lines) → synthesised into `MOD_REPO_ARCHAEOLOGY.md` (6 gems from unnamed repos, 15 direct opportunities, merge/stay/less/more tables). Clones under `archaeology/clones/` (gitignored).
- `PROTOTYPE_SHORTLIST.md` holds the running Phase-17 candidates.

## Jev — READY, BLOCKED ON KEY
- `experiments/jev/{build_states.py, questions.py, run_judge.py}`; 11 real+synthetic runtime states with ground truth; backends `jev | haiku | stub`. Stub 35/36, Haiku (via `claude -p`, subscription) 32/36 at ~40 s/call. No `TYPESAFE_API_KEY` on this machine (495 keys scanned). `creds mint typesafe --open` prints the key page; paste into `experiments/jev/.env`; then `python run_judge.py jev` (cap 60k tokens).

## Phases 4–16 — DONE (~20:35)
- `MOD_PORTFOLIO_ANALYSIS.md` (agent-drafted, 1,579 lines, 14 projects × 12 headings), `SPECIAL_INVESTIGATIONS.md`, `PORTFOLIO_RUNTIME_MAP.md`, `MOD_INVENTIONS.md`, `MOD_RISK_REGISTER.md`, `MOD_ROADMAP.md` (draft; patch after prototypes), `README.md`.
- Phase 14 adapter BUILT and proven: `adapter/claude-runtime` (custom noun `$.runtime`, cross-plugin `runtime.emit` bus, probed `supports`, `judge` with stub|model|jev; model judge 1.1 s in-process) + `adapter/consumers/echo`. README in `adapter/README.md`.
- Spikes proven: `lab/spike-handoff` ($.turn.abort + bundle at turn.complete), `lab/spike-compact` ($.session.compact from a plugin: 52,599→9,229 tokens), `lab/spike-describe` (tool.describe rewrite reaches the model; agent.offer hides Plan; prompt.suggest fires). Capability map §20 updated with all of it.
- Memory saved: `~/.claude/projects/C--Projects-claude-mods-rnd/memory/{function-hooks-sprint,typesafe-jev-key}.md`.

## Phase 17/18 — DONE (~21:05)
- Three prototypes built, validated, dogfooded individually (see each README + evidence/) and together (`DOGFOOD.md`: 2,308 events, 0 hook errors, one subagent routed opus→haiku and priced, one command contained via dialog). Divergences recorded (target-keyed interception, explain rewrites via context[], exempt SubagentHandback, rate-card drift).
- Final reports: `MOD_CAPABILITY_MAP.md` (updated through 20:35), `MOD_PORTFOLIO_ANALYSIS.md`, `PORTFOLIO_RUNTIME_MAP.md`, `MOD_RISK_REGISTER.md`, `MOD_ROADMAP.md` (patched with outcomes), `MOD_INVENTIONS.md`, `SPECIAL_INVESTIGATIONS.md`, `MOD_REPO_ARCHAEOLOGY.md`, `README.md`.
- Nothing committed (Wes decides); nothing outside the repo modified except: `C:\Projects\creds\creds.mjs` (+1 line: typesafe recipe), two memory files under `~/.claude/projects/C--Projects-claude-mods-rnd/memory/`, `pip install pywinpty pyte typesafe-sdk`.

## (historical) Phase 17 dispatch note (three opus-owner builders dispatched ~19:55, brief in `prototypes/BUILD_BRIEF.md`)
- `prototypes/supervisor` (routing+budget replacing 4 guards), `prototypes/costclaw-live` (HUD + cache interceptor), `prototypes/prodguard` (DashClaw×offlocal policy, approvals). Each must ship README/diagram/run/proves/does-not-prove/API assumptions/failure/migration/evidence.
- Phase 18 plan: after they report, run all three + adapter together via `tools/pty_drive.py` (adapter first), exercise allowed/denied/rewritten paths, record findings in `DOGFOOD.md`, patch `MOD_ROADMAP.md` and the capability map with anything that differed.

## Next
- Phases 4–13 write-ups (`MOD_PORTFOLIO_ANALYSIS.md`, `PORTFOLIO_RUNTIME_MAP.md`), the shared runtime adapter prototype (`adapter/`), then Phase 17 top-3 builds, dogfood, `MOD_RISK_REGISTER.md`, `MOD_ROADMAP.md`.
- Phase 2/3: `lab/xray` (on("*") inspector with filters, AbovePrompt HUD, pane) + demos MATRIX / REALITY BENDER / GUARDIAN / TUNNEL / BLACK BOX, dogfooded via `tools/pty_drive.py`.
- Archaeology subagents (parallel) → `archaeology/*.md` → `MOD_REPO_ARCHAEOLOGY.md`.
- Then phases 4–19 per the brief; prototype shortlist lives in `PROTOTYPE_SHORTLIST.md`.
