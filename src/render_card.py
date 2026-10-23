"""
render_card.py — 生成 README 首图用的卡片页 (dist/card.html), 再由浏览器截图成 images/heatmap.png

首图叙事跟着产品结论走。2026-10-22 起改成「菜单断层」版:
价格轴是平的(四档最便宜单品都是 ¥5 圆筒), 断层全在菜单构成上 ——
后三档在 360 座城市里菜单完全相同, 只有早餐是另一套。
所以首图不再讲「早去省一顿早餐钱」, 改讲「你这个点到店, 有什么可吃」。
1.2 起产品问题本身也换掉了: 不问「几点最便宜」, 只问「这个点卖什么」。

数据和口径与两页版完全一致: 优先 surface_batch.json(全菜单), 不够 50 城时退回
surface_national.json(探针快照); 全菜单缺的 8 座城用探针快照补, 保证 388 城不缺。
自包含, 零 JS(截图环境跑不了交互)。
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from render_report import FULL_MENU_MIN_CITIES, build_city, hero_facts

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface_national.json"
BATCH_PATH = ROOT / "data" / "surface_batch.json"
LEGACY_PATH = ROOT / "data" / "surface.json"
OUT_PATH = ROOT / "dist" / "card.html"

PERIOD_STYLE = {
    "早餐": ("#FFF2D9", "#8A5300", "#F0C987", "🌅"),
    "午餐": ("#FFE6D6", "#A64400", "#F2B48A", "🍔"),
    "下午茶": ("#EFE6FF", "#5B3BA8", "#C9B6F5", "🍰"),
    "夜市": ("#DDEAFF", "#1D4F91", "#A9C6F2", "🌙"),
}

SAMPLE_CITY = "上海"
SAMPLE_PERIOD = "午餐"

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
 background:#FFF1E2;border:1px solid #F2D9B6;border-radius:20px;padding:4px 14px;margin:0 0 20px}
.lead{font-size:17px;color:#3d4450;margin:0 0 22px}
.lead b{color:#B4531A}
.ans{background:#f8fafc;border:1px solid #F0E2CE;border-radius:16px;padding:22px 26px;margin:0 0 20px}
.state{display:inline-block;font-size:16px;font-weight:700;color:#B4531A;background:#FFF1E2;
 border:1px solid #F2D9B6;border-radius:10px;padding:6px 14px;margin:0 0 14px}
.big{font-size:15px;color:#6b7280;margin:0 0 2px}
.price{font-size:60px;font-weight:800;letter-spacing:-2px;line-height:1.1;margin:0;color:#B4531A}
.name{font-size:22px;font-weight:700;margin:2px 0 8px}
.note{font-size:15px;color:#3d4450;margin:8px 0 0}
.note b{color:#B4531A}
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


def load_cities() -> tuple[list[dict], dict]:
    """和两页版同一套取数逻辑: 全菜单优先, 探针快照补缺, 返回 (城市, 快照头)。"""
    path = SURFACE_PATH
    if BATCH_PATH.exists():
        try:
            n = len(json.loads(BATCH_PATH.read_text(encoding="utf-8")).get("cities") or [])
        except (json.JSONDecodeError, OSError):
            n = 0
        if n >= FULL_MENU_MIN_CITIES:
            path = BATCH_PATH
    if not path.exists():
        raise SystemExit(f"缺少采集数据。先跑: python src/survey_batch.py")
    surface = json.loads(path.read_text(encoding="utf-8"))
    cities = list(surface.get("cities") or [])
    if path == BATCH_PATH and SURFACE_PATH.exists():
        probe = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
        have = {c.get("city") for c in cities}
        cities += [c for c in (probe.get("cities") or []) if c.get("city") not in have]
    return cities, surface


def pick_sample(cities: list[dict]) -> dict:
    for c in cities:
        if c["city"] == SAMPLE_CITY and (c.get("floors", {}).get("pickup") or {}).get(SAMPLE_PERIOD):
            return c
    for c in cities:
        if (c.get("floors", {}).get("pickup") or {}).get(SAMPLE_PERIOD, {}).get("meal"):
            return c
    return cities[0]


def main() -> int:
    cities_raw, surface = load_cities()
    if not cities_raw:
        print("数据里没有城市。")
        return 1

    n_cities = len(cities_raw)
    n_calls = sum(c.get("calls", 0) for c in cities_raw)
    target = escape(str(surface.get("targetDate", "")))
    hf = hero_facts(cities_raw)

    # 样本城的那一档: 在售件数 / 有没有独有商品 / 和哪几档完全相同
    sample = pick_sample(cities_raw)
    sc = build_city(sample)
    per = next((p for p in sc["periods"] if p["name"] == SAMPLE_PERIOD), None)
    same_as: list[str] = []
    only_n = 0
    if per:
        mine = {m[0] for m in per["menu"]}
        for q in sc["periods"]:
            if q["name"] == SAMPLE_PERIOD:
                continue
            other = {m[0] for m in q["menu"]}
            if other == mine:
                same_as.append(q["name"])
        others = set()
        for q in sc["periods"]:
            if q["name"] != SAMPLE_PERIOD:
                others |= {m[0] for m in q["menu"]}
        only_n = len(mine - others)
    n_menu = len(per["menu"]) if per else 0

    segs = []
    for p in (sc["periods"] if per else []):
        bg, fg, bd, icon = PERIOD_STYLE.get(p["name"], ("#f0f2f5", "#333", "#ccc", "•"))
        v = f"¥{p['meal']['p'] / 100:.2f}" if p.get("meal") else "—"
        nm = (p["meal"]["n"][:10] if p.get("meal") else "")
        segs.append(
            f'<div class="seg" style="background:{bg};color:{fg};border-color:{bd}">'
            f'<p class="p">{icon} {escape(p["name"])} '
            f'<span style="font-weight:600">{escape(p["start"])}–{escape(p["end"])}</span></p>'
            f'<p class="v">{v}</p><p class="t">{escape(nm)}</p></div>')

    same_txt = "、".join(same_as) if same_as else "别的档"
    ans = ""
    if per and per.get("meal"):
        ans = (f'<div class="ans"><span class="state">{escape(sample["city"])} · '
               f'{escape(SAMPLE_PERIOD)}档 {escape(per["start"])}–{escape(per["end"])}</span>'
               f'<p class="big">这一档在售 <b style="color:#1f2329">{n_menu}</b> 件，'
               f'其中 <b style="color:#1f2329">{only_n}</b> 件是这一档独有的</p>'
               f'<p class="price">¥{per["meal"]["p"] / 100:.2f}</p>'
               f'<p class="name">{escape(per["meal"]["n"])}</p>'
               f'<p class="note">菜单和<b>{escape(same_txt)}</b>完全一样 —— 官方把一天切成四档，'
               f'但后三档卖的是同一套东西。早餐档才是另一套菜单：便宜 '
               f'<b>¥{(hf["lf_med"] - hf["bf_med"]) / 100:.2f}</b>，但少 {hf["bf_missing"]} 件，'
               f'另有 {hf["bf_only"]} 件只在早晨卖。</p></div>')

    facts = (
        f'<div class="fact"><b>{hf["lunch_eq_night"]} / {hf["full_n"]}</b>'
        f'<span>有完整四档的城市里，午餐和夜市的菜单完全相同</span></div>'
        f'<div class="fact"><b>+{hf["tea_extra"]:g} 件</b>'
        f'<span>下午茶平均只比午餐多的件数（学生专享）</span></div>'
        f'<div class="fact"><b>−{hf["bf_missing"]} / +{hf["bf_only"]} 件</b>'
        f'<span>早餐比午餐少的件数 / 只在早餐档卖的件数</span></div>'
        f'<div class="fact"><b>{n_cities} 城 · {n_calls} 次</b>'
        f'<span>向麦当劳订餐系统逐笔问价（{target}），全程只读、不下单</span></div>')

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>麦当劳这个点卖什么 · 全国 {n_cities} 城实测</title>
<style>{CSS}</style></head><body><div class="card">
<h1>麦当劳这个点卖什么</h1>
<span class="tag">✓ 全国 {n_cities} 座城市 · {n_calls} 次真实问价 · 逐笔实测</span>
<p class="lead">官方把一天切成四档，但<b>后三档卖的东西一模一样</b> ——
价格轴几乎是平的（四档最便宜的单品都是 ¥5 圆筒），断层全在菜单上。
所以「几点最便宜」的答案永远是早上、这句话没有信息量；
这个工具只回答<b>「我这个点到店，有什么可吃」</b>。</p>
{ans}
<div class="row">{"".join(segs)}</div>
<div class="facts">{facts}</div>
</div></body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB) · "
          f"{n_cities} 城 / {n_calls} 次问价 / 样本 {sample['city']}·{SAMPLE_PERIOD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
