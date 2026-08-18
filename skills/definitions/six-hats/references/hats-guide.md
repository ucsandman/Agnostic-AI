# The Six Hats: What Belongs, What Is Banned, Where They Leak

One hat per pass. The discipline is not in filling each hat — it is in keeping out the material that belongs to a different one. Each section below lists what belongs, what is banned, three example lines (software-flavored), and the leakage patterns that pull this hat toward its neighbours.

---

## White — Facts

**Belongs here:** verifiable statements, measured numbers, quotes from the spec or the data. And, just as importantly, the *named absence* of data — "we do not know the current p99 latency" is a first-class White-hat entry.

**Banned:** interpretation, opinion, prediction, "obviously". If a sentence could be argued with by a reasonable person looking at the same evidence, it is not White.

Examples:
- "The service handles 4,200 requests per second at peak, per last month's dashboard."
- "The library has had three CVEs in the past year; two are patched, one is open."
- "We do not have data on how many users reach the second onboarding screen. Missing."

**Leakage into Black/Yellow:** "the latency is *too high*" smuggles a judgement into a fact. The fact is the number; "too high" is a Black-hat point. State the number here, judge it later.

**Leakage into Red:** "the data looks worrying" is a feeling wearing a lab coat. Record the datum here; save the worry for Red.

---

## Red — Feelings

**Belongs here:** immediate gut reactions, intuitions, hunches. One line each. Excitement, dread, relief, suspicion, boredom. No reasons attached.

**Banned:** justification. The moment a feeling acquires a "because", it has become a Black or Yellow point and left the Red hat. "I don't trust this" is Red; "I don't trust this because the vendor is small" is Black.

Examples:
- "This feels like scope creep dressed as a quick win."
- "I'd be quietly relieved if we said no."
- "Something about the timing bothers me — can't name it."

**Leakage into Black/Yellow:** adding "because" is the universal tell. Strip the reason; if a real risk hides inside the feeling, it will resurface when Black comes around.

**Leakage into White:** "I feel the numbers are solid" is not a fact and not really a feeling either — it is a smuggled endorsement. Keep Red pre-verbal and honest.

---

## Black — Risks

**Belongs here:** failure modes, downsides, what breaks and *how*. Every point tied to a mechanism: the causal chain from decision to bad outcome.

**Banned:** free-floating pessimism ("this seems risky"), and any risk you cannot name a mechanism for. Also banned: solutions — Black identifies the failure, it does not fix it (fixes are Green).

Examples:
- "If the cache warms lazily, the first request after every deploy times out — that is a mechanism, not a maybe."
- "A new required config field breaks every existing install on upgrade, because there is no default."
- "Contention: two teams write this file weekly, so a shared lock here stalls both."

**Leakage into Red:** "this makes me nervous" with no mechanism is a Red-hat point that wandered in. Send it back; in Black, name the mechanism or drop it.

**Leakage into Green:** "...so we should add a default instead" — the moment you propose the fix, you are in Green. State the risk cleanly; the fix is a later hat.

---

## Yellow — Benefits

**Belongs here:** upsides, best-case outcomes, value — each tied to a mechanism, exactly as Black demands for risks. Why does the good thing actually happen?

**Banned:** vague optimism ("this would be great"), and benefits with no mechanism behind them. Yellow is not cheerleading; it is rigorous about upside the way Black is rigorous about downside.

Examples:
- "Onboarding drops from four steps to two because the config step becomes automatic — measured elsewhere at ~30% fewer drop-offs."
- "Native rendering means zero new dependencies to audit, so the security surface does not grow."
- "The change is reversible in one commit, which lowers the cost of being wrong."

**Leakage into Red:** "I'm excited about this" is a Red-hat feeling. In Yellow, convert excitement into a named mechanism or leave it in Red.

**Leakage into White:** "the benefit is that it's fast" restates a fact as a benefit without the *so-what*. Yellow needs the consequence: fast *so that* what improves?

---

## Green — Alternatives

**Belongs here:** other options, modifications, creative reframings. Minimum three. At least one must abandon the decision's premise entirely — not "do it differently" but "don't do it, do this other thing instead."

**Banned:** re-litigating the risks and benefits of the *original* option (that was Black and Yellow). Green generates new options; it does not re-judge the old one.

Examples:
- "Modification: ship it behind a flag, off by default, so the risk is opt-in."
- "Alternative: buy the hosted version instead of building it."
- "Abandon the premise: the real problem is discoverability, not this feature at all — solve that and the decision dissolves."

**Leakage into Black/Yellow:** immediately weighing each alternative's pros and cons collapses Green back into the earlier hats. Generate the options here; run a promising one through its own six hats later if the user wants.

**Leakage into Blue:** "and the best alternative is..." — picking a winner is synthesis. Green lists; Blue chooses.

---

## Blue — Synthesis

**Belongs here:** the meta-view. What did the hats disagree about? Which single piece of information would change the answer? A recommendation with an explicit confidence level, and the strongest unresolved tension named out loud.

**Banned:** new material. Every fact, risk, benefit, and option in Blue must trace back to an earlier hat. If something appears here for the first time, an earlier hat was run lazily — go back and rerun it.

Examples:
- "The hats split on one axis: White says the data is thin, Yellow says the upside is large. If we had the drop-off number, that split resolves."
- "Recommendation: defer, medium-low confidence. The Black-hat contention risk is real but the Red hat's reluctance is the louder signal."
- "Strongest unresolved tension: the benefit is large *only if* an assumption we cannot yet verify holds."

**Leakage from every hat:** Blue's characteristic failure is smuggling in a fact or risk nobody raised earlier, to force a tidy conclusion. If it wasn't in White through Green, it doesn't belong in Blue.

**Leakage into false consensus:** the opposite failure — smoothing a genuine disagreement into a bland "on balance." Name the split; do not average it away.
