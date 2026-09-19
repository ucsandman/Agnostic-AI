# Daily harness parity sync.
# Runs after NightlyMeditation (06:40), which is what promotes new rules into
# CLAUDE.md, so every other client picks them up the same morning instead of
# drifting for three months the way the hand-written versions did.
#
# The port is `npm run port` in this repository: it captures the Claude home and # applies rules, hooks, skills, agents, commands, MCP servers and permissions to # every installed client (Codex, Gemini CLI, Antigravity, Cursor and the rest).
#
# Registered as Task Scheduler job "HarnessParitySync". Remove with:
#   Unregister-ScheduledTask -TaskName HarnessParitySync -Confirm:$false

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$home_ = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.claude' }
$log = Join-Path $home_ 'logs\port-daily.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Add-Content -Path $log }

Log '--- harness parity sync start ---'

# Capture the Claude harness and apply it to every other installed client.
$cli = Join-Path $root 'engine\harness\cli.cjs'
$port = & node $cli port 2>&1
$port | ForEach-Object { Log $_ }
if ($LASTEXITCODE -ne 0) { Log "ALERT: port exited $LASTEXITCODE" }

# Prove the shared guards still block AND still pass. A guard that stopped firing
# is invisible otherwise (rule L1). The probe lives beside the hooks it exercises.
$probe = Join-Path $root 'engine\hooks\tests\guard-probe.cjs'
$test = & node $probe 2>&1
$test | ForEach-Object { Log $_ }
# Assert the positive result. "did not say FAILED" is not the same as "passed".
if (-not ($test -match '(\d+) passed / 0 failed')) {
  Log 'ALERT: guard self-check did not report success - the shared guards may not be firing'
}

# Refresh the human-facing status page (per-client, per-component matrix).
$status = & node $cli status --html 2>&1
$status | ForEach-Object { Log $_ }

Log '--- harness parity sync end ---'
