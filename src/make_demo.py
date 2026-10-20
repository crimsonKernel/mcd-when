"""
make_demo.py — 生成一份【演示用】surface.json, 仅用于预览 UI

生成的数据带 isDemo=true, 页面上会显示"演示数据 · 非真实价格"徽标。
拿到 MCP Token 后运行 survey.py, 会用真实数据覆盖并自动摘掉徽标。

演示数据按真机验证的结构手工构造(菜单断崖/真空带形态参考实测), 但所有数字均为虚构。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "surface.json"

SLOTS = [f"{h:02d}:{m:02d}" for h in range(7, 23) for m in (0, 30)]  # 07:00-22:30
PERIODS = [
    {"name": "早餐", "start": "07:14", "end": "10:15"},
    {"name": "午餐", "start": "10:44", "end": "14:15"},
    {"name": "下午茶", "start": "14:44", "end": "16:45"},
    {"name": "夜市", "start": "17:14", "end": "21:45"},
]

# (名称, 可售时段, 基准价/分) —— 数字全为虚构
ITEMS = [
    ("猪柳蛋麦满分套餐", "breakfast", 2600),
    ("原味板烧鸡腿麦满分", "breakfast", 2200),
    ("吉士蛋麦满分套餐", "breakfast", 2100),
    ("大脆薯饼", "breakfast", 800),
    ("「我就喜欢」鸡薯双全盒", "day", 1590),
    ("龙焰芝士棒鸡腿堡三件套", "day", 3990),
    ("精选单人餐三件套", "day", 2990),
    ("麦辣鸡腿堡三件套", "day", 3200),
    ("人气经典随心配", "day", 1390),
    ("蓝莓爆爆珠麦旋风", "afternoon", 1350),
    ("冰浓浓黑巧中杯", "afternoon", 1500),
    ("麦咖啡冰奶铁中杯", "allday", 1900),
]


def in_period(t: str, name: str) -> bool:
    def m(x):
        h, mi = x.split(":")
        return int(h) * 60 + int(mi)
    for p in PERIODS:
        if p["name"] == name:
            return m(p["start"]) <= m(t) < m(p["end"])
    return False


def available(t: str, span: str) -> bool:
    def m(x):
        h, mi = x.split(":")
        return int(h) * 60 + int(mi)
    open_ok = (7 * 60) <= m(t) < (22 * 60)
    if span == "allday":
        return open_ok
    if span == "breakfast":
        return open_ok and m(t) < 10 * 60 + 15
    if span == "day":
        return open_ok and m(t) >= 10 * 60 + 44
    if span == "afternoon":
        return open_ok and (14 * 60 + 44) <= m(t) < (16 * 60 + 45)
    return open_ok


def price_of(base: int, t: str) -> int:
    """演示用波动: 不要当真实规律。"""
    def m(x):
        h, mi = x.split(":")
        return int(h) * 60 + int(mi)
    mm = m(t)
    if 10 * 60 + 15 <= mm < 10 * 60 + 44:
        return base  # 真空带(演示中部分商品仍在, 真实情况以接口为准)
    if mm < 10 * 60 + 15:
        return base - (100 if mm < 8 * 60 + 30 else 0)
    return base + (100 if mm >= 17 * 60 else 0)


def build_channel() -> dict:
    grid: dict[str, dict[str, dict]] = {}
    for t in SLOTS:
        cells = {}
        for name, span, base in ITEMS:
            if available(t, span):
                cells[name] = {"price": price_of(base, t)}
            else:
                cells[str(name)] = {"unavailable": "商品已售罄或不可售(演示)"}
        grid[t] = cells
    return grid


def main() -> int:
    basket = [{"code": f"demo{i:03d}", "name": n, "category": "演示分类", "tags": [],
               "slotsSeen": 1, "firstSlot": "12:00"} for i, (n, _, _) in enumerate(ITEMS)]
    surface = {
        "project": "麦当劳几点最便宜 (mcd-when)",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "targetDate": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        "isDemo": True,
        "dataSource": "演示数据(虚构), 仅为预览 UI; 真实数据请运行 survey.py",
        "cities": [{
            "city": "演示城市",
            "store": {"code": "demo", "name": "演示门店(虚构)", "address": "",
                      "businessStart": "07:00", "businessEnd": "22:00"},
            "periods": PERIODS,
            "slots": SLOTS,
            "basket": basket,
            "channels": [{"id": "pickup", "label": "到店自提", "beType": 1, "orderType": 1, "beCode": None}],
            "grid": {"pickup": build_channel()},
            "dryRun": False,
        }],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(surface, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"演示数据已生成 -> {OUT} (isDemo=true, 页面会带演示徽标)")
    print("下一步: python src/render_report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
