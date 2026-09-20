@echo off
chcp 936 >nul
rem ============================================================
rem  so-vits-svc 唱歌换声服务
rem  启动后地址：http://127.0.0.1:6843
rem  停止：关掉本窗口即可，或双击 停止.bat
rem ============================================================
cd /d "%~dp0"
title so-vits-svc 6843
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

echo 正在启动 so-vits-svc 唱歌换声服务 ...
echo 启动后请访问 http://127.0.0.1:6843
echo （关掉本窗口就是停止服务）
echo.
"%PY%" svc_service.py -p 6843
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" echo [失败] 退出码 %RC%，往上翻看报错。
pause
exit /b 0

:nopy
echo [错误] 没找到运行环境 runtime\py312
echo 请先运行 安装环境.bat
pause
exit /b 1
