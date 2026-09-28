@echo off
rem Start the YuE2 singing workbench web page (http://127.0.0.1:7866) and open the browser.
rem Python resolution: D:\yue2 venv (fast SSD cache) if present, else portable runtime\py312.
rem The ONLY way to stop the background server is the stop script in this folder.
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYEXE="
if exist "D:\yue2\.venv\Scripts\pythonw.exe" set "PYEXE=D:\yue2\.venv\Scripts\pythonw.exe"
if not defined PYEXE if exist "%~dp0runtime\py312\pythonw.exe" set "PYEXE=%~dp0runtime\py312\pythonw.exe"
if not defined PYEXE set "PYEXE=pythonw.exe"
netstat -ano | findstr :7866 | findstr LISTENING >nul
if not errorlevel 1 (
    echo Server is already running. Opening the page...
    start "" "http://127.0.0.1:7866"
    timeout /t 2 >nul
    exit /b
)
start "" "%PYEXE%" "%~dp0server.py"
timeout /t 4 >nul
start "" "http://127.0.0.1:7866"
echo Server started in background. Page: http://127.0.0.1:7866
