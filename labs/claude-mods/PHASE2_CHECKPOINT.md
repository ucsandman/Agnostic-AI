# PHASE2_CHECKPOINT — promotion sprint (resume here)

Sprint 2026-09-16 21:10 → 22:45 (Fable 5.1 main loop; six subagents died at the five-hour limit at ~21:50 and their slices were finished inline). Brief: promote proven Function Hook capabilities into the real harness behind rollback. **Result: five guards MOD DEFAULT in `~/.claude/mods`, canary + liveness live, seven cross-repo seams prepared.** Read `PROMOTION_STATUS.md` first, then `SHADOW_MODE_ARCHITECTURE.md`, `MOD_MIGRATION_PLAN.md`, `INTEGRATION_MATRIX.md`, `PHASE2_DOGFOOD.md`.

## State of every repo (recorded 22:45; **all pushed 2026-09-16, see Ship record**)

| Repo | Branch | HEAD at start | My changes | Other sessions' dirt (untouched) |
|---|---|---|---|---|
| C:\Projects\claude-mods-rnd | master | bda6738 | 6 new docs, DECISIONS/ERRORS appends, `prototypes/prodguard/evidence/shadow-compare.mjs`, `experiments/jev/{results-jev.jsonl,summary-jev.json}`, `snapshot/2.1.273/payloads/phase2-dogfood-screens.txt` | — |
| C:\Users\sandm\.claude (live harness) | main | c03067e | `mods/**` (new), `hooks/lib/mods-mode.cjs`, `hooks/mods-liveness.cjs`, `hooks/tests/mods-mode-probe.cjs` (+README), seams in `agent-model-guard.cjs`, `subagent-budget-guard.cjs`, `context-nudge.py`, `tool-output-secret-watch.cjs`, `guard-canary.ps1`; `settings.json` (enabledPlugins ×2, extraKnownMarketplaces, UserPromptSubmit += mods-liveness); `statusline.ps1` badge; `scripts/mirror-sync.cjs` SYNC_DIRS+EXCLUDE; `.gitignore`; gate lock relocked | `settings.json` (model/statusLine edits), `projects/.../people/wes.md`, `skills` |
| C:\Projects\agnostic-ai | master | 7e35b51 | `engine/hooks/capability-graph-guard.cjs` seam, `engine/hooks/universal-adapter.cjs` (+capabilitiesOf/requires), `core/templates/targets.json` supports, `engine/tests/reg-capabilities.cjs`, README table, package.json test chain | `.claude/`, `CLAUDE.md` |
| C:\Projects\costclaw | main | 9f0ffdc | `packages/engine/src/{targets,live}.ts`, `parser.ts`/`index.ts` exports, `packages/engine/tests/targets.test.ts`, README | — |
| C:\Projects\leg | main | e47ee8b | `src/taps/mod.mjs`, `test/taps-mod.test.mjs`, `fixtures/runtime-events.jsonl`, `docs/runtime-tap.md` | 20+ files (history feature, board) |
| C:\Users\sandm\clawd\projects\context-handoff-bundle | main | 45644f1 | `src/context_handoff_bundle/from_events.py`, `tests/test_from_events.py`, README | `cli.py`, `pyproject.toml`, checkpoint/watcher files |
| C:\Projects\discovery-loop | master | f867681 | `runtime_ingest.py`, `tests/test_runtime_ingest.py`, README | solver.py, paper/, memory/ |
| C:\Projects\offlocalai-mcp | main | b0627ca | `src/policy-core.ts`, `test/policy-core.test.ts`, `docs/state-json-contract.md`, package.json exports | — |
| C:\Projects\DashClaw | main | e3a74e01 | `docs/mod-transport.md` | docs/launch, marketing |
| C:\Projects\claude-harness (mirror) | main | c5b7bea | to receive `mirror-sync.cjs` output (see Next) | — |

## Tests run (all read, all green)
harness-mods lib 10/10 · mods-mode-probe 18/18 · fanout-probe 5/5 · guard-probe 7/7 · gates gate-freeze 54 files match · `claude plugin validate` ×2 success · mods canary 8/8 legs · prodguard core 21/21 · agnostic `npm test` green incl. reg-capabilities 5/5 · costclaw 316/316 + typecheck · leg taps-mod 11/11 + eslint · handoff pytest 79 (3 new) · discovery 3/3 · offlocal 293/293 + build · Jev battery 32/36 (21.6k tokens of the 60k cap).

