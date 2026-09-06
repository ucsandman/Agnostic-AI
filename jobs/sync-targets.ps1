# sync-targets.ps1 — Re-port the captured harness into every installed client.
# Register with Task Scheduler (for example nightly, after whatever job edits
# your primary client's rules) or run by hand. Exit code is the port's.
$rootDir = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $rootDir
node engine/harness/cli.cjs port
