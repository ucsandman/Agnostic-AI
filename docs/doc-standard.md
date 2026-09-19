---
name: doc-standard
description: "How prose in this harness is placed, sized and kept honest: tiers, word budgets, checkable links, the slop list, expiring rules"
context:
  triggers:
    keywords: ["doc standard", "word budget", "doc-budgets", "md-links", "slop", "where does this doc go", "which doc", "write the docs"]
    paths: ["~/.claude/docs/**"]
  priority: 60
---
# Documentation standard

How prose in this harness is placed, sized, and kept honest. Enforced by
`node ~/.claude/tools/gates/gates.cjs` — the `doc-budgets`, `md-links`, and
`slop` checks.

## One home per fact

Each fact lives in exactly one tier. Everywhere else links to it.

| Tier | Job | Does NOT belong there |
|---|---|---|
| `CLAUDE.md` | Standing orders: rules needed in context in **every** session, one to three lines each, linking their home | Stories, incidents, worked examples, situational procedures, anything restated from a linked doc |
| `SOUL.md` | Identity and voice | Operating rules |
| `docs/*.md` | One reference doc per subject: the full contract, the procedure, the ladder | Repeated standing orders, change history |
| `docs/decisions/` | Why a decision was made and what it beat — see [decision-notes.md](decision-notes.md) | Current-state reference (→ `docs/`), incident stories (→ ERRORS.md) |
| `docs/ERRORS.md` | Failure log: what broke, root cause, prevention, newest first | Decisions, rationale, reference material |
| `meditations/` | Reflection entries and the promotion ladder | Anything another tier owns |
| Memory files | Facts about **this machine and this user** that the repo cannot carry | Anything derivable from code or git history |
| Skills | Reusable workflows | Product and runtime contracts |

Placement in one line: bugs → ERRORS.md; rationale → a decision note;
procedures → `docs/`; standing orders → `CLAUDE.md` with a link.

## Word budgets

[tools/gates/budgets.json](../tools/gates/budgets.json) sets a ceiling per
standing doc. `CLAUDE.md` loads into every session on this machine, so its
ceiling is the one that costs real tokens per turn.

**There is no goal word count.** A ceiling is an anti-growth ratchet: it exists
so a doc cannot grow without someone noticing. When the gate goes red:

1. **Move a section into its own file** and leave an index line behind — the
   rule and its pointer stay in the standing doc, the detail drills down.
2. **Condense** wording that can be shorter without losing a fact.
3. **Raise** the ceiling, with the reason in the commit. This is a legitimate
   outcome, not a failure. A too-low ceiling is a budget bug.

Never delete a rule, and never drop a pointer, to meet a number.

**Relocation loses things quietly.** `md-links` proves the pointers that exist
still resolve; nothing proves a pointer that used to exist still does. After
moving anything out of a standing doc, list the distinctive phrases and paths
you removed and grep for each one before claiming nothing was lost. This is how
the `TEAM_PROTOCOL.md` pointer went missing on 2026-08-17.

## Cross-reference with checkable links

Reference another file by a path in backticks or a markdown link, never by bare
prose. `md-links` resolves every one and fails on a dead target. A rename that
breaks a reference is caught at commit time instead of at the moment an agent
needs the doc.

Not checked, on purpose: globs (`C:\Projects\*\...`), paths with `${}` or
`$env:`, and bare unbackticked paths in prose — too many false positives from
example commands.

## The slop checklist

Hunt these in any doc. The `slop` gate finds the mechanical ones and is
advisory by default — a false positive must never block a commit. Run
`gates.cjs slop --strict` to enforce.

- **The same rule in two homes.** Grep a distinctive phrase. Keep one, link the rest.
- **Narrated history**: "previously", "used to live", "no longer", "was moved". State the current fact. The story goes in a decision note or ERRORS.md.
- **Status annotations**: "coming soon", "not yet implemented", "future:". Status rots in prose; the repo layout carries it.
- **Hand-restated inventories** of files, hooks, or skills when the directory itself is authoritative.
- **Reasoning transcripts**: step-by-step narration of how a thing was derived. Keep the resulting rule; delete the path to it.
- **Paragraph walls**: one paragraph carrying several rules plus asides. Split it, or demote the detail to its home.
- **Emphasis inflation**: bold, CAPS, and "critically" everywhere means nothing stands out. Reserve emphasis for the clause that changes behavior.
- **Spec-speak in a shipped record**: "we should", "the plan is to", migration plans. A shipped decision says what is.

## Rules that expire

A rule that is only true for a while carries its own expiry marker:

```markdown
<!-- expires: 2026-12-01 — re-check once the Fable routing settles -->
```

Past the date `rule-expiry` goes red. Without this, a situational rule quietly
becomes a permanent one and nobody remembers why it is there.
