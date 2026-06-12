# -*- coding: utf-8 -*-
"""
run_dashboard.py — 看板启动器（一个进程：本地libs上路径 + 起服务 + 自动开Chrome）
==================================================================================
依赖统一装在项目内的 libs 文件夹（不依赖用户目录，双击/cmd 都能找到），
本文件把它加进搜索路径后再启动 streamlit。桌面快捷方式直接 python run_dashboard.py。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 关键：依赖装在项目内 libs（任何启动方式都能访问），插到最前面
_libs = os.path.join(HERE, "libs")
if os.path.isdir(_libs) and _libs not in sys.path:
    sys.path.insert(0, _libs)

PORT, URL = 8501, "http://localhost:8501"
_CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]


def _open_browser_when_ready():
    import socket, subprocess, time
    for _ in range(120):
        try:
            s = socket.create_connection(("localhost", PORT), timeout=1)
            s.close()
            time.sleep(1.0)
            chrome = next((c for c in _CHROME if os.path.exists(c)), None)
            try:
                subprocess.Popen([chrome, URL]) if chrome else os.startfile(URL)
            except Exception:
                os.startfile(URL)
            return
        except OSError:
            time.sleep(1.0)


def main():
    import threading
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", os.path.join(HERE, "crm_dashboard.py")]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
