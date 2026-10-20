"""
render_report.py — 把 data/surface.json 渲染为完全自包含的离线 HTML 报告

新版数据形态(2026-10-20 真机验证后):
  - 矩阵: 探针商品(行) x 时刻(列) x 渠道(分节), 每格 = calculate-price 实价 或 不可售
  - 官方时段边界(早餐/午餐/下午茶/夜市) + 菜单真空带样式
  - 每时段"最便宜吃法"摘要
  - 真实数据/演示数据 徽标机制: surface.json 的 isDemo 字段决定

输出: dist/report.html —— 零外部依赖, 双击即开。
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface.json"
OUT_PATH = ROOT / "dist" / "report.html"

SURFACE: dict = {}


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def cell_style(price, row_min, row_max):
    """行内归一化的绿->黄->红色阶。"""
    if row_max is None or row_max == row_min:
        ratio = 0.0
    else:
        ratio = (price - row_min) / (row_max - row_min)
    hue = int(140 - 135 * ratio)
    return f"background:hsl({hue},55%,26%);color:hsl({hue},70%,82%)"


def render_city(city: dict) -> str:
    slots = city["slots"]
    basket = city["basket"]
    periods = city.get("periods") or []
    grid = city.get("grid") or {}

    # 真空带: 上一时段结束 -> 下一时段开始(含打烊后)
    gaps = []
    for i in range(len(periods) - 1):
        gaps.append((to_min(periods[i]["end"]), to_min(periods[i + 1]["start"])))
    if periods:
        gaps.append((to_min(periods[-1]["end"]), 24 * 60))

    def gap_class(t):
        m = to_min(t)
        return " gap" if any(a <= m < b for a, b in gaps) else ""

    html = [f'<section class="city"><h2>{escape(city["city"])} · {escape(city["store"]["name"])}</h2>']
    html.append(f'<p class="meta">门店编码 {escape(str(city["store"]["code"]))} · '
                f'营业 {escape(city["store"].get("businessStart") or "?")}-{escape(city["store"].get("businessEnd") or "?")} · '
                f'目标日期 {escape(str(SURFACE.get("targetDate", "")))}</p>')

    if periods:
        segs = " ".join(
            f'<span class="period"><b>{escape(p["name"])}</b> {escape(p["start"])}–{escape(p["end"])}</span>'
            for p in periods)
        html.append(f'<p class="periods">官方时段(来自门店接口 reservationTimeOptions): {segs}</p>')
        html.append('<p class="meta">虚线紫色列 = 「菜单真空带」: 上一时段已结束、下一时段未开始的缝隙。</p>')

    # 每时段最便宜吃法
    findings = []
    for ch in city["channels"]:
        g = grid.get(ch["id"]) or {}
        rows = []
        for p in periods:
            best = None
            for t, cells in g.items():
                if not (to_min(p["start"]) <= to_min(t) < to_min(p["end"])):
                    continue
                for it in basket:
                    c = cells.get(it["code"]) or {}
                    if "price" in c and (best is None or c["price"] < best[2]):
                        best = (it["name"], t, c["price"])
            if best:
                rows.append(f'<tr><td>{escape(p["name"])}</td><td>{escape(best[0])}</td>'
                            f'<td class="price">¥{best[2] / 100:.2f}</td><td>{escape(best[1])}</td></tr>')
        if rows:
            findings.append(
                f'<details open><summary>{escape(ch["label"])} · 各时段最便宜吃法</summary>'
                f'<table><thead><tr><th>时段</th><th>商品</th><th>实付</th><th>时刻</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></details>')
    html.extend(findings)

    # 热力矩阵(每渠道一节)
    for ch in city["channels"]:
        g = grid.get(ch["id"]) or {}
        html.append(f'<h3>{escape(ch["label"])}</h3><div class="matrix-wrap"><table class="matrix">')
        head = "".join(f'<th class="slot{gap_class(t)}">{escape(t)}</th>' for t in slots)
        html.append(f'<thead><tr><th class="item">商品 \\ 时刻</th>{head}</tr></thead><tbody>')
        for it in basket:
            row_prices: list[int] = []
            for t in slots:
                cell = (g.get(t) or {}).get(it["code"]) or {}
                if "price" in cell:
                    row_prices.append(cell["price"])
            rmin = min(row_prices) if row_prices else None
            rmax = max(row_prices) if row_prices else None
            cells = []
            for t in slots:
                cell = (g.get(t) or {}).get(it["code"]) or {}
                if "price" in cell:
                    p = cell["price"] / 100
                    cells.append(f'<td style="{cell_style(cell["price"], rmin, rmax)}" '
                                 f'title="{escape(it["name"])} @ {escape(t)}">¥{p:.2f}</td>')
                else:
                    msg = escape(str(cell.get("unavailable", "")))
                    cells.append(f'<td class="na{gap_class(t)}" title="{msg}">—</td>')
            html.append(f'<tr><th class="item">{escape(it["name"])}</th>{"".join(cells)}</tr>')
        html.append("</tbody></table></div>")

    html.append('<p class="note">— = 该时刻不可售(菜单断崖/营业外)。颜色按「同一商品全天价差」归一化: '
                '绿=最便宜, 红=最贵。所有金额均为 calculate-price 实时返回, 已换算为元。</p>')
    html.append("</section>")
    return "".join(html)


def main() -> int:
    global SURFACE
    if not SURFACE_PATH.exists():
        print(f"未找到 {SURFACE_PATH}。先运行 survey.py(或 make_demo.py 生成演示数据)。")
        return 1
    SURFACE = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    is_demo = bool(SURFACE.get("isDemo"))
    badge = ('<span class="badge demo">演示数据 · 非真实价格</span>' if is_demo
             else '<span class="badge real">真实数据 · calculate-price 实时核价</span>')

    cities = SURFACE.get("cities") or []
    cities_html = "".join(render_city(c) for c in cities)
    n_points = sum(len(v) for c in cities for g in (c.get("grid") or {}).values() for v in g.values())

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>麦当劳几点最便宜 · {escape(str(SURFACE.get('targetDate', '')))} 全天价格矩阵</title>
<style>
:root{{--bg:#1b1e24;--panel:#242832;--line:#343a46;--fg:#dfe4ec;--dim:#8b93a3}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
 font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;padding:24px}}
header{{max-width:1500px;margin:0 auto 18px}}
h1{{font-size:26px;margin:0 0 6px}}
.sub{{color:var(--dim);margin:0 0 8px;font-size:13px}}
.badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;vertical-align:middle}}
.badge.real{{background:#143d2b;color:#5ee6a0}}
.badge.demo{{background:#4a3510;color:#ffc94d}}
section.city{{max-width:1500px;margin:0 auto 22px;background:var(--panel);
 border:1px solid var(--line);border-radius:12px;padding:18px}}
h2{{font-size:18px;margin:0 0 4px}}
h3{{font-size:15px;margin:18px 0 8px;color:#aeb7c6}}
.meta,.note{{color:var(--dim);font-size:12px}}
.periods{{font-size:13px}} .period{{margin-right:14px}} .period b{{color:#7ab8ff}}
details{{margin:10px 0;background:#1f232c;border:1px solid var(--line);border-radius:8px;padding:10px}}
summary{{cursor:pointer;font-weight:600;font-size:14px}}
table{{border-collapse:collapse;font-size:12px;margin-top:8px}}
th,td{{border:1px solid var(--line);padding:5px 8px;text-align:left}}
details table td.price{{font-weight:700;color:#5ee6a0}}
.matrix-wrap{{overflow-x:auto}}
.matrix th,.matrix td{{padding:4px 6px;text-align:center;white-space:nowrap}}
.matrix th.item{{text-align:left;position:sticky;left:0;background:var(--panel);z-index:2;max-width:180px}}
.matrix th.slot{{font-size:10px;color:#aeb7c6}}
.matrix td.na{{color:#5c6472;background:#20242c}}
.matrix th.slot.gap,.matrix td.gap{{border-top:2px dashed #b78aff}}
footer{{max-width:1500px;margin:10px auto;color:var(--dim);font-size:11px}}
</style></head><body>
<header>
<h1>麦当劳几点最便宜 {badge}</h1>
<p class="sub">这个问题, 用 {n_points} 个真实数据点回答 —— 基于麦当劳中国官方 MCP 的全天价格矩阵</p>
</header>
{cities_html}
<footer>数据来源: 麦当劳中国官方 MCP (https://mcp.mcd.cn), calculate-price 实时返回 ·
生成于 {escape(str(SURFACE.get('generatedAt', datetime.now().isoformat(timespec='seconds'))))} ·
目标日期 {escape(str(SURFACE.get('targetDate', '')))} · 只读采集, 未产生任何真实订单</footer>
</body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB, 完全自包含, 双击即开)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
