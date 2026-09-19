# Errors and lessons

## 2026-09-16 - Secret scanning covered two map keys and the docs promised the whole bundle

- **Symptom:** an independent security review of the engine embedded in Leg
  planted a token in the rules text, a hook command line, an MCP argument and
  an MCP url; `validate()` reported one problem, the env one. The four canary
  tests only planted tokens where the scan already looked.
- **Root cause:** `looksSecret` was written for `env` and `headers` values and
  never applied to free text or command lines; the bare-URL exemption also
  waved through a password in a connection string.
- **Fix:** `findSecrets`/`redactSecrets` over every field, `bundle.sanitize()`
  before every save (redact text, drop an unsafe handler or server with a
  warning), URL userinfo, query and path-token checks, and fixtures that plant
  a token in every place the scan must reach. A check never seen failing has
  been run, not verified: the new fixture is the failing case.

## 2026-09-06 - Two writers for one target file, and a personal tool that never came home

- **Symptom:** Codex's AGENTS.md flipped between two shapes depending on which
  job ran last; the repo's own registry had no Codex, Gemini or Antigravity
  target at all while the README promised a 16-client harness.
- **Root cause:** the repo's sync wrote rules files only, so a working
  Claude-to-Codex port (hooks with trust hashes, agents, prompts, skills, MCP)
  grew as a personal script under ~/.claude with this machine's paths and hook
  names hardcoded. When both wrote the same file they fought; when the repo
  dropped its Codex target to stop the fight, the public repo no longer did the
  thing it was for.
- **Fix:** the port engine (engine/harness) with one writer per file, a
  registry that carries every client surface, a policy file for exclusions,
  and adapters written against a contract with fixture-home tests.
- **Lesson:** a capability proven in a personal script is not shipped until it
  is data-driven and lives where the tests run. Every hardcoded machine fact in
  that script (a hook name, a skill list, a model slug) became a field in
  core/port.json or a value read from the target's own files.
- **Retro, one change each:** grep `engine/tests/` for a behaviour BEFORE removing it (two
  first-run tests went red after the flat-format hook path was deleted, found only when the
  suite ran); a test fixture that hardcodes a `C:/` path is not absolute on the Ubuntu CI
  legs (`path.isAbsolute`), so fixtures build paths from a temp dir; and a value that YAML
  reads as a flow sequence (`argument-hint: [text]`) must be quoted by the frontmatter
  renderer, which the staged diff against the live Codex prompts caught before the real apply.

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

- **`reg-hooks.cjs` died whenever port 3000 was busy.** `listen()` failures are
  `'error'` events, not promise rejections, so the `.catch` never saw them. Fix:
  ephemeral port. Lesson: same as the 7842 entry below — a fixed port in a test
  is a guess about someone else's machine.
