---
name: adversarial-review
description: Multi-agent adversarial code review — parallel read-only finders across focused dimensions, then every finding is independently verified by a skeptic that defaults to REFUTED. Use when the user asks for an adversarial review, a deep/thorough review of recent changes, "did the agents break anything", or a pre-merge audit of a large diff. Pass an optional scope as args (base ref, PR number, or paths); default scope is all uncommitted changes. Pass --fix to apply confirmed fixes after the report.
---

# Adversarial Review

Review a change-set with a two-stage multi-agent pipeline: **find** (parallel
read-only reviewers, each owning one failure dimension) then **verify** (an
independent skeptic per finding, prompted to refute it). Only findings that
survive verification are reported. This kills the two classic failure modes of
LLM review: plausible-but-wrong findings, and one reviewer trying to hold every
concern at once.

This skill authorizes use of the Workflow tool for the orchestration.

## 1. Establish scope (cheap, inline)

- Default: the working tree — `git diff HEAD --stat` plus `git status --short`
  for untracked files. If the tree is clean, use commits ahead of the default
  branch (`git log origin/main..HEAD`); if none, the last commit.
- If args name a base ref, PR number (`gh pr diff <n> --stat`), or paths, scope
  to that instead.
- Build a SCOPE block: repo path, the changed-file list grouped by
  feature/area if discernible (read the recent commit messages), and one line
  of context per group ("X was just implemented by engineer A who did not know
  about Y"). If several independent changes landed in sequence, SAY SO in the
  scope — it unlocks the seams dimension.
- Note anything reviewers must NOT do (modify files, run test suites that
  would race a separate verification run).

## 2. Pick dimensions

Default four; drop or add based on what the diff actually contains:

| Dimension | Hunts for |
|---|---|
| correctness | real bugs: off-by-one, wrong clamps, unsorted-input assumptions, binary-search edges, stale caches, async races, undo/transaction leaks (begin without end on throw) |
| seams | CROSS-CHANGE integration bugs — each change was made by someone who didn't know the later ones existed; name concrete interaction pairs to check (the highest-yield dimension on multi-feature diffs) |
| silent-failures | swallowed errors: empty catch, no `response.ok` check, fire-and-forget `void` promises, schema `.optional()` hiding malformed data, handlers reporting success on failure, UI showing stale state when an async step fails |
| test-gaps | the 3–5 most dangerous untested behaviors only (persistence round-trips, undo of multi-step ops, boundary math, timestamp math at hour boundaries) — not blanket coverage demands |

Useful extras when relevant: `security` (injection, path traversal, secrets,
authz), `perf` (hot-path regressions, N+1, unbounded growth), `concurrency`.

## 3. Run the workflow

Use the Workflow tool with this shape (adapt SCOPE/DIMENSIONS; keep the
verification contract verbatim):

```js
export const meta = {
  name: 'adversarial-review',
  description: 'Adversarial review of the current change-set',
  phases: [
    { title: 'Find', detail: 'read-only finders per dimension' },
    { title: 'Verify', detail: 'adversarial verification of each finding' },
  ],
}

const SCOPE = `<repo, change-set description, per-area context, READ ONLY:
do not modify files or run builds/tests. Cite file:line for every claim.>`

const FINDINGS = {
  type: 'object', required: ['findings'],
  properties: { findings: { type: 'array', items: {
    type: 'object', required: ['title', 'file', 'severity', 'detail'],
    properties: {
      title: { type: 'string' },
      file: { type: 'string', description: 'file:line' },
      severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
      detail: { type: 'string', description: 'what is wrong, the concrete failure scenario, and the suggested fix' },
    } } } },
}

const DIMENSIONS = [ /* { key, prompt } per chosen dimension */ ]

phase('Find')
const found = await pipeline(
  DIMENSIONS,
  (d) => agent(
    `${SCOPE}\nYour dimension: ${d.prompt}\nReport at most 8 findings; only report things you are confident are real after reading the actual code (not the diff alone — open the files). No style nits.`,
    { label: `find:${d.key}`, phase: 'Find', schema: FINDINGS }),
  (result, d) => parallel((result?.findings ?? []).map((f) => () =>
    agent(
      `${SCOPE}\nAdversarially verify this finding from a ${d.key} reviewer. Read the cited code and trace the actual behavior. Default to refuted unless the failure scenario is concretely reachable. Finding:\n${JSON.stringify(f, null, 1)}`,
      { label: `verify:${f.title.slice(0, 30)}`, phase: 'Verify', schema: {
        type: 'object', required: ['real', 'reason'],
        properties: { real: { type: 'boolean' }, reason: { type: 'string' }, fixHint: { type: 'string' } },
      } }).then((v) => ({ ...f, dimension: d.key, verdict: v }))
  ))
)
const flat = found.filter(Boolean).flat().filter(Boolean)
const confirmed = flat.filter((f) => f.verdict?.real)
log(`${confirmed.length} confirmed, ${flat.length - confirmed.length} refuted`)
return {
  confirmed,
  refutedTitles: flat.filter((f) => f.verdict && !f.verdict.real).map((f) => f.title),
}
```

Why each piece matters — keep these properties when adapting:

- **Finders are read-only and capped** ("at most 8, no style nits") — volume
  is the enemy; verification costs one agent per finding.
- **Verifiers see the finding but not the finder's reasoning chain**, read the
  cited code fresh, and **default to refuted**. A finding must describe a
  concretely reachable failure to survive. This is the false-positive filter.
- **pipeline(), not a barrier** — each dimension's findings verify while other
  dimensions are still searching.
- For very high stakes, use 3 verifiers per finding with distinct lenses
  (reachability / severity / does-the-fix-direction-hold) and majority vote.

If the Workflow tool is unavailable, degrade gracefully: run the finders as
parallel Agent (subagent) calls in one message, then a verification subagent
per finding, same prompts.

## 4. Report and act

- Report ONLY confirmed findings: severity, file:line, the reachable failure
  scenario in one or two sentences, and the fix direction. List refuted titles
  in one line (it shows the filter worked).
- Spot-check any confirmed `critical` yourself by reading the cited code
  before fixing — verifiers are good, not infallible.
- If some verifications failed to run (limits, errors), say so explicitly and
  vet those findings yourself by reading the code — never silently drop an
  unverified critical.
- With `--fix` (or when the user asks): fix confirmed findings in
  severity order, each with a regression test where the failure scenario is
  testable, then re-run the project's tests/lint/build and report.
