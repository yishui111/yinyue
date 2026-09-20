@echo off
chcp 936 >nul
rem ============================================================
rem  停止 GPT-SoVITS（按端口 9880 结束进程）
rem ============================================================
cd /d "%~dp0"
title 停止 GPT-SoVITS 9880
set "PORT=9880"
set "FOUND=0"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":9880" ^| findstr "LISTENING"') do (
  set "FOUND=1"
  echo   结束进程 PID %%P
  taskkill /F /PID %%P >nul 2>nul
)

if "%FOUND%"=="0" echo [提示] 端口 9880 上没有服务在监听，不用停。
echo.
echo [完成]
pause
