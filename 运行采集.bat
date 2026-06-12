@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 微信客情全量采集（请勿关闭本窗口）

REM 优先用确实装了依赖的 LibreOffice 自带 Python（找不到再回退到 PATH 里的 python）
set "PYEXE=C:\Program Files\LibreOffice\program\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo ============================================================
echo   微信客情 · 全量数据采集（资料 + 会话摘要模式）
echo ------------------------------------------------------------
echo   预计耗时：约 4~5 小时（约 8500+ 位好友）
echo   运行期间：脚本会自动操控微信，请勿移动鼠标/键盘、
echo             勿切换窗口，并保持微信在前台、保持登录。
echo   断点保护：每 50 人自动落盘，中途中断已采数据不丢。
echo   建议：睡前/外出前启动，挂着跑；关掉本窗口即可随时中止。
echo ============================================================
echo.
echo  小提示：建议先把电脑电源/睡眠设为"从不"，避免中途息屏休眠。
echo.
echo  准备好后按任意键开始采集……
pause >nul
echo.
echo [开始] %date% %time%
"%PYEXE%" rpa_extractor.py
echo.
echo [结束] %date% %time%
echo 采集完成（或已中断）。数据已保存到 wechat_data.json。
echo 接下来双击「启动看板.bat」即可查看全量数据。
echo.
echo 按任意键关闭本窗口。
pause >nul
