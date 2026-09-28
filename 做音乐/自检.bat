@echo off
rem Environment self-check for the YuE2 singing workbench (no GPU load).
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYEXE="
if exist "D:\yue2\.venv\Scripts\python.exe" set "PYEXE=D:\yue2\.venv\Scripts\python.exe"
if not defined PYEXE if exist "%~dp0runtime\py312\python.exe" set "PYEXE=%~dp0runtime\py312\python.exe"
if not defined PYEXE set "PYEXE=python.exe"
"%PYEXE%" "%~dp0sing.py" --check
pause
