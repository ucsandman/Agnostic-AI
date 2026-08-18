---
name: fable-gpt
description: Use when a task involves heavy implementation, debugging, test fixing, refactoring, or multi-file edits that Codex could execute, or when orchestrating Claude + Codex together in a session.
---

# Fable-GPT: Claude orchestrates, Codex executes

## Role split

- **Claude (main thread):** planning, repo understanding, architecture decisions, task decomposition, final review, small surgical edits.
- **Codex (codex plugin):** heavy implementation, debugging, test fixing, refactors, multi-file edits. Runs on the ChatGPT subscription — zero Claude tokens for execution. Global default is `gpt-5.5` at `xhigh` reasoning (`~/.codex/config.toml`); do not pass `--model`/`--effort` unless deliberately overriding.

## How to delegate

| Situation | Route |
|---|---|
| Quick, bounded task | `/codex:rescue` (foreground) |
| Big, open-ended, or long-running | `codex-rescue` subagent (already `model: sonnet`, Bash-only — passes agent-model-guard) or `--background`; poll `/codex:status`, fetch `/codex:result` |
| Continue prior Codex work | say "resume"/"continue" (maps to `--resume-last`) |
| Routine pre-commit review or second-opinion diagnosis | `/codex:review` — default here before spending Claude subagent tokens; reserve `/code-review` or `/adversarial-review` for high-stakes diffs |

## Task prompt shape (keep it focused)

```
Goal: [one sentence]
Files: [paths]
Constraints: [style, don't touch X]
Done when: [verification command + expected result]
```

One task per delegation. Split unrelated work into separate rescues.

**Workspace root gotcha:** Codex's sandbox root is the session's cwd, not the task's target repo. If the target repo differs from cwd, the `codex-rescue` subagent and `/codex:rescue` will spawn a task that can't write ("patch rejected: writing outside of the project") — Codex burns the whole run discovering this. Invoke the companion runtime directly instead:

```
node "<plugin>/scripts/codex-companion.mjs" task --prompt-file <spec.md> --cwd "<target-repo>" --write --background
```

Long specs go in a `--prompt-file` (avoids shell quoting). Job state is keyed to the `--cwd` value — pass the SAME `--cwd` to `status`/`result`/`cancel` or the job appears not to exist. Errors print to stderr; don't `2>/dev/null` status calls.

## After Codex finishes — never accept blindly

1. `git diff` — read what actually changed.
2. Run the "Done when" verification command yourself and read the output.
3. Wrong or sloppy → re-delegate with specific corrections (use resume); small issues → fix inline.

## When NOT to delegate

- Trivial edits (faster inline than writing the delegation prompt).
- Architecture or product decisions — Claude's job.
- Anything under CLAUDE.md Hard Stops (deploy, migrations, auth/billing config, external comms).
- Tasks needing conversation context Codex doesn't have — inline the needed context into the task prompt or keep it in Claude.
