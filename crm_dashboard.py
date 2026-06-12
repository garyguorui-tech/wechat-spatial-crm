# -*- coding: utf-8 -*-
"""
crm_dashboard.py — 空间 CRM 客情看板（可编辑版）
================================================
读取 rpa_extractor.py 生成的 wechat_data.json，渲染两个标签页：
    📊 看板    ：KPI 卡片 / 合作伙伴地理分布地图 / 高危流失预警
    ✏️ 客户管理：可编辑表格，确认或修改【合作状态 / 公司 / 级别 / 行业 / 跟进人 / 备注】

设计要点：
    - RPA 抓取的客观数据存在 wechat_data.json（重跑采集会覆盖）
    - 人工维护的 CRM 标注存在独立的 crm_annotations.json，按【微信号 wxid】关联
      → 重跑采集不会丢失你的人工标注
    - 看板用的字段 = 人工标注优先，没标注则用智能猜测（公司/行业/状态）

启动方式：
    streamlit run crm_dashboard.py
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime

# 关键：依赖统一装在项目内 libs 文件夹（不依赖用户目录，双击/cmd 都能找到）
_libs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
if os.path.isdir(_libs) and _libs not in sys.path:
    sys.path.insert(0, _libs)

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

# ============================================================
# 全局配置
# ============================================================
HERE = os.path.dirname(os.path.abspath(__file__))
# 优先用真实采集数据；没有则回退到示例数据（让 clone 仓库的人开箱就能看 demo）
DATA_FILE = os.path.join(HERE, "wechat_data.json")
if not os.path.exists(DATA_FILE):
    DATA_FILE = os.path.join(HERE, "wechat_data.sample.json")
ANNOTATION_FILE = os.path.join(HERE, "crm_annotations.json")   # 人工标注独立存储

ALERT_THRESHOLD_DAYS = 30          # 流失预警默认阈值：超过 N 天未联系（界面可调）
ALERT_KEY = "alert_threshold_days"               # session_state 键：当前选中的预警天数
ALERT_OPTIONS = [7, 14, 21, 30, 45, 60, 90, 120, 180]   # 可选的预警天数档位
CHINA_CENTER = [35.0, 105.0]
DEFAULT_ZOOM = 4

# 可选项
STATUS_OPTIONS = ["潜在客户", "合作中", "已签约", "已流失", "暂不合作"]
TIER_OPTIONS = ["A（核心KA）", "B（重点）", "C（普通）", "D（观察）"]
PARTNER_STATUSES = {"合作中", "已签约"}      # 视为"合作伙伴"（上图 + 计入预警）的状态
DEFAULT_TIER = "C（普通）"
KA_TIER = "A（核心KA）"
HIGH_VALUE_CTYPES = {"投资机构", "证券/研究", "银行", "保险"}   # 这些公司类型默认评 B（重点）

# 中国央企关键词（含常见简称/英文）——命中即自动评为 A 级（核心KA）。
# 覆盖国资委监管的主要中央企业；可按需增删。匹配对象：备注/昵称/标签/公司名。
CENTRAL_SOE_KEYWORDS = [
    # —— 油气 / 能源 / 电力（你重点关注的）——
    "中国石化", "中石化", "石油化工", "sinopec",
    "中国石油", "中石油", "中油", "cnpc", "石油天然气",
    "中国海油", "中海油", "中国海洋石油", "cnooc",
    "国家能源集团", "国家能源投资", "神华",
    "国家电网", "国网", "南方电网", "南网",
    "中国华能", "华能", "中国大唐", "大唐集团", "大唐发电",
    "中国华电", "华电", "国家电投", "国电投", "国家电力投资",
    "中核", "中国核工业", "中国核电", "中广核", "中国广核",
    "三峡集团", "长江三峡", "中国三峡", "中国中煤", "中煤集团", "中煤能源",
    "中国能建", "能源建设", "中国电建", "电力建设",
    # —— 电信 ——
    "中国移动", "中国联通", "中国电信", "中国铁塔",
    # —— 军工 / 电子 / 装备 ——
    "航天科技", "航天科工", "航空工业", "中航工业", "中国商飞", "商飞",
    "中国船舶", "中船", "兵器工业", "兵器装备", "中国兵器", "北方工业",
    "中国电科", "中电科", "电子科技集团", "中国电子", "中国电子信息",
    "中国电气装备", "中国信科", "中国星网", "卫星网络",
    # —— 交通 / 基建 / 钢铁 / 材料 ——
    "中国中车", "中车", "国铁集团", "中国国家铁路", "中国铁路",
    "中国中铁", "中铁", "中国铁建", "中铁建", "中国交建", "中交集团", "交通建设",
    "中国建筑", "中建", "中国中冶", "中冶", "中国五矿", "五矿",
    "国机集团", "机械工业", "中国一重", "中国一汽", "一汽",
    "中国宝武", "宝武", "宝钢", "鞍钢", "中国中化", "中化集团",
    "中国化工", "中国建材", "中建材",
    # —— 航空运输 / 贸易 / 其他 ——
    "中国国航", "国航", "东方航空", "东航", "南方航空", "南航",
    "中粮", "cofco", "中储粮", "中国储备粮", "招商局", "华润", "保利",
    "国家开发投资", "国投", "通用技术", "中国黄金", "中金黄金",
    "中国诚通", "中国国新", "中国物流", "中国稀土", "中国矿产资源",
]

# 公司名智能猜测：匹配以这些后缀结尾的词
_COMPANY_SUFFIX = ("科技", "资本", "投资", "基金", "证券", "创投", "创富", "创安", "集团",
                    "股份", "网络", "传媒", "文化", "实业", "控股", "银行", "保险", "咨询",
                    "教育", "医疗", "生物", "能源", "地产", "置业", "物业", "酒店", "餐饮",
                    "有限公司", "公司", "大学", "学院", "研究院", "协会", "事务所",
                    "Capital", "Ventures", "Partners")
_COMPANY_RE = re.compile(r"[一-龥A-Za-z·\.]{2,14}?(?:" + "|".join(_COMPANY_SUFFIX) + r")")

st.set_page_config(page_title="微信客情 CRM 看板", page_icon="🗺️",
                   layout="wide", initial_sidebar_state="expanded")


# ============================================================
# 工具函数
# ============================================================
def display_name(rec: dict) -> str:
    """客户展示名：优先备注，备注为空或是"仅聊天"等权限标签时回退昵称。"""
    remark = (rec.get("remark") or "").strip()
    if remark and remark != "仅聊天":
        return remark
    return rec.get("nickname") or "未知客户"


def record_key(rec: dict) -> str:
    """记录主键：优先微信号（全局唯一稳定）；缺失时退回 昵称|备注 组合。"""
    return rec.get("wxid") or f"{rec.get('nickname','')}|{rec.get('remark','')}"


def days_since(date_str: str) -> int:
    """给定日期距今天数；解析失败返回 -1（视为无往来记录）。"""
    try:
        return (datetime.now() - datetime.strptime(date_str, "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return -1


def get_alert_threshold() -> int:
    """当前的流失预警阈值（天）。来自侧边栏滑块，默认 30。"""
    return int(st.session_state.get(ALERT_KEY, ALERT_THRESHOLD_DAYS))


def _launch_collector(script: str, env_extra: dict = None) -> bool:
    """在新控制台窗口里启动采集脚本（用当前 Python，已含 uiautomation）。返回是否成功。"""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    try:
        subprocess.Popen([sys.executable, os.path.join(HERE, script)],
                         cwd=HERE, env=env, creationflags=flags)
        return True
    except Exception as e:
        st.sidebar.error(f"启动失败：{e}")
        return False


def render_data_refresh() -> None:
    """侧边栏：从微信重新采集数据的入口（在新窗口运行，采集时勿操作电脑）。"""
    with st.sidebar.expander("🔄 刷新微信数据", expanded=False):
        st.caption("从微信重新采集，会**自动操控微信**，采集时请勿移动鼠标键盘、保持微信前台。"
                   "采集在**新弹出的黑色窗口**里跑，完成后回这里点〔重新加载〕。")

        if st.button("⚡ 快速刷新最近会话（约1~2分钟）", use_container_width=True):
            if _launch_collector("refresh_sessions.py"):
                st.success("已在新窗口启动『最近会话刷新』。跑完点下方〔🔁 重新加载〕。")

        if st.button("📇 采集前 200 位好友（约10分钟）", use_container_width=True):
            if _launch_collector("rpa_extractor.py", {"WX_MAX_CONTACTS": "200"}):
                st.success("已启动采集前 200 人。跑完点〔🔁 重新加载〕。")

        if st.button("📥 全量重新采集（数小时）", use_container_width=True):
            if _launch_collector("rpa_extractor.py"):
                st.warning("已启动全量采集（数小时），期间勿动电脑。跑完点〔🔁 重新加载〕。")

        st.divider()
        if st.button("🔁 重新加载已采数据", type="primary", use_container_width=True):
            load_data.clear()
            st.rerun()


def render_threshold_control() -> int:
    """侧边栏：流失预警阈值滑块（多少天未联系算高危）。返回选中的天数。"""
    st.sidebar.markdown("### ⏰ 流失预警阈值")
    st.sidebar.select_slider(
        "超过多少天未联系算「高危流失」",
        options=ALERT_OPTIONS, value=ALERT_THRESHOLD_DAYS, key=ALERT_KEY,
    )
    days = get_alert_threshold()
    st.sidebar.caption(f"当前：合作客户**超过 {days} 天**没真实对话 → 进预警 / 地图标红")
    st.sidebar.divider()
    return days


def is_followed_this_month(date_str: str) -> bool:
    """最后对话是否落在本月。"""
    try:
        last = datetime.strptime(date_str, "%Y-%m-%d")
        now = datetime.now()
        return last.year == now.year and last.month == now.month
    except (ValueError, TypeError):
        return False


def last_text_message(rec: dict) -> str:
    """最近一条文本消息（过滤掉图片/语音等非文本占位）。"""
    texts = [m for m in rec.get("chat_history", []) if not m.startswith("<非文本")]
    return texts[-1] if texts else ""


# ---------- 智能猜测（无人工标注时的默认值）----------
def guess_company(rec: dict) -> str:
    """从备注里猜公司名：匹配以"科技/资本/Ventures…"等结尾的词。
    只看备注、不看标签——标签多是行业词（投资基金/上市公司），猜成公司会出错，
    宁可留空让用户填。"""
    m = _COMPANY_RE.search(rec.get("remark", "") or "")
    return m.group(0) if m else ""


def guess_status(rec: dict) -> str:
    """默认合作状态：有真实往来消息 → 合作中；否则 → 潜在客户（待人工确认）。"""
    return "合作中" if last_text_message(rec) else "潜在客户"


def is_central_soe(rec: dict) -> bool:
    """判断该客户是否属于中国央企（匹配 备注/昵称/标签/公司名 中的央企关键词）。"""
    hay = f"{rec.get('remark', '')} {rec.get('nickname', '')} {rec.get('tags', '')} {guess_company(rec)}".lower()
    return any(kw in hay for kw in CENTRAL_SOE_KEYWORDS)


def guess_tier(rec: dict, status: str = None, ctype: str = None, company: str = None) -> str:
    """
    默认级别（人工标注可覆盖）：
      A 核心KA：中国央企
      B 重点  ：① 金融机构（投资机构/证券/银行/保险）——天然高价值目标；
               或 ② 已在合作（合作中/已签约）且有明确公司名——已建立关系的实体客户
      C 普通  ：其余
    """
    if is_central_soe(rec):
        return KA_TIER
    status = status if status is not None else guess_status(rec)
    ctype = ctype if ctype is not None else infer_company_type(rec)
    company = company if company is not None else guess_company(rec)
    if ctype in HIGH_VALUE_CTYPES:
        return "B（重点）"
    if status in PARTNER_STATUSES and company:
        return "B（重点）"
    return DEFAULT_TIER


def default_fields(rec: dict) -> dict:
    """一条记录在"无人工标注"时的默认 CRM 字段。"""
    company = guess_company(rec)
    status = guess_status(rec)
    ctype = infer_company_type(rec)
    return {
        "company": company,
        "status": status,
        "tier": guess_tier(rec, status=status, ctype=ctype, company=company),  # 央企A / 金融或在合作B / 其余C
        "industry": rec.get("tags", "") or "",
        "ctype": ctype,                       # 公司类型默认值（自动归类）
        "owner": "",
        "note": "",
    }


# ---------- 人工标注的读写（不缓存，保证保存后立即生效）----------
def load_annotations() -> dict:
    if not os.path.exists(ANNOTATION_FILE):
        return {}
    try:
        with open(ANNOTATION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_annotations(ann: dict) -> None:
    with open(ANNOTATION_FILE, "w", encoding="utf-8") as f:
        json.dump(ann, f, ensure_ascii=False, indent=2)


@st.cache_data(ttl=60)
def load_data(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_records(data: list, ann: dict) -> list:
    """把人工标注合并进记录：每条记录补 _company/_status/_tier/_industry/_owner/_note，
    并据 _status 重算 is_partner。人工标注优先，无标注用智能默认。"""
    for rec in data:
        d = default_fields(rec)
        a = ann.get(record_key(rec), {})
        rec["_company"] = a.get("company") if a.get("company") not in (None, "") else d["company"]
        rec["_status"] = a.get("status") or d["status"]
        rec["_tier"] = a.get("tier") or d["tier"]
        rec["_industry"] = a.get("industry") if a.get("industry") is not None else d["industry"]
        rec["_owner"] = a.get("owner", d["owner"])
        rec["_note"] = a.get("note", d["note"])
        rec["is_partner"] = rec["_status"] in PARTNER_STATUSES
        rec["_province"] = province_of(rec)
        rec["_ctype"] = a.get("ctype") or infer_company_type(rec)   # 标注优先，否则自动归类
    return data


# ============================================================
# 出差拜访：省份归属 + 公司类型推断
# ============================================================
# 少数地区字段只写了城市名（没带省），补一个城市→省映射
_CITY_TO_PROVINCE = {
    "武汉": "湖北", "杭州": "浙江", "南京": "江苏", "苏州": "江苏",
    "成都": "四川", "西安": "陕西", "广州": "广东", "深圳": "广东",
}
_PROVINCE_NORMALIZE = {"中国香港": "香港", "中国澳门": "澳门", "中国台湾": "台湾"}


def province_of(rec: dict) -> str:
    """取客户所属"省/直辖市/地区"（地区字段的第一段）。无法判断归到"其他/未知"。"""
    region = (rec.get("region") or "").strip()
    if not region or region == "中国大陆":
        return "其他/未知"
    first = region.split()[0]
    if first in _CITY_TO_PROVINCE:                 # 只写了城市名 → 映射到省
        return _CITY_TO_PROVINCE[first]
    return _PROVINCE_NORMALIZE.get(first, first)


# 公司类型推断规则（命中即返回，越靠前越优先）
_TYPE_RULES = [
    ("投资机构", ["vc", "创投", "风投", "投资基金", "基金", "创富", "capital", "ventures",
                  "partners", "fa", "母基金", "二级投资", "战投"]),
    ("证券/研究", ["证券", "券商", "行研", "研究所", "投行"]),
    ("银行", ["银行"]),
    ("保险", ["保险"]),
    ("科技/互联网", ["科技", "互联网", "软件", "网络", "智能", "数据", "信息", "通信",
                     "芯片", "机器人", "saas", "数智", "ai", "光电", "电子"]),
    ("制造/工业", ["制造", "工业", "机械", "设备", "装备", "内窥镜", "材料", "管道"]),
    ("能源/环保", ["能源", "电力", "石油", "双碳", "碳中和", "环保", "新能源", "粤能"]),
    ("地产/建筑", ["地产", "置业", "物业", "建科", "建设", "建筑", "城投", "园区"]),
    ("餐饮/酒店", ["餐饮", "餐厅", "酒家", "茶业", "ktv", "酒店", "食品", "茅台", "粽子"]),
    ("媒体/文化", ["媒体", "传媒", "文化", "娱乐", "影视"]),
    ("政府/机构", ["政府", "政务", "招商", "发改委", "商务厅", "人事处", "协会", "管委会", "院"]),
    ("教育", ["教育", "大学", "学院", "emba", "bimba", "学校", "培训"]),
    ("咨询", ["咨询", "顾问", "bcg", "cbre"]),
    ("法律", ["律所", "律师", "事务所"]),
    ("医疗/生物", ["医疗", "生物", "医药", "健康", "制药", "医院"]),
    ("零售/消费", ["消费", "零售", "品牌", "商贸", "贸易", "电商", "安踏", "租赁"]),
]


# 公司类型可选项（用于客户管理下拉 + 出差筛选）
CTYPE_OPTIONS = [label for label, _ in _TYPE_RULES] + ["其他/未分类"]


def infer_company_type(rec: dict) -> str:
    """从公司名/标签/备注推断公司类型（行业大类）。公司名优先用已合并的 _company，
    没有则现猜一个，保证在 merge 之前调用也能工作。"""
    company = rec.get("_company") or guess_company(rec)
    hay = f"{company} {rec.get('tags', '')} {rec.get('remark', '')}".lower()
    for label, kws in _TYPE_RULES:
        if any(kw in hay for kw in kws):
            return label
    return "其他/未分类"


# ============================================================
# 全局地区筛选（首页选省，地图/清单/预警一起联动）
# ============================================================
GLOBAL_PROV_KEY = "global_province"      # session_state 键：全局选中的省份原始标签


def selected_province() -> str:
    """读取当前全局选中的省份；返回省名，或 '全部'。"""
    raw = st.session_state.get(GLOBAL_PROV_KEY, "")
    if not raw or raw.startswith("（全部"):
        return "全部"
    return raw.rsplit("（", 1)[0]


def render_global_province_selector(data: list) -> str:
    """在侧边栏顶部放一个全局省份下拉，作为唯一来源。返回选中的省名或 '全部'。"""
    prov_count = {}
    for rec in data:
        prov_count[rec["_province"]] = prov_count.get(rec["_province"], 0) + 1
    ordered = sorted(prov_count.items(), key=lambda x: -x[1])
    options = ["（全部 · 总览）"] + [f"{p}（{n}）" for p, n in ordered]

    st.sidebar.markdown("### 🧭 出差目的地")
    st.sidebar.selectbox("选择省/地区（地图·清单·预警 全局联动）",
                         options, index=0, key=GLOBAL_PROV_KEY)
    prov = selected_province()
    if prov != "全部":
        st.sidebar.success(f"📍 已锁定：**{prov}** — 下方与首页均只看该地区")
    st.sidebar.divider()
    return prov


# ============================================================
# 侧边栏：高危流失预警
# ============================================================
def _tier_letter(rec: dict) -> str:
    """级别取首字母（A/B/C/D），用于紧凑展示。"""
    t = rec.get("_tier", "")
    return t[0] if t and t[0] in "ABCD" else "-"


def render_sidebar_alerts(data: list, province: str) -> None:
    threshold = get_alert_threshold()
    st.sidebar.title("🚨 高危流失预警")
    scope = "全部地区" if province == "全部" else province
    st.sidebar.caption(f"超过 {threshold} 天未联系的合作伙伴 · 当前范围：{scope}")

    # 全部预警（合作伙伴中超阈值未联系的），先按全局省份过滤
    partners = [d for d in data if d.get("is_partner")
                and (province == "全部" or d["_province"] == province)]
    all_alerts = [(p, days_since(p.get("last_chat_time", "")))
                  for p in partners
                  if days_since(p.get("last_chat_time", "")) > threshold]
    all_alerts.sort(key=lambda x: x[1], reverse=True)

    if not all_alerts:
        st.sidebar.success("✅ 该范围内合作伙伴均在活跃期，无流失风险")
        return

    # —— 公司类型筛选（省份已由顶部全局下拉控制）——
    type_opts = ["全部"] + sorted({p.get("_ctype", "其他/未分类") for p, _ in all_alerts},
                                  key=lambda t: CTYPE_OPTIONS.index(t) if t in CTYPE_OPTIONS else 99)
    sel_type = st.sidebar.selectbox("🏷️ 公司类型", type_opts, key="alert_type")

    alerts = all_alerts
    if sel_type != "全部":
        alerts = [(p, d) for p, d in alerts if p.get("_ctype") == sel_type]

    st.sidebar.metric("当前预警", f"{len(alerts)} 位",
                      delta=f"共 {len(all_alerts)} 位" if len(alerts) != len(all_alerts) else None,
                      delta_color="off")

    if not alerts:
        st.sidebar.info("该筛选条件下无预警客户。")
        return

    # —— 紧凑单行展示：客户 · 类型 · 级别 · 天数（红框只用一个整体容器）——
    lines = []
    for person, days in alerts:
        name = display_name(person)
        company = person.get("_company") or person.get("_ctype") or ""
        lines.append(
            f"<div style='padding:5px 8px;margin:4px 0;border-left:3px solid #e64545;"
            f"background:#fbeaea;border-radius:3px;font-size:13px;line-height:1.35;'>"
            f"<b>{name}</b> <span style='color:#c0392b;font-weight:600;'>{days}天</span><br>"
            f"<span style='color:#666;'>{company} · {person.get('_province','')} · {_tier_letter(person)}级</span>"
            f"</div>"
        )
    st.sidebar.markdown("".join(lines), unsafe_allow_html=True)


# ============================================================
# 主体：商业地图
# ============================================================
def build_map(partners: list) -> folium.Map:
    m = folium.Map(location=CHINA_CENTER, zoom_start=DEFAULT_ZOOM, tiles="CartoDB positron")
    # 标记聚合：上千个点也能流畅渲染，缩放时自动聚合/展开
    cluster = MarkerCluster(name="客户").add_to(m)
    coords_on_map = []

    for p in partners:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        coords_on_map.append([lat, lng])

        dname = display_name(p)
        days = days_since(p.get("last_chat_time", ""))
        is_alert = days > get_alert_threshold()
        last_chat_txt = f"{p['last_chat_time']}（{days} 天前）" if days >= 0 else "无往来记录"
        last_msg = last_text_message(p) or "（暂无文本消息）"

        popup_html = f"""
        <div style="font-family: 'Microsoft YaHei', sans-serif; width: 230px;">
            <h4 style="margin: 4px 0;">{dname}</h4>
            <hr style="margin: 4px 0;">
            <b>🏢 公司：</b>{p.get('_company') or '未填写'}<br>
            <b>🏷️ 类型：</b>{p.get('_ctype') or '-'}<br>
            <b>⭐ 级别：</b>{p.get('_tier') or '-'} &nbsp; <b>状态：</b>{p.get('_status') or '-'}<br>
            <b>📍 地区：</b>{p.get('region') or '未知'}<br>
            <b>🕐 最后对话：</b>{last_chat_txt}<br>
            <b>💬 最近消息：</b>{last_msg}
        </div>
        """
        folium.Marker(
            location=[lat, lng],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{dname}（点击查看客情详情）",
            icon=folium.Icon(color="red" if is_alert else "blue",
                             icon="exclamation-sign" if is_alert else "user"),
        ).add_to(cluster)

    if len(coords_on_map) >= 2:
        m.fit_bounds(coords_on_map, padding=(30, 30))
    elif len(coords_on_map) == 1:
        m.location, m.options["zoom"] = coords_on_map[0], 8
    return m


# ============================================================
# 出差拜访清单（按省筛选）
# ============================================================
_STATUS_ORDER = {"已签约": 0, "合作中": 1, "潜在客户": 2, "暂不合作": 3, "已流失": 4}


def _visit_sort_key(rec: dict):
    """拜访清单排序：级别(A→D) → 合作状态(已签约→流失) → 最近联系(越久越靠前，更该去拜访)。"""
    tier = rec.get("_tier", "")
    tier_rank = TIER_OPTIONS.index(tier) if tier in TIER_OPTIONS else 9
    status_rank = _STATUS_ORDER.get(rec.get("_status", ""), 9)
    days = days_since(rec.get("last_chat_time", ""))
    return (tier_rank, status_rank, -days)


def render_visit_planner(data: list, province: str) -> None:
    """出差拜访：按全局选定的省/地区列出可拜访客户（公司/类型/级别/状态/城市）。
    province 由侧边栏顶部的全局下拉控制。"""
    # —— 全部总览：沿用合作伙伴地图 ——
    if province == "全部":
        st.subheader("🌏 合作伙伴地理分布（总览）")
        st.caption("🔵 正常客户　🔴 流失预警客户。在左侧『🧭 出差目的地』选一个省，"
                   "地图 / 拜访清单 / 预警栏会一起聚焦该省。")
        partners = [d for d in data if d.get("is_partner")]
        on_map = [p for p in partners if p.get("lat") is not None]
        if on_map:
            st_folium(build_map(partners), height=480, use_container_width=True, returned_objects=[])
        else:
            st.info("当前没有『合作中/已签约』且能定位地区的客户。")
        return

    # —— 某个省：列出该省全部客户 + 地图聚焦 ——
    all_in_prov = [r for r in data if r["_province"] == province]

    # 公司类型筛选：只列出该省实际出现的类型供选择
    types_here = sorted({r.get("_ctype", "其他/未分类") for r in all_in_prov},
                        key=lambda t: CTYPE_OPTIONS.index(t) if t in CTYPE_OPTIONS else 99)
    c_left, c_right = st.columns([3, 1])
    picked_types = c_left.multiselect(
        "🏷️ 按公司类型筛选（留空 = 全部类型）", types_here, default=[])
    only_partner = c_right.checkbox("仅看合作伙伴", value=False)

    visit = all_in_prov
    if picked_types:
        visit = [r for r in visit if r.get("_ctype") in picked_types]
    if only_partner:
        visit = [r for r in visit if r.get("is_partner")]
    visit = sorted(visit, key=_visit_sort_key)

    on_map = [r for r in visit if r.get("lat") is not None]
    partners_here = [r for r in visit if r.get("is_partner")]
    filter_note = f"（已按类型筛选：{('、'.join(picked_types)) if picked_types else '全部'}）"
    st.subheader(f"🧳 {province} · 可拜访客户 {len(visit)} 位")
    st.caption(f"其中合作伙伴 {len(partners_here)} 位 ｜ 地图可定位 {len(on_map)} 位 "
               f"{filter_note} ｜ 🔴 = 超 {get_alert_threshold()} 天未联系，更建议拜访")

    # 地图：聚焦本省客户
    if on_map:
        st_folium(build_map(visit), height=420, use_container_width=True, returned_objects=[])

    # 拜访清单表格
    rows = []
    for r in visit:
        days = days_since(r.get("last_chat_time", ""))
        city = (r.get("region") or "").replace(province, "").strip() or "—"
        rows.append({
            "客户": display_name(r),
            "公司": r.get("_company") or "—",
            "公司类型": r.get("_ctype") or "—",
            "级别": r.get("_tier", ""),
            "合作状态": r.get("_status", ""),
            "城市/区县": city,
            "最后对话": r.get("last_chat_time", "") if days >= 0 else "无往来",
            "未联系天数": days if days >= 0 else "",
            "跟进人": r.get("_owner", ""),
            "微信号": r.get("wxid", ""),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=min(60 + 35 * len(rows), 460))

    # 下载本省拜访清单
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(f"⬇️ 导出 {province} 拜访清单（CSV）", csv,
                       file_name=f"拜访清单_{province}.csv", mime="text/csv")


# ============================================================
# 标签页一：看板
# ============================================================
def render_dashboard_tab(data: list, province: str) -> None:
    # KPI 随全局省份联动：选了省就只统计该省
    scope = data if province == "全部" else [d for d in data if d["_province"] == province]
    if province != "全部":
        st.info(f"📍 全局已锁定 **{province}** — KPI、地图、拜访清单、预警栏均只看该地区。"
                "（在左侧『🧭 出差目的地』选回『全部 · 总览』可解除）")

    partners = [d for d in scope if d.get("is_partner")]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(("👥 总客户数" if province == "全部" else f"👥 {province}客户数"), f"{len(scope)} 人")
    c2.metric("🤝 合作伙伴数", f"{len(partners)} 人")
    c3.metric("📅 本月跟进数",
              f"{sum(1 for d in scope if is_followed_this_month(d.get('last_chat_time', '')))} 人")
    c4.metric("⭐ 核心KA数", f"{sum(1 for d in scope if d.get('_tier', '').startswith('A'))} 人")
    st.divider()

    render_visit_planner(data, province)


# ============================================================
# 标签页二：客户管理（可编辑）
# ============================================================
def render_manage_tab(data: list, ann: dict) -> None:
    st.subheader("✏️ 客户管理")
    st.caption("直接在表格里确认/修改【合作状态·公司·级别·行业·跟进人·备注】，改完点下方『💾 保存』。"
               "标注按微信号独立保存，重跑采集不会丢失。")

    # 关键词过滤，便于在大量好友中定位
    kw = st.text_input("🔎 按 名称/公司/地区 过滤", "").strip()

    rows, index_map = [], []          # index_map[i] = 在 data 中的下标，用于保存时按行回写
    for i, rec in enumerate(data):
        dname = display_name(rec)
        if kw and kw.lower() not in (
            f"{dname} {rec.get('_company','')} {rec.get('region','')} "
            f"{rec.get('nickname','')} {rec.get('tags','')}"
        ).lower():
            continue
        days = days_since(rec.get("last_chat_time", ""))
        rows.append({
            "显示名": dname,
            "公司": rec.get("_company", ""),
            "公司类型": rec.get("_ctype", ""),
            "合作状态": rec.get("_status", "潜在客户"),
            "级别": rec.get("_tier", DEFAULT_TIER),
            "行业/标签": rec.get("_industry", ""),
            "跟进人": rec.get("_owner", ""),
            "地区": rec.get("region", ""),
            "最后对话": rec.get("last_chat_time", "") if days >= 0 else "无往来",
            "最近消息": last_text_message(rec),
            "备注跟进": rec.get("_note", ""),
        })
        index_map.append(i)

    if not rows:
        st.info("没有匹配的客户。")
        return

    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df,
        use_container_width=True,
        height=520,
        num_rows="fixed",                       # 禁止增删行，保证与 data 行对齐
        hide_index=True,
        column_config={
            "显示名": st.column_config.TextColumn("显示名", disabled=True, width="medium"),
            "公司": st.column_config.TextColumn("公司", width="medium"),
            "公司类型": st.column_config.SelectboxColumn("公司类型", options=CTYPE_OPTIONS, width="small"),
            "合作状态": st.column_config.SelectboxColumn("合作状态", options=STATUS_OPTIONS, width="small"),
            "级别": st.column_config.SelectboxColumn("级别", options=TIER_OPTIONS, width="small"),
            "行业/标签": st.column_config.TextColumn("行业/标签", width="medium"),
            "跟进人": st.column_config.TextColumn("跟进人", width="small"),
            "地区": st.column_config.TextColumn("地区", disabled=True, width="small"),
            "最后对话": st.column_config.TextColumn("最后对话", disabled=True, width="small"),
            "最近消息": st.column_config.TextColumn("最近消息", disabled=True, width="large"),
            "备注跟进": st.column_config.TextColumn("备注跟进", width="large"),
        },
        key="crm_editor",
    )

    c1, c2 = st.columns([1, 5])
    if c1.button("💾 保存修改", type="primary"):
        changed = 0
        for row_pos, data_idx in enumerate(index_map):
            rec = data[data_idx]
            key = record_key(rec)
            default = default_fields(rec)
            r = edited.iloc[row_pos]
            new = {
                "company": str(r["公司"]).strip(),
                "ctype": str(r["公司类型"]).strip(),
                "status": str(r["合作状态"]).strip(),
                "tier": str(r["级别"]).strip(),
                "industry": str(r["行业/标签"]).strip(),
                "owner": str(r["跟进人"]).strip(),
                "note": str(r["备注跟进"]).strip(),
            }
            # 只存"与默认猜测不同"的字段，避免把猜测值冻结进标注
            diff = {k: v for k, v in new.items() if v != (default.get(k) or "")}
            if diff:
                ann[key] = diff
                changed += 1
            elif key in ann:
                del ann[key]                    # 全部改回默认 → 移除该条标注
        save_annotations(ann)
        st.success(f"已保存 {changed} 位客户的人工标注到 crm_annotations.json")
        load_data.clear()                       # 让看板用最新合并结果
        st.rerun()

    c2.caption(f"当前已保存 {len(ann)} 位客户的人工标注。"
               "「合作状态=合作中/已签约」的客户会出现在地图与预警中。")


# ============================================================
# 页面主入口
# ============================================================
def main():
    st.title("🗺️ 微信客情 · 空间 CRM 看板")
    st.caption("数据来源：rpa_extractor.py 自动提取的微信通讯录与聊天记录 ｜ 合作关系等可在『客户管理』里人工确认")

    data = load_data(DATA_FILE)
    if not data:
        st.warning(f"⚠️ 未找到数据文件 `{DATA_FILE}`，请先运行 `python rpa_extractor.py` 采集数据。")
        st.stop()

    ann = load_annotations()
    data = merge_records(data, ann)

    # 侧边栏顶部：全局省份选择（唯一来源）+ 流失预警阈值，地图/清单/预警都读它们
    province = render_global_province_selector(data)
    render_threshold_control()
    render_data_refresh()
    render_sidebar_alerts(data, province)

    tab1, tab2 = st.tabs(["📊 看板", "✏️ 客户管理"])
    with tab1:
        render_dashboard_tab(data, province)
    with tab2:
        render_manage_tab(data, ann)


if __name__ == "__main__":
    main()
