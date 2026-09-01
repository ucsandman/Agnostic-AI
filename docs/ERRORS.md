# Errors and lessons

One line minimum every time something broke or a premise turned out wrong.
Full entries (symptom, root cause, fix) when it took more than one attempt.

## 2026-08-20 (review tournament)

- **The default prompt mode dropped the rules the repo exists to enforce.**
  Symptom: none visible — the agent just behaved generically. Root cause:
  `agnostic` defaults to compact mode, and the compact branch of
  `_load_harness_system_prompt` replaced the compiled `global-rules.md` with a
  hardcoded five-line prompt instead of shortening it; a fresh clone (no
  `storage/compiled/`) fell back to a two-sentence stub with no message. Fix:
  compact mode clips the real rules to ~4 KB; a missing compiled prompt is
  reported. Lesson: a "compact" variant must be derived from the full one, never
  hand-written beside it, or the two drift and nobody notices.
- **Every edit on Windows rewrote LF files as CRLF.** Root cause: reads used
  universal newlines, writes used `newline=None`; `/undo` restores did the same.
  Fix: `newline=''` on both sides plus newline-matching for edit targets.
  Lesson: a file tool that changes bytes it was not asked to change is a bug even
  when the diff "looks right" in the terminal.
- **An aborted turn bricked the session.** Root cause: the assistant message
  with `tool_calls` was appended before the calls ran; any exception or Ctrl+C in
  between left them unanswered and every later request failed with a 400. Fix:
  `_repair_history()` backfills `[aborted]` results in `finally`.
- **Tab never fired in the TUI.** Textual matches the Screen's `focus_next`
  binding before the App's, so the slash/`@`/`#` completion action was dead code
  since the TUI shipped. Fix: `Binding(..., priority=True)`. Lesson: a binding
  needs one test that presses the key.
- **`reg-hooks.cjs` died whenever port 3000 was busy.** `listen()` failures are
  `'error'` events, not promise rejections, so the `.catch` never saw them. Fix:
  ephemeral port. Lesson: same as the 7842 entry below — a fixed port in a test
  is a guess about someone else's machine.
- **Docs promised things the code did not do** (read-only output truncation,
  `grep_search` regex, TUI fuzzy completion, a TUI model picker). Each was fixed
  in code, not in the docs. Lesson: when a doc claim and the code disagree, the
  doc was usually the design — implement it.
- **Wrong premise: "no tool runs vulture, delete the whitelist."** The repo
  has no vulture step, but the machine's global pre-commit hook does, and the
  first commit of this release was blocked by 20 false positives (Textual
  `action_*`/`compose`/`on_print`, prompt_toolkit handlers, `to_dict`s). Fix:
  the whitelist is back as `.vulture_whitelist.py` (the hook's preferred name),
  pruned to real framework callbacks. Lesson: "nothing runs X" must include the
  global hooks in `~/.claude/git-hooks`, not just the repo's CI and scripts.
- **A harness wrapper (`rtk`) hung a subagent for 10 minutes on
  `pytest … | tail`.** Not a repo bug; recorded in the session memory. Lesson for
  briefs: redirect test output to a file and read the exit code.

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
  renamed classes, so it failed on a clean clone. Fixed at the time; the file
  has since been deleted along with the vulture pass.
- **`tools/errorlog --selftest` could not fail** (printed a check mark next to
  a literal `false`, exited 0). Fixed at the time; the tool has since been
  deleted — the command center is the only error surface.

## 2026-08-20 - CI py3.9 leg failed on a 3.10-only kwarg

- **Symptom:** 11 tests/test_memory.py failures on the Ubuntu py3.9 leg only:
  TypeError: write_text() got an unexpected keyword argument 'newline'.
- **Root cause:** Path.write_text(newline=...) exists only on Python 3.10+;
  the code was written and verified on 3.12.
- **Fix:** `open(tmp, "w", encoding="utf-8", newline="\n")` (commit 4f4d40a).
  (That line itself arrived here with a real newline in place of the escape —
  the heredoc-mangling bug two entries up, biting the entry that logs it.)
- **Lesson:** the support floor is 3.9 (pyproject + CI matrix). New code must
  avoid 3.10+ APIs; the local suite passing on 3.12 proves nothing about it.
- Also: git staging survives a blocked pre-commit hook, so a later narrow
  commit swept up everything staged by the earlier failed attempt - check
  git status before re-committing after a hook block (2e45beb was amended).

## 2026-08-20 - CI py3.9 leg failed on widgets built outside an event loop

- **Symptom:** 3 failures on the py3.9 leg only (two in test_tui_composer.py,
  one in test_tui_memory.py): RuntimeError: There is no current event loop in
  thread 'MainThread', raised from asyncio/locks.py inside Widget.__init__.
- **Root cause:** on 3.9 asyncio.Lock() calls get_event_loop() at construction,
  and every Textual widget builds one; asyncio.run() sets the thread's loop to
  None when it returns, so the first test to construct a widget outside a
  running app after any pilot test blew up. Order-dependent, which is why only
  3 of 432 tests tripped and why no single-file run reproduced it.
- **Fix:** tests/conftest.py hands every test a current event loop and closes
  what it opened. No-op on 3.10+, where Lock() no longer touches the policy.
- **Lesson:** second py3.9 break in two ships, same shape as the write_text one
  - the floor is 3.9 and 3.12-only verification keeps missing it. A real 3.9
  interpreter is one `uv venv --python 3.9` away; use it before pushing when a
  change touches asyncio, pathlib, or typing.

## 2026-08-31 - Subscription bridge died on Windows argv limits

- **Symptom:** every codex-sub turn answered only "The command line is too
  long." (0.04s turns, no model call).
- **Root cause:** the bridge passed the whole flattened transcript as one argv
  argument; `codex.cmd` runs through cmd.exe, whose command line caps at 8,191
  chars, and the harness prompt alone exceeds it. claude/agy were the same bug
  waiting at the 32K .exe limit.
- **Fix:** prompt rides stdin (`codex exec -`, piped `claude -p`); regression
  test asserts no argv element reaches 8,191 chars.
- **Lesson:** anything that puts model-scale text on a child argv is broken by
  design on Windows - pipe stdin or write a temp file, always.

## 2026-08-31 - Two Textual gotchas cost a test round each

- Overriding `_on_paste` and calling `super()._on_paste()` inserts pastes twice:
  the message pump dispatches `_on_paste` once per MRO class, so the base
  handler runs anyway. Fall through instead of delegating; block the base with
  `event.prevent_default()` when you handled it.
- Same-edge `dock:` siblings OVERLAP (they only reserve space from non-docked
  siblings). Measured regions proved #hint-bar and #input-container shared
  y=26. A widget that must sit above/below the composer goes INSIDE the one
  docked container, in flow layout.

## 2026-08-31 - Green on Windows, red on the Linux CI legs (stdin pipe)

- **Symptom:** both ubuntu CI legs failed test_subscription_bridge_kills_a_hung_cli
  with 'ValueError: I/O operation on closed file' while the Windows suite passed.
- **Root cause:** POSIX communicate() selector-registers self.stdin whenever it is
  not None; the bridge had written and closed it. Windows' thread-based
  communicate tolerates a closed stdin.
- **Fix:** proc.stdin = None after closing, so communicate() skips it.
- **Lesson:** a subprocess-pipe change is not verified until it has run on a POSIX
  interpreter - WSL is right there (pip install --break-system-packages pytest
  httpx openai prompt_toolkit textual rich pillow, then run the touched tests).
