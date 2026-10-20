"""
render_card.py — 把 data/surface.json 渲染为 README 首图(card.html), 供 headless 截图

与 render_report.py 的区别:
  report.html = 交互报告(宽表格/悬停明细/可折叠), 给人看完整数据
  card.html   = 一张静态首图, 信息密度经过裁剪, 给 README 第一眼用

设计要点: 时段带与矩阵列严格对齐到同一条时间轴(07:00 -> 打烊),
         「菜单真空带」用紫色虚线框显式标出。

输出: dist/card.html
下一步: 用 headless Chrome 截图 -> images/heatmap.png(见 tools/snap.ps1)
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface.json"
OUT_PATH = ROOT / "dist" / "card.html"

CARD_W = 1280
ROW_H = 26
LABEL_W = 232
GRID_X0 = 40 + LABEL_W
GRID_X1 = CARD_W - 40

BAND_COLORS = {
    "早餐": ("#2b4a7d", "#8fc0ff"),
    "午餐": ("#7d4a1f", "#ffc078"),
    "下午茶": ("#5a2f6b", "#e2a3f5"),
    "夜市": ("#1f4f45", "#7ee0bf"),
}


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def heat(price: int, rmin: int | None, rmax: int | None) -> str:
    """行内归一化绿->红白低温色阶。"""
    if rmax is None or rmax == rmin:
        ratio = 0.0
    else:
        ratio = (price - rmin) / (rmax - rmin)
    hue = int(142 - 142 * ratio)
    return f"hsl({hue},52%,24%)", f"hsl({hue},72%,78%)"


def render_city(surface: dict, city: dict) -> str:
    slots = city["slots"]
    basket = city["basket"]
    periods = city.get("periods") or []
    n = len(slots)
    col_w = (GRID_X1 - GRID_X0) / n

    t0, t1 = to_min(slots[0]), to_min(slots[-1])
    span = max(t1 - t0, 1)

    def x_of(t: str) -> float:
        return GRID_X0 + (to_min(t) - t0) / span * (GRID_X1 - GRID_X0)

    # 真空带: 相邻时段之间的缝隙 + 打烊后
    gaps = []
    for i in range(len(periods) - 1):
        gaps.append((periods[i]["end"], periods[i + 1]["start"]))
    if periods and periods[-1]["end"] < slots[-1]:
        gaps.append((periods[-1]["end"], slots[-1]))

    parts: list[str] = []

    # ---- 头部标题区 ----
    is_demo = bool(surface.get("isDemo"))
    badge = ("演示数据 · 非真实价格" if is_demo else "真实数据 · calculate-price 实时核价")
    badge_bg = "#4a3510" if is_demo else "#123a2a"
    badge_fg = "#ffc94d" if is_demo else "#5ee6a0"

    n_points = sum(len(v) for g in (city.get("grid") or {}).values() for v in g.values())
    ch = next((c for c in city["channels"] if c["id"] == "pickup"), city["channels"][0])
    g = (city.get("grid") or {}).get(ch["id"]) or {}

    parts.append(f"""
<div class="head">
  <div class="title-line">
    <h1>麦当劳几点最便宜</h1>
    <span class="badge" style="background:{badge_bg};color:{badge_fg}">{escape(badge)}</span>
  </div>
  <p class="sub">这个问题, 我用 <b>{n_points}</b> 次真实接口调用回答 ——
     把明天从开门到打烊切成 <b>{n}</b> 个时刻 × <b>{len(basket)}</b> 个探针商品, 逐格核价。</p>
  <p class="store">{escape(city['city'])} · {escape(city['store']['name'])} ·
     目标日 {escape(str(surface.get('targetDate', '')))} ·
     渠道 {escape(ch['label'])}</p>
