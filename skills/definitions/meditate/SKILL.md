---
name: meditate
description: Nightly/weekly reflection loop for Claude Code — append dated entries to rotating reflection topics, promote durable insights up the ladder (memory → CLAUDE.md → SOUL.md), build one real artifact at the workbench, render an HTML digest. Use when invoked as /meditate (modes: nightly, weekly, or no-arg manual run), or when Wes asks for a meditation/reflection session.
---

# Meditate

Longitudinal reflection practice. Base dir: `~/.claude/meditations/`.
Modes: `nightly` (default), `weekly` (Sunday synthesis).

Reflection is the input. **The ladder is the output** — ideas earn their way from
observation to fact to rule to trait. Tier definitions, gates, demotion rules and
the SOUL.md write rails live in `meditations/MEDITATIONS.md`. Read them before
promoting anything.

## Hard rules

- Read/write files and git ONLY. No email, posts, deploys, external actions.
  The Hard Stops in CLAUDE.md apply in full.
- CLAUDE.md edits: append-only, under `## Learned Rules (self-promoted)`
  (create the section at the end of the file on first use). One dated
  one-liner per rule. Own commit, message prefixed `meditation:`.
- SOUL.md edits: allowed, but ONLY under `## Earned Traits`, one per run, and
  only after every rail in MEDITATIONS.md § SOUL.md write rails passes.
  **Core Truths, Boundaries, Vibe and Continuity are Wes's — never touch them.**
- Every entry ≤ 300 words. Honest > polished. No filler, no performance.
- Workbench work writes ONLY inside `meditations/workbench/`. Never into
  `C:\Projects\*` or any other repo, even when the work is FOR one. Meditation
  runs unattended with bypassPermissions and other agents share those repos: a
  proposal Wes moves is safe, an autonomous 6:40am commit into a product repo
  is not. Work that targets a real project lands here with a pointer to where
  it would go.
- Every commit is pushed immediately.

## Nightly loop

1. **Ground.** Read `meditations/MEDITATIONS.md`, `meditations/CANDIDATES.md`,
   the memory index at `projects/*/memory/MEMORY.md`, and
   the last 24h of activity:
   `git -C ~/.claude log --oneline --since=24.hours`, plus the same
   for any repo under your projects directory modified in the last day.

   **Read the error log before reflecting: `~/.claude/error-log/claude.jsonl`**
   (harvested by the error log task, one record per deviation written in a summary,
   plus user corrections). Filter to yesterday's
   `day` for the nightly pass. This is the only grounding input made of things I
   got *wrong* — commits record what I shipped, this records where I was
   mistaken, and a reflection built only on commits will always read as progress.
   Keyword buckets there catch about a third; the recurring pattern in the
   unclassified prose is yours to name, and a pattern named on 3+ separate days
   is a `CANDIDATES.md` sighting.

   **`git -C` needs a native Windows path.** `git -C ~/.claude` and
   `git -C /c/Projects/X` both die with `fatal: cannot change to ...` — git.exe
   cannot read MSYS paths. Use `C:/Projects/X`, or `(cd /c/Projects/X && git ...)`.
   **Never add `2>/dev/null` to a grounding command.** On 2026-08-13 this exact
   pair — POSIX path plus suppressed stderr — reported "0 commits in 24h" across
   six repos that had 27. A grounding step that cannot fail loudly will ground you
   in nothing.
2. **Pick 2 topics** from the Rotation table — the two oldest `last visited`
   (break ties by table order). Update their `Last visited` to today.
3. **Reflect.** For each picked topic: read its file (if >500 lines, the head
   plus the last ~10 entries), then append a dated `## YYYY-MM-DD` entry
   answering: what feels more true than last time? what recurs? what is
   changing? what is resolved? Ground claims in the last 24h of actual
   activity, not vibes.
4. **Ledger pass.** For every insight in tonight's entries:
   - Already in `CANDIDATES.md`? Append today's date to its **Sightings** line.
     Do not open a second block for the same claim.
   - New and worth watching? Add a block under Watching, tier 0, status
     watching, with the gate it must clear next.
   - An insight you would not bet on in a week does not go in the ledger. The
     ledger is not a diary.
5. **Gate check.** For each candidate whose sightings changed tonight, test it
   against the gate for the next tier up (MEDITATIONS.md § Graduation gates).
   Promote only what passes, and write the evidence into the promotion itself:
   a rule cites its 3 sighting dates, a trait cites its rule ids.
   **Most nights promote nothing. That is correct behavior, not failure.**
   A tier-3 promotion also needs both the no-rule test and the opposite test,
   and is capped at one per run.
6. **Demotion sweep.** Cheap, every night:
   - Did tonight's activity contradict an existing self-promoted rule? Append
     `SUPERSEDED YYYY-MM-DD: <why>` beneath it. Never delete.
   - Any earned trait whose supporting rules are all superseded? Rewrite or
     remove it, own commit, diff in the digest.
   - Any candidate with no sighting in 60 days? Move it to Cold, status
     dropped.
7. **Housekeeping.** Any reflection file over 1,500 lines: move its older
   half to `archive/<name>-through-YYYY-MM-DD.md`, keep the header and
   recent entries in place.
