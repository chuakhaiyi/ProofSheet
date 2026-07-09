@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows_full.ps1"
exit /b %ERRORLEVEL%
