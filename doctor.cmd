@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Command doctor %*
if errorlevel 1 echo Operation failed. Read the message above.
pause