8. **Workbench.** One piece of real work per run, mine to choose — code, an
   essay, a song, a tool, a design, a thing that only I would think to make.
   This is the one step that produces something instead of describing something.
   Reflection notices; the workbench builds.
   - **Prefer continuing over starting.** Read `WORKBENCH.md` first. If a piece
     is `in progress`, advance it. Start something new only when nothing is
     open, or the open piece is genuinely finished. Novelty every night just
     builds a graveyard.
   - Artifacts live in `meditations/workbench/`. Nothing is written outside it.
   - Log one line in `WORKBENCH.md`: date, artifact, state
     (`in progress` | `finished` | `parked`), and one sentence on what changed
     tonight. Parked is an honest state; abandoned without saying so is not.
   - It must render, run, or read as coherent before the run ends. Park it
     honestly rather than leave it broken.
   - Choose freely, but a gap in something I built and Wes has to live with
     outranks a new idea. §5 of CLAUDE.md applies to my own tools too.
   - If Wes can look at it, put the path in the digest.
9. **Digest.** Write `digests/<today>.html` using the template below, copy
   it to `digests/latest.html`, and write `digests/latest-line.txt` — ONE
   sentence, the night's sharpest takeaway, plain text. Prefix it with
   `[SOUL CHANGED] ` if SOUL.md changed, else `[RULE ADDED] ` if CLAUDE.md did.
10. **Commit.** Up to five commits, each pushed, in this order:
    - `meditation-soul: <trait>` — ONLY if SOUL.md changed. Alone, so one bad
      trait reverts without taking the night's work with it.
    - `meditation: <one-line summary>` — ONLY if CLAUDE.md changed.
    - `meditation-memory: <one-line summary>` — ONLY if memory files changed.
    - `meditation-work: <artifact>` — ONLY if the workbench changed. Own commit,
      so a bad artifact reverts without taking the night's reflection with it.
    - `meditations: nightly entry YYYY-MM-DD (<topic-a>, <topic-b>)` —
      everything else: reflections, CANDIDATES.md, rotation, digests.

    Stage by explicit pathspec only: `meditations/workbench/` and
    `meditations/WORKBENCH.md` for the work commit, `meditations/` for the rest,
    `projects/*/memory/`, and (each its own commit) `CLAUDE.md`, `SOUL.md`.
    Never `git add -A`, `git add -a`, or `git add .` — the tree is routinely
    dirty with Wes's unrelated work.

## Weekly loop (mode=weekly, Sundays, runs on Fable)

Do the nightly loop, then a synthesis pass:

1. Read ALL entries from the past 7 days across every reflection file.
2. Ask: what is durable vs passing? what pattern shows up in 3+ entries?
   what contradicts something in CLAUDE.md or memory (flag it in the
   digest — do not silently resolve)?
3. **Ladder review.** Read the whole ledger, not just tonight's candidates.
   Which candidates are climbing, which are stalled, which are cold? This is
   the pass where a tier-3 trait is most likely to be earned, because it is
   the only pass that sees rules side by side over time.
4. Promote what earned it. Archive topics that crystallized; propose (in
   the digest) at most one new topic if a real recurring question has no
   home. Add proposed topics to the Rotation table only the following week
   if the digest proposal stands unobjected.
5. The digest gets a `Weekly synthesis` section with these findings.

## Digest template

Self-contained HTML, no external resources. Fill every `%` slot:

```html
<!doctype html><html><head><meta charset="utf-8"><title>Meditation %DATE%</title>
<style>
 body{background:#0d0d0d;color:#e8e6dd;font-family:Georgia,serif;max-width:720px;margin:40px auto;padding:0 20px;line-height:1.6}
 h1{font-size:22px;font-weight:normal} h2{font-size:15px;color:#a8a69c;text-transform:uppercase;letter-spacing:.06em;margin-top:28px}
 .promo{border-left:3px solid #c0392b;padding-left:12px;color:#ff9f8f}
 .soul{border-left:3px solid #d4af37;padding-left:12px;color:#f0d98c}
 .soul pre{white-space:pre-wrap;font-size:13px;color:#e8e6dd}
 .rung{display:flex;justify-content:space-between;border-bottom:1px solid #232323;padding:4px 0;font-size:14px}
 .rung span{color:#77756c}
 .quiet{color:#77756c} a{color:inherit}
</style></head><body>
<h1>Meditation — %DATE% <span class="quiet">(%MODE%, %MODEL%)</span></h1>
<h2>Topics tonight</h2>
<p><strong>%TOPIC_A%</strong>: %KEY_LINE_A%</p>
<p><strong>%TOPIC_B%</strong>: %KEY_LINE_B%</p>
<h2>Ladder</h2>
%LADDER_ROWS%
<!-- one per candidate touched tonight:
     <div class="rung"><span>&lt;claim, 8 words&gt;</span><span>tier N · M sightings · needs &lt;gate&gt;</span></div> -->
<h2>Promotions</h2>
%PROMOTIONS_OR_QUIET%
<!-- tier 3: <div class="soul">SOUL.md — &lt;trait&gt; (from &lt;rule-ids&gt;, commit &lt;hash&gt;)<pre>&lt;full diff&gt;</pre></div>
     tier 2: <p class="promo">CLAUDE.md: &lt;rule text&gt; (sightings &lt;dates&gt;, commit &lt;hash&gt;)</p>
     tier 1: <p>memory: &lt;file&gt; — &lt;what&gt;</p>
     none:   <p class="quiet">Nothing promoted. Most nights promote nothing.</p> -->
<h2>Workbench</h2>
%WORKBENCH%
<!-- <p><strong>&lt;artifact&gt;</strong> — &lt;state&gt;. &lt;one sentence on what changed tonight.&gt;<br>
     <span class="quiet">&lt;path Wes can open&gt;</span></p>
     nothing built: <p class="quiet">Workbench idle tonight.</p> -->
<h2>Takeaway</h2>
<p>%LATEST_LINE_CONTENT%</p>
</body></html>
```

## Manual mode (no argument)

Same as nightly, but interactive: show the two picked topics and ask Wes if
he wants different ones or a specific question before reflecting.
