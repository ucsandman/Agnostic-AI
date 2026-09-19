# Who holds the RAM and which processes belong to which Claude Code session (Windows).
#   powershell -NoProfile -ExecutionPolicy Bypass -File memmap.ps1
# Read-only. Pair with hookpar.cjs: when `node -e 0` takes seconds, this says why.
$all = Get-CimInstance Win32_Process
$byId = @{}; foreach ($p in $all) { $byId[$p.ProcessId] = $p }
function chain($pid0) { $s = @(); $cur = $byId[$pid0]; $n = 0; while ($cur -and $n -lt 4) { $par = $byId[$cur.ParentProcessId]; $s += ($(if ($par) { "$($par.Name):$($par.ProcessId)" } else { "gone:$($cur.ParentProcessId)" })); $cur = $par; $n++ }; $s -join " <- " }
function kids($pid0) { ($all | Where-Object { $_.ParentProcessId -eq $pid0 } | ForEach-Object { $_.Name.Replace('.exe','') }) -join ',' }
$os = Get-CimInstance Win32_OperatingSystem
"RAM free MB: $([math]::Round($os.FreePhysicalMemory/1024)) / $([math]::Round($os.TotalVisibleMemorySize/1024))   commit used MB: $([math]::Round(($os.TotalVirtualMemorySize-$os.FreeVirtualMemory)/1024)) / $([math]::Round($os.TotalVirtualMemorySize/1024))"
""
"== spawn latency: 5 x cmd /c ver (healthy: under 100 ms) =="
1..5 | ForEach-Object { "{0} ms" -f [math]::Round((Measure-Command { cmd /c ver | Out-Null }).TotalMilliseconds) }
""
"== top 15 processes by working set (MB) =="
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 | ForEach-Object { "{0,6}MB  {1,-26} pid={2}" -f [math]::Round($_.WorkingSet64/1MB), $_.ProcessName, $_.Id }
""
"== summed working set by process name (top 10) =="
Get-Process | Group-Object ProcessName | ForEach-Object { [pscustomobject]@{ n = $_.Count; mb = [math]::Round(($_.Group | Measure-Object WorkingSet64 -Sum).Sum / 1MB); name = $_.Name } } | Sort-Object mb -Descending | Select-Object -First 10 | ForEach-Object { "{0,6}MB  x{1,-3} {2}" -f $_.mb, $_.n, $_.name }
""
"== claude.exe sessions =="
foreach ($p in ($all | Where-Object { $_.Name -eq 'claude.exe' })) {
  $cl = $p.CommandLine; if ($cl.Length -gt 90) { $cl = $cl.Substring(0, 90) }
  "pid={0,-6} WS={1,5}MB  chain: {2}" -f $p.ProcessId, [math]::Round($p.WorkingSetSize/1MB), (chain $p.ProcessId)
  "        cmd: $cl"
  "        kids: $(kids $p.ProcessId)"
}
""
"== language servers (tsserver / typescript-language-server) and who owns them =="
foreach ($p in ($all | Where-Object { $_.CommandLine -match 'tsserver\.js|typingsInstaller|typescript-language-server' })) {
  $c = $p; $n = 0; while ($c -and $c.Name -ne 'claude.exe' -and $n -lt 6) { $c = $byId[$c.ParentProcessId]; $n++ }
  "pid={0,-6} WS={1,5}MB session={2}" -f $p.ProcessId, [math]::Round($p.WorkingSetSize/1MB), $(if ($c) { $c.ProcessId } else { '?' })
}
""
"== node/python/shell processes whose parent is gone (orphans) =="
$all | Where-Object { $_.Name -match '^(node|python|py|pwsh|powershell|cmd|bash|conhost)' -and -not $byId.ContainsKey($_.ParentProcessId) } | ForEach-Object { $cl = ($_.CommandLine -replace '^.*?\.exe"?\s*', ''); if ($cl.Length -gt 80) { $cl = $cl.Substring(0, 80) }; "pid={0,-6} {1,-12} WS={2,4}MB  {3}" -f $_.ProcessId, $_.Name, [math]::Round($_.WorkingSetSize/1MB), $cl }
