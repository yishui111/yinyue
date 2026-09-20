@echo off
chcp 936 >nul
rem ============================================================
rem  按端口停掉三个服务（6843 / 9880 / 7865）
rem ============================================================
cd /d "%~dp0"
title 全部停止

for %%P in (6843 9880 7865) do call :killport %%P
echo.
echo [完成]
pause
exit /b 0

:killport
echo --- 端口 %1 ---
for /f "tokens=5" %%I in ('netstat -ano ^| findstr ":%1" ^| findstr "LISTENING"') do (
  echo   结束进程 PID %%I
  taskkill /F /PID %%I >nul 2>nul
)
goto :eof
