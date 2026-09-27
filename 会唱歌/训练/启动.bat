@echo off
chcp 936 >nul
rem ============================================================
rem  训练工作台：页面上训练自己的二次元唱歌音色
rem  启动后地址：http://127.0.0.1:8103
rem  停止：关掉本窗口即可，或双击 停止.bat
rem ============================================================
cd /d "%~dp0"
title 训练工作台 8103
set PYTHONIOENCODING=utf-8
set "PY=..\runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

netstat -ano | findstr ":8103" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 goto :busy

echo 正在启动训练工作台 ...
echo 启动后请用浏览器打开 http://127.0.0.1:8103
echo.
"%PY%" 训练工作台.py -p 8103
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" echo [失败] 退出码 %RC%，往上翻看报错。
pause
exit /b 0

:busy
echo [提示] 端口 8103 已经有服务在监听（可能已启动过）。
echo 直接用浏览器打开 http://127.0.0.1:8103 即可；想重启先双击 停止.bat。
pause
exit /b 0

:nopy
echo [错误] 没找到运行环境 ..\runtime\py312，请先运行 ..\安装环境.bat
pause
exit /b 1
