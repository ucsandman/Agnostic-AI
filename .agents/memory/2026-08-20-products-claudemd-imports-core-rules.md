# 2026-08-20 — External binding: Practical Systems builds import core/rules by absolute path

FYI for sessions working in agnostic-ai (from the company-loop session; scope
claim: I touched NO agnostic-ai files, only `Practical Systems/products/`):

The claude target in `core/templates/targets.json` now writes
`~/.claude/agnostic-rules.md` (was `~/.claude/CLAUDE.md`, which
agents-memory-sync owns — the two syncs were fighting over one file). The
agents-memory source template (`~/.agents/AGENTS.md`, linked to
`~/.claude/CLAUDE.md`) imports it with an @ line, and
`C:/Projects/Practical Systems/products/CLAUDE.md` imports the same path as a
belt for headless company-loop builds. So every session — default and
headless — loads the compiled agnostic working agreement + distilled lessons.
`npm run sync:check` is clean (18/18), `docs/targets.md` regenerated,
`npm test` green, verified 2026-08-20 with headless probes from a product dir
and a neutral dir.

Constraint for this repo: renaming the claude target's rulesFile again means
updating the import lines in `~/.agents/AGENTS.md` and
`Practical Systems/products/CLAUDE.md` — CLAUDE.md imports fail silently.
