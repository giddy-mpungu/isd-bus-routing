@echo off
rem Installs and runs isd-bus-routing on this PC: double-click it, or run
rem "deploy.cmd update" (and the other commands) from a terminal.
rem See docs\home-install.md. It only runs deploy\home.ps1 without changing
rem PowerShell's execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\home.ps1" %*
set EXITCODE=%ERRORLEVEL%
rem Double-clicked (no command given): keep the window open to read the result.
if "%~1"=="" pause
exit /b %EXITCODE%
