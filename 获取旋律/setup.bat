@echo off
cd /d "%~dp0"
echo === [1/3] Creating virtual env (.venv) ===
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
echo === [2/3] Installing dependencies ===
echo     torch/demucs/faster-whisper are large; on slow networks this can take 10-30 minutes.
pip install -r requirements.txt
if errorlevel 1 (
  echo === Install FAILED. Check your network and re-run setup.bat ===
  pause
  exit /b 1
)
echo === [3/3] Done ===
echo Next: put your DeepSeek API Key into config.json, then run start.bat
pause
