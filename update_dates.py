# -*- coding: utf-8 -*-
"""
update_dates.py — 为已采集数据补「真实最后对话日期」
====================================================
只针对有聊天记录的好友重新打开聊天窗口、解析时间分隔行得到真实日期；
没有往来消息的好友 last_chat_time 置空。其余字段（昵称/地区/合作/坐标）保持不变。
"""
import json
import os
import sys
import time

import rpa_extractor as R

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "wechat_data.json")


def main():
    data = json.load(open(DATA, encoding="utf-8"))
    targets = [r for r in data if r.get("chat_history")]   # 仅有聊天记录的才有日期可解析
    print(f"共 {len(data)} 条，其中 {len(targets)} 条有聊天记录，开始补真实日期...")

    win = R.get_wechat_window()
    R.goto_contacts(win)
    time.sleep(1)

    updated = 0
    for i, rec in enumerate(data):
        if not rec.get("chat_history"):
            rec["last_chat_time"] = ""                     # 无往来消息 → 留空
            continue
        query = R.search_query_for(rec)
        try:
            history, last_date = R.extract_chat_by_search(win, query)
        except Exception as e:
            print(f"  [{query[:16]}] 异常: {e}")
            history, last_date = [], ""
        if history:
            rec["chat_history"] = history                  # 顺便刷新为最新消息
        rec["last_chat_time"] = last_date                  # 真实日期（解析不出则空）
        if last_date:
            updated += 1
        print(f"  {query[:18]:20} → 日期={last_date or '未解析'} | {len(history)}条")
        R.human_sleep()

    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n[DONE] 已为 {updated} 位好友写入真实最后对话日期，保存至 {DATA}")


if __name__ == "__main__":
    main()
