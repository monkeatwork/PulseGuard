@echo off
rem Windows launcher: runs scripts\windows\config-everything.ps1 without changing the PowerShell execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\config-everything.ps1" %*
exit /b %ERRORLEVEL%
