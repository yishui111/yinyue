@echo off
chcp 936 >nul
rem ============================================================
rem  会唱歌 自测：小星星旋律 + 示例填词 → DiffSinger 唱出来
rem  产物：输出\测试_小星星.wav（干声）；6843 在线时再出一个换声版
rem ============================================================
cd /d "%~dp0"
title 会唱歌 自测
set PYTHONIOENCODING=utf-8
set "PY=runtime\py312\python.exe"
if not exist "%PY%" goto :nopy
if not exist "checkpoints\0211_opencpop_ds1000_keyshift\model_ckpt_steps_360000.ckpt" goto :nomodel

"%PY%" sing.py testdata\小星星.json testdata\填词示例.json -o 输出\测试_小星星.wav
if errorlevel 1 goto :fail

echo.
echo [试听] 输出\测试_小星星.wav
echo [提示] 3-so-vits-svc(6843) 开着的话，可以再加 --role 芙宁娜 等角色名换成二次元音色
pause
exit /b 0

:nopy
echo [错误] 没找到运行环境 runtime\py312，请先运行 安装环境.bat
pause
exit /b 1

:nomodel
echo [错误] 没找到 checkpoints\0211_opencpop_ds1000_keyshift 模型
echo 下载地址见 说明.md（openvpi 官方 release，735MB）
pause
exit /b 1

:fail
echo [失败] 合成报错了，往上翻看详细信息。
pause
exit /b 1
