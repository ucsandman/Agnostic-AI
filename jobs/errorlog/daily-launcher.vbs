' The human daily error log form: invoked by Windows Task Scheduler (9:15pm).
' wscript has no console, so the node server runs with zero window flash and
' no stray black window sitting open for the 30 minutes it stays alive.
' The browser is opened here rather than by node, so the only window that
' appears is the page itself.
Dim sh, fso, here, home, log
Set sh = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
home = sh.ExpandEnvironmentStrings("%CLAUDE_CONFIG_DIR%")
If home = "%CLAUDE_CONFIG_DIR%" Then home = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\.claude"
If Not fso.FolderExists(home & "\logs") Then fso.CreateFolder(home & "\logs")
log = home & "\logs\errorlog-daily.log"
sh.Run "cmd /c node """ & fso.GetAbsolutePathName(here & "\..\..\tools\errorlog\daily.cjs") & """ --no-open >> """ & log & """ 2>&1", 0, False
WScript.Sleep 1500
sh.Run "http://localhost:7841", 1, False
