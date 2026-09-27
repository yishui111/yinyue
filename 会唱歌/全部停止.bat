@echo off
chcp 936 >nul
cd /d "%~dp0"
title 会唱歌 全部停止
echo 停止唱歌工作台（8102）...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8102" ^| findstr "LISTENING"') do taskkill /F /PID %%P >nul 2>nul
echo 停止训练工作台（8103）...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8103" ^| findstr "LISTENING"') do taskkill /F /PID %%P >nul 2>nul
echo 停止常驻渲染器（8105，空闲时也会自动退出）...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8105" ^| findstr "LISTENING"') do taskkill /F /PID %%P >nul 2>nul
echo 停止本地换声引擎（8106，空闲时也会自动退出）...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8106" ^| findstr "LISTENING"') do taskkill /F /PID %%P >nul 2>nul
echo [完成] 两个服务都已停止。
pause
