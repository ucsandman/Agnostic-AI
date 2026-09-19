' Launches lsp-reaper.ps1 (beside this file) with zero window flash (wscript has no console).
' Registered as a scheduled task by jobs/install.cjs.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("Wscript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\lsp-reaper.ps1""", 0, False
