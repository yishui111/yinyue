@echo off
chcp 936 >nul
rem ============================================================
rem  端到端（视频换声） 自测
rem  前置：3-so-vits-svc 的服务必须已经在跑
rem ============================================================
cd /d "%~dp0"
title 端到端（视频换声） 自测
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

"%PY%" e2e_test.py
echo.
pause
exit /b 0

:nopy
echo [错误] 没找到运行环境 runtime\py312
echo 请先运行 安装环境.bat
pause
exit /b 1
