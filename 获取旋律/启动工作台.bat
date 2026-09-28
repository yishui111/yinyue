@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [!] Not installed yet. Please run setup.bat first.
  pause
  exit /b 1
)

rem Clear the stop flag left by the stop script, then wake the watchdog.
del /q ".workbench_stop" 2>nul

rem Already running? Then just open the page.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wd_portcheck.ps1" -port 17865 >nul 2>&1
if not errorlevel 1 goto open

echo Starting workbench (watchdog + server)...
start "WorkbenchWatchdog" /min cmd /c "watchdog.bat"

:waitport
ping -n 3 127.0.0.1 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wd_portcheck.ps1" -port 17865 >nul 2>&1
if errorlevel 1 goto waitport

:open
start "" "http://127.0.0.1:17865"
echo.
echo ================================================
echo  Workbench is running: http://127.0.0.1:17865
echo  A watchdog keeps the server alive and restarts
echo  it automatically if it ever goes down.
echo  To stop: double-click the other bat file.
echo ================================================
echo.
pause
