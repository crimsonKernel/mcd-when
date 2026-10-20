"""
render_card.py — README 首图渲染器(第二版: 时段着色)

设计决策(基于第一版的视觉诊断):
  - 第一版把格子颜色编码为「行内价格归一化」, 但真机数据显示同一商品全天价不变,
    结果整片绿, 没有信息量。第二版改为「按官方时段着色」: 早餐蓝/午餐橙/下午茶紫/夜市青,
    不可售深灰 —— 颜色编码的是「这一刻属于哪个档」, 菜单断崖和真空带一眼可见。
  - 首图的任务是 2 秒内传达「这个项目有意思」, 不是展示全部数据。
    所以: 4 张大数字结论卡 + 一条时间轴(带真空带缺口) + 8 行精简矩阵。
    完整 20 商品矩阵在 dist/report.html。

输出: dist/card.html -> headless Chrome 截图 -> images/heatmap.png
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface.json"
OUT_PATH = ROOT / "dist" / "card.html"

CARD_W = 1280
LABEL_W = 216
GRID_X0 = 48 + LABEL_W          # 矩阵左缘(相对卡片内容区)
GRID_X1 = CARD_W - 48           # 矩阵右缘
ROW_H = 30

# 时段配色: 背景(深) + 前景(亮)
PERIOD_COLORS = {
    "早餐": ("#1d3f66", "#7db8f7"),
    "午餐": ("#6b3a10", "#f7b267"),
    "下午茶": ("#45265e", "#c99df0"),
    "夜市": ("#134b41", "#5eead4"),
}
NA_BG = "#1a1e26"


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def pick_showcase(basket: list[dict], periods: list[dict]) -> list[dict]:
    """挑 8 个有代表性的商品: 4 个早餐档专属 + 4 个正餐/全天。"""
    bf = next((p for p in periods if p["name"] == "早餐"), None)
    bf_end = to_min(bf["end"]) if bf else 10 * 60 + 15
    breakfast = [it for it in basket if to_min(it.get("firstSlot") or "23:59") < bf_end]
    main = [it for it in basket if it not in breakfast]
    return (breakfast[:4] + main[:4])[:8]


def period_of(t: str, periods: list[dict]) -> dict | None:
    m = to_min(t)
    for p in periods:
        if to_min(p["start"]) <= m < to_min(p["end"]):
            return p
    return None


def render_city(surface: dict, city: dict, all_cities: list[dict]) -> str:
    slots = city["slots"]
    periods = city.get("periods") or []
    basket = city.get("basket") or []
    ch = next((c for c in city["channels"] if c["id"] == "pickup"), city["channels"][0])
    g = (city.get("grid") or {}).get(ch["id"]) or {}

    n = len(slots)
    t0, t1 = to_min(slots[0]), to_min(slots[-1])
    span = max(t1 - t0, 1)

    def x_of(t: str) -> float:
        return (to_min(t) - t0) / span * (GRID_X1 - GRID_X0)

    # 真空带
    gaps = []
    for i in range(len(periods) - 1):
        gaps.append((periods[i]["end"], periods[i + 1]["start"]))
    if periods and to_min(periods[-1]["end"]) < t1:
        gaps.append((periods[-1]["end"], slots[-1]))

    is_demo = bool(surface.get("isDemo"))
    badge = "演示数据 · 非真实价格" if is_demo else "真实数据 · calculate-price 实时核价"
    badge_bg, badge_fg = ("#4a3510", "#ffc94d") if is_demo else ("#123a2a", "#5ee6a0")
    total_points = sum(len(v) for c in all_cities for gg in (c.get("grid") or {}).values()
                       for v in gg.values())

    # ---- 大数字结论 ----
    def floor_price(period_name: str) -> tuple[str, int] | None:
        p = next((x for x in periods if x["name"] == period_name), None)
        if not p:
            return None
        best = None
        for t in slots:
            if not (to_min(p["start"]) <= to_min(t) < to_min(p["end"])):
                continue
            for it in basket:
                cell = (g.get(t) or {}).get(it["code"]) or {}
                if "price" in cell and (best is None or cell["price"] < best[1]):
                    best = (it["name"], cell["price"])
        return best

    bf = floor_price("早餐")
    lunch = floor_price("午餐")
    gap_min = max(((to_min(b) - to_min(a)) for a, b in gaps), default=0)
    wuhan = next((c for c in all_cities if c["city"] == "武汉"), None)
    wuhan_bf = next((p for p in (wuhan or {}).get("periods", []) if p["name"] == "早餐"), None)

    stats = []
    if bf:
        stats.append((f"¥{bf[1] / 100:.2f}", "早餐地板价", bf[0], "#5ee6a0"))
    if lunch:
        stats.append((f"¥{lunch[1] / 100:.2f}", "午餐起地板价", lunch[0], "#f7b267"))
    if gap_min:
        stats.append((f"{gap_min}min", "菜单真空带", "早餐已收, 午餐未开", "#c99df0"))
    if wuhan_bf:
        stats.append((wuhan_bf["start"], "武汉早餐开档", "24小时店, 早 2 小时", "#5eead4"))
    stats_html = "".join(
        f'<div class="stat"><span class="sv" style="color:{c}">{escape(v)}</span>'
        f'<span class="sl">{escape(l)}</span><span class="sn">{escape(s)[:16]}</span></div>'
        for v, l, s, c in stats)

    # ---- 时间轴(时段带 + 真空带缺口) ----
    band = [f'<div class="tl-wrap">']
    for p in periods:
        a, b = x_of(p["start"]), x_of(p["end"])
        bg, fg = PERIOD_COLORS.get(p["name"], ("#333", "#ccc"))
        band.append(
            f'<div class="tl-band" style="left:{a:.1f}px;width:{b - a:.1f}px;'
            f'background:{bg};color:{fg}">'
            f'<b>{escape(p["name"])}</b><span>{escape(p["start"])}–{escape(p["end"])}</span></div>')
    for i, (gs, ge) in enumerate(gaps):
        a, b = x_of(gs), x_of(ge)
        band.append(f'<div class="tl-gap" style="left:{a:.1f}px;width:{b - a:.1f}px"></div>')
    # 小时刻度
    ticks = []
    for h in range(t0 // 60 + 1, t1 // 60 + 1):
        if h % 2 == 1:
            ticks.append(f'<div class="tl-tick" style="left:{x_of(f"{h:02d}:00"):.1f}px">{h:02d}</div>')
    band.append("".join(ticks))
    band.append("</div>")

    # ---- 精简矩阵(时段着色) ----
    showcase = pick_showcase(basket, periods)
    hcells = []
    for i, t in enumerate(slots):
        h, mm = int(t[:2]), t[3:]
        show = (mm == "00" and h % 2 == 1) or i == 0
        hcells.append(f'<div class="hcell">{h:02d}</div>' if show else '<div class="hcell"></div>')
    rows = [f'<div class="mrow hdr"><div class="mlab"></div>'
            f'<div class="mcells">{"".join(hcells)}</div></div>']
    for it in showcase:
        cells = []
        for t in slots:
            cell = (g.get(t) or {}).get(it["code"]) or {}
            p = period_of(t, periods)
            if "price" in cell and p:
                bg, _fg = PERIOD_COLORS.get(p["name"], ("#333", "#ccc"))
                cells.append(f'<div class="mcell" style="background:{bg}" '
                             f'title="{escape(it["name"])} {t} ¥{cell["price"] / 100:.2f}"></div>')
            else:
                cells.append(f'<div class="mcell" style="background:{NA_BG}"></div>')
        rows.append(f'<div class="mrow"><div class="mlab" title="{escape(it["name"])}">'
                    f'{escape(it["name"])}</div><div class="mcells">{"".join(cells)}</div></div>')
    overlay = "".join(
        f'<div class="m-gap" style="left:{LABEL_W + x_of(gs):.1f}px;width:{x_of(ge) - x_of(gs):.1f}px"></div>'
        for gs, ge in gaps)
    matrix = f'<div class="matrix">{"".join(rows)}<div class="m-overlay">{overlay}</div></div>'

    # ---- 图例 ----
    legend_items = "".join(
        f'<span><i class="sw" style="background:{bg}"></i>{escape(name)}</span>'
        for name, (bg, _) in PERIOD_COLORS.items())
    legend = f"""
