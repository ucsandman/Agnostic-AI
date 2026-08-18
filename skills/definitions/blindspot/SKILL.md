---
name: blindspot
description: Use before modifying unfamiliar or high-stakes code — when the user invokes /blindspot, inherits a module or codebase, asks "what am I missing?", or is about to change auth, billing, data migration, or concurrency code they didn't write. Not for routine changes in well-understood code.
---

# Blindspot

Hunt unknown unknowns: the risks nobody thought to ask about. Output is a short ranked set of blindspot cards, each grounded in this codebase with a concrete next move — never a generic risk checklist.

## Steps

1. **Map the territory.** Read the target module, its callers, its tests, and its config/env wiring. Blindspots live in the connections, not the file itself.
2. **Sweep the classic hiding places** against the actual code:
   - Hidden state and side effects (module-level mutables, caches, singletons)
   - Implicit invariants the code assumes but never checks (ordering, uniqueness, non-null)
   - Swallowed errors: catch blocks that hide failure, fallbacks that mask bugs
   - Concurrency and ordering: races, double-fires, retry without idempotency
   - Config/env coupling: behavior that changes across environments
   - AuthZ edges: who else can reach this path, what happens unauthenticated
   - Back-compat and migration traps: persisted data shaped by old code
3. **Write blindspot cards.** Each card:
   - **What you likely don't know** — one sentence
   - **Evidence** — `file:line` in this repo (no evidence, no card)
   - **How it bites** — the concrete failure scenario
   - **Next move** — a question to answer or a copyable fix prompt
4. **Rank and cap.** Order by blast-radius × likelihood. Max 7 cards — if you found 20, the bottom 13 are noise.
5. **Hand off.** If the user wants fixes, feed the cards into normal implementation flow (interview first if a card exposes a real decision).

## Common mistakes

- Generic risks not grounded in this code ("consider adding error handling") — every card cites `file:line` or gets cut.
- Restating known unknowns the user already raised — the job is what they *didn't* ask.
- 20-card dumps — capping at 7 forces the ranking that makes the output usable.
- Reading only the target file — the callers and tests are where assumptions break.
