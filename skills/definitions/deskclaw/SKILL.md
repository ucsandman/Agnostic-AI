---
name: deskclaw
description: Use when you need to see or inspect the Windows desktop — Wes asks "what's on my screen", pastes or offers a screenshot, mentions a native app, dialog, installer or window that is not a browser or a phone, or asks you to check/read/screenshot something outside a web page. Also use before claiming you cannot see the desktop, and whenever a task needs a window's contents, position, or a list of what is open.
---

# deskclaw — the read-only desktop eye

You CAN see the Windows desktop. Before this existed, Wes had to paste screenshots
by hand; that is the workflow you are replacing. Reach for this instead of asking
him what a window says.

**Read-only.** There is no click, type, key or focus verb. Do not promise one.

`~/.claude/tools/deskclaw/` — spec at `~/.claude/docs/superpowers/specs/2026-08-12-deskclaw-design.md`.

## Use it, or use something else

| Target | Tool |
|---|---|
| A web page, logged-in or not | `agent-browser` / Playwright over CDP. NOT deskclaw. |
| Wes's iPhone | `sidetap` (the `phone` skill). NOT deskclaw. |
| An Electron app (Magnetic, VS Code, Slack) | Playwright Electron or `agent-browser skills get electron` — it renders web UI, so the DOM is richer than the UIA tree. |
| Blender, Unity | Their headless paths (`feeders/blender/render.py`, Unity CLI). They draw their own UI in OpenGL and expose almost nothing to UIA. |
| Native Windows: dialogs, installers, Explorer, Task Scheduler, Office, legacy apps | **deskclaw** |
| "What is open right now?" / "what does that window say?" | **deskclaw** |

## The four verbs

```bash
~/.claude/tools/deskclaw/desk windows                 # what is open
~/.claude/tools/deskclaw/desk snapshot <@wN|title>    # a window's UIA tree
~/.claude/tools/deskclaw/desk shot <@wN|title>        # PNG to disk
~/.claude/tools/deskclaw/desk viewer [port]           # Wes's control page, default 4849
```

Wes also has a `desk` function in his PowerShell profile. In YOUR tool calls prefer
the Bash wrapper — the rtk compression hook only covers Bash.

Output shapes:

```
@w7 "Calculator" (CalculatorApp, 31548)
@w4 [SKIPPED: denylisted]
  @e12 Button "Memory add" [2718,548]
```

Address a window by ref (`@w7`) or any substring of its title. Refs come from the
last `desk windows`, so re-run it if the desktop changed.

**Cost:** a dense app is cheap. Calculator's full tree is 69 elements, ~3,057
characters, roughly 777 tokens. A dialog is a fraction of that. Snapshot freely;
this is not an expensive call.

## Exit codes — check them, they carry meaning

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | hard error, **including a missing or empty `deny.txt`** — the denylist cannot be switched off by deleting a file |
| 2 | not found, denylisted, occluded by a denylisted window, or a tree under 5 elements (a canvas app) |
| 3 | `state/STOP` is set — Wes has switched the tool off |

Exit 3 is not a failure to route around. It means Wes decided you may not look.
Say so and stop. Do not delete `state/STOP` to get past it — that file is his
control, and `desk viewer` is deliberately the one verb that still runs so he can
clear it himself.

## The safety model, and why you must not fight it

This tool reads a screen, so it is built to **fail closed**. When a guard cannot do
its job it refuses rather than proceeding. A refusal is the tool working.

- **Denylisted windows are skipped entirely**, never redacted. They appear as
  `[SKIPPED: denylisted]` with no title. Patterns live in `deny.txt`.
- **Screenshots go to disk.** `desk shot` prints a path and a byte count. **Do not
  Read a PNG into context unless Wes asked you to look at that specific image.**
  Nothing in the tool enforces this — it is your rule to keep.
- **A screenshot is refused when a denylisted window OVERLAPS the target**, because
  screen capture takes the pixels on that region, not the window's own content.
- **Never bypass a refusal.** If `desk shot` exits 2, report why. Do not screenshot
  the full screen instead, do not move windows to dodge the check.
- Every invocation is logged to `state/audit.jsonl`, including refusals and the
  STOP toggle. Assume Wes can see what you looked at.

## Traps, all measured on this machine — do not re-derive

- **Never kill a process by name.** `Stop-Process -Name`, `taskkill /IM`, `pkill`
  and `killall` match by image name and cannot tell your process from Wes's. On
  2026-08-12 exactly this killed his real Notepad with ~40 tabs and unsaved work
  while a test cleaned up after itself. `process-kill-guard.cjs` now blocks these;
  capture the PID when you START a process and kill that.
- **Titleless windows are invisible to `desk windows` but still have pixels.** The
  overlap guard enumerates raw windows separately for that reason. Credential
  prompts and password-manager overlays often have no title.
- **UWP apps expose two windows** — an `ApplicationFrameHost` shell and the real
  one, identically named. Deduped already; do not "fix" it.
- **Some UIA elements return an infinite `BoundingRectangle`** and crash an `[int]`
  cast. Guarded already.
- **A tree under 5 elements means a canvas app** (Unity, Blender, games). That is
  exit 2, and stage 3 is unbuilt, so use the app's headless path instead.
- PowerShell traps this tool paid for: `ConvertFrom-Json` silently converts ISO-8601
  strings to `[DateTime]`; `Write-Error` is terminating under
  `$ErrorActionPreference = 'Stop'` so any `exit N` after it never runs; a
  `Where-Object` matching zero items returns `$null` and `$null.Count` throws under
  StrictMode.

## Testing it

```bash
pwsh -NoProfile -File "$HOME/.claude/tools/deskclaw/tests/run.ps1"
```

Green is all-passed (89 as of 2026-08-13), exit 0. The count varies slightly
because some assertions loop over however many denylisted windows are open — that
is expected, not a regression. The suite launches and closes its own Calculator,
and refuses to run while STOP is set.

## Stage 2: acting (built 2026-08-13)

`desk click @eN`, `desk type @eN "text"`, `desk key <win> "{ENTER}"`,
`desk focus <win>`. All refuse with exit 4 until armed: run `desk arm [minutes]`
(auto-expires, default 30) at the start of an acting task and `desk disarm` when
done. Elements re-resolve by RuntimeId against a fresh snapshot — if a click
refuses with `element-gone`, re-run `desk snapshot` and use the new ref; never
work around a refusal with SendKeys or coordinates.

**DashClaw governance convention** (policies created 2026-08-13, verified firing):
guard desktop acts with these exact action types — `desktop_click`,
`desktop_type`, `desktop_focus`, `desktop_arm` (policy: warn — proceed, it lands
in the ledger) and `desktop_key` (policy: require_approval — record
pending_approval and wait; raw SendKeys chords are the one verb a human reviews).
Name-based process kills guard as `process_kill_by_name` (require_approval);
PID-based kills of processes you started need no approval. A freshly created
policy can take a few seconds to reach every serverless instance — on a
surprising `allow` right after policy changes, re-guard once.

## Not built

Stage 3 (OCR for canvas apps: Unity, Blender) does not exist. Gated on proving
`Windows.Media.Ocr` is reachable from PowerShell 7. Both named targets have
headless code paths that beat clicking.
