# claude-mods-rnd — Claude Code Function Hooks ("Mods") R&D sprint

Sprint of 2026-09-16 against Claude Code **2.1.273**. Nothing here touches the production harness; every
plugin loads only with `--plugin-dir`. The API is early access and undocumented; treat every claim as dated.

## Read in this order
1. `MOD_CAPABILITY_MAP.md` — what the API can do, by status (CONFIRMED / EXPERIMENTAL / INCOMPLETE / NOT POSSIBLE / UNKNOWN), plus the classic-vs-function benchmark.
2. `snapshot/2.1.273/` — the extracted declarations (`claude-code.d.ts`), the build/gate/loader facts, raw event payloads, debug logs. Diff against future builds.
3. `lab/README.md` — the X-RAY inspector and the five physical middleware demos (MATRIX, REALITY BENDER, GUARDIAN, TUNNEL, BLACK BOX), all dogfooded.
4. `MOD_REPO_ARCHAEOLOGY.md` — what the portfolio already contains (six forgotten gems from repos not named in the brief), synthesised from `archaeology/A..G-*.md`.
5. `MOD_PORTFOLIO_ANALYSIS.md` — per-project: architecture, limitation, what Mods change, demos, risks.
6. `SPECIAL_INVESTIGATIONS.md` — LegCli, handoff bundle, CostClaw, Agnostic + harness, DashClaw, offlocal, giti, economic routing, capsule/rewind, declick, memory, Discovery Loop, Jev.
7. `PORTFOLIO_RUNTIME_MAP.md` — the shared runtime layer (built: `adapter/`), capability negotiation, the generic judgment interface, the combinations.
8. `MOD_INVENTIONS.md` — the unfair advantage and fifteen new capabilities ranked against the real API.
9. `prototypes/` — the three Phase-17 builds (`supervisor`, `costclaw-live`, `prodguard`), each with README, diagram, run steps, evidence.
10. `MOD_RISK_REGISTER.md`, `MOD_ROADMAP.md` — risks and DO NOW / PREPARE INTERFACES NOW / WAIT / DO NOT BUILD.
11. `CHECKPOINT.md`, `PROTOTYPE_SHORTLIST.md` — resume points and the candidate list.

## Quick start
```
claude --plugin-dir C:\Projects\claude-mods-rnd\lab\xray                       # the X-RAY
claude --plugin-dir C:\Projects\claude-mods-rnd\adapter\claude-runtime ^
       --plugin-dir C:\Projects\claude-mods-rnd\prototypes\supervisor ^
       --plugin-dir C:\Projects\claude-mods-rnd\prototypes\costclaw-live ^
       --plugin-dir C:\Projects\claude-mods-rnd\prototypes\prodguard           # the three prototypes on the adapter
claude plugin validate <dir> --json                                          # before any run
python tools\pty_drive.py out.txt 25 "<dir>[,<dir>]" "<prompt>|||KEYS:1|||WAIT:5" 30 "" --debug   # scripted interactive dogfood
```
Requires `pip install pywinpty pyte` for the driver. Headless probes: `claude --plugin-dir <dir> -p "..." --model haiku --allowedTools "Bash,Read"`, with `# SEQ: probe` on Bash commands (the production batch-guard) and `# EST: … # SPAWN_OK: …` in Agent prompts.

## Experiments
- `experiments/jev/` — the TypeSafe Jev judgment battery (11 real runtime states with ground truth; backends `jev | haiku | stub`). Blocked on a `TYPESAFE_API_KEY` that is not on this machine (`creds mint typesafe --open`).
- `lab/spike-handoff`, `lab/spike-compact` — `$.turn.abort`, bundle-at-boundary, `$.session.compact()` from a plugin.
