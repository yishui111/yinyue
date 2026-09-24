@echo off
chcp 936 >nul
rem ============================================================
rem  会唱歌服务：旋律+歌词 → DiffSinger 唱出来（可选再换二次元音色）
rem  启动后地址：http://127.0.0.1:8102  （GET /health, POST /sing）
rem  停止：关掉本窗口即可，或双击 停止.bat
rem ============================================================
cd /d "%~dp0"
title 会唱歌服务 8102
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

echo 正在启动会唱歌服务 ...
echo 启动后地址 http://127.0.0.1:8102
echo （命令行合成也可以直接用：runtime\py312\python.exe sing.py testdata\小星星.json testdata\填词示例.json）
echo.
"%PY%" sing_service.py -p 8102
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
