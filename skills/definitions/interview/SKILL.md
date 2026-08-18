---
name: interview
description: Use before implementing any non-trivial feature or change — when the user invokes /interview, when a spec has multiple plausible interpretations, when a request is vague ("make it better", "add auth"), or before committing to an architecture. Not for trivial mechanical edits.
---

# Interview

Surface the decisions hiding in a request before writing code. Ask questions ordered by architectural blast radius, capture the answers in a decisions table, and end with an implementation prompt that encodes them.

## Steps

1. **Read the territory first.** Explore the relevant code before asking anything. A question answerable from the codebase is wasted user time — only ask what the code cannot tell you.
2. **Ask in blast-radius order.** Batch questions with AskUserQuestion, highest blast radius first:
   1. Data model / schema / persisted state (wrong = migration pain)
   2. External contracts: APIs, events, integration boundaries (wrong = breaks consumers)
   3. Behavior and edge cases: auth, errors, concurrency, empty states
   4. UX and workflow shape
   5. Cosmetics — usually skip; cheap to change later
3. **Every question carries a recommended default** with a one-line reason, listed first and marked "(Recommended)", so the user can accept-all in seconds. State what happens if the default is wrong.
4. **Stop when remaining unknowns are cheap.** Max two rounds. If a question's wrong answer costs less than an hour to reverse later, don't ask it — decide and note it.
5. **Emit the decisions table.** Columns: Decision | Choice | Why | Cost if wrong. Include the defaults you decided unilaterally, marked as such.
   - **If the table has 3+ rows at the data-model or external-contract tier, or the work will span sessions or agents:** also render it as an HTML artifact (Artifact tool; load the `artifact-design` skill first) — table plus the implementation prompt in a copyable block. Artifacts survive compaction and handoffs; the inline table is gone after the next `/clear`.
   - Otherwise the inline markdown table is enough — don't ceremony up a two-decision change.
6. **Emit the implementation prompt.** One contiguous block restating the task with every decision baked in, ready to execute in this session or paste into another. No open questions inside it.

## Common mistakes

- Asking cosmetics first because they're easy to phrase — order by blast radius, not by ease.
- Asking things `Grep` could answer — read before you interview.
- Questions with no recommended default — forces the user to do your thinking.
- Endless interviewing — two rounds max, then decide and disclose.
- Skipping the decisions table and jumping to code — the table is the artifact; the answers otherwise evaporate at compaction.