- **Wrong premise: "no tool runs vulture, delete the whitelist."** The repo
  has no vulture step, but the machine's global pre-commit hook does, and the
  first commit of this release was blocked by 20 false positives (Textual
  `action_*`/`compose`/`on_print`, prompt_toolkit handlers, `to_dict`s). Fix:
  the whitelist is back as `.vulture_whitelist.py` (the hook's preferred name),
  pruned to real framework callbacks. Lesson: "nothing runs X" must include the
  global hooks in `~/.claude/git-hooks`, not just the repo's CI and scripts.
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
- 2026-09-19 — Consolidation stage A replaced the Mods' hardcoded home paths with an environment read at module load; the hooks worker has no Node globals, so both Mods failed to load ("process is not defined") until a headless session after the fix proved the heartbeat. Lesson: a change to code that runs in another runtime is verified in that runtime before it ships, not by the unit tests beside it. A wrapper around `on()` was then refused by the validator (`$` only to top-level functions); each hook resolves the home itself.
- 2026-09-19 — The same stage copied a private research repository into `labs/` wholesale and published 32 transcript-derived data files for a day. Lesson: a directory copy from a private repository is scanned for data before the first push; the doctor's `data-files` check now blocks a recurrence. History still holds the blobs until the owner decides on a rewrite.
- 2026-09-19 — **"Claude is incredibly slow" was process spawn cost, and the Bash tool's login shell.** Symptom: every tool call took 15 to 30 s; a Bash tool call in a fresh session measured 31.6 s for an `echo`. Root cause, in layers: process creation on the machine was 10 to 30x slow and erratic (0.77 GB RAM free, three tsservers from the typescript-lsp plugin at 2.2 GB each indexing all of `C:\Projects`, orphan node sentinels; freeing 5 GB helped RAM but not spawn); every Bash tool call ran `bash -c -l`, and Git for Windows' `/etc/profile` forks ~14 times (5 to 14 s per call, never measured before); 56 hook commands, each a `bash -c` plus node or python, 15 of them on every Bash call. Prompt caching was fine, so the token audit was not where the time went. Fix: `tools/bash-noprofile` shim on `CLAUDE_CODE_GIT_BASH_PATH` (31.6 s to 4.2 s per call), typescript-lsp off, orphans killed, `tools/hook-latency` so the next pass starts with numbers. Three probes were lost to a shim that inherited handles instead of passing them: Claude Code spawns the shell detached, so the child wrote to a console nobody read and the tool said "(Bash completed with no output)". Lesson: before adding any hook or shell layer, time one process spawn and one empty login shell on the machine; the 2026-09-06 "a dispatcher buys nothing" verdict was true on a fast box and inverted on a slow one. Second lesson: a custom `CLAUDE_CODE_GIT_BASH_PATH` binary must pass std handles explicitly.
- 2026-09-19 — **Every saved workflow was unlaunchable after the fan-out guard shipped, and the by-name form kept failing after the fix.** Symptom: `Workflow({name: "tournament"})` denied with "no declared ceiling"; none of the four scripts in `workflows/` carried `// MAX_AGENTS:` because the guard postdates them. After the ceiling was added to `tournament.js`, the by-name launch was still denied while a local run of `agent-model-guard.cjs` on the same payload passed: the harness hands the guard a script resolved earlier in the session, so an in-session edit to a saved workflow is invisible to the name form. Fix: `tournament.js` declares its arithmetic (`lenses + judgeLenses + 1`) and throws above 30; relaunch with `Workflow({scriptPath: "C:/Projects/agnostic-ai/workflows/<name>.js", args})`, which reads the file fresh. Still open: `understand.js`, `adversarial-review.js`, `fix-findings.js` carry no ceiling; the verify stage in `adversarial-review.js` is the exact shape that queued 225 agents and needs a real cap, not a comment. Lesson: a new guard is applied to the saved shapes it governs in the same change, or the shapes stop working silently.
- 2026-09-19 — **Every prompt printed six "UserPromptSubmit hook timed out after 5s" lines, and a waiting session answered "Waiting." seventeen times.** Symptom: red timeout rows after each prompt in a sense-memory session running a tournament; the model woke on every PNG a Monitor watched, replied "Waiting.", and re-armed; 1.4M tokens in 45 minutes for 0 of 12 agents. Root cause: settings.json spawned eight UserPromptSubmit processes per prompt (seven node, one python) with 5 s budgets, and under ~30 concurrent sessions a bare node start measured 2.6 s and the python nudge 5.2 s, so every hook's output was discarded, including the guard that briefs a Fable session; each Monitor event is a prompt, so the set re-ran per wake-up. Fix: `prompt-dispatch.cjs` (one process, hooks in-process, 30 s budget), `wakeup-guard.cjs` (third consecutive machine wake-up: no text, stop the stalled task), `context-nudge.cjs` replacing the python, doctor `prompt-hooks` check, `first-run.cjs` wires the dispatcher. Lesson: a hook budget is set against the machine's worst spawn time, not its best, and N hooks on one event are one process; the 2026-09-06 note already said the dispatcher verdict inverts on a slow box, and this is that box. Second lesson: a Monitor that fires per file is the wrong grain when a workflow already notifies on completion.
