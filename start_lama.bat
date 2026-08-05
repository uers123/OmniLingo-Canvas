@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   lama-cleaner 擦除修复服务 (端口 7860)
echo ============================================
echo.
start "lama-cleaner" "C:\Users\39528\AppData\Roaming\Python\Python311\Scripts\lama-cleaner.exe" --model lama --device cpu --port 7860
timeout /t 3 /nobreak >nul
echo 服务已启动: http://127.0.0.1:7860
echo 窗口可关闭, 服务在后台运行
pause
