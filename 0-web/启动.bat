@echo off
chcp 936 >nul
rem ============================================================
rem  总控页：一个页面对应 1-rvc / 2-gpt-sovits / 3-so-vits-svc / 4-e2e
rem  启动后地址：http://127.0.0.1:8100
rem  停止：关掉本窗口即可，或双击 停止.bat
rem ============================================================
cd /d "%~dp0"
title 总控页 8100
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

echo 正在启动总控页 ...
echo 启动后请访问 http://127.0.0.1:8100
echo （总控页只是页面+转发，三个引擎服务要用各自的 启动.bat 或根目录 全部启动.bat 先拉起来）
echo.
"%PY%" web_service.py -p 8100
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" echo [失败] 退出码 %RC%，往上翻看报错。
pause
exit /b 0

:nopy
echo [错误] 没找到运行环境 runtime\py312
echo 请先运行 安装环境.bat（免联网，硬链接克隆一份即可）
pause
exit /b 1
