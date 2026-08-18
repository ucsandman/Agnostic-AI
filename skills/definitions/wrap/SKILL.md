---
name: wrap
description: Use when a session is ending — the user says "wrap up", "get to a good stopping point", is near a rate limit or context limit, wants to compact safely, or asks for handoff notes / a resume prompt.
---

# Wrap

End a session so the next one starts at full speed: stop at a seam, lock state, persist it, emit a resume prompt.

## Steps

1. **Stop at the seam.** Finish only the smallest in-flight unit (the current edit plus its verification). Start nothing new.
2. **Lock state in bullets:**
   - Goal (one line) and current phase
   - Done and verified — with the evidence (command + result)
   - In progress — exact file and step
   - Next concrete action
   - Deviations from plan made this session and why (from the DEVIATIONS log, if kept)
   - Risks/gotchas that will bite a fresh session
3. **Persist.** Run `/handoff-save`. If the bundle CLI is unavailable, write the bullets to the project's progress-notes doc instead.
4. **Resume prompt.** Emit one contiguous pasteable block containing: project directory, recommended model and effort level, `/handoff-load <bundle-name>`, and the next concrete action. No commentary inside the block.
5. **Hand control back.** Never suggest stopping for the day or postponing — pacing is the user's call.

## Common mistakes

- Vague notes ("continue the refactor") — the next session needs file paths and the exact next command.
- Resume prompt missing model/effort/directory — sessions run across many projects; make it self-locating.
- Doing "one more improvement" after wrap is requested.
- Locking state that was never verified — "done" without evidence becomes a false fact in the next session.
