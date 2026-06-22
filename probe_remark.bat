@echo off
chcp 65001 >nul
cd /d "%~dp0"
title probe remark control - WeChat

set "PYEXE=C:\Program Files\LibreOffice\program\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo ============================================================
echo   探测微信『资料卡改备注』控件路径（一次性）
echo ------------------------------------------------------------
echo   先确认：PC 微信 4.x 已登录、在前台。
echo   运行时勿动鼠标键盘，让脚本自己操作。
echo ============================================================
echo.
"%PYEXE%" wx_remark_writer.py probe
echo.
echo ------------------------------------------------------------
echo 若上面提示已写出 remark_probe_tree.txt，回 Claude 说一声"跑完了"。
echo ------------------------------------------------------------
echo.
pause
