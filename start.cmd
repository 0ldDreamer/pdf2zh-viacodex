@echo off
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
set "TEMP=%~dp0.runtime\tmp"
set "TMP=%TEMP%"
set "TMPDIR=%TEMP%"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%TEMP%" mkdir "%TEMP%"
start "" "%~dp0.venv\Scripts\pythonw.exe" -B "%~dp0app\pdf_gui.py" %*
