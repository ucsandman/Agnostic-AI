# bash-noprofile

A `bash.exe` shim for Claude Code's Bash tool on Windows. It runs Git Bash with
`--noprofile --norc` so a tool call does not pay the login profile.

## Why

Claude Code starts every Bash tool call as `bash -c -l "<command>"`. Git for
Windows' `/etc/profile` and `profile.d/*` fork about 14 times (`cygpath`,
`hostname`, `which`, subshells). On a machine where process creation is slow,
that is the whole cost of the call. Measured 2026-09-19 on a loaded box:

| | stock `bash -c -l` | shim |
|---|---|---|
| empty command | 5 to 14 s | 0.6 to 3.8 s |
| Bash tool call in a fresh session (`echo`) | 31.6 s | 4.2 s |

The rest of the story, including why the machine was slow, is in
[docs/hook-latency.md](../../docs/hook-latency.md).

## What it does

1. Execs `<Git>\bin\bash.exe --noprofile --norc <args>` with the original
   arguments quoted the way Git Bash parses them.
2. Prepends `<Git>\usr\local\bin;<Git>\usr\bin;<Git>\bin;<Git>\mingw64\bin`
   to PATH (what `/etc/profile` would have added), sets `LANG` and `MSYSTEM`
   when unset. `BASH_ENV` still applies, so a per-command env loader keeps working.
3. Passes its own stdin, stdout and stderr to bash with `STARTF_USESTDHANDLES`.
   Claude Code spawns the shell detached, and a child started by plain handle
   inheritance from a detached parent writes to a console nobody reads: the tool
   returns "(Bash completed with no output)". This was the bug that cost a few
   probes; keep the explicit handles.
4. Puts bash in a job object with kill-on-close, so a shim killed on timeout
   takes its shell with it.

## Install

```
build.cmd
```

Then in `~/.claude/settings.json`:

```json
"env": { "CLAUDE_CODE_GIT_BASH_PATH": "C:\\Users\\<you>\\.claude\\tools\\bash-noprofile\\bash.exe" }
```

Sessions started after the change use it. `bash.exe` is built, not tracked.

## Verify (cheapest model, fresh session)

```
claude -p 'Use the Bash tool to run exactly: echo SHIM_OK && command -v grep' --model haiku --allowedTools Bash --max-turns 2
```

Expect `SHIM_OK` and `/usr/bin/grep`. With `--debug`, the session's debug log
says `Using bash path: ...bash-noprofile\bash.exe` and `Shell snapshot created`.

## Revert

Delete the `CLAUDE_CODE_GIT_BASH_PATH` line from settings.json.

## Caveats

- Claude Code's shell snapshot has a hard 10 s timeout and no knob. The
  snapshot script forks ~30 times; if the machine cannot fork that fast the
  snapshot fails and the session runs without one (the tool still works).
- Nothing from `~/.bashrc` or `/etc/profile.d` reaches tool shells any more.
  Put PATH additions the tools need in the Windows user PATH or in the file
  `BASH_ENV` points at.
- `BASH_NOPROFILE_GIT=<root>` overrides the Git for Windows location.
