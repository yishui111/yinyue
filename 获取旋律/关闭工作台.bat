@echo off
cd /d %~dp0
echo Stopping workbench...

rem 1) tell the watchdog loop to exit (so it does not resurrect the server)
type nul > ".workbench_stop"
taskkill /FI "WINDOWTITLE eq WorkbenchWatchdog*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq WorkbenchServer*" /F >nul 2>&1

rem 2) kill the web server listening on 17865
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 17865 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

rem 3) kill any analysis worker still running
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*jobrunner.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo Done. Workbench is stopped.
pause
