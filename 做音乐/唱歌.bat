@echo off
rem Sing a song: drag a work folder (containing song.json) onto this file,
rem or double-click and paste the folder path.
set "PYTHONUTF8=1"
chcp 65001 >nul
set "PYEXE="
if exist "D:\yue2\.venv\Scripts\python.exe" set "PYEXE=D:\yue2\.venv\Scripts\python.exe"
if not defined PYEXE if exist "%~dp0runtime\py312\python.exe" set "PYEXE=%~dp0runtime\py312\python.exe"
if not defined PYEXE set "PYEXE=python.exe"
if "%~1"=="" (
    "%PYEXE%" "%~dp0sing.py"
) else (
    "%PYEXE%" "%~dp0sing.py" "%~1"
)
pause
