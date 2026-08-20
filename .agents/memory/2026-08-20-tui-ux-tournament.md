# Agnostic TUI — tournament synthesis

## 1. Research digest: what the two leaders actually do differently

1. **Claude Code turns latency into signal, Codex turns it into an affordance.** Claude pairs a `∴` glyph with ~190 rotating present-participle verbs (user-overridable via `spinnerVerbs`) and live-ticks a *dimmed* elapsed counter per long tool call; Codex writes `• Working (10s • esc to interrupt)` — the interrupt key lives **inside** the busy string, not in a static legend. Both exist to kill "is it hung?", which is what makes users force-kill sessions.
2. **Two-tier stop.** Codex: Esc interrupts the turn and keeps the session; Ctrl+C/Ctrl+D twice quits. Claude: the same split, plus a *reused* "press again within N ms" idiom across exit (800 ms), clear (2 s) and rewind — one idiom, no per-action modal.
3. **Double-Esc rewind with a 2D restore.** Claude's rewind menu restores **code only / conversation only / both**. Head-to-head research says flatly that a single flat undo stack is a worse UX than this 2-axis choice. Codex has no per-turn restore at all and its Esc has a tracked "suspends instead of interrupts" bug (#4380, #5905).
4. **Permission level is glanceable and one keystroke away.** Shift+Tab cycles Claude's permission modes with the current mode always in the footer. Codex hides it behind `/permissions` + `config.toml`, cannot switch mid-session (#33974), and has shipped a bug where the displayed mode drifted from the enforced sandbox (#33702). The portable lesson: **read the enforcing object on every repaint; never cache a label.**
5. **A rejection should be an instruction, not a dead end.** Claude's permission prompts carry an inline free-text comment field, and Anthropic *hardened* it (v2.1.235) so a stray keystroke cannot grant more scope than intended. Our TUI has the mirror-image accident: any non-y/n text silently **denies** a governance hard-stop.
6. **Fold output, but ship the escape hatch in the same commit.** Codex folds long shell output in the TUI with no opt-out — issues #4550/#5095/#5163 open for years. Claude's answer is Ctrl+O into the unabridged transcript. We clip tool output to 600 chars with no way back, i.e. exactly the Codex mistake.
7. **Context visibility: ship bar *and* number.** Codex replaced the raw context % with a meter, ate four issues demanding the number back (#17497, #17874, #17618, #27984), and ended up shipping `CTX ██░░░ 31%`. Claude adds proactive compaction *before* the ceiling and `/autocompact` reporting where the threshold came from.
8. **Compaction must be readable.** Codex's fast-path compaction is an encrypted black box; Claude's summary is readable and steerable. When a session goes sideways after compaction, an unreadable summary makes it undebuggable. Community guidance is to compact manually at 60–85% because a silent auto-compact visibly changes model behaviour mid-task.
9. **Errors are diagnosed, not reported.** Claude's context-limit error names *why* (auto-compact disabled vs. compact failed) and embeds the exact remediation command. A raw regex in a permission prompt gets muscle-memory-approved; a named blast radius gets read.
10. **Queued prompts are visible.** Typing during a turn queues instead of interrupting, and the queue is listed above the input until sent, with a small whitelist of informational commands that bypass it.
11. **Diffs are conversation state, not git state.** Claude's `/diff` browser is indexed by turn and reconstructed from the conversation, so it still works after the user stages or hand-edits the same files.
12. **Composer sub-modes beat panels.** Codex overloads the single input: `@` fuzzy file search, `!` local shell whose output never reaches the model, screenshot paste. Keyboard-only users never leave the composer — and `!git status` costs zero context.
13. **Resume is cwd-scoped by default.** `codex resume` lists recent sessions with timestamp + preview, filtered to the current repo, with `--all` as the explicit opt-out.
14. **Consistency is a feature, and discoverability debt is real.** Codex's Ctrl+T overlay documents its scroll keys but not the key that closes it — filed and closed "not planned" (#2782). Claude's opposite bet (one idiom reused everywhere) is why users guess keys they have never pressed.
15. **Status lines are composable.** Codex's `/statusline` is an opt-in checklist of segments (model, approval policy, context %, quota meters, branch, cwd) rather than one hardcoded footer.

**What retains users, distilled:** never look hung; never lose work to one keystroke; never lie about the enforced policy; never hide what you truncated or summarised; keep the frequent adjustment out of a modal.

## 2. Tournament table

| Idea | Angle | Avg | Fatal flaw / disposition |
|---|---|---|---|
| `!` shell escape via the run_command tool | input-ergonomics | 7.3 | none → **WINNER 6** |
| /compact shows what it dropped, and can be undone | control-and-trust | 7.3 | none → **merged into WINNER 5** |
| /theme picker that rethemes Textual chrome + high-contrast palette | polish | 7.3 | dup of the other theme picker; **cut** (real fix, but lowest daily frequency; see §4) |
| End-of-turn "what changed" card from undo_manager | visibility | 7.0 | none, but subsumed by the rewind/diff surface; **cut** |
| Shift+Tab cycles trust tier (v1) | input-ergonomics | 7.0 | dup → **merged into WINNER 3** |
| Double-Esc rewind, 3-way restore (v1) | control-and-trust | 7.0 | dup → **merged into WINNER 8** |
| One double-tap helper for Ctrl+C and Ctrl+L | control-and-trust | 7.0 | none → **merged into WINNER 2** |
| /session resume picker | pickers | 7.0 | none → **WINNER 9** |
| /effort picker + ctrl+up/down nudge | pickers | 7.0 | none; **cut** for budget (see §4) |
| Live working indicator (elapsed + verb + interrupt key) | visibility | 6.7 | dup ×3 → **WINNER 1** |
| /diff turn-indexed browser | visibility | 6.7 | none, but L effort on top of an L rewind; **cut** — WINNER 8 lays its groundwork |
| Typing ahead during confirm must queue, not deny | input-ergonomics | 6.7 | dup → **WINNER 4** |
| Shift+Tab trust tier (v2) | control-and-trust | 6.7 | dup → merged |
| Extract a PickerScreen base | pickers | 6.7 | judged fatal: zero user-visible value alone → **folded into WINNER 8** as a prerequisite |
| Live busy indicator (v2, env-overridable verbs) | polish | 6.7 | dup → merged into WINNER 1 (its per-turn verb choice wins) |
| Confirm panels that explain blast radius + remediation | control-and-trust | 6.3 | none; needs a refactor of `_tool_simulate_command`'s regexes it doesn't own up to; **cut** |
| Context gauge + one-shot compact nudge (v1) | polish | 6.3 | dup → **merged into WINNER 5** |
| Context segment bar + % + nudge (v2) | visibility | 6.0 | dup; reimplements `render_gauge` → merged with reuse noted |
| Busy composer + Ctrl+C escalation | input-ergonomics | 6.0 | dup of two others → split: timer to W1, escalation to W2 |
| Tab on ambiguous slash opens a palette | pickers | 6.0 | dup of the `/` palette; **cut** for budget |
| First-run welcome card + rotating tip | polish | 6.0 | none; **cut** (one-time touchpoint) |
| Tool cards: duration, size, ctrl+o expand | visibility | 5.7 | dup ×4 → **WINNER 7** |
| Turn-done notification (v1) | visibility | 5.7 | dup; depends on the shaky AppBlur foundation; **cut** |
| Paste-as-block multi-line paste | input-ergonomics | 5.7 | **FATAL** — `Input._on_paste` consumes and `event.stop()`s the Paste event before it can reach an App handler; the proposed mechanism cannot fire |
| Ctrl+R history search (v1/v2) | input-ergonomics | 5.7 | dup pair; embedded-filter-Input-in-modal is a new pattern, M is optimistic; **cut** |
| Hard-stop confirm y/n/"n reason" (v2) | control-and-trust | 5.7 | **FATAL** — removes the exact source string an existing regression test asserts, without saying so; W4 takes the honest variant |
| Ctrl+O expands clipped tool output | control-and-trust | 5.7 | dup → merged into W7 (this one's lean shape wins) |
| Turn-done notification (v2) | polish | 5.7 | dup; **cut** |
| "Since you left" recap (v1/v2) | polish/visibility | 5.7/5.3 | **FATAL** for our platform — DECSET 1004 focus reporting is unreliable on Windows terminals, so the feature can silently never fire here |
| Slash palette modal on `/` | input-ergonomics | 5.3 | dup; `/` keystroke may never reach `on_key` while Input is focused; **cut** |
| Ctrl+O transcript overlay | pickers | 5.3 | **FATAL** — claims Ctrl+O for a different behaviour than W7; keybinding conflict |
| Tool-output cards (v3) | polish | 5.3 | dup → merged into W7 |
| Live-tail `↓N new · End` indicator | visibility | 5.0 | **FATAL** — `end` is already `Input`'s own binding; a non-priority App binding never fires |
| Visible queue stack + ctrl+u unqueue | input-ergonomics | 5.0 | **FATAL** — `ctrl+u` is `Input`'s `delete_left_all`; without `priority=True` the gesture never fires |
| `↓ N new below` pill (v2) | polish | 5.0 | **FATAL** — same `end` collision, plus adds a widget where the twin reused one |
| /theme picker with live preview (v2) | pickers | 4.7 | **FATAL** — previews a theme change that doesn't repaint Textual chrome; the preview shows nothing |

## 3. The winners and why

Nine items, one big move, and they compose. The through-line: **the TUI currently looks hung, loses work on one keystroke, hides its enforced policy, silently denies hard-stops, and throws away truncated evidence.** Five S-effort fixes close all of that. Then two Codex-composer wins (`!`, fold-with-escape-hatch), then the one Claude flagship we can actually build on our own governance primitives (double-Esc rewind over `undo_manager` checkpoints + history snapshots), which also pays for the picker base class the ninth item spends.

**Composition contracts (binding — read before implementing any of them):**

- `_update_status_bar` is **rebuilt once, by Winner 1**, into a `rich.text.Text` assembled from named segments. Winners 3 and 5 append their segment into that same builder in the stated order. Nobody else rewrites it. (Bonus: `Text` also kills the latent markup bug where a cwd containing `[` is parsed as Rich markup by `Static.update(str)`.)
- `_mark_busy()` is **introduced by Winner 1** as the single place `_agent_busy` flips True. Winner 8 hangs its per-turn checkpoint off the same method. No other winner adds a second busy-entry point.
- `_double_tap(name, window)` is **introduced by Winner 2** in `agent/tui.py`. Winner 8 calls it; it does not define its own timer.
- `action_cancel_turn` gains exactly three branches, in this order: **(a) awaiting-confirm → deny (Winner 4)**, **(b) busy → cooperative cancel (unchanged)**, **(c) idle + empty input + double-tap → rewind (Winner 8)**.
- `agent/tui_picker.py::PickerScreen` is **extracted by Winner 8**; Winner 9 subclasses it. If 8 is dropped, 9 must extract it instead.
- Shared pilot harness: **Winner 6** adds `_pilot_tui(agent)` to `tests/test_ui_common.py` — it builds `AgnosticTUI` with `detection={"status": "offline", "base_url": "http://x/v1"}` (so `on_mount` skips `_detect_model_bg`, which would `AttributeError` on `doctor=None`), a `SimpleNamespace` code indexer, and monkeypatches `tui.index_workspace` to a no-op. Winners 7, 8, 9 reuse it and do not write their own.

**What I deliberately cut and when to add it:** `/diff` turn browser (add once Winner 8's `_turn_marks` exists — it is then ~40 lines), `/theme` chrome retheme + high-contrast palette (real bug, low daily frequency — add in the accessibility pass), `/effort` nudge keys, Ctrl+R history search, slash palette, first-run card, notifications. Cut permanently: multi-line paste (framework-blocked), away-recap (platform-blocked on Windows), any `end`/`ctrl+u` binding without `priority=True`.

**Docs note (free, do it with Winner 2):** `docs/slash-commands.md` claims `/theme` opens a picker "when no name is given" — true in the legacy CLI, false in the TUI. Fix the doc line while you are editing the Keys table.


# Winner specs

## 1. Live busy indicator: elapsed clock + per-turn verb + the interrupt key, in one string [S]
Files: C:/Projects/agnostic-ai/agent/ui_common.py, C:/Projects/agnostic-ai/agent/tui.py, C:/Projects/agnostic-ai/agent/tui_commands.py, C:/Projects/agnostic-ai/tests/test_ui_common.py, C:/Projects/agnostic-ai/docs/slash-commands.md

BEHAVIOUR
While a turn or background worker is running, the status bar's busy fragment becomes a live, once-per-second ticking string: `∴ Percolating… 47s · esc to cancel` (dim). Idle, it is empty. The verb is chosen once per turn (not per tick) so it reads as a label, not a slot machine. Users can override the verb pool with the env var AGNOSTIC_SPINNER_VERBS (comma separated).

agent/ui_common.py — add, near stream_tail():
  BUSY_VERBS: tuple[str, ...] = ("Percolating", "Noodling", "Untangling", "Wrangling", "Pondering", "Marinating", "Whirring", "Spelunking", "Rummaging", "Distilling", "Simmering", "Triangulating")
  def busy_verbs(env: Optional[dict] = None) -> tuple[str, ...]:  reads (env or os.environ).get("AGNOSTIC_SPINNER_VERBS"), splits on ',', strips, drops empties; returns BUSY_VERBS when unset or when the override parses to nothing.
  def busy_indicator(elapsed_s: float, verb: str) -> str:
      s = max(0, int(elapsed_s));  clock = f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s"
      return f"∴ {verb}… {clock} · esc to cancel"
  Both pure; no Textual import.

agent/tui.py — __init__: add `self._busy_started: float = 0.0` and `self._busy_verb: str = ""`.

agent/tui.py — NEW method (this is the composition anchor other winners use):
  def _mark_busy(self) -> None:
      """The ONE place _agent_busy flips True."""
      self._agent_busy = True
      self._busy_started = time.monotonic()
      self._busy_verb = random.choice(busy_verbs())
      self._update_status_bar()
  Replace the three existing busy-entry points with a call to it:
    - _process_input's final block: `self._agent_busy = True; self._update_status_bar(); self._run_agent_turn(user_input)` -> `self._mark_busy(); self._run_agent_turn(user_input)`
    - _dispatch_background: same two lines -> `self._mark_busy()` then `self._run_background(fn)`
    - agent/tui_commands.py `/plan` branch: `self._agent_busy = True; self._update_status_bar()` -> `self._mark_busy()`. (The AST dispatch test only inspects identifier names in the branch body; `_run_agent_turn` stays, so it remains green.)
  Add `import random` to tui.py.

agent/tui.py — on_mount: after the existing `self.set_interval(3.0, self._update_status_bar)` add `self.set_interval(1.0, self._tick_busy)`.
  def _tick_busy(self) -> None:
      if self._agent_busy:
          self._update_status_bar()

agent/tui.py — _update_status_bar REBUILD (this winner owns the final shape; Winners 3 and 5 append into it):
  Replace the f-string + `Static.update(str)` with a rich.text.Text builder:
      line = Text(" ", style="dim")
      line.append(f"📁 {display_cwd}{git_str}")
      line.append(f"  │  🤖 {disp_model} ({curr_effort})")
      # <-- Winner 3 appends the trust segment here
      # <-- Winner 5 appends the context segment here (replacing today's 📊 fragment)
      if queue_count: line.append(f"  │  📬 {queue_count} queued", style="yellow")
      if self._agent_busy:
          line.append("  " + busy_indicator(time.monotonic() - self._busy_started, self._busy_verb), style="dim")
      self.query_one("#status-bar", Static).update(line)
  Keep the existing try/except (NoMatches, KeyError, AttributeError) wrapper exactly as-is.

EDGE CASES
- _busy_started == 0.0 while idle: the busy fragment is never rendered when _agent_busy is False, so no 55-year clock.
- A queue drain calls _process_input again, which calls _mark_busy again -> the clock restarts per turn. Correct.
- Do not make busy_indicator depend on wall clock (time.time); time.monotonic only.
- The 1s interval must not shell out: _refresh_git_status keeps its own 3s worker interval, untouched.

LOOK: dim, right-most segment of the status bar, so it never outranks the model/context segments. Single glyph `∴` for brand recognition.

DOCS: update the docs/slash-commands.md Keys table `Esc` row to mention the status bar now names it.

Acceptance: python -m pytest tests/test_ui_common.py -k "busy_indicator or mark_busy" -q > check.log 2>&1 — new pure tests: busy_indicator(0,'X') and busy_indicator(47,'X') both end with 'esc to cancel'; '47s' appears for 47 and '1m05s' for 65; the same (elapsed, verb) returns an identical string twice (idempotent re-render); busy_verbs({'AGNOSTIC_SPINNER_VERBS':'a, b'}) == ('a','b') and busy_verbs({'AGNOSTIC_SPINNER_VERBS':' , '}) == BUSY_VERBS. Plus a source assertion that inspect.getsource(tui) contains no remaining '_agent_busy = True' outside _mark_busy, and inspect.getsource(tui_commands) contains none at all.

## 2. Ctrl+C escalates (cancel → force-exit) and Ctrl+L asks twice — one double-tap helper [S]
Files: C:/Projects/agnostic-ai/agent/tui.py, C:/Projects/agnostic-ai/tests/test_ui_common.py, C:/Projects/agnostic-ai/docs/slash-commands.md

BEHAVIOUR
One timing helper serves every destructive key. Ctrl+C while busy stops being a scold and becomes the escalation users already have muscle memory for; Ctrl+L stops nuking the log on a slipped keystroke.

agent/tui.py — __init__: `self._taps: dict[str, float] = {}`.

agent/tui.py — NEW helper (owned here; Winner 8 calls it, does not redefine it):
  def _double_tap(self, name: str, window: float = 1.5) -> bool:
      """True only on the second press of `name` within `window` seconds."""
      now = time.monotonic()
      first = now - self._taps.get(name, 0.0) > window
      self._taps[name] = 0.0 if not first else now   # a consumed double-tap resets the timer
      return not first

agent/tui.py — action_quit_safe REWRITE:
  def action_quit_safe(self) -> None:
      if self._agent_busy:
          # A worker thread cannot be interrupted mid-run: the flag is left alone so a
          # second overlapping turn can never start on the same agent.history.
          if self._double_tap("quit", 1.5):
              self.exit()
              return
          self.agent.cancel_event.set()
          self._write_output(Text("⏹ cancelling after the current step — press Ctrl+C again to force-exit.", style="yellow"))
          return
      if self._double_tap("quit", 1.5):
          self.exit()
          return
      self._write_output(Text("Press Ctrl+C again to exit.", style="dim yellow"))
  HARD CONSTRAINT: the literal string `_agent_busy = False` must not appear anywhere in this function — tests/test_ui_common.py::test_ctrl_c_does_not_clear_busy_flag_mid_turn asserts on the source text.

agent/tui.py — action_clear_output REWRITE:
  first press -> `self._write_output(Text("Press Ctrl+L again to clear the log.", style="dim yellow"))` and return; second press within 2.0s -> existing `log.clear(); self._print_banner()`.

agent/tui.py — BINDINGS: change the ctrl+c row's description from "Exit" to "Cancel/Exit" and the ctrl+l row's to "Clear ×2". Leave the key strings alone.

EDGE CASES
- Esc's meaning is unchanged by this winner (Winner 4 and 8 own the Esc branches). Ctrl+C-while-busy now duplicates Esc's cancel deliberately: it is the reflex key, and the second press is the escalation.
- Two different names ('quit', 'clear') keep independent timers, so Ctrl+C then Ctrl+L never counts as a double-tap.
- `self.exit()` inside a pilot test ends the app; write the acceptance check as a unit/source test (below), not a pilot, to avoid a torn-down-app race.

DOCS: docs/slash-commands.md Keys table — rewrite the `Ctrl+C` row ("Cancel the running turn; press again within 1.5s to force-exit. Idle: press twice to quit.") and the `Ctrl+L` row ("Clear the output log — press twice."). While in that file, fix the `/theme` row, which wrongly claims the TUI opens a picker with no argument.

Acceptance: python -m pytest tests/test_ui_common.py -k "double_tap or ctrl_c" -q > check.log 2>&1 — new test builds the existing `_make_tui(SimpleNamespace(confirm_callback=None, output_callback=None, cancel_event=threading.Event()))` object, asserts `app._double_tap('quit') is False` then `app._double_tap('quit') is True` then `app._double_tap('quit') is False` (a consumed tap resets), and that `app._double_tap('x', window=0.0)` is always False; plus source assertions that action_quit_safe contains 'cancel_event.set()' and '_double_tap' and does NOT contain '_agent_busy = False', and that action_clear_output contains '_double_tap'. The pre-existing test_ctrl_c_does_not_clear_busy_flag_mid_turn must still pass unchanged.

## 3. Shift+Tab cycles the trust tier, and the status bar reads it live from the guard [S]
Files: C:/Projects/agnostic-ai/agent/tui.py, C:/Projects/agnostic-ai/tests/test_ui_common.py, C:/Projects/agnostic-ai/docs/slash-commands.md

BEHAVIOUR
One keystroke dials autonomy up or down mid-task; the enforced tier is permanently on screen and is re-read from SafetyGuard on every repaint, so the badge can never drift from the policy check_command_safety actually applies (the Codex #33702 failure class).

agent/tui.py — BINDINGS: add
  Binding("shift+tab", "cycle_trust", "Trust", show=True, priority=True)
  priority=True is mandatory and for the same documented reason the existing `tab` binding needs it: Screen binds shift+tab to focus_previous with no priority, so a plain App binding loses while #prompt-input has focus. Put the same one-line comment above it.

agent/tui.py — module constant next to the class:
  TRUST_TIERS = ("strict", "trust-reads", "trust-tests", "trust-all")
  (These are exactly the four values SafetyGuard.set_trust_tier normalises to; set_trust_tier accepts them verbatim — see agent/governance/guard.py:79-91.)

agent/tui.py — new action:
  def action_cycle_trust(self) -> None:
      from agent.governance.guard import guard
      nxt = TRUST_TIERS[(TRUST_TIERS.index(guard.get_trust_tier()) + 1) % len(TRUST_TIERS)] if guard.get_trust_tier() in TRUST_TIERS else TRUST_TIERS[0]
      self._write_output(Text(f"🛡️ {guard.set_trust_tier(nxt)}", style="bold yellow" if nxt == "trust-all" else "bold green"))
      self._update_status_bar()

agent/tui.py — _update_status_bar (the Text builder Winner 1 created): append the trust segment immediately after the model segment and before the context segment:
      tier = guard.get_trust_tier()                      # read LIVE every repaint, never cached
      line.append("  │  ")
      line.append(f"🛡 {tier}", style={"strict": "dim", "trust-reads": "dim", "trust-tests": "yellow", "trust-all": "bold red"}.get(tier, "dim"))
  Import `guard` at module top in tui.py (tui_commands.py already imports it; a second import of the same singleton is fine).

EDGE CASES
- Never store the tier on the app. If a /trust command, a subagent, or anything else changes it, the next 3s repaint shows the truth.
- guard.get_trust_tier() returning an unexpected value (a future tier) must not raise: the `if ... in TRUST_TIERS else TRUST_TIERS[0]` guard handles it, and the style dict uses .get with a 'dim' default.
- trust-all is bold red on purpose: 'the agent can now run hard-stop commands without a human' must be impossible to miss.
- Does not touch /trust or /untrust in tui_commands.py — both keep working and are now visible in the bar for free.

COMPOSITION: appends into the Text builder Winner 1 owns; adds no interval and no state.

DOCS: add a `Shift+Tab` row to the docs/slash-commands.md Keys table.

Acceptance: python -m pytest tests/test_ui_common.py -k trust_cycle -q > check.log 2>&1 — new test: from agent.governance.guard import guard; guard.set_trust_tier('strict'); build the unmounted app via _make_tui(...) and call app.action_cycle_trust() twice, asserting guard.get_trust_tier() == 'trust-reads' then 'trust-tests' (documented order, no wrap surprises), then set it to 'trust-all' and call once more asserting it wraps to 'strict'. Plus a source assertion that inspect.getsource(tui.AgnosticTUI._update_status_bar) contains 'get_trust_tier()' and does NOT assign it to an instance attribute (no 'self._trust' in the module).

## 4. Typing ahead during a hard-stop confirm queues the prompt instead of silently denying it; `n <reason>` becomes the next instruction [S]
Files: C:/Projects/agnostic-ai/agent/ui_common.py, C:/Projects/agnostic-ai/agent/tui.py, C:/Projects/agnostic-ai/tests/test_ui_common.py

BEHAVIOUR
Today any non-y/n submission while a governance hard-stop is pending sets _confirm_response=False and releases the blocked worker — i.e. a mistimed keystroke revokes a safety decision with no warning. After this change: unrecognised text is treated as a *prompt*, queued, and the confirm stays pending. `n: too risky, patch the test instead` denies AND feeds the reason into the next turn. Esc while a confirm is pending is the explicit deny path, so the worker can never block forever.

agent/ui_common.py — parse_confirm_answer signature change (it has exactly one caller, agent/tui.py:544 — verified by grep; cli.py does not use it):
  def parse_confirm_answer(answer: str) -> Tuple[bool, bool, str]:
      """(approved, unrecognized, reason). 'y'/'yes' -> (True, False, ''). 'n'/'no' -> (False, False, '').
      'y <text>' / 'n: <text>' -> the verdict plus the text as reason. Anything else -> (False, True, '')
      and the CALLER MUST NOT treat that as an answer."""
  Parsing: strip, lower the first token; split on the first whitespace or ':' after that token; accept leading 'y'/'yes'/'n'/'no' only.

agent/tui.py — __init__: `self._confirm_reason: str = ""`.

agent/tui.py — on_input_submitted, the `if self._awaiting_confirm:` branch REWRITE:
      approved, unrecognized, reason = parse_confirm_answer(user_input)
      if unrecognized:
          # NOT an answer: queue it as a prompt. The confirm stays pending and the
          # worker stays blocked — a typo must never revoke a safety decision.
          self._prompt_queue.append(user_input)
          self._update_queue_indicator()
          self._write_output(Text("📬 Queued — still waiting on approve? [y/n] (or 'n <reason>')", style="yellow"))
          return
      self._confirm_reason = reason
      self._confirm_response = approved
      self._confirm_event.set()
      self._write_output(Text(f"→ {'Approved' if approved else 'Denied'}{(': ' + reason) if reason else ''}", style="bold green" if approved else "bold yellow"))
      return

agent/tui.py — action_cancel_turn, NEW FIRST BRANCH (before the busy check):
      if self._awaiting_confirm:
          self._confirm_response = False
          self._confirm_reason = ""
          self._confirm_event.set()
          self._write_output(Text("→ Denied (Esc)", style="bold yellow"))
          return

agent/tui.py — _process_input: right after the exit check, if self._confirm_reason is set and the input is not a slash command, prepend it once and clear it:
      if self._confirm_reason and not user_input.startswith("/"):
          user_input = f"### [Operator note on the last approval]: {self._confirm_reason}\n\n{user_input}"
          self._confirm_reason = ""
  (The reason must be consumed exactly once — clear it in the same statement block.)

EXISTING TESTS THAT MUST BE UPDATED (do not skip this — it is why the rival version of this idea was disqualified):
  - tests/test_ui_common.py::test_parse_confirm_answer_denies_but_flags_an_unrecognized_answer — update every assert to the 3-tuple, and add `parse_confirm_answer('n: too risky') == (False, False, 'too risky')`.
  - tests/test_ui_common.py::test_unrecognized_confirm_answer_is_echoed_back_into_the_input — the old contract (`event.input.value = user_input`) is intentionally gone. Rename it to test_unrecognized_confirm_answer_is_queued_not_denied and assert the source of on_input_submitted contains 'self._prompt_queue.append(user_input)' and no longer contains 'self._confirm_event.set()' inside the `unrecognized` path.

EDGE CASES
- Default stays deny: nothing here can auto-approve. An unrecognised answer approves nothing and releases nothing.
- The queued prompt drains through the existing _process_queue once the worker finishes, so the user's typing is never lost.
- Queue growth during a long-pending confirm is bounded only by the user; that is the same as today's normal queue. Fine.

COMPOSITION: owns branch (a) of action_cancel_turn. Winner 8 adds branch (c) after the existing busy branch (b); neither touches the other's branch.

Acceptance: python -m pytest tests/test_ui_common.py -k confirm -q > check.log 2>&1 — must cover: parse_confirm_answer('y')==(True,False,''), ('n: too risky')==(False,False,'too risky'), ('now fix the parser')==(False,True,''); and on a _make_tui app with app._awaiting_confirm=True, app._confirm_event.clear(), calling app.on_input_submitted with a stub event carrying value='now fix the parser' leaves app._confirm_event.is_set() False, app._confirm_response False, and list(app._prompt_queue)==['now fix the parser']. The pre-existing test_tui_confirm_callback_blocks_until_answered must still pass unchanged.

## 5. Context gauge (bar + exact % + colour), a one-shot compact nudge, and a /compact you can read and undo [M]
Files: C:/Projects/agnostic-ai/agent/ui_common.py, C:/Projects/agnostic-ai/agent/tui.py, C:/Projects/agnostic-ai/agent/tui_commands.py, C:/Projects/agnostic-ai/tests/test_ui_common.py, C:/Projects/agnostic-ai/docs/slash-commands.md

BEHAVIOUR
Three connected fixes to the least visible, most session-ending subsystem: you see context filling, you get told once before the cliff with the exact remediation, and a manual compaction shows what it kept and can be reversed.

A) THE GAUGE — agent/ui_common.py, new pure function:
  def context_segment(st: dict, width: int = 10) -> Tuple[str, str]:
      """(text, rich_style) for the status bar. Fixed width so the bar never jitters.
      Thresholds match ContextManager.render_gauge: green <60, yellow <80, red above."""
      pct = float(st["percentage"]) ;  filled = min(width, int(pct / 100 * width))
      bar = "█" * filled + "░" * (width - filled)
      style = "green" if pct < 60 else "yellow" if pct < 80 else "red"
      return f"CTX {bar} {pct:.0f}% ({_short(st['used_tokens'])}/{_short(st['max_tokens'])})", style
  Add a tiny module-private `_short(n)` -> '620k' / '2.0M' / '843'.
  Note the deliberate duplication call: ContextManager.render_gauge exists but returns a 16-block Rich *markup* string keyed to a messages list — unusable in a Text-based status bar. Keep render_gauge untouched; context_segment takes the already-computed status dict, so no second estimate pass.

  agent/tui.py — _update_status_bar (Winner 1's Text builder): replace today's `📊 {used:,}/{total:,} tok ({pct:.1f}%)` fragment with
      seg, seg_style = context_segment(st)
      line.append("  │  "); line.append(seg, style=seg_style)

B) THE ONE-SHOT NUDGE — agent/tui.py __init__: `self._ctx_warned = False`. In _update_status_bar, after appending the segment:
      if st["near_limit"] and not self._ctx_warned:
          self._ctx_warned = True
          self._write_output(Text(
              f"Context at {st['percentage']:.0f}% of {st['max_tokens']:,} tok. Auto-compaction fires at "
              f"{context_manager.compaction_threshold * 100:.0f}% (ContextManager default) and rewrites older turns. "
              f"Run /compact now to do it deliberately — /compact undo reverses it.", style="yellow"))
  Reset `self._ctx_warned = False` in exactly two places: the /compact branch after a successful compaction, and in _output_callback's `system` branch when `content.startswith("🧹 Compacted")` (that is the literal prefix agent/loop.py:270-271 emits for an auto-compaction — see ContextManager.compact_messages' return message).

C) READABLE + UNDOABLE /compact — agent/tui_commands.py, change `elif user_input == "/compact":` to `elif cmd == "compact":` and:
      if args.strip().lower() == "undo":
          prev = getattr(self, "_pre_compact_history", None)
          if prev is None:
              self._write_output(Text("Nothing to undo — no /compact has run this session.", style="yellow"))
          else:
              self.agent.history = list(prev)
              self._pre_compact_history = None
              self._write_output(Text(f"⏪ Restored {len(self.agent.history)} pre-compaction messages.", style="bold green"))
          return True
      self._pre_compact_history = list(self.agent.history)
      self.agent.history, ok, msg = context_manager.compact_messages(self.agent.history, force=True)
      self._write_output(Text(msg, style="bold green" if ok else "yellow"))
      if ok:
          self._ctx_warned = False
          block = self.agent.history[0]["content"].partition("### [Session Distillation")
          if block[1]:
              self._write_output(Panel(safe_text(block[1] + block[2]), title="🧹 What compaction kept", border_style="green", box=box.ROUNDED, padding=(0, 1)))
      return True
  (`box` is already imported in tui_commands? It is not — add `from rich import box`, or drop the box kwarg and use the default.)
  Declare `self._pre_compact_history = None` in AgnosticTUI.__init__ so the attribute always exists.

EDGE CASES
- The AST dispatch test walks branch string constants: `cmd == "compact"` keeps the constant "compact" in the branch test, and the body still touches no expensive names, so the test stays green.
- /compact undo after an *auto*-compaction restores the last MANUAL pre-compact state, not the auto one — the message says 'pre-compaction messages' and the auto path never sets the stash, so it correctly reports 'nothing to undo' if no manual compact ran. Do not try to stash inside the worker; agent/loop.py:270 reassigns self.history on a worker thread.
- st['max_tokens'] defaults to 2,000,000, so real percentages are tiny; the bar must still render 0 filled blocks cleanly (int() floor handles it).
- context_segment must never divide by zero: get_status already clamps to <=100 and max_tokens has a 1024 floor.

DOCS: extend the `/compact` row in docs/slash-commands.md with `undo`. The doc-sync test only compares `/token` sets, and `/compact` is already listed, so no SLASH_COMMANDS change is needed — but update the SLASH_COMMANDS hint string for /compact to mention `undo`.

Acceptance: python -m pytest tests/test_ui_common.py -k "context_segment or compact_undo" -q > check.log 2>&1 — pure test: context_segment({'percentage':31.0,'used_tokens':620000,'max_tokens':2000000}) returns a text containing '31%' and '620k/2.0M' with style 'green'; the 70% case is 'yellow' and the 95% case 'red'; the rendered text has identical length at 5%, 70% and 95% (no status-bar jitter). Plus a FakeTUI-style test (same shape as test_tui_confirm_callback_blocks_until_answered) with a 10-message history: call the /compact branch, assert len(history) shrank and 'Session Distillation' appears in the written output, then call '/compact undo' and assert app.agent.history equals the original list.

## 6. `!` prefix runs a shell command through the run_command tool without spending a turn [M]
Files: C:/Projects/agnostic-ai/agent/tui.py, C:/Projects/agnostic-ai/tests/test_ui_common.py, C:/Projects/agnostic-ai/docs/slash-commands.md

BEHAVIOUR
A line starting with `!` is a local shell escape: `!git status`, `!ls tests`. It runs through the agent's existing run_command tool (so core/safety/guards.json stays the single policy source and `!rm -rf /` still hits the same hard-stop confirm), streams its output through the existing tool_chunk/tool_end rendering, and appends NOTHING to agent.history — a sanity check costs zero context and zero LLM calls.

agent/tui.py — _process_input, insert immediately after the `/exit` check and BEFORE the user-panel render:
      if user_input.startswith("!") and user_input[1:].strip():
          cmd = user_input[1:].strip()
          self._write_output(Text(f"$ {cmd}", style="dim cyan"))
          self._dispatch_background(lambda: self._run_bang(cmd))
          return

agent/tui.py — new method:
  def _run_bang(self, cmd: str):
      """Local shell escape. Deliberately routed through the registry's run_command so
      SafetyGuard.check_command_safety and the hard-stop confirm apply exactly as they do
      to a model-issued call — never subprocess directly from the UI layer."""
      res = self.agent.registry.execute("run_command", {"command": cmd}, confirm_callback=self.agent.confirm_callback)
      return None if not res.is_error else Panel(safe_text(res.output, style="bold red"), title="[bold red]❌ Command failed[/bold red]", title_align="left", border_style="red", box=box.ROUNDED, padding=(0, 1))
  Verified against the code: AgentLoop exposes `self.registry` (agent/loop.py:48); ToolRegistry.execute(name, args, confirm_callback=...) is real (registry.py:140); _tool_run_command reads args['command'], calls guard.check_command_safety first, and its Popen reader already emits tool_chunk/tool_end through the agent's output_callback — which AgnosticTUI wired once in __init__ — so the live block and the Tool Output panel render for free with no extra code.

EDGE CASES
- A bare `!` (or `!` + whitespace) falls through to the normal path and is sent to the model. That is deliberate: no silent no-op.
- Because it goes through _dispatch_background, _agent_busy is set and Winner 1's clock ticks; a `!` typed while busy is queued by the existing on_input_submitted queue path and drains through _process_queue, hitting the same branch later. Correct.
- Cancellation: run_command's poll loop already honours agent.cancel_event, so Esc kills a long `!npm test` child.
- The AST structural test only parses tui_commands.py's if/elif chain; this branch lives in tui.py's _process_input, so it is out of scope — but it still uses _dispatch_background, matching the repo's own rule.
- Do NOT add `!` to SLASH_COMMANDS: tests/test_ui_common.py::test_documented_commands_and_the_table_are_the_same_set compares the table against `/[a-z][a-z-]*` tokens in the docs and would fail on a non-slash key.

DISCOVERABILITY: append `· !cmd runs a shell command locally` to the banner's yellow Commands line in _print_banner, and add a `!command` row to the Keys table in docs/slash-commands.md (backticked non-slash tokens are ignored by the doc-sync regex).

TEST HARNESS (this winner owns it; Winners 7/8/9 reuse it): add to tests/test_ui_common.py
  def _pilot_tui(agent, monkeypatch):
      monkeypatch.setattr(tui, "index_workspace", lambda: None)
      return tui.AgnosticTUI(agent=agent, code_indexer_inst=SimpleNamespace(get_all_symbols=list, get_indexed_files=list), detected_model="test-model", doctor=None, test_runner=None, detection={"status": "offline", "base_url": "http://x/v1"})
  Passing a non-empty `detection` is what stops on_mount from launching _detect_model_bg, which would AttributeError on doctor=None inside a worker thread.

Acceptance: python -m pytest tests/test_ui_common.py -k bang_prefix -q > check.log 2>&1 — pilot test using _pilot_tui with a SimpleNamespace agent whose .registry.execute records its call and returns SimpleNamespace(output='hello-from-bang', is_error=False), .run_turn appends to a list, .history=[], .cancel_event=threading.Event(): async with app.run_test() as pilot, type '!echo hi' into #prompt-input and press enter, poll `await pilot.pause()` in a bounded loop until app._agent_busy is False, then assert registry.execute was called once with ('run_command', {'command': 'echo hi'}), that agent.run_turn was never called, and that agent.history == [].

## 7. Tool cards show duration and how much was hidden; Ctrl+O prints the full output [M]
Files: C:/Projects/agnostic-ai/agent/ui_common.py, C:/Projects/agnostic-ai/agent/tui.py, C:/Projects/agnostic-ai/tests/test_ui_common.py, C:/Projects/agnostic-ai/docs/slash-commands.md

BEHAVIOUR
Tool output is still folded to keep the transcript scannable, but the fold now says how much it hid and one key gets it back — the escape hatch ships in the same commit as the fold (the multi-year Codex #4550/#5095/#5163 lesson). The collapsed line also carries the elapsed time, so a long build visibly progressed.

agent/ui_common.py — new pure function:
  def fold_summary(text: str, limit: int = 600) -> Tuple[str, int]:
      """(clipped, hidden_line_count). Clips at the last newline at or before `limit`
      so a card never ends mid-line; returns (text, 0) when nothing is hidden."""
      if len(text) <= limit: return text, 0
      cut = text.rfind("\n", 0, limit)
      cut = limit if cut <= 0 else cut
      return text[:cut], text[cut:].count("\n") + 1

agent/tui.py — __init__: `self._tool_outputs: deque[tuple[str, float, str]] = deque(maxlen=10)`, `self._tool_name = ""`, `self._tool_t0 = 0.0`.

agent/tui.py — _output_callback:
  - `tool_start` branch: before the existing label write, `self._tool_name, self._tool_t0 = content, time.monotonic()`.
  - `tool_end` branch: replace the `clipped = content[:600] + (...)` line with
        secs = max(0.0, time.monotonic() - self._tool_t0)
        self._tool_outputs.append((self._tool_name or "tool", secs, content))
        clipped, hidden = fold_summary(content)
        title = f"⚙️ {self._tool_name or 'Tool Output'} · {secs:.1f}s" + (f" · +{hidden} lines hidden — ctrl+o" if hidden else "")
    and pass `title=title` (plain string, NOT markup — the tool name is untrusted) plus `title_align="left"`, keeping the existing Panel(safe_text(clipped), ...) shape and `border_style="dim blue"`.

agent/tui.py — BINDINGS: add `Binding("ctrl+o", "expand_output", "Full output", show=True)`. ctrl+o is unbound in App, Screen and Input (verified), so no priority flag is needed.

agent/tui.py — new action:
  def action_expand_output(self) -> None:
      if not self._tool_outputs:
          self._write_output(Text("No tool output captured yet.", style="dim"))
          return
      name, secs, full = self._tool_outputs[-1]
      self._write_output(Text(f"── full output: {name} ({secs:.1f}s, {len(full)} chars) ──", style="dim blue"))
      self._write_output(safe_text(full))

EDGE CASES
- Titles must not go through Rich markup: a tool name or path containing '[' would raise MarkupError. Use a plain str title (Rich renders panel titles as markup only when given a markup string — pass a plain str and keep no bracket-tag syntax in it).
- The RichLog is capped at max_lines=5000; a 200k-char expand is written as one safe_text renderable and will scroll. Acceptable — the user asked for it. No extra truncation.
- tool_start/tool_end are not strictly paired for every tool; _tool_t0 defaulting to 0.0 would give a huge duration, so clamp: if self._tool_t0 == 0.0, render the title without the duration segment.
- The deque(maxlen=10) bounds memory; `deque` is already imported in tui.py.

COMPOSITION: touches only the tool_start/tool_end branches of _output_callback. Winner 5 touches the `system` branch of the same method; they do not overlap.

DOCS: add a `Ctrl+O` row to the Keys table.

Acceptance: python -m pytest tests/test_ui_common.py -k "fold_summary or expand_output" -q > check.log 2>&1 — pure test: fold_summary('x'*100) == ('x'*100, 0); fold_summary(('line\n'*100), limit=20) clips on a newline boundary (result[0].endswith('line')) and reports the right hidden count; and a pilot test via _pilot_tui that calls app._output_callback('tool_start','run_command') then app._output_callback('tool_end','X'*2000+'TAIL-MARKER'), awaits pilot.pause(), asserts 'TAIL-MARKER' is absent from the captured log writes, presses ctrl+o, and asserts it is then present.

## 8. Double-Esc rewind: pick a turn, then restore files / conversation / both (plus the shared PickerScreen base) [L]
Files: C:/Projects/agnostic-ai/agent/tui_picker.py, C:/Projects/agnostic-ai/agent/tui_model_picker.py, C:/Projects/agnostic-ai/agent/tui_rewind.py, C:/Projects/agnostic-ai/agent/tui.py, C:/Projects/agnostic-ai/tests/test_ui_common.py, C:/Projects/agnostic-ai/docs/slash-commands.md

BEHAVIOUR
Every turn is silently checkpointed. Esc while idle with an empty input, pressed twice within 800 ms, opens a two-step modal: which turn to rewind to, then whether to restore the files, the conversation, or both. Esc while busy keeps today's cooperative cancel; Esc during a confirm keeps Winner 4's deny. This is the one feature in the research users name as recovery-from-mistakes, and it is buildable here because undo_manager already owns the file half and agent.history is the conversation half — they have simply never been reachable as one gesture.

STEP 0 — agent/tui_picker.py (NEW): lift the generic half of ModelPickerScreen verbatim.
  class PickerScreen(ModalScreen):
      FOOTER_KEYS = "↑/↓ move · Space/Enter select · Esc back"
      DEFAULT_CSS = <the existing #picker-box/#picker-title/#picker-list/#picker-hint block, with the selector renamed from ModelPickerScreen to PickerScreen>
      BINDINGS = [Binding("escape", "back", "Back", show=False), Binding("space", "pick", "Select", show=False)]
      compose() -> the same Vertical(#picker-box) with Static(FOOTER_KEYS, id="picker-hint")
      _steps / _push / _fill / action_pick / action_back — moved unchanged from ModelPickerScreen.
  agent/tui_model_picker.py then becomes `class ModelPickerScreen(PickerScreen)` keeping only __init__, on_mount, _show_presets, _show_sub_models, _show_effort, on_option_list_option_selected, _advance, and its own FOOTER_KEYS if it differs. tests/test_ui_common.py::test_model_picker_walks_preset_sub_model_and_effort_with_the_keyboard must pass UNCHANGED — that is the regression proof for the refactor. Do not touch its assertions.

STEP 1 — turn marks. agent/tui.py __init__: `self._turn_marks: deque[tuple[str, str, list]] = deque(maxlen=20)`.
  In Winner 1's `_mark_busy()`, before setting the flag:
      n = len(self._turn_marks) + 1
      name = f"turn-{n}"
      undo_manager.create_checkpoint(name)          # file side: snapshots len(history) at this instant
      self._turn_marks.append((name, time.strftime("%H:%M:%S"), list(self.agent.history)))
  Import undo_manager in tui.py. create_checkpoint is O(len(history)) list copy of FileSnapshot refs — cheap.

STEP 2 — agent/tui_rewind.py (NEW):
  class RewindScreen(PickerScreen):
      FOOTER_KEYS = "↑/↓ move · Space/Enter select · Esc back/cancel"
      def __init__(self, marks: list[tuple[str, str, list]]): stores marks; self._mark = None
      _show_turns(): one Option per mark, newest first, id=the checkpoint name, label = Text(f"{name}", 'bold') + Text(f"  {clock} · {len(history)} messages", 'dim'). Title 'Rewind to which turn?'
      _show_scope(): three Options with ids 'files' / 'conversation' / 'both' and dim blurbs
        ('revert file writes made since this turn', 'restore the conversation as it was', 'both').
      on_option_list_option_selected: on step _show_turns store the mark and self._push(self._show_scope);
        on _show_scope -> self.dismiss((mark_name, stored_history, choice)).
      Empty marks list: _show_turns renders one disabled-looking row 'no turns yet' whose selection dismisses(None).

STEP 3 — agent/tui.py action_cancel_turn, THIRD branch (after Winner 4's confirm branch and the existing busy branch):
      inp = self.query_one("#prompt-input", Input)
      if inp.value.strip() or not self._double_tap("rewind", 0.8):
          return
      self.push_screen(RewindScreen(list(self._turn_marks)), callback=self._apply_rewind)
  (Uses Winner 2's _double_tap — do not add a second timer.)

  def _apply_rewind(self, pick) -> None:
      if not pick: return
      name, history, scope = pick
      if scope in ("files", "both"):
          ok, msg = undo_manager.rollback_to_checkpoint(name)
          self._write_output(Text(f"⏪ {msg}", style="bold green" if ok else "bold yellow"))
      if scope in ("conversation", "both"):
          self.agent.history = list(history)
          self._write_output(Text(f"⏪ Conversation restored to {name} ({len(history)} messages).", style="bold green"))
      self._update_status_bar()

EDGE CASES
- Rewinding while busy is impossible by construction (branch (b) returns first) — no restore can race a worker writing to agent.history.
- rollback_to_checkpoint already no-ops safely when the history is already at or before the checkpoint; surface its message verbatim.
- A conversation restore must copy the list (`list(history)`), never alias the stored snapshot, or the next turn mutates the mark.
- deque(maxlen=20) means old checkpoints linger in undo_manager.checkpoints after their mark is evicted; that is harmless (a dict of name -> list of refs) and out of scope.
- Esc inside the modal is PickerScreen's own back/cancel; the app-level double-tap timer is not consulted while a screen is pushed.

COMPOSITION: consumes Winner 1's `_mark_busy` and Winner 2's `_double_tap`; adds branch (c) of action_cancel_turn only. If Winners 1 or 2 are dropped, this item must inline their two helpers first.

DOCS: Keys table row for `Esc Esc`; a `/checkpoint` cross-reference line noting the automatic per-turn checkpoints.

Acceptance: python -m pytest tests/test_ui_common.py -k "model_picker or rewind" -q > check.log 2>&1 — the pre-existing test_model_picker_walks_preset_sub_model_and_effort_with_the_keyboard must pass unchanged (refactor proof), plus a new headless test in its exact shape: a Host(App) pushes RewindScreen([('turn-1','10:00:00',[{'role':'user','content':'a'}]), ('turn-2','10:01:00',[{'role':'user','content':'b'}])]) with callback=results.append; asyncio.run(drive(['enter','down','enter'])) asserts results == [('turn-2', [...], 'conversation')] (newest-first ordering, scope step reached); drive(['escape']) asserts results == [None]; and a tmp_path test that records a file change through undo_manager, checkpoints it, then calls app._apply_rewind((name, hist, 'files')) and asserts the file content reverted while len(app.agent.history) is unchanged.

## 9. Bare `/session` opens a resume picker instead of printing a flat list [M]
Files: C:/Projects/agnostic-ai/agent/tui_sessions.py, C:/Projects/agnostic-ai/agent/tui_commands.py, C:/Projects/agnostic-ai/agent/ui_common.py, C:/Projects/agnostic-ai/tests/test_ui_common.py, C:/Projects/agnostic-ai/docs/slash-commands.md

BEHAVIOUR
`/session` with no arguments opens an arrow-key picker of saved sessions (newest first, which is the order session_manager.list_sessions already returns) and loads the chosen one through the existing load path. `/session save|load|list <name>` keeps working verbatim. Because .agnostic/sessions is workspace-local, the picker is cwd-scoped for free — Codex's `resume` default without the flag.

agent/tui_sessions.py (NEW):
  class SessionPickerScreen(PickerScreen):     # from agent.tui_picker, extracted by Winner 8
      FOOTER_KEYS = "↑/↓ move · Space/Enter load · Esc cancel"
      def __init__(self, sessions: list[dict]): stores them.
      on_mount -> self._push(self._show_sessions)
      _show_sessions(): title 'Resume a session'; one Option per entry, id=s['name'],
        label = Text(s['name'], style='bold') + Text(f"  {s['turn_count']} turns · {s['saved_at']}", style='dim')
        + Text(f"  {s['notes'][:40]}", style='dim') when notes is non-empty.
        Empty list -> a single 'no saved sessions' row that dismisses(None) on select.
      on_option_list_option_selected -> self.dismiss(event.option.id)
  (Fields verified against agent/governance/session_manager.py::list_sessions, which returns name / saved_at / turn_count / notes.)

agent/tui_commands.py — the `elif cmd == "session":` branch: insert at the top, before `parts = args.split()`:
      if not args.strip():
          from agent.tui_sessions import SessionPickerScreen
          self.push_screen(SessionPickerScreen(session_manager.list_sessions()), callback=self._load_session_pick)
          return True
  and add the callback next to _apply_model_pick in the same mixin:
      def _load_session_pick(self, name) -> None:
          if not name: return
          hist, msg = session_manager.load_session(name)
          if hist:
              self.agent.history = hist
              self._write_output(Text(f"📂 {msg}", style="bold green"))
          else:
              self._write_output(Text(f"❌ {msg}", style="bold red"))
          self._update_status_bar()
  The existing subcmd chain below is untouched, so `/session list` still prints the flat list on purpose (scriptable/greppable).

EDGE CASES
- Do not load a session while a turn is running: guard the picker push with `if self._agent_busy: self._write_output(Text('Finish or cancel the current turn first.', style='yellow')); return True`. Replacing agent.history under a live worker is the same hazard Winner 8 avoids.
- list_sessions() reads and caches JSON off a small directory; it already swallows corrupt files. It runs on the UI thread — acceptable (cached by mtime, no network, no subprocess), and the AST dispatch test does not flag it since none of its names are in EXPENSIVE_WORK.
- Deliberately skipped: the first-user-message preview per row (it would require opening every session file). Add it if the picker feels thin — read it lazily in an on_option_list_option_highlighted handler, not in _show_sessions.
- Depends on agent/tui_picker.py existing. If Winner 8 is dropped, this item extracts PickerScreen itself, under the same rule that the model-picker test must pass unchanged.

DOCS: update the `/session save|load|list <name>` row in docs/slash-commands.md to note that bare `/session` opens the picker, and update the SLASH_COMMANDS hint for /session the same way (the doc-sync test compares command tokens only, so the hint text is free to change).

Acceptance: python -m pytest tests/test_ui_common.py -k session_picker -q > check.log 2>&1 — headless test in the model-picker shape: a Host(App) pushes SessionPickerScreen([{'name':'alpha','turn_count':4,'saved_at':'2026-08-19 10:00','notes':''},{'name':'beta','turn_count':9,'saved_at':'2026-08-20 09:00','notes':'wip'}]) with callback=results.append; asyncio.run(drive(['down','enter'])) asserts results == ['beta'] and that the rendered option label for that row contains '9 turns' and 'wip'; drive(['escape']) asserts results == [None]. Plus test_documented_commands_and_the_table_are_the_same_set must still pass after the hint/doc edits.