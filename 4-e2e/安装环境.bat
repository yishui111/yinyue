@echo off
chcp 936 >nul
rem ============================================================
rem  安装 / 修复 端到端测试 的运行环境
rem  正常情况不用跑它：项目自带的 runtime\py312 拷到新电脑就能用。
rem  只有在环境被弄坏、或想重装依赖时才需要跑。
rem  要求：本机装有 Python 3.12，且能联网（走阿里云镜像）
rem ============================================================
cd /d "%~dp0"
title 安装环境 - 端到端测试
set "REQ=requirements.txt"
set "IDX=https://mirrors.aliyun.com/pypi/simple/"

if exist "runtime\py312\python.exe" goto :has_rt

echo [1/4] 没找到运行环境，用本机的 Python 3.12 新建一个 ...
where py >nul 2>nul
if errorlevel 1 goto :nopy
py -3.12 -c "import sys" >nul 2>nul
if errorlevel 1 goto :nopy
py -3.12 -m venv runtime\py312
if errorlevel 1 goto :fail
set "PY=runtime\py312\Scripts\python.exe"
echo [2/4] 装 torch / torchaudio（cu118 版，不能用默认的 CPU 版）...
"%PY%" -m pip install torch==2.7.1+cu118 torchaudio==2.7.1+cu118 --index-url https://mirrors.nju.edu.cn/pytorch/whl/cu118 --extra-index-url %IDX%
if errorlevel 1 goto :fail
goto :pip

:has_rt
echo [1/4] 运行环境已存在：runtime\py312
set "PY=runtime\py312\python.exe"
echo [2/4] 装 torch / torchaudio（cu118 版，不能用默认的 CPU 版）...
"%PY%" -m pip install torch==2.7.1+cu118 torchaudio==2.7.1+cu118 --index-url https://mirrors.nju.edu.cn/pytorch/whl/cu118 --extra-index-url %IDX%
if errorlevel 1 goto :fail

:pip
echo [3/4] 升级 pip ...
"%PY%" -m pip install -U pip -i %IDX%
echo [4/4] 安装依赖 %REQ% ...
"%PY%" -m pip install -r %REQ% -i %IDX%
if errorlevel 1 goto :fail

echo.
echo [5/5] 转成免安装的自带解释器环境 ...
"%PY%" 转为便携环境.py
if errorlevel 1 goto :fail
echo.
echo [完成] 现在双击 启动.bat 就能用了。
pause
exit /b 0

:nopy
echo [错误] 没找到 Python 3.12（py -3.12 不可用）。
echo 请先安装 Python 3.12 再运行本脚本。
pause
exit /b 1

:fail
echo [失败] 上面有报错，往上翻看详细信息。
pause
exit /b 1