</div>""")

    # ---- 统计卡 ----
    # 各时段地板价
    floors = []
    for p in periods:
        best = None
        for t, cells in g.items():
            if not (to_min(p["start"]) <= to_min(t) < to_min(p["end"])):
                continue
            for it in basket:
                cell = cells.get(it["code"]) or {}
                if "price" in cell and (best is None or cell["price"] < best[1]):
                    best = (it["name"], cell["price"])
        if best:
            floors.append((p["name"], best[0], best[1]))

    cards = "".join(
        f'<div class="stat"><span class="sv">¥{p / 100:.2f}</span>'
        f'<span class="sl">{escape(nm)}地板价</span>'
        f'<span class="sn">{escape(n)[:14]}</span></div>'
        for nm, n, p in floors)
    if gaps:
        cards += (f'<div class="stat hi"><span class="sv">{len(gaps)}</span>'
                  f'<span class="sl">菜单真空带</span>'
                  f'<span class="sn">早午档切换缝隙</span></div>')
    parts.append(f'<div class="stats">{cards}</div>')

    # ---- 官方时段带(与矩阵同一时间轴) ----
    band = [f'<div class="band-wrap" style="margin-left:{GRID_X0}px;width:{GRID_X1 - GRID_X0}px">']
    for p in periods:
        a, b = x_of(p["start"]), x_of(p["end"])
        bg, fg = BAND_COLORS.get(p["name"], ("#333", "#ccc"))
        band.append(f'<div class="band" style="left:{a - GRID_X0:.1f}px;width:{b - a:.1f}px;'
                    f'background:{bg};color:{fg}">{escape(p["name"])} '
                    f'<span>{escape(p["start"])}–{escape(p["end"])}</span></div>')
    band.append("</div>")
    parts.append("".join(band))

    # ---- 矩阵(时刻表头 + 商品行 + 真空带覆盖层, 全部相对 GRID_X0 起算) ----
    hcells = []
    for i, t in enumerate(slots):
        h = t[:2]
        show = (i == 0 or h != slots[i - 1][:2])
        hcells.append(f'<div class="hcell">{escape(h) if show else ""}</div>')
    rows = [f'<div class="row hdr"><div class="lab"></div>'
            f'<div class="cells">{"".join(hcells)}</div></div>']
    for it in basket:
        prices = [(g.get(t) or {}).get(it["code"], {}).get("price") for t in slots]
        vals = [p for p in prices if p]
        rmin, rmax = (min(vals), max(vals)) if vals else (None, None)
        cells = []
        for t in slots:
            cell = (g.get(t) or {}).get(it["code"]) or {}
            if "price" in cell:
                bg, fg = heat(cell["price"], rmin, rmax)
                cls = "cell ok"
                txt = f"{cell['price'] / 100:.0f}"
            else:
                bg, fg = "#1a1d24", "#4d5563"
                cls = "cell na"
                txt = "·"
            cells.append(f'<div class="{cls}" style="background:{bg};color:{fg}">{txt}</div>')
        rows.append(f'<div class="row"><div class="lab" title="{escape(it["name"])}">'
                    f'{escape(it["name"])}</div>'
                    f'<div class="cells">{"".join(cells)}</div></div>')
    # 真空带覆盖层: 贯穿整个矩阵高度的虚线框
    overlay = []
    for gs, ge in gaps:
        a = LABEL_W + (to_min(gs) - t0) / span * (GRID_X1 - GRID_X0)
        b = LABEL_W + (to_min(ge) - t0) / span * (GRID_X1 - GRID_X0)
        overlay.append(f'<div class="gapcol" style="left:{a:.1f}px;width:{b - a:.1f}px">'
                       f'<span>真空带</span></div>')
    parts.append(f'<div class="matrix">{"".join(rows)}<div class="overlay">{"".join(overlay)}</div></div>')

    # ---- 图例 ----
    parts.append(f"""
<div class="legend">
  <span><i class="sw ok"></i>数字 = 该时刻实付金额(元, 取整)</span>
  <span><i class="sw na"></i>· = 不可售 / 未开档</span>
  <span><i class="sw gap"></i>紫色虚线框 = 菜单真空带</span>
  <span class="src">数据: 麦当劳中国官方 MCP · calculate-price 实时核价 · 未产生任何真实订单</span>
