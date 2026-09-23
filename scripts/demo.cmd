@echo off
rem Convenience wrapper so scripts\demo.ps1 runs without changing the
rem PowerShell execution policy. Usage: scripts\demo.cmd up | share | stop | ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo.ps1" %*
