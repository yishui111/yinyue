@echo off
chcp 936 >nul
rem ============================================================
rem  so-vits-svc 唱歌换声 自测
rem  服务没开会自动拉起，然后换一个角色的音色
rem ============================================================
cd /d "%~dp0"
title so-vits-svc 唱歌换声 自测
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

"%PY%" tests\test_svc.py
echo.
pause
exit /b 0

:nopy
echo [错误] 没找到运行环境 runtime\py312
echo 请先运行 安装环境.bat
pause
exit /b 1
