@echo off
chcp 936 >nul
rem ============================================================
rem  总控页的"环境"就是 runtime\py312
rem  本项目只用 Python 标准库，不联网装任何包；
rem  缺环境时从 1-rvc / 4-e2e 硬链接克隆一份（不占磁盘）
rem ============================================================
cd /d "%~dp0"
title 总控页 安装环境
set "PY=runtime\py312\python.exe"
if exist "%PY%" goto :has

echo 没找到 runtime\py312，开始从邻居项目硬链接克隆（不联网、不占磁盘）...
if exist "..\1-rvc\runtime\py312\python.exe" set "SRC=..\1-rvc\runtime\py312" & goto :clone
if exist "..\4-e2e\runtime\py312\python.exe" set "SRC=..\4-e2e\runtime\py312" & goto :clone
echo [失败] 邻居项目里也没找到 runtime\py312。
echo        请先保证 1-rvc 或 4-e2e 的环境在，再运行本脚本。
pause
exit /b 1

:clone
python 克隆运行环境.py "%SRC%"
echo.
echo [完成] 现在可以双击 启动.bat 了。
pause
exit /b 0

:has
echo [提示] 本项目已有 runtime\py312，无需安装。
echo        总控页只用 Python 标准库，不需要 pip 装任何东西。
pause
exit /b 0
