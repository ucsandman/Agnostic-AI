# daily-distill.ps1 — Scheduled Agnostic AI Self-Maintenance Run
# Runs headless every night to cluster errors, evaluate candidate rules, and emit PROPOSAL.md.

$ErrorActionPreference = 'Continue'
$rootDir = Resolve-Path (Join-Path $PSScriptRoot '..')
$logFile = Join-Path $rootDir 'storage\daily-distill.log'
$start   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

Add-Content $logFile "`n===== [$start] daily-distill start ====="

Set-Location $rootDir
try {
  $out = (node engine/distill/distill.cjs 2>&1) | Out-String
  $code = $LASTEXITCODE
  Add-Content $logFile $out
  $end = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  Add-Content $logFile "[$end] complete (exit $code)"
  exit $code
} catch {
  $end = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  Add-Content $logFile "[$end] ERROR: $_"
  exit 1
}
