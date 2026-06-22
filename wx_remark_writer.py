# -*- coding: utf-8 -*-
"""
wx_remark_writer.py — 微信 PC 4.x「备注规范化」回写（RPA）
================================================================
路径已在 4.1.10.31 真机探明并验证：
  通讯录 → 搜索定位联系人 → 点资料卡右上「...」(Name 恰为 '备注') 弹菜单
  → 点『设置备注和标签』→ 弹窗 mmui::ProfileUniquePop
  → 编辑框 EditControl Name='修改备注名' 填新备注 → 按钮 Name='完成' 保存 / '取消' 放弃。

确认机制：备注的「确认」在看板「🏷️ 备注规范化」页逐个 ✅采纳时已完成，
故回写按批执行。但默认 dry_run=False 才真存；提供 dry 模式只演练不保存。

命令：
  单个测试（演练，不保存）：
    python wx_remark_writer.py test "搜索名" "新备注" dry
  单个真改：
    python wx_remark_writer.py test "搜索名" "新备注"
  批量回写队列 remark_change_queue.json（看板导出的）：
    python wx_remark_writer.py            # 真存
    python wx_remark_writer.py dry        # 全部只演练不存
"""
import json
import os
import sys
import time
import random

_HERE = os.path.dirname(os.path.abspath(__file__))
_libs = os.path.join(_HERE, "libs")
if os.path.isdir(_libs) and _libs not in sys.path:
    sys.path.insert(0, _libs)

import uiautomation as auto

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WECHAT_CLASS = "mmui::MainWindow"
DIALOG_CLASS = "mmui::ProfileUniquePop"
QUEUE_FILE = os.path.join(_HERE, "remark_change_queue.json")
DONE_FILE = os.path.join(_HERE, "remark_change_done.json")


def human_sleep(low=0.7, high=1.3):
    time.sleep(random.uniform(low, high))


def find_first(root, pred, max_depth=30):
    def walk(c, d):
        if d > max_depth:
            return None
        try:
            if pred(c):
                return c
            for ch in c.GetChildren():
                h = walk(ch, d + 1)
                if h is not None:
                    return h
        except Exception:
            pass
        return None
    return walk(root, 0)


def find_all(root, pred, max_depth=30):
    hits = []
    def walk(c, d):
        if d > max_depth:
            return
        try:
            if pred(c):
                hits.append(c)
            for ch in c.GetChildren():
                walk(ch, d + 1)
        except Exception:
            pass
    walk(root, 0)
    return hits


def id_endswith(c, leaf):
    aid = c.AutomationId or ""
    return aid == leaf or aid.endswith("." + leaf)


def get_wechat_window():
    win = auto.WindowControl(searchDepth=1, ClassName=WECHAT_CLASS)
    if not win.Exists(maxSearchSeconds=5):
        raise RuntimeError("未找到微信主窗口，请先启动并登录 PC 端微信 4.x！")
    if win.IsMinimize():
        try:
            win.ShowWindow(auto.SW.Restore)   # SW.Restore=9（此库无 ShowWindowState）
        except Exception:
            pass
        human_sleep()
    win.SetActive()
    human_sleep()
    return win


def get_search_box(win):
    return find_first(win, lambda c: c.ControlTypeName == "EditControl" and (c.Name or "") == "搜索")


# ---------------------------------------------------------------
# 导航：定位到联系人「资料卡」(mmui::DetailView)
# ---------------------------------------------------------------
def count_controls(c, max_depth=30):
    n = 0
    def walk(x, d):
        nonlocal n
        if d > max_depth:
            return
        try:
            n += 1
            for ch in x.GetChildren():
                walk(ch, d + 1)
        except Exception:
            pass
    walk(c, 0)
    return n


def _chat_info_btn(win):
    return find_first(win, lambda c: id_endswith(c, "more_button")
                      or (c.ControlTypeName == "ButtonControl" and (c.Name or "") == "聊天信息"))


def ensure_chat_info_panel(win):
    """『聊天信息』是开关按钮，确保打开：点后控件数没明显变多说明点关了，再点一次。"""
    b = _chat_info_btn(win)
    if b is None:
        return False
    before = count_controls(win)
    try:
        b.Click(simulateMove=True)
    except Exception:
        return False
    human_sleep(1.0, 1.5)
    if count_controls(win) <= before + 5:        # 没展开 → 再点一次
        b2 = _chat_info_btn(win)
        if b2 is not None:
            try:
                b2.Click(simulateMove=True)
                human_sleep(1.0, 1.5)
            except Exception:
                pass
    return True


