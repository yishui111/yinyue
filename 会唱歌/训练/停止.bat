@echo off
chcp 936 >nul
cd /d "%~dp0"
title 停止训练工作台 8103
set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8103" ^| findstr "LISTENING"') do (
  set "FOUND=1"
  echo   结束进程 PID %%P
  taskkill /F /PID %%P >nul 2>nul
)
if "%FOUND%"=="0" echo [提示] 端口 8103 上没有服务在监听，不用停。
echo.
echo [完成]
pause
