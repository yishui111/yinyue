@echo off
chcp 936 >nul
rem ============================================================
rem  停止 RVC WebUI（按端口 7865 结束进程）
rem ============================================================
cd /d "%~dp0"
title 停止 RVC WebUI 7865
set "PORT=7865"
set "FOUND=0"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":7865" ^| findstr "LISTENING"') do (
  set "FOUND=1"
  echo   结束进程 PID %%P
  taskkill /F /PID %%P >nul 2>nul
)

if "%FOUND%"=="0" echo [提示] 端口 7865 上没有服务在监听，不用停。
echo.
echo [完成]
pause