def open_contact_card(win, query):
    """确认链路（4.1.10.31 真机验证）：
       搜索→点联系人开聊天 → 点『聊天信息』开面板 → 点头像 single_chat_member_cell → 弹资料卡。
       成功返回 True（资料卡的「...」按钮可见），否则 False。"""
    search = get_search_box(win)
    if search is None:
        return False
    search.Click(simulateMove=True)
    human_sleep(0.4, 0.7)
    search.SendKeys("{Ctrl}a", waitTime=0.1)
    search.SendKeys("{Delete}", waitTime=0.1)
    try:
        auto.SetClipboardText(query)
    except Exception:
        return False
    search.SendKeys("{Ctrl}v", waitTime=0.1)
    human_sleep(1.3, 1.9)

    # 搜索结果里点联系人项 → 打开聊天
    slist = find_first(win, lambda c: id_endswith(c, "search_list"))
    cells = []
    if slist is not None:
        cells = [c for c in slist.GetChildren()
                 if "search_item_" in (c.AutomationId or "") or "CellView" in (c.ClassName or "")]
    target = None
    for c in cells:
        if (c.Name or "").strip() == query:
            target = c
            break
    if target is None:
        for c in cells:
            if query in (c.Name or ""):
                target = c
                break
    if target is None:
        return False
    target.Click(simulateMove=True)
    human_sleep(1.1, 1.6)

    # 开『聊天信息』面板 → 点头像进资料卡
    ensure_chat_info_panel(win)
    avatar = find_first(win, lambda c: id_endswith(c, "single_chat_member_cell")
                        or (c.ControlTypeName == "ButtonControl" and c.ClassName == "mmui::ChatMemberCell"))
    if avatar is None:
        return False
    try:
        avatar.Click(simulateMove=True)
        human_sleep(1.0, 1.5)
    except Exception:
        return False
    # 资料卡出现的标志：能找到「...」更多按钮（Name 恰为 '备注'）
    for _ in range(5):
        if find_more_button() is not None:
            return True
        human_sleep(0.4, 0.7)
    return False


# ---------------------------------------------------------------
# 触发改备注弹窗 + 填入 + 保存/取消
# ---------------------------------------------------------------
def find_card_window():
    """联系人资料卡弹窗：class=mmui::ProfileUniquePop 且含资料明细(ProfileDetail* / 头像)。
    注意改备注对话框也是 ProfileUniquePop，靠是否含『修改备注名』编辑框区分（卡片没有）。"""
    root = auto.GetRootControl()
    for w in root.GetChildren():
        if (w.ClassName or "") != DIALOG_CLASS:
            continue
        if find_first(w, lambda c: c.ControlTypeName == "EditControl"
                      and (c.Name or "") == "修改备注名"):
            continue   # 这是改备注对话框，不是卡片
        if find_first(w, lambda c: "ProfileDetail" in (c.ClassName or "")
                      or id_endswith(c, "head_view_")):
            return w
    return None


def find_more_button():
    """资料卡弹窗右上角「...」更多按钮（弹窗卡片里 Name='更多'；在窗内找避免误中主窗"更多"tab）。"""
    card = find_card_window()
    if card is None:
        return None
    return find_first(card, lambda c: c.ControlTypeName == "ButtonControl"
                      and (c.Name or "") in ("更多", "备注", "...")
                      and (c.ClassName or "").startswith("mmui::XButton"))


def find_edit_dialog():
    """改备注对话框：含『修改备注名』编辑框的 ProfileUniquePop。"""
    root = auto.GetRootControl()
    for w in root.GetChildren():
        if (w.ClassName or "") != DIALOG_CLASS:
            continue
        if find_first(w, lambda c: c.ControlTypeName == "EditControl"
                      and (c.Name or "") == "修改备注名"):
            return w
    return None


def open_remark_dialog():
    """点资料卡「...」→『设置备注和标签』，返回改备注对话框窗口或 None。"""
    more = find_more_button()
    if more is None:
        return None
    try:
        more.Click(simulateMove=True)
        human_sleep(0.8, 1.2)
    except Exception:
        return None
    root = auto.GetRootControl()
    item = find_first(root, lambda c: "设置备注和标签" in (c.Name or "")
                      and c.ControlTypeName in ("ButtonControl", "MenuItemControl", "TextControl"))
    if item is None:
        return None
    try:
        item.Click(simulateMove=True)
        human_sleep(0.9, 1.3)
    except Exception:
        return None
    for _ in range(5):
        dlg = find_edit_dialog()
        if dlg is not None:
            return dlg
        human_sleep(0.4, 0.7)
    return None


