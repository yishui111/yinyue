@echo off
chcp 936 >nul
rem ============================================================
rem  停止总控页（按端口 8100 结束进程；不影响三个引擎服务）
rem ============================================================
cd /d "%~dp0"
title 停止总控页 8100
set "PORT=8100"
set "FOUND=0"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8100" ^| findstr "LISTENING"') do (
  set "FOUND=1"
  echo   结束进程 PID %%P
  taskkill /F /PID %%P >nul 2>nul
)

if "%FOUND%"=="0" echo [提示] 端口 8100 上没有服务在监听，不用停。
echo.
echo [完成]
pause
