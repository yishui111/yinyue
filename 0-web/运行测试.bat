@echo off
chcp 936 >nul
rem ============================================================
rem  总控页自测：起一个临时总控服务，逐项验证与 4 个项目的对应接口
rem  （三个引擎服务必须已经在跑，没跑会提示先去 启动.bat）
rem ============================================================
cd /d "%~dp0"
title 总控页 自测
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

"%PY%" tests\selftest.py
echo.
pause
exit /b 0

:nopy
echo [错误] 没找到运行环境 runtime\py312
echo 请先运行 安装环境.bat（免联网，硬链接克隆一份即可）
pause
exit /b 1
