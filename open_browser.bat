@echo off
REM 等服务器起来后用 Chrome 打开看板（被 启动看板.bat 后台调用）
timeout /t 14 /nobreak >nul
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" http://localhost:8501
