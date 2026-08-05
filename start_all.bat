@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   一键启动: 修复服务 + Web UI
echo ============================================
echo.
start "lama-cleaner" "C:\Users\39528\AppData\Roaming\Python\Python311\Scripts\lama-cleaner.exe" --model lama --device cpu --port 7860
timeout /t 5 /nobreak >nul
echo 修复服务已启动, 正在打开 UI...
python webui.py
pause
