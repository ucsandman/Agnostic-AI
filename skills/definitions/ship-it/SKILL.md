---
name: ship-it
description: Ship a product end to end — render marketing assets with the animations studio, then run the launch-engine flow with videos attached to X and LinkedIn posts. Run from the product's repo.
---

# /ship-it — develop → public, one command

Run from the product repo you want to ship. Engines: the animations studio at
`C:\Projects\animations` (rendering) and launch-engine at `C:\Projects\launch-engine`
(distribution). Repos stay separate; this skill is the pipeline.

## Steps

1. **Find the brand + kit.** Brand id = the product's brand in `C:\Projects\animations\brands\<id>.json`
   (ask the user if ambiguous). Kit = `C:\Projects\animations\out\<brand>\postkit\manifest.json`.
2. **Render if needed.** If the manifest is missing, run `/marketing` first (full pipeline, its own
   approval gates). If it exists, show its `generatedAt` and ask: reuse or re-render? Staleness is
   the user's judgment call, never a heuristic.
3. **Launch flow.** In the product repo, run the launch-engine sequence — `launch init` (if no
   `.launch/launch.config.json`), then research, copy scaffold/fill, validate. Wire the kit:
   either set `postkitDir` in the config (the dashboard marketing tab does this with a picker) or
   pass `--kit C:\Projects\animations\out\<brand>\postkit` to `launch post`.
4. **Dry-run, then post.** `launch post <dir> --all --dry-run` and show the user the previews —
   X and LinkedIn must show the video upload step. Live posting only after the user confirms,
   through the normal gates (ledger, validation, typed confirmation in the dashboard).
5. **Manual platforms.** TikTok / Shorts / YouTube / Instagram are manual by design. Point the
   user at the dashboard marketing tab (Open folder per platform) or the kit's `POST.md` checklists.

## Rules

- Never skip the dry-run step. Never post live without explicit user confirmation.
- If the kit manifest promises a video whose file is missing, posting refuses — fix by re-running
  `render-matrix.mjs` + `build-postkit.mjs` in the animations repo, not by unwiring the kit silently.
- Drafts own the copy; the kit contributes media. Do not paste kit captions over validated drafts.
