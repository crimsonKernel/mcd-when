"""
render_card.py — 生成 README 首图用的卡片页 (dist/card.html), 再由浏览器截图成 images/heatmap.png

首图 = 一张「问答卡」+ 一天四档 + 三条全国实测发现。
自包含, 与 report.html 共用同一套浅色大众视觉; 不依赖 JS(截图环境跑不了交互)。
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface_national.json"
LEGACY_PATH = ROOT / "data" / "surface.json"
OUT_PATH = ROOT / "dist" / "card.html"

PERIOD_STYLE = {
    "早餐": ("#FFF2D9", "#8A5300", "#F0C987", "🌅"),
    "午餐": ("#FFE6D6", "#A64400", "#F2B48A", "🍔"),
    "下午茶": ("#EFE6FF", "#5B3BA8", "#C9B6F5", "🍰"),
    "夜市": ("#DDEAFF", "#1D4F91", "#A9C6F2", "🌙"),
}

SAMPLE_CITY = "上海"

CSS = """
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:#FBF7F2;color:#1f2329;width:1200px;
 font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB","Source Han Sans SC",
  "Noto Sans CJK SC",system-ui,-apple-system,sans-serif;
 font-size:16px;line-height:1.65}
.card{width:1200px;background:#fff;padding:34px 40px 30px}
h1{font-size:42px;margin:0 0 6px;letter-spacing:-.5px}
.tag{display:inline-block;font-size:15px;font-weight:700;color:#1a7f37;
 background:#FFF1E2;border:1px solid #F2D9B6;border-radius:20px;padding:4px 14px;margin:0 0 22px}
.lead{font-size:17px;color:#3d4450;margin:0 0 24px}
.ans{background:#f8fafc;border:1px solid #F0E2CE;border-radius:16px;padding:22px 26px;margin:0 0 20px}
.state{display:inline-block;font-size:16px;font-weight:700;color:#B4531A;background:#FFF1E2;
 border:1px solid #F2D9B6;border-radius:10px;padding:6px 14px;margin:0 0 14px}
.big{font-size:15px;color:#6b7280;margin:0 0 2px}
.price{font-size:60px;font-weight:800;letter-spacing:-2px;line-height:1.1;margin:0;color:#B4531A}
.name{font-size:22px;font-weight:700;margin:2px 0 8px}
.note{font-size:15px;color:#3d4450;margin:8px 0 0}
.row{display:flex;gap:12px;margin:0 0 18px}
.seg{flex:1;border-radius:14px;padding:14px 16px;border:1px solid}
.seg .p{font-size:17px;font-weight:800;margin:0 0 2px}
.seg .t{font-size:13.5px;margin:0;opacity:.85}
.seg .v{font-size:26px;font-weight:800;margin:6px 0 0;font-variant-numeric:tabular-nums}
.facts{border-top:1px solid #e3e6ec;padding-top:16px;display:flex;gap:26px}
.fact{flex:1;font-size:15px;color:#3d4450;margin:0}
.fact b{display:block;font-size:22px;color:#1f2329;margin:0 0 2px;font-variant-numeric:tabular-nums}
.fact span{font-size:13.5px;color:#6b7280}
"""


def to_min(t: str) -> int:
    try:
        h, m = str(t).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, IndexError):
        return 0


def pick_sample(cities: list[dict]) -> dict:
    for c in cities:
        if c["city"] == SAMPLE_CITY and (c.get("floors", {}).get("pickup") or {}).get("早餐"):
            return c
    for c in cities:
        if (c.get("floors", {}).get("pickup") or {}).get("早餐", {}).get("meal"):
            return c
    return cities[0]


def main() -> int:
    path = SURFACE_PATH if SURFACE_PATH.exists() else LEGACY_PATH
    if not path.exists():
        print("缺少采集数据。")
        return 1
    s = json.loads(path.read_text(encoding="utf-8"))
    cities = s.get("cities") or []
    if not cities:
        print("数据里没有城市。")
        return 1

    n_cities = len(cities)
    n_calls = sum(c.get("calls", 0) for c in cities)
    c = pick_sample(cities)
    fl = (c.get("floors", {}).get("pickup") or {})
    periods = c.get("periods") or []

    bf = (fl.get("早餐") or {}).get("meal")
    lunch = (fl.get("午餐") or {}).get("meal")
    save = (lunch["price"] - bf["price"]) / 100 if (bf and lunch and lunch["price"] > bf["price"]) else 0

    segs = []
    for p in periods:
        bg, fg, bd, icon = PERIOD_STYLE.get(p["name"], ("#f0f2f5", "#333", "#ccc", "•"))
        f = (fl.get(p["name"]) or {}).get("meal")
        v = f"¥{f['price'] / 100:.2f}" if f else "—"
        nm = f["name"][:10] if f else ""
        segs.append(
            f'<div class="seg" style="background:{bg};color:{fg};border-color:{bd}">'
            f'<p class="p">{icon} {escape(p["name"])} '
            f'<span style="font-weight:600">{escape(p["start"])}–{escape(p["end"])}</span></p>'
            f'<p class="v">{v}</p><p class="t">{escape(nm)}</p></div>')

    # 全国发现
    bf_cities = [(x["city"], x["periods"][0]["start"]) for x in cities
                 if x.get("periods") and x["periods"][0]["name"] == "早餐"]
    earliest = min(bf_cities, key=lambda x: to_min(x[1])) if bf_cities else ("—", "—")
    latest = max(bf_cities, key=lambda x: to_min(x[1])) if bf_cities else ("—", "—")
    lunches = [(x["city"], (x.get("floors", {}).get("pickup") or {}).get("午餐", {}).get("meal"))
               for x in cities]
    lunches = [(a, b) for a, b in lunches if b]
    cheapest = min(lunches, key=lambda x: x[1]["price"]) if lunches else ("—", None)
    priciest = max(lunches, key=lambda x: x[1]["price"]) if lunches else ("—", None)

    def med(pname: str) -> int | None:
        vals = sorted(m["price"] for x in cities
                      for m in [(x.get("floors", {}).get("pickup") or {}).get(pname, {}).get("meal")]
                      if m)
        return vals[len(vals) // 2] if vals else None

    bf_med, lunch_med = med("早餐"), med("午餐")

    facts = (
        f'<div class="fact"><b>{escape(earliest[1])} / {escape(latest[1])}</b>'
        f'<span>早餐开档最早 {escape(earliest[0])}，最晚 {escape(latest[0])}，'
        f'差 {int((to_min(latest[1]) - to_min(earliest[1])) / 60)} 小时</span></div>'
        + (f'<div class="fact"><b>¥{bf_med / 100:.2f} → ¥{lunch_med / 100:.2f}</b>'
           f'<span>{len([1 for x in cities if (x.get("floors", {}).get("pickup") or {}).get("早餐", {}).get("meal")])}'
           f' 座城市的早餐地板价中位数 → 午餐中位数，早去更便宜</span></div>'
           if bf_med and lunch_med else "")
        + (f'<div class="fact"><b>¥{cheapest[1]["price"] / 100:.2f} / '
           f'¥{priciest[1]["price"] / 100:.2f}</b>'
           f'<span>午餐地板价最低 {escape(cheapest[0])}，最高 {escape(priciest[0])}</span></div>'
           if cheapest[1] and priciest[1] else "")
        + f'<div class="fact"><b>{n_cities} 城 · {n_calls} 次</b>'
        f'<span>向麦当劳订餐系统问价，全程只读、不下单</span></div>')

    ans = ""
    if bf:
        ans = (f'<div class="ans"><span class="state">{escape(c["city"])} · 早餐档 '
               f'{escape(periods[0]["start"])}–{escape(periods[0]["end"])}</span>'
               f'<p class="big">这一档最便宜的一餐</p>'
               f'<p class="price">¥{bf["price"] / 100:.2f}</p>'
               f'<p class="name">{escape(bf["name"])}</p>'
               + (f'<p class="note">同一家店午餐档最便宜的一餐 ¥{lunch["price"] / 100:.2f}'
                  f'（{escape(lunch["name"])}）—— 早餐去能省 <b>¥{save:.2f}</b>。</p>'
                  if save else "")
               + "</div>")

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>{CSS}</style></head><body><div class="card">
<h1>麦当劳几点最便宜</h1>
<span class="tag">✓ 全国 {n_cities} 座城市 · 真实价格 · 逐笔实测</span>
<p class="lead">选城市和几点去，直接告诉你那一刻最便宜能点什么 —— 麦当劳的菜单按时段切换，
早餐档和午餐档的地板价差出一顿早餐钱。</p>
{ans}
<div class="row">{"".join(segs)}</div>
<div class="facts">{facts}</div>
</div></body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
