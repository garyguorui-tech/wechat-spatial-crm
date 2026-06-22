# -*- coding: utf-8 -*-
"""
remark_suggester.py — 为「备注==昵称」(未规范化) 的联系人生成规范备注建议
================================================================
产物：remark_suggestions.json  —— 逐个确认界面 / RPA 回写的输入。
每条字段：
  wxid, nickname(原昵称=当前备注), region, tags, chat_summary,
  cleaned_name(清洗后的人名/主体), phone(解析出的手机号),
  is_investor(是否投资类), suggested(系统建议的新备注),
  reason(为何这么建议), linkedin_hint(领英检索线索, 投资/英文名才给)

设计原则（与项目地理编码同理：宁缺毋滥）：
  - 只在「能让备注更可识别」时才建议改；信息不足就保守，把判断权交给人。
  - 建议 = 清洗后主体 + 机构/标签线索(若有) + 地区(若昵称里没有)。
  - 绝不臆造机构名；标签/地区是已知事实，可用。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "wechat_data.json")
OUT = os.path.join(HERE, "remark_suggestions.json")
PREVIEW = os.path.join(HERE, "remark_suggestions_preview.txt")

# ============================================================
# 统一备注结构（用户拍板 2026-06-21）： 姓名 单位 地区 [角色]  空格连接
# ============================================================
SEP = " "
SLOT_ORDER = ("name", "org", "region", "role")   # 拼接顺序

# 投资类标签线索（命中即 is_investor）
INVESTOR_TAGS = {
    "vc", "fa", "投", "投头", "券商", "母基金", "机构", "gp", "lp",
    "天使", "创投", "投资", "fo", "family office", "pe", "投资人",
}
# 标签里这些是「人群/分组」噪音，不进备注（按需扩充）
NOISE_TAGS = {"bimba", "lunar"}
# 角色/身份类标签 → 进「角色」槽（不是公司名）
ROLE_TAGS = {
    "vc", "fa", "券商", "天使", "fof", "fo", "投资人", "猎头", "创业人",
    "二级投资", "母基金", "投资基金", "投资", "lp", "gp",
}
# 这些是「品类/赛道/分组」泛词，既非公司也非角色，不单独成单位
GENERIC_TAGS = {"投资基金", "二级投资", "投资", "母基金", "一级市场", "二级市场"}
# 单位（公司/机构）名特征：含这些词且前面有专名 → 当作单位
ORG_SUFFIX_RE = re.compile(r"(资本|创投|基金|控股|集团|科技|Ventures|Capital|Partners|VC基金)")
# 可信地点（中国省/直辖市/主要城市）。微信 region 字段常是假地区，
# 但「用户自己打在 tags 里的城市」是可信的——优先用它。
CN_LOCATIONS = {
    "北京", "上海", "天津", "重庆", "广东", "广州", "深圳", "珠海", "东莞", "佛山",
    "浙江", "杭州", "宁波", "温州", "江苏", "南京", "苏州", "无锡", "山东", "青岛",
    "济南", "福建", "厦门", "福州", "湖北", "武汉", "湖南", "长沙", "四川", "成都",
    "陕西", "西安", "河南", "郑州", "河北", "辽宁", "大连", "沈阳", "安徽", "合肥",
    "江西", "南昌", "云南", "昆明", "贵州", "贵阳", "山西", "太原", "广西", "南宁",
    "海南", "甘肃", "内蒙古", "新疆", "吉林", "黑龙江", "香港", "澳门", "台湾",
}

PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
# 通讯录排序前缀：AA / A01- / A级 / A. 等（用户为置顶加的）
LEAD_CATALOG_RE = re.compile(r"^(?:A{1,3}|A\d{1,3})[\s\.\-:：、]+")
# 纯英文名判断
ASCII_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z\.\s'\-]{0,30}$")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F02F"
    "\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]",
    flags=re.UNICODE,
)


def clean_name(nickname: str):
    """从昵称里剥出可读主体 + 手机号。返回 (cleaned, phone)。"""
    s = nickname or ""
    phones = PHONE_RE.findall(s)
    phone = phones[0] if phones else ""
    s = PHONE_RE.sub("", s)
    s = EMOJI_RE.sub("", s)
    s = LEAD_CATALOG_RE.sub("", s)
    # 去掉首尾分隔噪声
    s = s.strip(" .-_，,、|/\\：:　")
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(), phone


def classify_tags(tags: str):
    """把标签分成 (单位org, 角色role, 城市city)。
    - 城市：标签里的中国地名（用户自打，可信）。
    - 单位：含资本/创投/基金等且非泛词的标签 → 公司/机构名。
    - 角色：VC/FA/券商/赛道 等身份/品类词。"""
    org, role, city = "", "", ""
    for t in re.split(r"[,，;；\s]+", tags or ""):
        t = t.strip()
        if not t:
            continue
        if t in CN_LOCATIONS:
            city = city or t
            continue
        if t.lower() in NOISE_TAGS:
            continue
        low = t.lower()
        if low in ROLE_TAGS or t in ROLE_TAGS:
            role = role or t
            continue
        # 单位：含机构后缀且不是泛词
        if ORG_SUFFIX_RE.search(t) and t not in GENERIC_TAGS:
            org = org or t
            continue
        # 其余（赛道/品类，如"消费""硬科技"）暂归角色槽兜底
        role = role or t
    return org, role, city


CN_NAME_RE = re.compile(r"^[一-龥]{2,4}$")


def region_city(region: str) -> str:
    """仅当 region 首段是可信中国地点时返回，否则空（防假地区）。"""
    region = (region or "").replace("中国大陆", "").replace("中国", "").strip()
    if not region:
        return ""
    first = region.split(" ")[0].strip()
    return first if first in CN_LOCATIONS else ""


def is_investor(tags: str) -> bool:
    low = (tags or "").lower()
    return any(k in low for k in INVESTOR_TAGS)


def chat_summary(c) -> str:
    h = c.get("chat_history") or []
    return (h[0][:30] if h else "")


def compose(slots: dict) -> str:
    """按统一结构 姓名 单位 地区 角色 拼，空槽跳过。"""
    return SEP.join(slots[k].strip() for k in SLOT_ORDER
                    if slots.get(k) and slots[k].strip()).strip()


def suggest(c):
    nickname = c.get("nickname") or ""
    region = (c.get("region") or "").strip()
    tags = c.get("tags") or ""
    cleaned, phone = clean_name(nickname)
    org, role, tag_city = classify_tags(tags)
    inv = is_investor(tags)

    city = tag_city or region_city(region)

    # 统一结构槽位（缺的留空，交给人在界面里补）
    slots = {
        "name": cleaned,           # 姓名/handle：清洗后的昵称（人可改成纯姓名）
        "org": org,                # 单位：来自标签里的机构名（昵称内的单位由人补）
        # 城市若已在姓名里出现则不重复
        "region": "" if (city and city in cleaned) else city,
        "role": "" if (role and role in cleaned) else role,
    }
    suggested = compose(slots)

    changed = bool(suggested and suggested != nickname)
    reasons = []
    if phone:
        reasons.append("剥离手机号")
    if LEAD_CATALOG_RE.search(nickname):
        reasons.append("去置顶前缀")
    if slots["org"]:
        reasons.append(f"单位:{slots['org']}")
    if slots["region"]:
        reasons.append(f"地区:{slots['region']}")
    if slots["role"]:
        reasons.append(f"角色:{slots['role']}")
    if not reasons and changed:
        reasons.append("清洗格式")
    if not changed:
        reasons.append("信息不足/已规范，建议保持或人工补槽")

    # 领英检索线索：投资类 或 英文名 才给
    linkedin_hint = ""
    if inv or ASCII_NAME_RE.match(cleaned or ""):
        bits = [cleaned, org]
        linkedin_hint = " ".join(b for b in bits if b).strip()

    return {
        "wxid": c.get("wxid"),
        "nickname": nickname,
        "region": region,
        "tags": tags,
        "chat_summary": chat_summary(c),
        "cleaned_name": cleaned,
        "phone": phone,
        "is_investor": inv,
        "slots": slots,            # 结构化槽位：界面据此渲染4个输入格
        "suggested": suggested or nickname,
        "changed": changed,
        "reason": "；".join(reasons),
        "linkedin_hint": linkedin_hint,
    }


def main():
    data = json.load(open(DATA, encoding="utf-8"))
    need = [c for c in data if (c.get("remark") or "") == (c.get("nickname") or "")]
    out = [suggest(c) for c in need]
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    n_inv = sum(1 for x in out if x["is_investor"])
    n_changed = sum(1 for x in out if x["changed"])
    # 可读预览
    lines = []
    lines.append(f"待规范联系人: {len(out)} | 投资类: {n_inv} | 建议改动: {n_changed}\n")
    lines.append("=== 投资类样本(最多30) ===")
    for x in [y for y in out if y["is_investor"]][:30]:
        lines.append(
            f"[VC] {x['nickname']!r}  ->  {x['suggested']!r}\n"
            f"     tags={x['tags']} region={x['region']} reason={x['reason']}\n"
            f"     linkedin_hint={x['linkedin_hint']!r}"
        )
    lines.append("\n=== 非投资·有改动样本(最多30) ===")
    for x in [y for y in out if y["changed"] and not y["is_investor"]][:30]:
        lines.append(f"  {x['nickname']!r}  ->  {x['suggested']!r}   [{x['reason']}]")
    open(PREVIEW, "w", encoding="utf-8").write("\n".join(lines))
    print(f"OK wrote {OUT} ({len(out)} items, {n_inv} investor, {n_changed} changed)")
    print(f"preview -> {PREVIEW}")


if __name__ == "__main__":
    main()
