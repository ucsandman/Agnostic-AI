# Errors and lessons

One line minimum every time something broke or a premise turned out wrong.
Full entries (symptom, root cause, fix) when it took more than one attempt.

## 2026-08-20

- **`launch.py` opened a different project's app.** Symptom: `python launch.py`
  brought up an unrelated local UI (hooop) instead of the command center. Root
  cause: another app already owned 7842, so `EADDRINUSE` took the dashboard's
  "already running" branch, which trusted the port instead of identifying the
  occupant, and `--open` launched a browser at it. Fix: every response carries
  an `x-agnostic-dashboard` header, the collision path HEAD-probes for it, and
  a foreign occupant means bind the next free port. The same fixed-port
  assumption in `start_companion_server` (returned failure on a busy 7843) got
  the same walk-up. Lesson: a hardcoded local port is a guess about someone
  else's machine — verify the occupant before reusing a port, and never print a
  URL you did not bind. This is the second time this bug shipped (see the
  distill digest entry about 7842 vs a Next.js dev server).

- **Dashboard POST routes were unauthenticated.** Symptom: nothing visible;
  found in a review. Root cause: the Python companion got an auth pass, the
  Node dashboard never did. Fix: token + loopback-origin gate on all POSTs,
  regression tests in `engine/tests/run-all.cjs`. Lesson: a second server in
  the same repo needs the same review as the first.
- **Fabricated "audit events" in the governance view** asserted a secret scan
  that never ran. Removed. Lesson: never seed a safety UI with placeholder
  results.
- **README claimed features the code did not have** (swarm "Implementer" and
  worktree isolation, interactive `launch.py`, `npm install` with no
  dependencies, `/multiline` in the TUI). Fix: docs rewritten from the code;
  `docs/targets.md` generated. Lesson: fact-check every README claim against
  source before a ship.
- **Wrong premise during the fix pass:** a grep for `cmd == "schedule"` found
  nothing, so `/schedule` and `/loop` were assumed unhandled. They are handled
  via `startswith(("/schedule", "/loop"))` in both UIs. Caught by the
  implementing agent before any removal. Lesson: grep for the command string,
  not one dispatch idiom.
- **Bash heredoc mangled a JS string.** A `python - <<'EOF'` edit through the
  Bash tool turned `'\\n'` into a literal newline in
  `engine/skills/recommend.cjs` (SyntaxError). Fix: use the Edit tool for code
  edits on this machine.
- **`vulture_whitelist.py` imported gitignored `skills/definitions`** and three
  renamed classes, so it failed on a clean clone. Fixed; it now imports clean.
- **`tools/errorlog --selftest` could not fail** (printed a check mark next to
  a literal `false`, exited 0). Now uses `assert`.
