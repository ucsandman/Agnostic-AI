# Decision notes

A decision note records **why** something was decided and **what it beat** —
the parts code, docs, and git history cannot carry. Enforced by
`node ~/.claude/tools/gates/gates.cjs note-format`.

A decision note is not a postmortem. A postmortem is backward-looking: a bug
reached somewhere it should not have, and the interesting part is why the
safety nets missed it. Those stay in [ERRORS.md](ERRORS.md). A decision note is
forward-looking: this is what we chose and what we gave up.

## Where they live

```
docs/decisions/<class>/yyyy-mm-dd-topic-title.md
docs/decisions/archived/<class>/...     frozen, never edited
```

The date is when the topic was first proposed. The class is one of a closed
set; the gate rejects any other folder:

| Class | What it covers |
|---|---|
| `architecture` | A structural decision about what ships — how parts relate, what the vocabulary is |
| `process` | Tooling, policy, or workflow **around** the work — gates, hooks, routing |
| `feature` | A new capability |
| `bug-fix` | Corrects a defect or closes a gap a failure surfaced |
| `simplification` | Removes code, behavior, or surface without adding a capability |
| `testing` | Test and verification strategy |

No index file. The folder tree is the inventory; grep is the search.

## When to write one

Write one when a choice is worth revisiting later: it changes behavior,
changes a contract shared across files, changes process or tooling, or picks
one option over a genuinely tempting other. Purely mechanical edits are exempt.

Updating the note that already owns a decision satisfies the rule. Do not
create a duplicate. A note is never edited into a *different* decision:
supersede it with a new one and cross-link both.

## The format

Line 1, then a `Status:` line, then a blank line:

```markdown
# Decision: <title>

Status: implemented
```

`Status:` is exactly one of `proposed`, `implemented`, or
`rejected — <why, in one line>`. No dates, no parentheticals — the filename
carries the date and git carries the rest.

The body opens with `## Problem`, written so it stands without the solution.
Then:

```markdown
## Problem
## Decision            (proposed notes use ## Proposal)
…bespoke sections…
## Alternatives considered
## Consequences
```

An implemented note describes shipped reality in the present tense. The gate
rejects `## Proposal`, `## Plan`, `## Migration plan`, and
`## Acceptance criteria` in an implemented note — that is proposal-era
spec-speak, and it is the tell that a note was never updated after the work
landed.

## Alternatives considered is mandatory

Every note carries it. One bold-led paragraph per alternative, naming why it
lost.

A decision recorded without what it beat invites re-litigation — which is the
exact failure decision notes exist to prevent. Alternatives are **recorded, not
invented**: if the real alternatives are not reconstructible, say so in one
line rather than writing plausible fiction.

## Archived means frozen

Archive an implemented note when the decision is complete and its rationale is
unlikely to guide future work. Move the file to `docs/decisions/archived/<class>/`
and add an `Archived: YYYY-MM-DD` line under the status. That is the only
permitted content change.

Once archived, a note is **permanently frozen**: never edited, never updated,
and **never treated as authority for current behavior**. Gates skip it. Active
prose may still link into one when it intentionally cites history.

This is the rule that keeps a stale record from being read as a live one.
