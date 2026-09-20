@echo off
chcp 936 >nul
rem ============================================================
rem  RVC 换声 / 训练 WebUI
rem  启动后地址：http://127.0.0.1:7865
rem  停止：关掉本窗口即可，或双击 停止.bat
rem ============================================================
cd /d "%~dp0"
title RVC WebUI 7865
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

echo 正在启动 RVC 换声 / 训练 WebUI ...
echo 启动后请访问 http://127.0.0.1:7865
echo （关掉本窗口就是停止服务）
echo.
"%PY%" webui.py --port 7865
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