## Promotion status (short)
MOD DEFAULT: canary/heartbeat, contextNudge, rewrite explanations, subagentAccounting, routing, secretRedaction, readCache. INTERFACE PREPARED: CostClaw, LegCli, handoff bundle, offlocal, DashClaw doc, Agnostic supports (declaration live). SHADOW: Discovery ingest (observations), prodguard replay. LAB: Jev/judge.

## Known failures / open items
- Fable-parent routing and the Haiku-leaf deny are unit-tested only (no Fable-main probe at 98–100 % five-hour usage).
- A real 80 % context crossing was not reached; the nudge path is tested + CONFIRMED mechanism only.
- The pty dogfood's redaction turn did not run (limit hit); redaction evidence is from S1/S2 headless.
- DashClaw pure re-export boundary not built (doc only). LegCli/handoff wiring lines documented, not applied (files owned by live sessions).
- `RUNTIME_PIN` = 2.1.273; after a Claude update the canary goes red until re-probed.

## Commits (2026-09-16 ~23:00, ALL PUSHED — see Ship record)
- `~/.claude` main `67ad847` feat(mods) — settings.json deliberately left uncommitted (carries another session's model/statusLine edits + my enabledPlugins/marketplace/liveness-hook hunks); review its diff, then commit it.
- `C:\Projects\claude-harness` main `7e088ea` (twenty-ninth sync; mirror-sync copied 39 files, sweep clean)
- `C:\Projects\claude-mods-rnd` master `f754524` + this checkpoint
- costclaw `1d05596` · leg `2670fdb` · context-handoff-bundle `eb748ed` · discovery-loop `c9aa350` · agnostic-ai `9792625` · offlocalai-mcp `11d9349` · DashClaw `93ce5abe`

## Ship record (2026-09-16, verified with `git rev-list --left-right --count @{u}...HEAD`)

| Repo | Remote | State |
|---|---|---|
| ~/.claude | claude-config | pushed, `c8cf872`, clean |
| ~/.claude/skills | claude-skills | pushed, `00583f8`, clean |
| claude-harness (mirror) | claude-harness | pushed, `61b3169` (thirtieth sync), clean |
| claude-mods-rnd | claude-mods-rnd | pushed, clean |
| costclaw, leg, agnostic-ai, discovery-loop, context-handoff-bundle, DashClaw | own remotes | pushed; four carry other sessions' uncommitted files, none of them this sprint's |
| offlocalai-mcp | adi4x4/offlocalai-mcp | **NOT pushed** — ahead 27 / behind 5 on a remote Wes does not own; needs a rebase and Wes's call |

Checkpoint items 1 and 2 are done. The harness `settings.json` hunks landed in `c870385`;
this session committed only the leftover `model` line (`claude-fable-5-1[1m]` → `opus[1m]`)
and a skills-repo `.gitignore` for `ctx/`, `typesafe-ai/` and `synced/`, which had been
keeping the `skills` gitlink permanently modified.

## Post-ship defect (2026-09-16, found by Wes starting a session in another repo)

The layer armed in exactly one terminal. `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` was exported by hand in
the promoting session and never written to the user config, so a normally started session loaded no
function hooks: `/mods` unknown, statusline `MOD none`, all five guards silently classic, while
`claude plugin list` still showed both plugins enabled. Fixed in `~/.claude` `405195c` (config + README
section), mirrored in `97c7254`. Also synced the plugin cache, which still held the 17:22 skeleton
(1.7 KB `index.tsx`, 1 of 10 lib modules) because the version never changed. Both in `docs/ERRORS.md`.

Verification, three headless runs in `C:\Projects\leg`: switch absent = 0 heartbeats, exported = 1,
config-supplied = 1 with `runtime=true`, 5/5 armed, canary ok, pin 2.1.273.

## Next exact action
1. offlocalai-mcp: rebase the 27 local commits onto the 5 upstream ones, then ask Wes before
   pushing to a repo he does not own.
2. First real session on Fable: check `/mods` and the statusline badge; run
   `node ~/.claude/mods/shadow-report.cjs` after a day.
