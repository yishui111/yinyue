@echo off
chcp 936 >nul
rem ============================================================
rem  一次拉起总控页 + 三个服务（每个一个独立窗口）
rem  注意：三个引擎同时开会抢显存，训练时建议只开一个
rem ============================================================
cd /d "%~dp0"
title 全部启动

echo 正在拉起 3 个引擎服务和总控页，每个一个新窗口，请稍等它们各自加载模型...
echo.
start "so-vits 唱歌换声 (6843)" "%~dp03-so-vits-svc\启动.bat"
start "GPT-SoVITS 文字转语音 (9880)" "%~dp02-gpt-sovits\启动.bat"
start "RVC 换声 WebUI (7865)" "%~dp01-rvc\启动.bat"
start "总控页 (8100)" "%~dp00-web\启动.bat"

echo 已发出启动命令。引擎模型加载完、总控页状态灯变绿即可使用。
echo.
echo   总控页     http://127.0.0.1:8100   （四个板块对应下面四个项目）
echo   so-vits    http://127.0.0.1:6843
echo   GPT-SoVITS http://127.0.0.1:9880
echo   RVC WebUI  http://127.0.0.1:7865
echo.
echo 要全部停掉：双击 全部停止.bat（总控页另双击 0-web\停止.bat，或直接关它的窗口）
pause