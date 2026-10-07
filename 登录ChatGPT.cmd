@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Command login %*
set "loginResult=%ERRORLEVEL%"
if not "%loginResult%"=="0" echo 本次操作未完成，请查看上方提示。
if not "%PDF2ZH_LOGIN_FROM_GUI%"=="1" pause
exit /b %loginResult%
