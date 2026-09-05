# Errors and lessons

## 2026-09-05 - Injected clients must not depend on local subscription CLIs

CI failed three flat-subagent tests because preset availability checked for local
subscription executables before calling the supplied client factory. Installed
CLIs hid the defect locally. A forced-unavailable probe reproduced all three
failures without changing tests. Custom subscription factories now validate their
own transport at construction; built-in clients retain the CLI check and metered
API restrictions still run first. Keep this missing-provider case in release
verification so a developer machine cannot supply an undeclared dependency.

## 2026-09-05 - Preserve shared lifecycle hook configuration

Claude's setup correction and Codex's stdout repair address different boundaries. Setup now leaves an existing lifecycle `hooks` object unchanged instead of adding a flat event key. Four fixture checks cover empty and populated Codex/Gemini configurations and guard-presence reporting. The new check failed against the previous installer and passed with the correction.

What worked: pausing the release when the operator identified another active session, then reviewing its separate installer change before including it. What did not: assuming a clean initial checkout meant no other session would begin writing later. Prevention: recheck the working tree immediately before staging and validate the combined state when another agent's completed work is included.

## 2026-09-05 — Codex rejected the pre-tool hook JSON

The Agnostic guard returned a top-level permissionDecision. Current Codex lifecycle hooks require that field inside hookSpecificOutput with hookEventName set to PreToolUse. This produced repeated invalid pre-tool-use JSON warnings even for benign commands. Internal decision tests passed because they inspected the flat object rather than the wire response.

The shared adapter now wraps decisions at the stdout boundary for Codex and Claude, preserving the existing internal decision dialect and other clients. Both guard runners also put denial reasons on stderr for exit code 2. The installed Codex command directly references this source, so the next invocation loads the repair without a config rewrite or disabling a hook.

What worked: replaying a harmless payload through the actual runner and comparing the response with the documented lifecycle envelope. What did not: testing only the internal return object. Prevention: the npm suite now includes eight real-process protocol checks covering both runners, Bash/MCP inputs, and allow/deny results. The new check was observed failing before the repair.

Wire contract: https://learn.chatgpt.com/docs/hooks#pretooluse

Verification: eight wire checks, 73 existing hook regressions, 13 sync regressions and Ruff passed. Generated target and orchestration documentation checks pass after regenerating the target table. The broader npm suite initially failed its obsolete assertion of 18 targets against a registry of 16 (27 passed, one failed). The operator explicitly approved correcting that assertion to 16 on 2026-09-05; the registry is unchanged. Package descriptions and the README now reflect the same count. Prevention: when intentionally removing a sync target, update the parity assertion and regenerate the target documentation in the same change.

All 530 Python tests also passed with `python -m pytest tests/ -q -p no:xonsh`. The default invocation crashed during plugin startup because the globally installed xonsh plugin requires a Windows console; excluding that unrelated plugin required no repository or test changes.

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

## 2026-09-02 - Subscription fallback ignored a failed process

- **Symptom:** an orchestration role with fallback models could accept diagnostic
  output from a failed subscription CLI as a successful model response.
- **Root cause:** the bridge treated non-empty stdout as success without first
  checking the child process exit status.
- **Fix:** nonzero subscription CLI exits now raise an availability error with
  redacted diagnostics, allowing the orchestration router to record and try the
  configured fallback.
- **Lesson:** process output is evidence, not success; bridges must validate exit
  status before interpreting stdout as a provider response.

## 2026-09-02 - Subscription CLI billed the API key, and an unknown model id ran the default

- **Symptom:** `claude -p` children answered "Credit balance is too low" although the
  machine has a Claude subscription login; a child pinned to `claude-haiku-4.5` cost
  219k cache tokens on one question.
- **Root cause:** the bridge inherited the shell environment, and Claude Code prefers
  `ANTHROPIC_API_KEY` over the login when it sees one. The harness names models by
  API preset key; the CLI logs `unrecognized_model` for `claude-haiku-4.5` and
  silently runs the session default model.
- **Fix:** subscription CLIs launch without the vendor key variables
  (`subscription_env`), and harness names map to CLI aliases
  (`CLAUDE_CLI_MODEL_ALIASES`: haiku/sonnet/opus/fable). Verified by three real
  researcher children on the login returning the expected file content.
- **Lesson:** a zero-key preset must scrub the keys from the child environment, and
  a model pin is only verified when the CLI's usage report names that model.

## 2026-09-02 - `--tools ""` plus `--dangerously-skip-permissions` broke the JSON tool protocol

- **Symptom:** confined children replied "tool call could not be parsed", "read_file
  is not available", or an empty result instead of the JSON tool block.
- **Root cause:** measured combinations: `--tools ""` alone yields the block;
  `--tools ""` with the bypass flag drops it; `--restricted --tools ""` returns an
  empty result. With no built-in tools there is nothing to bypass.
- **Fix:** confined children run `claude -p --tools "" --output-format json` without
  the bypass flag; an empty reply is nudged once before it is reported as a failure.
- **Lesson:** a CLI flag combination is a measurement, not a reading of `--help`;
  run the matrix before wiring it.
