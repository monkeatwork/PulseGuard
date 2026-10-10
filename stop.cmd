@echo off
rem Windows launcher: runs scripts\windows\stop.ps1 without changing the PowerShell execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\stop.ps1" %*
exit /b %ERRORLEVEL%