</div>""")
    return "".join(parts)


def main() -> int:
    if not SURFACE_PATH.exists():
        print(f"未找到 {SURFACE_PATH}。先运行 survey.py 或 make_demo.py。")
        return 1
    surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    cities = surface.get("cities") or []
    # 首图只渲染第一个城市(信息密度考虑); 完整多城市见 dist/report.html
    card = render_city(surface, cities[0]) if cities else ""

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>麦当劳几点最便宜 · 首图</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:{CARD_W}px;background:#11141a;color:#e6eaf2;
 font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif;
 padding:34px 40px 26px}}
.head{{margin-bottom:18px}}
.title-line{{display:flex;align-items:center;gap:14px}}
h1{{font-size:34px;letter-spacing:.5px}}
.badge{{font-size:13px;font-weight:600;padding:4px 12px;border-radius:20px}}
.sub{{font-size:15px;color:#9aa4b6;margin-top:8px}}
.sub b{{color:#ffd479;font-weight:700}}
.store{{font-size:12.5px;color:#6f7889;margin-top:5px}}
.stats{{display:flex;gap:10px;margin:16px 0 20px}}
.stat{{flex:1;background:#181c24;border:1px solid #262c38;border-radius:10px;padding:10px 12px}}
.stat.hi{{background:#241a33;border-color:#4b3a6b}}
.sv{{display:block;font-size:23px;font-weight:800;color:#5ee6a0;line-height:1.15}}
.stat.hi .sv{{color:#c9a2ff}}
.sl{{display:block;font-size:12px;color:#8b93a3;margin-top:2px}}
.sn{{display:block;font-size:11px;color:#5f6778;margin-top:1px;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.band-wrap{{position:relative;height:26px;margin-bottom:6px}}
.band{{position:absolute;top:0;height:26px;line-height:26px;text-align:center;
 font-size:12.5px;font-weight:700;border-radius:5px;overflow:hidden;white-space:nowrap}}
.band span{{font-weight:400;opacity:.75;font-size:11px}}
.hcell{{flex:1;height:16px;line-height:16px;text-align:center;font-size:10px;color:#7e8798}}
.row.hdr{{height:16px;margin-bottom:3px}}
.matrix{{position:relative}}
.overlay{{position:absolute;inset:0;pointer-events:none}}
.gapcol{{position:absolute;top:0;bottom:0;border:1px dashed #b78aff;border-radius:3px;
 background:rgba(183,138,255,.05)}}
.gapcol span{{position:absolute;top:-1px;left:50%;transform:translateX(-50%);
 font-size:9px;color:#c9a2ff;background:#11141a;padding:0 4px;white-space:nowrap}}
.row{{display:flex;height:{ROW_H}px}}
.lab{{width:{LABEL_W - 12}px;flex:0 0 auto;height:{ROW_H}px;line-height:{ROW_H}px;
 font-size:12px;color:#b9c1d0;padding-right:10px;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.cells{{display:flex;flex:1}}
.cell{{flex:1;height:{ROW_H - 2}px;line-height:{ROW_H - 2}px;text-align:center;
 font-size:11px;border-radius:2px;margin-right:1px}}
.legend{{display:flex;gap:20px;align-items:center;margin-top:16px;font-size:11.5px;color:#7e8798}}
.legend span{{display:flex;align-items:center;gap:6px}}
.sw{{width:11px;height:11px;border-radius:2px;display:inline-block}}
.sw.ok{{background:hsl(90,52%,24%)}} .sw.na{{background:#1a1d24;border:1px solid #2c323d}}
.sw.gap{{background:transparent;border:1px dashed #b78aff}}
.src{{margin-left:auto;color:#5f6778}}
</style></head><body>{card}</body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
