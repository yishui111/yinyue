@echo off
rem Stop the YuE2 music web server and any running synthesis job.
chcp 65001 >nul
set "FOUND="
if exist "%~dp0.server.pid" (
    for /f %%p in (%~dp0.server.pid) do taskkill /F /T /PID %%p >nul 2>&1 && set "FOUND=1"
    del "%~dp0.server.pid" >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :7866 ^| findstr LISTENING') do taskkill /F /T /PID %%a >nul 2>&1 && set "FOUND=1"
if defined FOUND (echo Server stopped.) else (echo Server was not running.)
pause
