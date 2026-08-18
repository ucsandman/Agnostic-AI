---
name: six-hats
description: Parallel thinking with six enforced perspectives, based on Edward de Bono's Six Thinking Hats® method - examine one decision through sequential passes for facts, feelings, risks, benefits, alternatives, and synthesis, never blending them. Use when a decision is being made too fast or from one angle, when everyone agrees suspiciously quickly, when the discussion mixes emotions with data, or for "six hats", "thinking hats", "look at this from every angle", "structured devil's advocate". Do NOT use for analytical work like debugging, code review, or implementation tasks.
---

# Six Thinking Hats

## What this technique does

Take one decision and run it through six deliberately separated perspectives, one at a time. Each pass wears a single "hat": facts, feelings, risks, benefits, alternatives, then synthesis. The power is in the separation — a group that argues all six dimensions at once collapses into whoever talks loudest, but a group that examines facts *only*, then feelings *only*, surfaces things the argument would have buried. It converts a tug-of-war into six clean passes over the same ground.

Based on Edward de Bono's Six Thinking Hats® method (*Six Thinking Hats*, 1985). Six Thinking Hats is a registered trademark of the de Bono Group; this skill is an independent educational implementation.

## Workflow

### Step 1: Confirm the target

A valid target is a *decision* — something with an option to accept, reject, or modify. "Should we ship X in v1?", "Do we adopt this dependency?", "Which of these two rollout plans?" all qualify. If the request is open-ended ideation with no decision to weigh ("what could we build next?"), this is the wrong technique — point the user to a generative technique such as [`../random-stimulus/SKILL.md`](../random-stimulus/SKILL.md) instead. If the target is unclear, ask one focused question: "What's the specific decision, and what are the options on the table?"

Refuse requests to *perform* analytical work — "debug this", "review this code", "implement this change" — and suggest an analytical approach instead. Redesigning or ideating about such a process is a valid target: "reinvent our code-review ritual" is in scope; "review this PR" is not.

### Step 2: Run the six passes in fixed order

Run all six, each under its own clear heading, never blending. If material for one hat surfaces while wearing another, park it and raise it when its hat comes up.

- **White — facts only.** State only what is verifiable. Name the missing data explicitly rather than guessing at it. No opinions, no interpretation.
- **Red — gut reactions.** One line each, no justification permitted. The instant "this feels wrong" or "I'd be relieved" — recorded, not defended. Justifying a feeling turns it into a Black or Yellow point; don't.
- **Black — risks and failure modes.** Each risk tied to a *mechanism* — how it actually goes wrong — not a vibe. "This could fail" is not a Black-hat point; "this fails if traffic doubles because the queue is unbounded" is.
- **Yellow — benefits and best-case.** Each benefit tied to a mechanism too. Not "this would be great" but "this cuts onboarding time because the config step disappears."
- **Green — alternatives and modifications.** Minimum three. At least one must abandon the premise of the decision entirely rather than tweak it.
- **Blue — synthesis.** What did the hats disagree about? What piece of information would change the answer? End with a recommendation carrying a *stated confidence level*.

### Step 3: Offer next moves

Offer, don't push: re-run a single hat deeper, take one of the Green alternatives through all six hats, switch to another technique, or stop here. Never pressure the user to commit to the recommendation.

## Honesty mechanics

**The Red hat must bite.** It must contain at least one feeling that *contradicts* the emerging conclusion — the discomfort with a decision that otherwise looks clean, or the reluctance to reject something that fails on paper. If no such feeling genuinely surfaced, say so explicitly rather than manufacturing one: `Red hat is suspiciously aligned — flagging possible motivated reasoning.` A Red hat where every feeling agrees with the answer is a tell.

**The Blue hat must not paper over the split.** Name the strongest unresolved tension in plain terms — the one thing that, if it broke the other way, flips the recommendation. Synthesis is not the same as consensus; a real disagreement between the hats is more useful reported than smoothed.

## What NOT to do

- **Don't blend the hats.** A risk that occurs to you during Yellow gets deferred to Black, explicitly ("noting a risk here — holding it for Black"). Mixing dimensions is the exact failure the technique exists to prevent.
- **Don't let Blue introduce new material.** Blue synthesizes what the other five hats produced. A fresh fact or risk appearing for the first time in Blue means an earlier hat was run lazily — go back.
- **Don't run this on a problem with no decision in it.** No option to accept or reject means no target. Redirect to a generative technique.
- **Don't skip Red because "feelings aren't data."** Surfacing the feelings *is* the hat's job. Unspoken reluctance sinks more decisions than any spreadsheet; the Red hat drags it into the open where it can be examined.

## References

- [`references/hats-guide.md`](references/hats-guide.md) — what belongs in each hat, what is banned, examples, and the leakage patterns between neighbouring hats
- [`references/worked-example.md`](references/worked-example.md) — a real run of all six hats on one decision, disagreement and confidence level included
