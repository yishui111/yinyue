@echo off
chcp 936 >nul
rem ============================================================
rem  GPT-SoVITS 文字转语音 API
rem  启动后地址：http://127.0.0.1:9880
rem  停止：关掉本窗口即可，或双击 停止.bat
rem ============================================================
cd /d "%~dp0"
title GPT-SoVITS API 9880
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy

echo 正在启动 GPT-SoVITS 文字转语音 API ...
echo 启动后请访问 http://127.0.0.1:9880
echo （关掉本窗口就是停止服务）
echo.
"%PY%" api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
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
