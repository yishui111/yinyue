@echo off
chcp 936 >nul
rem ============================================================
rem  停止会唱歌服务（按端口 8102 结束进程）
rem ============================================================
cd /d "%~dp0"
title 停止会唱歌服务 8102
set "PORT=8102"
set "FOUND=0"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8102" ^| findstr "LISTENING"') do (
  set "FOUND=1"
  echo   结束进程 PID %%P
  taskkill /F /PID %%P >nul 2>nul
)

if "%FOUND%"=="0" echo [提示] 端口 8102 上没有服务在监听，不用停。
echo.
echo [完成]
pause
