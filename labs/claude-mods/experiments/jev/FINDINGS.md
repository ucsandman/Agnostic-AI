# Jev skill suggestion: measured on real transcripts, 2026-09-17

Question: can Jev pick the right skill for a turn, the way TypeSafe's
`skill_suggestion` cookbook reports for Nous Research's 182-skill Hermes roster?

Answer on this machine: **not at 407 skills.** The bottleneck is candidate volume in
the ranking call, and it is measured below, not inferred.

## Data

- `build_roster.py` -> 407 loadable skills. Excludes `plugins/cache` (the versioned
  download cache, one copy per release: counting it gives a fake 495) and test fixtures.
  23 of the 103 skills this session was offered ship inside the binary or as slash
  commands, have no SKILL.md, and can never be suggested by this design.
- `mine_turns.py` -> 230 positives / 126 negatives from 838 transcripts, labeled by
  which skill the agent actually loaded. Drops image-only turns, context-dependent
  replies ("wait, wrong repo"), and explicit `/slash` invocations, all of which are
  unanswerable or leak the answer. 78 of 230 still name their skill in plain text and
  are flagged `names_skill`, so the hard subset (152) is reported separately.
- Ground truth is a past Claude decision, not a human label. A turn where the agent
  chose badly is scored as if that choice were right.

## Results

| backend | wrong_load | needless_load | hard subset | cost | n |
| --- | --- | --- | --- | --- | --- |
| keyword baseline | 96.5% | 83.3% | 98.7% | $0 | 356 |
| jev, two calls | 73.3% | 80.0% | 94.4% | $0.10 | 90 |

Jev beats the free baseline by 23 points, so it is reading the request, not matching
strings. It is nowhere near the cookbook's 7.3%.

## Where the loss is

`_diag.py` splits the failure in two. Call 2 is healthy: when call 1 shortlists the
right skill, call 2 keeps it 16 times out of 19. **Call 1 recall is the ceiling** -
the gold skill reaches the top 3 only 32% of the time.

`_recall_probe.py` isolates the cause. Same model, same question, same 40 hard turns,
only the candidate list changes:

| ranking over | top-1 | top-3 |
| --- | --- | --- |
| all 407 skills | 5% | 8% |
| the 22 skills that are ever correct | 18% | 42% |

Recall is 5x better on the small roster. The model is not failing to understand the
requests; it is being asked to separate the answer from 400 distractors, many of them
near-duplicates (27 duplicate names: three `launch`, two `chrome-devtools`, two
`skill-creator`). One shortlist was `['launch', 'launch', 'preflight']`, two of three
slots spent on the same name.

The 255-option API cap forces 407 into two chunks, and probabilities are only
comparable within a chunk, which costs further precision.

## What this does not say

- Not that Jev is weak. 18% top-1 over 22 plausible candidates on genuinely ambiguous
  turns, from a model that sees the roster and nothing else, is real signal.
- Not that the cookbook is wrong. It measured 182 curated, deduplicated skills.
- Not measured: whether the suggestion changes what the agent loads. Every number here
  is agreement with a past decision, not an improvement over one.

## If this is picked up again

1. Deduplicate the roster by name and drop skills never once loaded in 838 transcripts.
   A roster near 40 is where recall was usable.
2. Two-stage it: cheap category Choice first, then skills within the category, per the
   hierarchical_classification cookbook. Keeps every skill reachable without one
   407-option question.
3. Only then measure against live turns, where the comparison is the agent's choice
   with and without the hint.

---

# Round 2: the lean roster, 2026-09-17

`build_roster_lean.py` ranks skills by how often they were actually loaded across 838
transcripts, dedupes by name, keeps the top N. Built from usage history, never from the
eval labels, so it is honestly constructible at hook-install time.

Turns whose gold skill misses the cut are kept as **orphans** and counted, so a smaller
roster cannot buy its score by discarding the turns it made unanswerable.

| roster | backend | wrong_load | needless_load | orphan noise | cost |
| --- | --- | --- | --- | --- | --- |
| 407 full | keyword | 96.5% | 83.3% | - | $0 |
| 407 full | jev | 73.3% | 80.0% | - | $0.10 |
| 40 lean | keyword | 84.1% | 72.2% | 79.6% | $0 |
| 40 lean | jev | **56.8%** | **27.8%** | 45.9% | $0.06 |

Shrinking the roster helped a lot: wrong loads 73% -> 57%, and needless loads fell by
two thirds. Still far from the cookbook's 7.3%.

## Two things the breakdown shows

**1. One label is a convention, not a topic.** `dispatch-blocks` is 31 of 132
answerable turns, and Jev returns "no skill" on 22 of them. It is right to. The skill
is a briefing format the agent applies to any delegated work, so requests carrying it
("build the pack script", "apply the SEO floor to the other sites") contain no signal
pointing at it. Scoring it as a miss punishes the model for a labeling artifact.
Excluding it: 45.5% wrong.

**2. The split that matters.** Among those 101 turns:

| subset | n | wrong |
| --- | --- | --- |
| request names its skill in plain text | 48 | **4.2%** |
| request does not | 53 | **83.0%** |

Jev is near-perfect at matching a named skill and near-useless at inferring an unnamed
one, on this data. A hook built on it would mostly fire correctly when you already said
the skill's name, which is the case that needed no help.

## Verdict

Not worth shipping as a suggester on this machine. Total spend to establish that: $0.21.

The honest read is that this roster is the wrong shape for the technique, not that the
technique is broken. Only 26 skills were ever loaded in 838 transcripts, three of them
account for 190 loads, and the frequent ones are conventions rather than topics. The
cookbook's 182 skills were curated, deduplicated and topical.

Worth trying if picked up again: a category-level Choice first (hierarchical_
classification), which never asks one question to separate 400 near-duplicates; and
scoring against whether the suggestion IMPROVES the agent's choice, rather than whether
it agrees with a past one.
