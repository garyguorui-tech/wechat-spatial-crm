@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 微信客情CRM看板（请勿关闭本窗口）

REM 优先用装了依赖的 LibreOffice 自带 Python（找不到再回退到 PATH 里的 python）
set "PYEXE=C:\Program Files\LibreOffice\program\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo ============================================
echo   微信客情 CRM 看板服务器
echo   本窗口=看板服务器，启动后请勿关闭！
echo   约 15 秒后 Chrome 自动打开；
echo   若没弹出，双击桌面「微信客情看板(网页)」
echo ============================================
echo.

REM 后台小助手：等十几秒后用 Chrome 打开（纯 cmd 命令，不用 powershell）
start "" /min "%~dp0open_browser.bat"

echo 服务启动中，请稍候 10~20 秒……
REM run_dashboard.py 会在进程内修好搜索路径再启动 streamlit
"%PYEXE%" run_dashboard.py

echo.
echo 看板已停止。按任意键关闭窗口。
pause >nul
