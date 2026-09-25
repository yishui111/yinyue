@echo off
chcp 936 >nul
rem ============================================================
rem  安装/修复 会唱歌 的运行环境
rem  1) runtime\py312 不在就并行硬链接克隆 1-rvc 的（免联网、不占磁盘）
rem  2) 自检依赖；缺什么才联网补装（阿里云镜像），都齐了直接过
rem  模型权重不在仓库里：checkpoints\ 下需要
rem    0211_opencpop_ds1000_keyshift（openvpi 官方发布，735MB）
rem    nsf_hifigan（声码器，50MB）
rem  下载地址与摆放位置见 说明.md
rem ============================================================
cd /d "%~dp0"
title 安装环境 - 会唱歌
set "IDX=https://mirrors.aliyun.com/pypi/simple/"
set "PY=runtime\py312\python.exe"

if exist "%PY%" goto :check

echo [1/3] 克隆运行环境（并行硬链接，来自 1-rvc）...
where py >nul 2>nul
if errorlevel 1 goto :nopy
py -3 并行克隆.py
if errorlevel 1 goto :fail

:check
echo [2/3] 自检依赖 ...
"%PY%" -c "import click, librosa, yaml, tqdm, pypinyin, lightning" >nul 2>nul
if errorlevel 1 goto :pip
echo       依赖齐全，跳过联网安装。
goto :selftest

:pip
"%PY%" -m pip install -r requirements.txt -i %IDX%
if errorlevel 1 goto :fail

:selftest
echo [3/3] 自检 ...
"%PY%" -c "import click, librosa, yaml, tqdm, pypinyin, lightning; print('依赖 OK')"
if errorlevel 1 goto :fail

echo.
echo [完成] 双击 运行测试.bat 验证，或 启动.bat 开工作台（http://127.0.0.1:8102）。
pause
exit /b 0

:nopy
echo [错误] 没找到 Python（py 不可用），且没有 runtime\py312。
pause
exit /b 1

:fail
echo [失败] 上面有报错，往上翻看详细信息。
pause
exit /b 1
