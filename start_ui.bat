@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   图像本地化翻译工作室 - Web UI
echo   http://127.0.0.1:7861
echo ============================================
echo.
echo 检查 lama-cleaner 修复服务...
powershell -NoProfile -Command "if (Test-NetConnection -ComputerName 127.0.0.1 -Port 7860 -InformationLevel Quiet -WarningAction SilentlyContinue) { Write-Host '[OK] 修复服务运行中' } else { Write-Host '[!] 修复服务未运行, 擦除修复将被自动跳过 (可运行 start_lama.bat)' }"
echo.
python webui.py
pause
