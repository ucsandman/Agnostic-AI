---
name: dispatch-blocks
description: Use when writing ANY subagent, Task, or Workflow dispatch brief — provides the proven verbatim brief blocks (file ownership, ground truth, revert-to-red, real-binary, rtk-distrust, pure-test STOP, adversarial judge, read-only reviewer, harness tool family). Copy the matching blocks into the brief instead of re-deriving them.
---

# Dispatch Blocks

Reusable brief blocks for subagent dispatches. Each exists because its absence caused
a recorded failure (session-archaeology corpus, 2026-08-14; recurrence counts cited).
Pick EVERY block that matches the dispatch and paste it into the brief. Do not
paraphrase — these exact framings are the ones measured to work.

## Selection table

| Dispatch involves... | Blocks to include |
|---|---|
| 2+ agents editing one tree | OWNERSHIP |
| 3+ parallel agents on one repo/facts | GROUND TRUTH |
| Any bugfix task | REVERT-TO-RED |
| Feature wrapping an external CLI/binary | REAL-BINARY |
| Any gate/verify/test-running agent | RTK-DISTRUST |
| Proof/test-only task | PURE-TEST STOP |
| Tournament or design judging | DEFAULT-FATAL JUDGE |
| Review personas | READ-ONLY REVIEWER |
| New tool in ~/.claude/tools | HARNESS TOOL FAMILY |

Also: per CLAUDE.md, every dispatch sets `model:` explicitly, and test/build commands
run foreground with a timeout (bg-test-guard enforces this mechanically).

## OWNERSHIP — mandatory for 2+ agents in one tree
Reused verbatim ×21 across DashClaw, pineapple, phone-claude; its absence caused two
reflog-recovery incidents from shared-index races.

```
FILE OWNERSHIP: Edit ONLY the files on your list:
  <explicit file list>
Touch nothing else. Do not run ANY git commands (add/commit/stash/checkout) — the
coordinator owns staging and commits. Match the existing style of each file exactly.
Your test command is: <command>. Run it foreground with a timeout and read the real
exit code.
```

## GROUND TRUTH — mandatory for 3+ parallel agents on one repo
Reused ×11 in one sweep; its absence cost ~12 judge agents re-reading the same five
files from scratch.

```
VERIFIED GROUND TRUTH about <target> as of <date> (do NOT contradict these; they were
measured today):
  <bullet list of measured facts>
Do not re-verify these. Verify only what your specific task adds on top of them.
```

## REVERT-TO-RED — mandatory for every bugfix task
When mandated, 13/13 parallel fix agents complied and produced non-vacuous fixes; when
absent, a regression test shipped that still passed with its fix reverted.

```
Regression-test discipline (mandatory, in this order):
1. Write the regression test FIRST.
2. Prove it FAILS against the pre-fix code, with the failure message you expect.
3. Apply the fix. Prove the test passes.
4. Report BOTH observations (the red run and the green run) in your DONE report.
A test never seen red proves nothing.
```

## REAL-BINARY — mandatory when the feature shells out to an external CLI
A 9-task plan shipped `dashclaw install openclaw` with 35 passing tests and the
feature had never run once — every test mocked the subprocess.

```
At least one verification step MUST execute the real <binary> end to end and assert on
its actual output. Mocked subprocess calls do not count toward "works". If the real
binary cannot run in this environment, report BLOCKED — do not substitute a mock and
call it verified.
```

## RTK-DISTRUST — mandatory for every gate/verify agent
Hand-injected ×9 into verification prompts; rtk compression misreported commit file
counts and hid a real pytest failure.

```
Do NOT trust compressed or piped summaries — pipe each command's output to a log file,
read the actual exit code separately, and quote failing lines from the log. If a
summary and an exit code disagree, the exit code wins; re-run with `rtk proxy` to see
raw output.
```

## PURE-TEST STOP — for proof/test-only tasks
Keeps bug-fixing and test-writing in separate reviewable commits.

```
This is a PURE TEST task — no production code changes of any kind. If a test failure
reveals a real production bug, STOP and report BLOCKED with the evidence (failing
test, observed vs expected) instead of patching production code inside this task.
```

## DEFAULT-FATAL JUDGE — for tournament/design judging
Reused verbatim ×5 per panel; skeptics repeatedly caught finders who checked one
instance of a pattern and concluded about all of them.

```
You are an adversarial judge. Your DEFAULT VERDICT IS FATAL — assume the proposal is
broken until it survives your attack. Attack the weakest load-bearing claim first.
State explicitly how many instances of each pattern you examined (not just the first).
A verdict of "survives" requires naming what you tried that failed to kill it.
```

## READ-ONLY REVIEWER — for review personas
Reused verbatim ×5 across a 5-persona pre-merge audit.

```
Do not edit files. Produce concise findings with file paths and line numbers,
severity, and rationale. Also say explicitly if there are no material findings.
```

## HARNESS TOOL FAMILY — for new tools in ~/.claude/tools
Produced five clean single-pass tool builds back to back in one afternoon.

```
This environment has a family of zero-dependency Node tools in
~/.claude/tools/ (spend, recall, gitradar, cronwatch, envdoctor). Match
their conventions exactly: single .cjs file, zero npm dependencies, generated .html
output is gitignored, a README.md, and an --open flag that opens the rendered page.
```
