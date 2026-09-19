# Decision: Mechanical gates over the harness's own docs and wiring

Status: implemented

## Problem

The harness governs work in other repos but had almost no checks on itself. Its
own rules lived as prose in `CLAUDE.md` and were trusted because nobody had
observed them failing — the exact pattern L1 names. Three specific gaps:

- `CLAUDE.md` cited roughly twenty file paths. Every one resolved on
  2026-08-17, but nothing would have caught a rename. The reference set had
  never been checked, so its greenness carried no information.
- `CLAUDE.md` was 5,369 words and grew with every incident. It loads into every
  session on this machine, so its size is a standing per-turn cost, and nothing
  pushed back on growth.
- A `settings.json` hook pointing at a moved script fails silently. The
  `harness-health` skill checked this, but a skill only runs when a model
  decides to invoke it, which is not a check.

deepseek-ai/deepseek-harness demonstrates the shape that fixes this: many small
`verify-*` scripts, one runner with named aggregates, wired into a pre-commit
hook and CI, plus a word-budget manifest for standing docs.

## Decision

One zero-dependency runner at `tools/gates/gates.cjs` holds every check as a
function in a `CHECKS` table. `node gates.cjs` runs all of them; `gates.cjs
<id>` runs one; `--report` writes and opens a self-contained HTML report;
`--staged` narrows the doc checks to staged files so the pre-commit path stays
fast.

Seven checks ship:

- `doc-budgets` — word ceilings from `budgets.json`. A missing budgeted file fails.
- `md-links` — every backticked path and markdown link in a standing doc resolves.
- `ref-ratchet` — a path the docs once pointed at is referenced nowhere any more.
- `note-format` — decision notes follow the format, including mandatory alternatives.
- `rule-expiry` — `<!-- expires: YYYY-MM-DD -->` markers that are past due.
- `skill-metadata` — every `SKILL.md` has frontmatter, a name matching its directory, and a description.
- `hook-wiring` — every absolute path in a `settings.json` hook exists; unreferenced hook scripts are reported.
- `slop` — the doc slop checklist, advisory.

Advisory checks report and do not block. `--strict` promotes them. The global
pre-commit hook runs the doc checks when a tracked `.md` file is staged inside
the harness repo, and skips entirely everywhere else.

Each check was proved with `tools/prove` — broken on purpose, watched go red,
restored — before being trusted.

## Alternatives considered

**A file per check, as in the source harness.** Rejected. Seven checks at ~40
lines each is one coherent 500-line file. Their split earns its keep at 150+
gates across a monorepo; here it would be six extra files and an import graph
to maintain for no gain.

**`knip` for dead JS and `jscpd` for clone detection**, both named in the
original recommendation. Rejected: `~/.claude` has no `node_modules` and every
tool in it is zero-dependency by convention. Adding a package manager to the
harness to find dead code in twenty hook scripts is worse than the problem.
`hook-wiring`'s orphan report covers the failure that actually happens here — a
guard nothing invokes.

**Extend the `harness-health` skill instead.** Rejected: a skill runs when a
model chooses to invoke it. That is a suggestion, not a gate. The skill keeps
its diagnostic role; the mechanical subset became an executed check.

**Block on slop findings.** Rejected for now. The patterns are regexes over
English prose and will produce false positives; a doc smell blocking a commit
teaches people to pass `--no-verify`, which costs the secret scan too. Advisory
by default, `--strict` when auditing.

**Set `CLAUDE.md`'s ceiling at the 1,900-word figure the source repo uses.**
Rejected: a ceiling below what the content needs is a budget bug, and hitting
it would mean deleting rules. The ceiling was set after a relocation pass that
moved stories out and kept every rule.

### The gap `md-links` could not close

The first relocation pass under these gates dropped the
`~/clawd/agent-comms/TEAM_PROTOCOL.md` pointer out of `CLAUDE.md`, and all seven
gates stayed green. `md-links` checks that the references present resolve; a
reference that stopped being present is invisible to it. `ref-ratchet` closes
that: `references.json` records the referenced set, and the gate fails when a
recorded path is referenced nowhere.

Global set, not per-doc — moving a pointer into a linked file is the intended
index pattern, not a loss. Both directions were proved: dropped everywhere goes
red, moved between docs stays green.

A ceiling is an anti-growth ratchet with **no goal word count**. An earlier
draft of this decision carried a 3,500-word target for `CLAUDE.md`, scaled from
the source repo's 1,900. That number described a different document with a
different job and was never derived for this one. Removed.

## Consequences

- A dead reference, an oversized standing doc, a malformed decision note, an
  expired rule, a broken skill description, and a dangling hook target now all
  fail at commit time instead of at the moment someone needs them.
- The pre-commit path grew by one node process, on `.md` commits inside this
  repo only.
- `budgets.json` is now a file that must be updated when a standing doc is
  renamed. That is deliberate: the alternative is a budget that silently stops
  applying.
- The orphan report has known benign entries (`lsp-reaper.ps1` runs from Task
  Scheduler). It is advisory precisely because that class of caller exists
  outside anything the gate can read.
