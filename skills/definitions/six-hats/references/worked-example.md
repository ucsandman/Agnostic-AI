# Worked Example: Should v1 Ship a Docs Website?

A real run of all six hats on one decision:

> "Should this repo ship a documentation website in v1?"

Context the hats were given: the repo is a free, MIT-licensed collection of 8 lateral-thinking technique skills plus a router, aimed at AI coding agents, installable via `npx skills add`. It is authored by one person in spare time. The v1 scope *explicitly excludes* a docs site, scripts, an MCP server, and a CLI. Today the entire documentation surface is the README plus one markdown file per skill, and the host renders markdown natively. The project's own spec already says no docs site — the hats were run honestly to see whether they agree, not to rubber-stamp it.

---

## White — Facts

Only what is verifiable, plus what is missing.

- Documentation today: one README plus one markdown file per skill. That is the whole surface.
- The hosting platform renders markdown natively, so every file is already browsable in a formatted view without any site.
- Install path is `npx skills add`; nobody has to visit a website to obtain or use a skill.
- The project has one maintainer working in spare time.
- The v1 scope document lists a docs site, scripts, an MCP server, and a CLI as explicitly excluded.
- License is MIT; the project is free.

Missing data, named rather than guessed:
- No usage or install numbers. We do not know how many people have run the install command.
- No evidence either way that anyone is confused by, or bounced off, the markdown-only presentation.
- No data on whether a docs site would measurably increase adoption. Missing.

---

## Red — Gut reactions

One line each, no justification.

- A docs site feels like a trophy — built to look established, not because anyone asked for it.
- Faint contrary tug: markdown-only reads as slightly under-invested, like the project doesn't take itself seriously yet.
- Relief at the thought of *not* maintaining a website.
- Mild boredom — this feels like the least interesting thing the author could spend the next weekend on.

The second line contradicts where this is heading. Everything else leans toward "no site," but there is a real pull that the bare-markdown look undersells the work. Flagging it rather than burying it — the Red hat is doing its job precisely because it disagrees with the emerging answer.

---

## Black — Risks

Each tied to a mechanism.

- **Documentation drift.** A separate site duplicates content that already lives in the skill markdown. The moment a skill changes, the site is stale unless someone remembers to update both — and with one spare-time maintainer, "remembers to" is exactly the thing that fails.
- **Opportunity cost, concretely.** Every hour on a site is an hour not spent on a ninth skill or on sharpening the router. For a solo author this is a zero-sum trade, not an "and also."
- **Implied promise.** A polished site signals a level of ongoing support and completeness the project cannot currently guarantee, which sets up a credibility fall when a link rots or a page lags the code.
- **New failure surface.** A site means a build and a deploy that can break independently of the skills, which work fine on their own today.

---

## Yellow — Benefits

Each tied to a mechanism.

- **Cross-skill browsing.** A site could present all 8 skills and the router on one indexed, searchable page, which the scattered per-folder markdown cannot do — a newcomer sees the whole toolkit at a glance instead of spelunking directories.
- **Explaining the router.** The router concept is the hardest thing to grasp from markdown alone; a single landing page with one diagram could make "how these fit together" click in a way eight separate files do not.
- **Adoption signal.** For a project seeking users, a real homepage lowers the trust barrier — mechanism: people evaluate legitimacy partly by presentation before they will run an install command.
- **Reversibility.** A minimal static page is cheap to remove later, so being wrong here is not expensive.

---

## Green — Alternatives

Minimum three; at least one abandons the premise.

1. **Strengthen the README into an index.** Add a single table listing all 8 skills, one-line descriptions, and trigger phrases, plus a short router explainer. This captures most of the "browse the whole toolkit" benefit with zero new infrastructure and nothing to drift out of sync — it lives beside the code.
2. **Generate the site, don't author it.** If a page is wanted, produce it mechanically from the existing skill markdown at release time, so there is no second copy to maintain by hand. The site becomes a view of the source, not a parallel document. Deferring the *hand-authored* site while allowing a *generated* one splits the difference.
3. **Abandon the premise.** The real question may not be "docs site vs. no docs site" at all — the audience is AI coding agents, and an agent never visits a website; it reads the skill descriptions the router feeds it. If discoverability is the actual goal, the highest-leverage work is sharpening those descriptions and trigger phrases so the right skill fires at the right moment. A human-facing site solves a problem the primary user does not have.

---

## Blue — Synthesis

**Where the hats disagreed.** The split is narrow and specific: Yellow and one Red line say a site buys credibility and a coherent view of the whole toolkit; Black and White say the project has neither the evidence that this is needed nor the maintainer capacity to keep a second surface honest. White is the quiet tiebreaker — there is no data showing anyone is bouncing off the markdown, so the Yellow benefits are hypothetical while the Black costs are concrete.

**What would change the answer.** A single piece of information: evidence that people are actually failing to understand or adopt the toolkit *because* of the markdown-only presentation. If that surfaced (support questions, drop-off, direct feedback), Yellow's case would harden and the recommendation would flip toward at least the generated-page alternative.

**Recommendation, with confidence.** Agree with the spec: **do not ship a hand-authored docs website in v1. Confidence: medium-high.** Instead take Green alternative 1 now (a stronger README index — cheap, no drift, captures most of the upside) and keep alternative 2 (a generated page) in reserve for when there is usage data to justify it. Green 3 is the real long-game: for an agent audience, description quality outranks any website.

**Strongest unresolved tension.** The Black-hat maintenance-and-opportunity-cost case is decisive *today*, but it rests entirely on the project staying small and solo. The one Red-hat feeling that a bare repo undersells the work is not irrational — if the goal shifts from "a tidy personal toolkit" to "a project actively courting a user base," the credibility argument gets stronger and this recommendation should be revisited. The hats agree with the spec, but they agree *conditionally*, and the condition is the project's own ambition.

---

*Next moves, your call: re-run Black or Yellow deeper, take Green alternative 2 (the generated page) through its own six hats, switch to a generative technique if the question is really "what should v1 include," or stop here.*
