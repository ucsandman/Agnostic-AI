# sync-targets.ps1 — Syncs single-source-of-truth rules across all agent harnesses
$rootDir = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $rootDir
node engine/sync/sync.cjs