def set_remark(win, new_remark, dry_run=False):
    """对当前资料卡执行改备注。返回 (ok, msg)。dry_run=True 则只填不保存（点取消）。"""
    try:
        auto.SetClipboardText(new_remark)
    except Exception:
        pass
    pop = open_remark_dialog()
    if pop is None:
        return False, "没能打开『设置备注和标签』弹窗"
    edit = find_first(pop, lambda c: c.ControlTypeName == "EditControl"
                      and (c.Name or "") == "修改备注名")
    if edit is None:
        edit = find_first(pop, lambda c: c.ControlTypeName == "EditControl")
    if edit is None:
        # 关掉弹窗避免残留
        _click_dialog_btn(pop, "取消")
        return False, "弹窗里没找到备注名输入框"
    try:
        edit.Click(simulateMove=True)
        human_sleep(0.3, 0.5)
        edit.SendKeys("{Ctrl}a", waitTime=0.05)
        edit.SendKeys("{Delete}", waitTime=0.05)
        edit.SendKeys("{Ctrl}v", waitTime=0.1)
        human_sleep(0.3, 0.6)
    except Exception:
        _click_dialog_btn(pop, "取消")
        return False, "填入备注失败"
    if dry_run:
        _click_dialog_btn(pop, "取消")
        return True, "演练成功：已填入但按取消未保存"
    if _click_dialog_btn(pop, "完成"):
        return True, "已保存（点了完成）"
    return False, "没点到完成按钮"


def _click_dialog_btn(pop, name):
    btn = find_first(pop, lambda c: c.ControlTypeName == "ButtonControl" and (c.Name or "") == name)
    if btn is None:
        return False
    try:
        btn.Click(simulateMove=True)
        human_sleep(0.6, 1.0)
        return True
    except Exception:
        return False


def change_one(win, query, new_remark, dry_run=False):
    """完整一条：定位联系人→改备注。返回 (ok, msg)。"""
    if not open_contact_card(win, query):
        return False, f"没定位到联系人资料卡：{query}"
    return set_remark(win, new_remark, dry_run=dry_run)


# ---------------------------------------------------------------
# 入口
# ---------------------------------------------------------------
def main():
    args = sys.argv[1:]

    if args and args[0] == "test":
        query = args[1] if len(args) > 1 else ""
        new_remark = args[2] if len(args) > 2 else ""
        dry = (len(args) > 3 and args[3] == "dry")
        if not query or not new_remark:
            print('用法：wx_remark_writer.py test "搜索名" "新备注" [dry]')
            return
        win = get_wechat_window()
        ok, msg = change_one(win, query, new_remark, dry_run=dry)
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
        return

    dry_all = bool(args and args[0] == "dry")
    if not os.path.exists(QUEUE_FILE):
        print(f"[ERR] 找不到队列 {QUEUE_FILE}。请先在看板「🏷️ 备注规范化」页导出。")
        return
    data = json.load(open(QUEUE_FILE, encoding="utf-8"))
    items = data.get("items", [])
    if not items:
        print("[队列为空] remark_change_queue.json 里没有条目，所以没改任何东西。")
        print("  → 请回看板「🏷️ 备注规范化」页：先逐个 ✅采纳几位，再点〔① 生成回写队列〕，")
        print("    然后再点〔🚀 开始回写〕。")
        return
    print(f"== 备注回写：共 {len(items)} 条（{'演练不保存' if dry_all else '真写入'}）==")
    win = get_wechat_window()
    done, failed, results = [], [], []
    for i, it in enumerate(items, 1):
        q = it.get("search") or it.get("name")
        new = it.get("new_remark", "")
        print(f"[{i}/{len(items)}] {it.get('name')}  → {new}")
        ok, msg = change_one(win, q, new, dry_run=dry_all)
        print(f"     {'OK' if ok else 'FAIL'}: {msg}")
        (done if ok else failed).append(it.get("wxid"))
        results.append({"wxid": it.get("wxid"), "name": it.get("name"),
                        "old_remark": it.get("old_remark", ""), "new_remark": new,
                        "ok": ok, "msg": msg})
        # 实时落盘：中途关窗也能在看板看到已处理部分
        json.dump({"mode": "dry" if dry_all else "write", "total": len(items),
                   "ok": len(done), "failed": len(failed),
                   "done": done, "failed_ids": failed, "results": results},
                  open(DONE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        human_sleep(1.0, 2.0)   # 防风控
    print(f"\n[完成] 成功 {len(done)} / 失败 {len(failed)}，记录 → {DONE_FILE}")
    if failed:
        print("失败的（回看板『上次回写结果』可看原因）：")
        for r in results:
            if not r["ok"]:
                print(f"  - {r['name']}: {r['msg']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print("\n[出错] 回写脚本异常：")
        traceback.print_exc()
    # 让黑窗别秒关，看清结果/错误（从看板按钮启动时尤其重要）
    try:
        input("\n按回车关闭本窗口……")
    except EOFError:
        pass
