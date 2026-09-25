@echo off
chcp 936 >nul
rem ============================================================
rem  会唱歌工作台：旋律+歌词 → DiffSinger 唱出来（可选再换二次元音色）
rem  启动后地址：http://127.0.0.1:8102
rem  停止：关掉本窗口即可，或双击 停止.bat
rem ============================================================
cd /d "%~dp0"
title 会唱歌工作台 8102
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

netstat -ano | findstr ":8102" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 goto :busy

echo 正在启动会唱歌工作台 ...
echo 启动后请用浏览器打开 http://127.0.0.1:8102
echo （页面里：载入旋律 → 逐行填词 → 点「唱出来」试听下载）
echo.
"%PY%" sing_service.py -p 8102
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" echo [失败] 退出码 %RC%，往上翻看报错。
pause
exit /b 0

:busy
echo [提示] 端口 8102 已经有服务在监听（可能之前已启动过）。
echo 直接用浏览器打开 http://127.0.0.1:8102 即可；
echo 想重启就先双击 停止.bat 再运行本脚本。
pause
exit /b 0

:nopy
echo [错误] 没找到运行环境 runtime\py312
echo 请先运行 安装环境.bat
pause
exit /b 1
