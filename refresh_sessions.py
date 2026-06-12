# -*- coding: utf-8 -*-
"""
refresh_sessions.py — 快速刷新「最近会话/最后对话时间」
======================================================
不重新遍历整个通讯录（那要数小时），只做一件事：
    读取微信「会话列表」里近期的聊天，更新已采客户的 最近消息 / 最后对话日期。
适合日常"看看最新动态"，约 1~2 分钟。

由看板上的〔⚡ 快速刷新最近会话〕按钮调用，也可单独运行：
    python refresh_sessions.py
"""
import json
import os
import sys

import rpa_extractor as R

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "wechat_data.json")


def main():
    if not os.path.exists(DATA):
        print("[FAIL] 未找到 wechat_data.json，请先做一次完整采集（运行采集.bat）")
        return

    data = json.load(open(DATA, encoding="utf-8"))
    print(f"已载入 {len(data)} 位客户，开始刷新最近会话……")

    win = R.get_wechat_window()
    session_map = R.build_session_map(win)      # 切到"微信"标签、滚动会话列表、解析最近消息

    updated = 0
    for rec in data:
        for key in (rec.get("remark"), rec.get("nickname")):   # 备注名/昵称匹配会话
            if key and key in session_map:
                last_msg, last_time = session_map[key]
                if last_msg:
                    rec["chat_history"] = [last_msg]
                if last_time:
                    rec["last_chat_time"] = last_time
                updated += 1
                break

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[DONE] 已更新 {updated} 位客户的最近消息/对话日期，保存完毕。")
    print("回到看板点〔🔁 重新加载已采数据〕即可看到最新信息。")


if __name__ == "__main__":
    main()
