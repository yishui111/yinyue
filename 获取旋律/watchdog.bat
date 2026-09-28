@echo off
title WorkbenchWatchdog
cd /d %~dp0
if exist ".workbench_stop" del /q ".workbench_stop"
echo [%date% %time%] watchdog started >> "%~dp0watchdog.log"

:loop
if exist ".workbench_stop" (
  echo [%date% %time%] stop flag found, exiting >> "%~dp0watchdog.log"
  exit
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wd_portcheck.ps1" -port 17865 >nul 2>&1
if not errorlevel 1 goto panel
rem if a fresh boot marker exists, a server is already starting - do not spawn again
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wd_bootmark.ps1" -marker "%~dp0.server_booting" -maxage 240 >nul 2>&1
if not errorlevel 1 goto panel
echo [%date% %time%] server down, starting... >> "%~dp0watchdog.log"
start "WorkbenchServer" /min /D "%~dp0" ".venv\Scripts\python.exe" -u server.py >> "%~dp0server.log" 2>&1
ping -n 161 127.0.0.1 >nul

:panel
rem also keep the GPT-SoVITS control panel (8550, needed by singing) alive
".venv\Scripts\python.exe" -u workbench\keep_panel.py >> "%~dp0watchdog.log" 2>&1
ping -n 6 127.0.0.1 >nul
goto loop
