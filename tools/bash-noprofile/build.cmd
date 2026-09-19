@echo off
rem Builds bash.exe next to this script with the C# compiler that ships with every Windows 10/11 (.NET Framework 4.x).
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
"%CSC%" -nologo -optimize -out:"%~dp0bash.exe" "%~dp0bash.cs"
if errorlevel 1 (echo build failed & exit /b 1)
echo built %~dp0bash.exe