<div class="legend">
  {legend_items}
  <span><i class="sw" style="background:{NA_BG};border:1px solid #2c323d"></i>不可售 / 未开档</span>
  <span><i class="sw" style="background:repeating-linear-gradient(45deg,transparent,transparent 2px,rgba(199,157,240,.5) 2px,rgba(199,157,240,.5) 4px);border:1px dashed #9d7fd4"></i>菜单真空带</span>
  <span class="src">数据: 麦当劳中国官方 MCP · {total_points} 次 calculate-price 实时核价 · 未产生任何订单</span>
</div>"""

    return f"""
<div class="head">
  <div class="title-line">
    <h1>麦当劳几点最便宜</h1>
    <span class="badge" style="background:{badge_bg};color:{badge_fg}">{escape(badge)}</span>
  </div>
  <p class="sub">5 座城市 × 全天 {n} 个时刻 × 20 个探针商品 × 2 个渠道 =
     <b>{total_points}</b> 次真实核价, 回答一个问题: 几点去, 能买到什么?</p>
</div>
<div class="stats">{stats_html}</div>
{''.join(band)}
{matrix}
{legend}
<p class="store">{escape(city['city'])} · {escape(city['store']['name'])} ·
   目标日 {escape(str(surface.get('targetDate', '')))} · 渠道 {escape(ch['label'])} ·
   完整矩阵见 report.html</p>"""


def main() -> int:
    if not SURFACE_PATH.exists():
        print(f"未找到 {SURFACE_PATH}。先运行 survey.py 或 make_demo.py。")
        return 1
    surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    cities = surface.get("cities") or []
    card = render_city(surface, cities[0], cities) if cities else ""

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>麦当劳几点最便宜 · 首图</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:{CARD_W}px;background:#0f1218;color:#e6eaf2;
 font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif;
 padding:40px 48px 30px}}
.head{{margin-bottom:22px}}
.title-line{{display:flex;align-items:center;gap:14px}}
h1{{font-size:36px;letter-spacing:1px}}
.badge{{font-size:13px;font-weight:600;padding:4px 14px;border-radius:20px}}
.sub{{font-size:15px;color:#9aa4b6;margin-top:10px}}
.sub b{{color:#ffd479;font-weight:700}}
.stats{{display:flex;gap:12px;margin-bottom:26px}}
.stat{{flex:1;background:#161a22;border:1px solid #232936;border-radius:12px;padding:14px 16px}}
.sv{{display:block;font-size:30px;font-weight:800;line-height:1.1;letter-spacing:.5px}}
.sl{{display:block;font-size:13px;color:#98a1b3;margin-top:6px;font-weight:600}}
.sn{{display:block;font-size:11px;color:#5f6778;margin-top:3px;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.tl-wrap{{position:relative;height:34px;margin-left:{GRID_X0}px;width:{GRID_X1 - GRID_X0}px;
 margin-bottom:8px}}
.tl-band{{position:absolute;top:0;height:34px;border-radius:6px;display:flex;
 align-items:center;justify-content:center;gap:6px;overflow:hidden;white-space:nowrap}}
.tl-band b{{font-size:14px}} .tl-band span{{font-size:11px;opacity:.8}}
.tl-gap{{position:absolute;top:0;height:34px;border-radius:6px;
 background:repeating-linear-gradient(45deg,rgba(199,157,240,.12),rgba(199,157,240,.12) 3px,transparent 3px,transparent 7px);
 border:1px dashed #9d7fd4;display:flex;align-items:center;justify-content:center}}
.tl-gap span{{font-size:9.5px;color:#c99df0;letter-spacing:1px}}
.tl-tick{{position:absolute;top:38px;font-size:10px;color:#6a7385;transform:translateX(-50%)}}
.matrix{{position:relative;margin-top:30px}}
.mrow{{display:flex;height:{ROW_H}px;align-items:center}}
.mrow.hdr{{height:18px;margin-bottom:4px}}
.mlab{{width:{LABEL_W - 14}px;flex:0 0 auto;font-size:13px;color:#c3cad8;padding-right:12px;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.mcells{{display:flex;flex:1;gap:1px}}
.hcell{{flex:1;text-align:center;font-size:10px;color:#7e8798}}
.mcell{{flex:1;height:{ROW_H - 8}px;border-radius:2px}}
.m-overlay{{position:absolute;inset:0;pointer-events:none}}
.m-gap{{position:absolute;top:0;bottom:0;border:1px dashed #9d7fd4;border-radius:3px;
 background:rgba(157,127,212,.07)}}
.legend{{display:flex;gap:18px;align-items:center;margin-top:22px;font-size:12px;color:#8b93a3}}
.legend span{{display:flex;align-items:center;gap:6px}}
.sw{{width:13px;height:13px;border-radius:3px;display:inline-block}}
.src{{margin-left:auto;color:#5f6778}}
.store{{margin-top:10px;font-size:11.5px;color:#565e6e}}
</style></head><body>{card}</body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
