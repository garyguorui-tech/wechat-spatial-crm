# -*- coding: utf-8 -*-
"""
rpa_extractor.py — 微信 PC 端 4.x 客情数据提取脚本（RPA）
=========================================================
适配版本：微信 Windows 4.1（mmui:: Qt 控件框架，已在真机控件树上验证）

为什么重写：
    微信 4.x 是全新的 Qt 重构版本，老的 WeChatMainWndForPC 窗口类名已废弃，
    控件树结构与 3.x 完全不同。本脚本所用的所有 ClassName / AutomationId
    均来自对微信 4.1 真实控件树的实地探测（见同目录 uia_*.txt 探测产物）。

核心控件锚点（微信 4.1）：
    主窗口        ClassName = "mmui::MainWindow", Name = "微信"
    导航栏        ToolBar Name="导航" → Button Name="通讯录"
    通讯录列表    AutomationId 以 ".contact_list" 结尾（虚拟滚动列表）
    好友单元格    ClassName = "mmui::ContactsCellItemView"
    资料面板      ClassName = "mmui::DetailView"
      昵称        基础行 key="昵称："  value=ProfileTextView
      地区        基础行 key="地区："  value=ProfileTextView
      备注        remark_line          value 按钮 Name 即备注
      标签        tag_line             value_reader 文本
    发消息按钮    AutomationId 以 ".chat_img_button" 结尾, Name="发消息"
    聊天消息列表  AutomationId = "chat_message_list"
      文本消息    ClassName = "mmui::ChatTextItemView"（Name 即正文）
      时间戳行    ClassName = "mmui::ChatItemView"（Name 如 "10:13"）

防风控：每个动作之间 1~2 秒随机延时；全程 try-except 容错，单点失败不中断整体。
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta

# 关键：依赖统一装在项目内 libs 文件夹（不依赖用户目录，双击/cmd 都能找到）
_libs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
if os.path.isdir(_libs) and _libs not in sys.path:
    sys.path.insert(0, _libs)

import uiautomation as auto

# 让控制台正确输出中文（Windows 默认 GBK 控制台会把中文打成乱码）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# 全局配置
# ============================================================
WECHAT_CLASS_NAME = "mmui::MainWindow"   # 微信 4.x 主窗口类名
OUTPUT_FILE = "wechat_data.json"
import os as _os                         # 允许看板按钮通过环境变量 WX_MAX_CONTACTS 指定采集人数
MAX_CONTACTS = int(_os.environ.get("WX_MAX_CONTACTS", "99999"))   # 默认全量；遍历到底部自动停止
MAX_CHAT_MESSAGES = 10                   # 每个好友最多提取的聊天条数
EXTRACT_CHAT = True                      # 是否提取聊天消息
CHAT_MODE = "session"                    # 聊天提取方式（全量推荐 session）：
                                         #   "session" = 仅解析会话列表（快，覆盖近期有会话的客户，风控风险低）★全量用这个
                                         #   "search"  = 逐个搜索好友打开聊天窗口取真实消息（慢，全量约 +12h，不建议）
CHECKPOINT_EVERY = 50                    # 每采集多少人增量落盘一次（断点保护，全量用 50 减少磁盘开销）
ADVANCE_MAX_PUSH = 25                    # 找下一个好友时最多连按多少次 DOWN（跨过"已停用账号"等空白/卡点）
SKIP_NAMES = {"已停用的微信用户"}          # 这些显示名视为空白项，遍历时跳过、不作为到底信号

# 资料卡字段标签（去掉冒号后的标准键名）
PROFILE_LABELS = {"昵称", "微信号", "地区", "备注", "标签", "描述", "来源", "添加时间"}

# ============================================================
# 离线地名库（地理编码）：把真实"地区/备注/标签"里的地名解析为经纬度。
# 完全离线、确定性、不依赖外部 API。覆盖：中国省级+主要城市、常见区县、海外国家/城市。
# ============================================================
# 直辖市/省会/主要城市坐标 (lat, lng)
_CITY_COORDS = {
    # 直辖市
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737),
    "天津": (39.0842, 117.2009), "重庆": (29.5630, 106.5516),
    # 省会及主要城市
    "广州": (23.1291, 113.2644), "深圳": (22.5431, 114.0579),
    "东莞": (23.0207, 113.7518), "佛山": (23.0218, 113.1219),
    "杭州": (30.2741, 120.1551), "宁波": (29.8683, 121.5440),
    "南京": (32.0603, 118.7969), "苏州": (31.2989, 120.5853),
    "镇江": (32.1880, 119.4250), "无锡": (31.4912, 120.3119),
    "福州": (26.0745, 119.2965), "厦门": (24.4798, 118.0894),
    "合肥": (31.8206, 117.2290), "武汉": (30.5928, 114.3055),
    "荆州": (30.3346, 112.2410), "石家庄": (38.0428, 114.5149),
    "沧州": (38.3037, 116.8388), "邯郸": (36.6256, 114.5391),
    "郑州": (34.7466, 113.6254), "济南": (36.6512, 117.1201),
    "青岛": (36.0671, 120.3826), "成都": (30.5728, 104.0668),
    "西安": (34.3416, 108.9398), "长沙": (28.2282, 112.9388),
    "沈阳": (41.8057, 123.4315), "大连": (38.9140, 121.6147),
    "乌鲁木齐": (43.8256, 87.6168), "伊犁": (43.9219, 81.3179),
    "南昌": (28.6829, 115.8579), "昆明": (24.8801, 102.8329),
    "贵阳": (26.6470, 106.6302), "南宁": (22.8170, 108.3665),
    "太原": (37.8706, 112.5489), "兰州": (36.0611, 103.8343),
    "哈尔滨": (45.8038, 126.5350), "长春": (43.8171, 125.3235),
    "呼和浩特": (40.8426, 111.7510), "银川": (38.4872, 106.2309),
    "西宁": (36.6171, 101.7782), "海口": (20.0440, 110.1999),
    "拉萨": (29.6520, 91.1721),
}
# 省/自治区/特别行政区 → 代表城市坐标（只给省名时用）
_PROVINCE_COORDS = {
    "广东": _CITY_COORDS["广州"], "浙江": _CITY_COORDS["杭州"],
    "江苏": _CITY_COORDS["南京"], "福建": _CITY_COORDS["福州"],
    "安徽": _CITY_COORDS["合肥"], "湖北": _CITY_COORDS["武汉"],
    "河北": _CITY_COORDS["石家庄"], "河南": _CITY_COORDS["郑州"],
    "山东": _CITY_COORDS["济南"], "四川": _CITY_COORDS["成都"],
    "陕西": _CITY_COORDS["西安"], "湖南": _CITY_COORDS["长沙"],
    "辽宁": _CITY_COORDS["沈阳"], "新疆": _CITY_COORDS["乌鲁木齐"],
    "江西": _CITY_COORDS["南昌"], "云南": _CITY_COORDS["昆明"],
    "贵州": _CITY_COORDS["贵阳"], "广西": _CITY_COORDS["南宁"],
    "山西": _CITY_COORDS["太原"], "甘肃": _CITY_COORDS["兰州"],
    "黑龙江": _CITY_COORDS["哈尔滨"], "吉林": _CITY_COORDS["长春"],
    "内蒙古": _CITY_COORDS["呼和浩特"], "宁夏": _CITY_COORDS["银川"],
    "青海": _CITY_COORDS["西宁"], "海南": _CITY_COORDS["海口"],
    "西藏": _CITY_COORDS["拉萨"],
    "香港": (22.3193, 114.1694), "中国香港": (22.3193, 114.1694),
    "澳门": (22.1987, 113.5439), "中国澳门": (22.1987, 113.5439),
    "台湾": (25.0330, 121.5654), "中国台湾": (25.0330, 121.5654),
}
# 海外国家 → 代表城市，以及常见海外城市
_FOREIGN_COORDS = {
    "中国": (35.8617, 104.1954),
    "美国": (38.9072, -77.0369), "纽约": (40.7128, -74.0060),
    "圣迭戈": (32.7157, -117.1611), "洛杉矶": (34.0522, -118.2437),
    "旧金山": (37.7749, -122.4194), "加利福尼亚州": (36.7783, -119.4179),
    "纽约州": (40.7128, -74.0060),
    "英国": (51.5074, -0.1278), "英格兰": (51.5074, -0.1278), "伦敦": (51.5074, -0.1278),
    "法国": (48.8566, 2.3522), "巴黎": (48.8566, 2.3522),
    "意大利": (41.9028, 12.4964), "罗马": (41.9028, 12.4964),
    "德国": (52.5200, 13.4050), "柏林": (52.5200, 13.4050),
    "荷兰": (52.3676, 4.9041), "阿姆斯特丹": (52.3676, 4.9041),
    "爱尔兰": (53.3498, -6.2603), "都柏林": (53.3498, -6.2603),
    "日本": (35.6762, 139.6503), "东京": (35.6762, 139.6503), "东京都": (35.6762, 139.6503),
    "韩国": (37.5665, 126.9780), "首尔": (37.5665, 126.9780),
    "新加坡": (1.3521, 103.8198), "台北": (25.0330, 121.5654),
    "加拿大": (45.4215, -75.6972), "澳大利亚": (-33.8688, 151.2093),
    "悉尼": (-33.8688, 151.2093), "墨尔本": (-37.8136, 144.9631),
    # 更多国家（命中国名时定位到首都），避免落到标签里的国内城市
    "墨西哥": (19.43, -99.13), "巴西": (-15.79, -47.88), "阿根廷": (-34.60, -58.38),
    "智利": (-33.45, -70.67), "西班牙": (40.42, -3.70), "葡萄牙": (38.72, -9.14),
    "比利时": (50.85, 4.35), "瑞士": (46.95, 7.45), "奥地利": (48.21, 16.37),
    "瑞典": (59.33, 18.07), "挪威": (59.91, 10.75), "丹麦": (55.68, 12.57),
    "芬兰": (60.17, 24.94), "波兰": (52.23, 21.01), "希腊": (37.98, 23.73),
    "捷克": (50.08, 14.44), "俄罗斯": (55.76, 37.62), "乌克兰": (50.45, 30.52),
    "土耳其": (39.93, 32.86), "朝鲜": (39.04, 125.76), "马来西亚": (3.14, 101.69),
    "泰国": (13.76, 100.50), "越南": (21.03, 105.85), "菲律宾": (14.60, 120.98),
    "印度尼西亚": (-6.21, 106.85), "印尼": (-6.21, 106.85), "印度": (28.61, 77.21),
    "巴基斯坦": (33.69, 73.06), "孟加拉国": (23.81, 90.41), "斯里兰卡": (6.93, 79.86),
    "尼泊尔": (27.72, 85.32), "阿联酋": (24.45, 54.38), "沙特阿拉伯": (24.71, 46.68),
    "沙特": (24.71, 46.68), "卡塔尔": (25.29, 51.53), "以色列": (31.77, 35.21),
    "伊朗": (35.69, 51.39), "约旦": (31.95, 35.93), "黎巴嫩": (33.89, 35.50),
    "埃及": (30.04, 31.24), "南非": (-25.75, 28.19), "尼日利亚": (9.08, 7.40),
    "肯尼亚": (-1.29, 36.82), "摩洛哥": (34.02, -6.83), "埃塞俄比亚": (9.03, 38.74),
    "中非共和国": (4.39, 18.56), "坦桑尼亚": (-6.16, 35.75), "加纳": (5.60, -0.19),
    "新西兰": (-41.29, 174.78), "哈萨克斯坦": (51.16, 71.47), "蒙古": (47.89, 106.91),
}
# 区县 → 所属城市坐标（命中区县时定位到城市）
_BJ, _SH, _HK = (39.9042, 116.4074), (31.2304, 121.4737), (22.3193, 114.1694)
_DISTRICT_COORDS = {}
for _d in "朝阳 东城 西城 海淀 房山 密云 丰台 通州 昌平 大兴 顺义 石景山 门头沟 平谷 怀柔 延庆".split():
    _DISTRICT_COORDS[_d] = _BJ
for _d in "浦东新区 浦东 徐汇 静安 黄浦 嘉定 长宁 普陀 虹口 杨浦 闵行 宝山 松江 青浦 奉贤 金山 崇明".split():
    _DISTRICT_COORDS[_d] = _SH
for _d in "湾仔区 湾仔 中西区 东区 南区 九龙 油尖旺 深水埗".split():
    _DISTRICT_COORDS[_d] = _HK

# 合并为统一地名库（城市优先级最高，其次区县/省/海外）
PLACE_COORDS = {**_PROVINCE_COORDS, **_FOREIGN_COORDS, **_DISTRICT_COORDS, **_CITY_COORDS}


def human_sleep(low: float = 1.0, high: float = 2.0) -> None:
    """防风控随机延时：模拟真人操作节奏"""
    time.sleep(random.uniform(low, high))


# ============================================================
# 通用控件查找工具
# ============================================================
def find_first(root: auto.Control, predicate, max_depth: int = 26):
    """
    深度优先递归查找首个满足 predicate 的控件。
    微信 4.x 的 mmui 框架上，uiautomation 内置的条件搜索不够稳定，
    手动遍历反而更可靠（控件树虽深但单页节点有限）。
    """
    def walk(ctrl, depth):
        if depth > max_depth:
            return None
        try:
            if predicate(ctrl):
                return ctrl
            for child in ctrl.GetChildren():
                hit = walk(child, depth + 1)
                if hit is not None:
                    return hit
        except Exception:
            pass
        return None
    return walk(root, 0)


def id_endswith(ctrl: auto.Control, leaf: str) -> bool:
    """判断控件 AutomationId 是否等于 leaf 或以 '.leaf' 结尾（4.x 的 AutoId 是点分长路径）"""
    aid = ctrl.AutomationId or ""
    return aid == leaf or aid.endswith("." + leaf)


# ============================================================
# Step 1: 锁定微信主窗口
# ============================================================
def get_wechat_window() -> auto.WindowControl:
    """查找、还原（若最小化）、激活并置顶微信主窗口"""
    win = auto.WindowControl(searchDepth=1, ClassName=WECHAT_CLASS_NAME)
    if not win.Exists(maxSearchSeconds=5):
        raise RuntimeError("未找到微信主窗口，请先启动并登录 PC 端微信 4.x！")

    if win.IsMinimize():                              # 最小化时先还原，否则点击会落空
        win.ShowWindow(auto.ShowWindowState.Restore)
        human_sleep()
    win.SetActive()
    human_sleep()
    print("[OK] 已锁定微信主窗口")
    return win


# ============================================================
# Step 2: 进入通讯录并定位列表
# ============================================================
def goto_contacts(win: auto.WindowControl) -> auto.Control:
    """
    点击导航栏"通讯录"，返回好友列表控件。
    通讯录视图是懒加载的，点击后带 3 次重试等待列表挂载。
    """
    nav = win.ToolBarControl(Name="导航")
    contacts_btn = nav.ButtonControl(Name="通讯录")
    if not contacts_btn.Exists(maxSearchSeconds=3):
        raise RuntimeError("未找到导航栏'通讯录'按钮，微信版本可能不兼容")

    contact_list = None
    for attempt in range(3):
        contacts_btn.Click(simulateMove=True)
        time.sleep(1.5 + attempt)                    # 每次重试多等 1 秒
        contact_list = find_first(win, lambda c: id_endswith(c, "contact_list"))
        if contact_list is not None:
            break
        print(f"  [RETRY {attempt + 1}] 通讯录列表未挂载，重试...")

    if contact_list is None:
        raise RuntimeError("进入通讯录后未找到好友列表控件")
    print("[OK] 已进入通讯录")
    return contact_list


def get_selected_name(win: auto.WindowControl) -> str:
    """读取当前资料面板顶部的显示名（display_name_text），用于判断选中项是否已切换"""
    ctrl = find_first(win, lambda c: id_endswith(c, "display_name_text"))
    return (ctrl.Name or "").strip() if ctrl else ""


def _first_visible_friend(contact_list: auto.Control):
    """返回当前可见区域里第一个真实好友单元格（ContactsCellItemView），没有则 None。
    需跳过顶部的'新的朋友/群聊/公众号...'分组入口（ContactsCellGroupView）
    和字母分隔行（ContactsCellClassifyView）。"""
    for item in contact_list.GetChildren():
        if item.ClassName == "mmui::ContactsCellItemView" and (item.Name or "").strip():
            return item
    return None


def focus_first_contact(contact_list: auto.Control) -> bool:
    """
    定位并选中通讯录里的「第一个好友」，建立键盘焦点，供后续 {DOWN} 遍历。

    关键：通讯录顶部是"新的朋友/群聊/公众号.../联系人N"这些分组入口，好友列表
    默认折叠在"联系人"分组之下。直接读列表往往只看到这些分组项、看不到好友。
    实测可靠做法：点击名为"联系人NNNN"的分组项，即可展开并跳到好友区顶部，
    随后点击第一个好友单元格建立键盘焦点，后续纯 {DOWN} 即可顺序遍历全部好友。
    """
    # 1) 若当前看不到好友项，点击"联系人"分组展开/跳转到好友区
    if _first_visible_friend(contact_list) is None:
        for c in contact_list.GetChildren():
            if c.ClassName == "mmui::ContactsCellGroupView" and (c.Name or "").startswith("联系人"):
                c.Click(simulateMove=True)
                human_sleep(1.0, 1.5)
                break

    # 2) 点击第一个好友单元格：建立键盘焦点 + 选中列表第一个好友
    item = _first_visible_friend(contact_list)
    if item is None:
        return False
    item.Click(simulateMove=True)
    human_sleep()
    return True


# ============================================================
# Step 3: 从资料面板提取昵称/备注/地区/标签
# ============================================================
def extract_profile(win: auto.WindowControl) -> dict:
    """
    解析右侧 DetailView 资料面板。
    策略：按控件树深度优先顺序遍历，"标签文本(key)在前、值文本(value)在后"，
    据此把 昵称：/地区：/备注/标签 等键值配对，对 4.x 各种行型都通用。
    """
    profile = {"nickname": "", "remark": "", "region": "", "tags": "", "wxid": ""}

    detail = find_first(win, lambda c: c.ClassName == "mmui::DetailView")
    if detail is None:
        return profile

    kv = {}            # 配对结果：{标准键名: 值}
    display_name = ""  # 资料卡顶部大号显示名（备注优先，无备注则昵称）
    pending_label = [None]

    def visit(ctrl, depth):
        if depth > 24:
            return
        try:
            cls = ctrl.ClassName or ""
            name = (ctrl.Name or "").strip()

            # 顶部显示名
            if id_endswith(ctrl, "display_name_text") and name:
                nonlocal_display(name)

            if cls == "mmui::XTextView" and name:
                key = name.rstrip("：:")
                if key in PROFILE_LABELS:        # 这是一个字段标签，记下来等下一个值
                    pending_label[0] = key
            elif cls == "mmui::ProfileTextView" and name:
                if pending_label[0]:             # 紧跟标签的第一个值文本即该字段的值
                    kv.setdefault(pending_label[0], name)
                    pending_label[0] = None

            for child in ctrl.GetChildren():
                visit(child, depth + 1)
        except Exception:
            pass

    def nonlocal_display(v):
        nonlocal display_name
        if not display_name:
            display_name = v

    visit(detail, 0)

    profile["nickname"] = kv.get("昵称") or display_name
    profile["remark"] = kv.get("备注") or display_name
    profile["region"] = kv.get("地区", "")
    profile["tags"] = kv.get("标签", "")
    profile["wxid"] = kv.get("微信号", "")     # 微信号全局唯一，用作去重/到底判断的稳定主键
    return profile


# ============================================================
# Step 4: 解析会话列表，获取每个好友的最近一条消息与时间
# ============================================================
def _parse_session_time(raw: str) -> str:
    """
    把会话单元格里的时间串归一化为 YYYY-MM-DD：
      "10:34"  → 今天（HH:MM 表示当天）
      "06/02"  → 今年 06-02（MM/DD）
      "昨天"   → 昨天
      "2026年6月1日" / "2026-06-01" → 对应日期
    无法解析则返回空串（交给 mock_enrich 兜底）。
    """
    today = datetime.now()
    raw = raw.strip()
    if re.match(r"^\d{1,2}:\d{2}$", raw):                       # 当天
        return today.strftime("%Y-%m-%d")
    if raw == "昨天":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    m = re.match(r"^(\d{1,2})/(\d{1,2})$", raw)                 # MM/DD（默认今年）
    if m:
        try:
            return datetime(today.year, int(m.group(1)), int(m.group(2))).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    m = re.match(r"^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    return ""


def build_session_map(win: auto.WindowControl) -> dict:
    """
    切到"微信"标签，读取会话列表（session_list），把每个会话的
    最近一条消息和时间解析出来，返回 {会话名: (最近消息, YYYY-MM-DD)}。

    优势：会话单元格的 Name 本身就含"名称\\n[N条]\\n最近消息\\n时间\\n"，
    直接解析即可拿到真实聊天摘要，无需逐个打开聊天窗口——
    既不破坏通讯录的遍历状态，也大幅降低风控风险。
    """
    session_map = {}
    nav = win.ToolBarControl(Name="导航")
    wechat_btn = nav.ButtonControl(Name="微信")
    if not wechat_btn.Exists(maxSearchSeconds=3):
        print("  [WARN] 未找到导航栏'微信'按钮，跳过会话解析")
        return session_map
    wechat_btn.Click(simulateMove=True)
    human_sleep(1.5, 2.0)

    session_list = find_first(win, lambda c: id_endswith(c, "session_list"))
    if session_list is None:
        print("  [WARN] 未找到会话列表，跳过会话解析")
        return session_map

    def parse_visible():
        """解析当前可见的会话单元格，并入 session_map。"""
        for cell in session_list.GetChildren():
            try:
                raw = cell.Name or ""
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
                lines = [ln for ln in lines
                         if ln not in ("已置顶", "消息免打扰") and not re.match(r"^\[\d+条\]$", ln)]
                if len(lines) < 2:
                    continue
                name = lines[0]
                time_str = ""
                if re.match(r"^(\d{1,2}:\d{2}|\d{1,2}/\d{1,2}|昨天|星期.|\d{4}[-/年].*)$", lines[-1]):
                    time_str = lines[-1]
                    msg_lines = lines[1:-1]
                else:
                    msg_lines = lines[1:]
                last_msg = msg_lines[-1] if msg_lines else ""
                last_msg = re.sub(r"^[^:：]{1,20}[:：]\s*", "", last_msg)
                if name not in session_map:          # 已解析过的会话不覆盖
                    session_map[name] = (last_msg, _parse_session_time(time_str))
            except Exception:
                continue

    # 滚动会话列表，尽量多加载一些会话（虚拟列表只挂载可见项，需边滚边解析）
    parse_visible()
    stale_rounds = 0
    for _ in range(60):                              # 上限 60 屏，足够覆盖数百个会话
        prev_count = len(session_map)
        try:
            session_list.WheelDown(wheelTimes=8, waitTime=0.05)
        except Exception:
            break
        human_sleep(0.4, 0.7)
        parse_visible()
        if len(session_map) == prev_count:           # 连续没有新增 → 已到会话列表底部
            stale_rounds += 1
            if stale_rounds >= 3:
                break
        else:
            stale_rounds = 0

    print(f"[OK] 已解析 {len(session_map)} 个会话的最近消息")
    return session_map


# ============================================================
# Step 4b: 逐个搜索好友 → 打开聊天窗口 → 提取真实最近消息
# ============================================================
_WEEKDAYS = {"星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3,
             "星期五": 4, "星期六": 5, "星期日": 6, "星期天": 6}


def parse_chat_date(text: str) -> str:
    """
    把聊天里的「时间分隔行」文本解析为真实日期 YYYY-MM-DD。支持微信 4.x 的全部格式：
      "10:34"            → 今天
      "昨天 14:30"        → 昨天
      "星期三 09:12"      → 最近一个过去的周三（7 天内）
      "5月28日 12:09"     → 今年 5-28（若该日尚未到，则按去年算）
      "2025年12月21日 18:03" → 2025-12-21
    解析不出则返回空串。
    """
    today = datetime.now()
    text = (text or "").strip()

    if re.match(r"^\d{1,2}:\d{2}$", text):                         # 今天
        return today.strftime("%Y-%m-%d")
    if text.startswith("昨天"):
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    for wd, idx in _WEEKDAYS.items():                              # 星期X → 最近的那天
        if text.startswith(wd):
            delta = (today.weekday() - idx) % 7
            delta = 7 if delta == 0 else delta                    # 同为周X时取上周（聊天分隔不会标“今天”为星期X）
            return (today - timedelta(days=delta)).strftime("%Y-%m-%d")

    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)        # 含年份的完整日期
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            return ""

    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)                # 今年的 M月D日
    if m:
        try:
            d = datetime(today.year, int(m.group(1)), int(m.group(2)))
            if d > today:                                         # 日期还没到 → 实为去年
                d = datetime(today.year - 1, int(m.group(1)), int(m.group(2)))
            return d.strftime("%Y-%m-%d")
        except ValueError:
            return ""
    return ""


def _parse_chat_list(msg_list: auto.Control) -> tuple:
    """从聊天消息列表控件解析消息，返回 (chat_history, last_chat_date)。
    - 文本气泡 ChatTextItemView      → 收录正文（仅保留最后 MAX_CHAT_MESSAGES 条）
    - 时间分隔行 ChatItemView         → 取最后一个，解析成真实日期 YYYY-MM-DD
    - 引用/图片/语音等其它气泡        → 以占位符标记后收录
    """
    history, last_date = [], ""
    try:
        children = msg_list.GetChildren()
    except Exception:
        return history, last_date

    # 先在全部已挂载子项里找“最后一个时间分隔行”，解析为真实日期
    for item in children:
        try:
            if item.ClassName == "mmui::ChatItemView":
                d = parse_chat_date(item.Name or "")
                if d:
                    last_date = d                                 # 越靠后越新，循环结束即最新
        except Exception:
            continue

    # 再取最后 N 条消息正文
    for item in children[-MAX_CHAT_MESSAGES:]:
        try:
            cls = item.ClassName or ""
            text = (item.Name or "").strip()
            if not text:
                continue
            if cls == "mmui::ChatTextItemView":
                history.append(text)
            elif cls == "mmui::ChatItemView":
                continue                                          # 时间行不计入正文
            else:
                history.append(f"<非文本:{text[:10]}>")
        except Exception:
            continue
    return history, last_date


def get_search_box(win: auto.WindowControl):
    """获取顶部搜索框（EditControl Name='搜索'）；微信/通讯录视图都存在。"""
    return find_first(win, lambda c: c.ControlTypeName == "EditControl" and (c.Name or "") == "搜索")


def extract_chat_by_search(win: auto.WindowControl, query: str) -> tuple:
    """
    用搜索框定位好友 → 点击搜索结果打开聊天窗口 → 提取最近消息。
    位置无关，不依赖通讯录遍历状态，适合对全部好友逐个取真实聊天。

    返回 (chat_history, last_chat_time)；找不到/无消息则返回空。
    输入名字用「剪贴板粘贴」而非 SendKeys，避免名字里的 () + ^ 等被当作快捷键转义。
    """
    if not query:
        return [], ""
    search = get_search_box(win)
    if search is None:
        return [], ""

    # 聚焦搜索框 → 清空 → 粘贴查询词
    search.Click(simulateMove=True)
    human_sleep(0.4, 0.7)
    search.SendKeys("{Ctrl}a", waitTime=0.1)
    search.SendKeys("{Delete}", waitTime=0.1)
    try:
        auto.SetClipboardText(query)
    except Exception:
        return [], ""
    search.SendKeys("{Ctrl}v", waitTime=0.1)
    human_sleep(1.2, 1.8)

    # 在搜索结果里挑「联系人」单元格（AutoId 以 search_item_ 开头）
    slist = find_first(win, lambda c: id_endswith(c, "search_list"))
    if slist is None:
        return [], ""
    cells = [c for c in slist.GetChildren()
             if "search_item_" in (c.AutomationId or "") or c.ClassName == "mmui::SearchContentCellView"]
    target = None
    for c in cells:                              # 优先精确同名
        if (c.Name or "").strip() == query:
            target = c
            break
    if target is None:                           # 退而求其次：包含查询词的第一个
        for c in cells:
            if query in (c.Name or ""):
                target = c
                break
    if target is None:
        return [], ""

    target.Click(simulateMove=True)              # 点击打开聊天窗口
    msg_list = None
    for _ in range(5):
        human_sleep(0.6, 0.9)
        msg_list = find_first(win, lambda c: id_endswith(c, "chat_message_list"))
        if msg_list is not None and msg_list.GetChildren():
            break
    if msg_list is None:
        return [], ""

    history, last_date = _parse_chat_list(msg_list)
    # 若最新消息上方的时间分隔行未挂载（拿不到日期），向上小幅滚动把它带进可视区再取一次日期
    if history and not last_date:
        try:
            for _ in range(2):
                msg_list.WheelUp(wheelTimes=3, waitTime=0.05)
                human_sleep(0.4, 0.7)
                _, d = _parse_chat_list(msg_list)
                if d:
                    last_date = d
                    break
        except Exception:
            pass
    return history, last_date


def search_query_for(rec: dict) -> str:
    """为一条记录选用于搜索的名字：优先备注，但备注是'仅聊天'/'N个'等占位时改用昵称。"""
    remark = (rec.get("remark") or "").strip()
    nickname = (rec.get("nickname") or "").strip()
    if remark and remark != "仅聊天" and not re.match(r"^\d+个$", remark):
        return remark
    return nickname or remark


# ============================================================
# Step 5a: 地理编码（基于好友真实地区/备注/标签里的地名）
# ============================================================
def _place_tokens(text: str) -> list:
    """把文本按空格/逗号/顿号切成词，用于匹配地名。"""
    return [t for t in re.split(r"[\s,，、/]+", text or "") if t]


def geocode_location(region: str = "", remark: str = "", tags: str = "") -> tuple:
    """
    依据好友的真实地区/备注/标签解析经纬度，返回 (lat, lng)，无法定位返回 None。
    匹配优先级：
      1) region 从最具体到最粗（"广东 深圳" 先认 深圳，再认 广东）——逐词右→左查地名库
      2) 标签里的地名词（如 "深圳,VC" → 深圳；"武汉,餐厅" → 武汉）
      3) 备注自由文本里的地名子串（如 "AA.雪儿 武汉茅台" → 武汉）
    """
    region = (region or "").strip()

    # 1) 结构化地区优先：右（最具体）→ 左（最粗）。地区明确就只认地区。
    region_tokens = _place_tokens(region)
    for tok in reversed(region_tokens):
        if tok in PLACE_COORDS:
            return PLACE_COORDS[tok]

    # 地区有明确地名但坐标库里没有（如某个没收录的国家）→ 返回 None，
    # 绝不退而求其次用 标签/备注 里的地名（否则约旦客户会被标签里的"北京"带偏）。
    if region and region != "中国大陆":
        return None

    # 2) 仅当地区为空 / "中国大陆"（无具体地点）时，才用标签/备注兜底
    for tok in _place_tokens(tags):
        if tok in PLACE_COORDS:
            return PLACE_COORDS[tok]
    for text in (remark, tags):
        for place, coords in PLACE_COORDS.items():
            if len(place) >= 2 and place in (text or ""):
                return coords
    return None


# ============================================================
# Step 5b: mock 数据增强（仅 is_partner 为模拟，经纬度为真实地理编码）
# ============================================================
def mock_enrich(records: list) -> list:
    """
    为看板补全字段：
    - lat / lng : 由 geocode_location() 依据【真实地区/备注/标签】解析得到（非随机）。
                  解析不出地点的好友留空，不上图。
    - is_partner: 仍为模拟（约 60% 概率）——合作关系需业务规则/大模型判定，此处占位。
    chat_history 与 last_chat_time 一律保留真实提取结果。
    """
    for rec in records:
        rec["is_partner"] = random.random() < 0.6
        coords = geocode_location(rec.get("region", ""), rec.get("remark", ""), rec.get("tags", ""))
        if coords:
            lat, lng = coords
            # 同城多个好友加微小抖动，避免标记完全重叠
            rec["lat"] = round(lat + random.uniform(-0.03, 0.03), 4)
            rec["lng"] = round(lng + random.uniform(-0.03, 0.03), 4)
        else:
            rec["lat"], rec["lng"] = None, None
    return records


# ============================================================
# 主流程
# ============================================================
def save_records(records: list, enrich: bool = True) -> None:
    """把当前已采集的数据落盘。enrich=True 时先做 mock 后处理（补经纬度/预警字段）。
    用 copy 避免就地修改正在采集的 records（断点续采时还会继续往里加原始数据）。"""
    import copy
    out = mock_enrich(copy.deepcopy(records)) if enrich else copy.deepcopy(records)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def main():
    auto.SetGlobalSearchTimeout(3)
    records = []

    win = get_wechat_window()

    # ---------- 阶段一：遍历通讯录，采集每个好友的资料卡 ----------
    # 全程停留在通讯录视图：点第一个好友建立焦点，之后纯 {DOWN} 逐个下移，
    # 不进聊天窗口、不切标签，遍历状态稳定不被打断。
    contact_list = goto_contacts(win)
    if not focus_first_contact(contact_list):
        print("[FAIL] 通讯录中没有可见的好友项，结束")
        return

    seen_wxids = set()   # 已采集的微信号（全局唯一），用于跨列表去重
    prev_sig = None      # 上一个好友的签名，用于判断 {DOWN} 是否真的移动了选中项

    def signature(p: dict) -> tuple:
        """好友签名：优先用全局唯一的微信号；无微信号时退回 昵称+备注+地区 组合。
        用于两件事：① 判断 {DOWN} 后选中项是否真的换人（换人则签名变）；
                    ② 避免把'显示名恰好相同的两个不同好友'误判为到底。"""
        return (p.get("wxid", ""), p.get("nickname", ""),
                p.get("remark", ""), p.get("region", ""))

    def advance_to_next(prev: tuple):
        """从当前选中项向下推进到「下一个真实好友」，返回 (profile, sig)。
        遇到"已停用的微信用户"等空白项、或选中项暂时没变（UI 卡顿），会连续多按 DOWN 跨过；
        只有连按 ADVANCE_MAX_PUSH 次仍找不到新的真实好友，才认定到达列表底部，返回 (None, prev)。
        —— 修复了此前被"已停用账号"空白资料卡误判到底、导致 Y/Z 段漏采的问题。"""
        for _ in range(ADVANCE_MAX_PUSH):
            contact_list.SendKeys("{DOWN}", waitTime=0.3)
            human_sleep(0.25, 0.4)
            try:
                profile = extract_profile(win)
            except Exception:
                continue
            name = (profile.get("nickname") or profile.get("remark") or "").strip()
            sig = signature(profile)
            if name and name not in SKIP_NAMES and sig != prev:
                return profile, sig          # 找到新的真实好友
        return None, prev                    # 连按多次仍无新好友 → 真到底

    # 用 try/finally 包裹：无论正常结束、报错还是 Ctrl+C 中断，
    # 都会执行 finally 里的"会话补充 + 落盘"，保证已采集数据不丢。
    try:
        for i in range(MAX_CONTACTS):
            print(f"\n===== 正在处理第 {i + 1}/{MAX_CONTACTS} 个好友 =====")

            if i == 0:
                # 第 1 个好友已被 focus_first_contact 选中，直接读
                try:
                    profile = extract_profile(win)
                except Exception:
                    profile = None
                if profile is None or not (profile.get("nickname") or profile.get("remark")):
                    print("  [FAIL] 第一个好友资料读取失败，结束")
                    break
                sig = signature(profile)
            else:
                # 向下推进到下一个真实好友（自动跨过"已停用账号"等空白/卡点）
                profile, sig = advance_to_next(prev_sig)
                if profile is None:
                    print(f"  [STOP] 连按 {ADVANCE_MAX_PUSH} 次下移仍无新好友，判定已到列表底部，结束遍历")
                    break

            wxid = profile.get("wxid", "")
            if wxid and wxid in seen_wxids:     # 微信号重复 = 列表回卷/卡住，停止
                print(f"  [STOP] 微信号 '{wxid}' 已采集过，判定遍历到底，结束")
                break
            if wxid:
                seen_wxids.add(wxid)
            prev_sig = sig

            print(f"  [{len(records) + 1}] 昵称: {profile['nickname']} | 备注: {profile['remark']} "
                  f"| 地区: {profile['region']} | 标签: {profile['tags']}")

            records.append({
                "nickname": profile["nickname"],
                "remark": profile["remark"],
                "region": profile["region"],
                "tags": profile["tags"],
                "wxid": wxid,
                "last_chat_time": "",
                "chat_history": [],
            })

            # 断点保护：每采集 CHECKPOINT_EVERY 人增量落盘一次
            if len(records) % CHECKPOINT_EVERY == 0:
                save_records(records)
                print(f"  [CHECKPOINT] 已增量保存 {len(records)} 条到 {OUTPUT_FILE}")

    except KeyboardInterrupt:
        print("\n[中断] 检测到 Ctrl+C，正在保存已采集数据...")
    except Exception as e:
        print(f"\n[异常] 采集主循环出错：{e}，正在保存已采集数据...")

    # ---------- 阶段二：补充聊天记录 ----------
    if EXTRACT_CHAT and records:
        if CHAT_MODE == "search":
            # 方式一：逐个搜索好友、打开聊天窗口，提取真实最近消息（慢但准）
            print(f"\n===== 阶段二：逐个提取真实聊天记录（共 {len(records)} 人）=====")
            for idx, rec in enumerate(records, start=1):
                query = search_query_for(rec)
                try:
                    history, last_time = extract_chat_by_search(win, query)
                except Exception as e:
                    print(f"  [{idx}] '{query}' 聊天提取异常: {e}")
                    history, last_time = [], ""
                if history:
                    rec["chat_history"] = history
                if last_time:
                    rec["last_chat_time"] = last_time
                tip = (history[-1][:20] if history else "（无消息/未匹配）")
                print(f"  [{idx}/{len(records)}] {query[:16]} → {len(history)} 条 | 最近: {tip}")
                # 断点保护：每处理 CHECKPOINT_EVERY 人增量落盘
                if idx % CHECKPOINT_EVERY == 0:
                    save_records(records)
                    print(f"  [CHECKPOINT] 已保存聊天进度 {idx}/{len(records)}")
                human_sleep()                    # 防风控延时
        else:
            # 方式二：仅解析会话列表（快，覆盖近期有会话的好友）
            try:
                session_map = build_session_map(win)
                for rec in records:
                    for key in (rec["remark"], rec["nickname"]):
                        if key and key in session_map:
                            last_msg, last_time = session_map[key]
                            if last_msg:
                                rec["chat_history"] = [last_msg]
                            if last_time:
                                rec["last_chat_time"] = last_time
                            break
            except Exception as e:
                print(f"[WARN] 会话摘要解析失败（不影响资料数据）: {e}")

    # 最终落盘（含 mock 大模型后处理）
    save_records(records)
    print(f"\n[DONE] 共提取 {len(records)} 条客情数据，已保存至 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
