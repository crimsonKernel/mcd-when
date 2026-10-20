"""
render_report.py — 把 data/surface.json 渲染为「给所有人看」的离线 HTML 页面

设计原则(2026-10-20 重构):
  * 受众是全体麦当劳顾客, 不是程序员 —— 全篇不出现 MCP / 接口名 / 参数名
  * 浅色底 + 大字号 + 单栏 880px, 手机可读、可打印、不吃深色对比度
  * 排版防错乱: 全局 box-sizing; 卡片用 grid auto-fit; 表格 table-layout:fixed
    外套 overflow-x:auto; 数字 tabular-nums; 不用 sticky / 不用 JS 参与布局
  * 技术细节收进页面底部折叠区, 不抢占普通人视线

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

# 时段视觉(浅底深字, 白底上清晰可辨)
PERIOD_STYLE = {
    "早餐":   ("#FFF2D9", "#8A5300", "#F0C987", "🌅"),
    "午餐":   ("#FFE6D6", "#A64400", "#F2B48A", "🍔"),
    "下午茶": ("#EFE6FF", "#5B3BA8", "#C9B6F5", "🍰"),
    "夜市":   ("#DDEAFF", "#1D4F91", "#A9C6F2", "🌙"),
}

CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#f6f7f9;color:#1f2329;
 font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB","Source Han Sans SC",
   "Noto Sans CJK SC",system-ui,-apple-system,sans-serif;
 font-size:16px;line-height:1.7;padding:20px 14px 40px;
 word-break:break-word;overflow-wrap:break-word}
.wrap{max-width:880px;margin:0 auto}
h1{font-size:30px;line-height:1.35;margin:0 0 10px;letter-spacing:-.2px}
h2{font-size:21px;margin:34px 0 12px;padding-top:6px}
h3{font-size:17px;margin:22px 0 8px}
p{margin:0 0 12px}
a{color:#1D4F91}
.lead{font-size:17px;color:#3d4450;margin:0 0 14px}
.tag{display:inline-block;background:#e6f4ea;color:#1a7f37;border:1px solid #b7e1c4;
 border-radius:20px;padding:3px 12px;font-size:13px;font-weight:700;vertical-align:middle}
.tag.demo{background:#fff4ce;color:#8a6100;border-color:#f0d999}
.card{background:#fff;border:1px solid #e3e6ec;border-radius:14px;padding:18px 18px 16px;
 margin:0 0 16px}
.sub{color:#6b7280;font-size:14px;margin:0}
.num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}

/* —— 城市切换: 纯 CSS 锚点, JS 失败也不影响阅读 —— */
.citynav{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 6px}
.citynav a{display:inline-block;padding:7px 15px;border:1px solid #d7dbe3;border-radius:20px;
 background:#fff;color:#1f2329;text-decoration:none;font-size:15px}
.citynav a:hover{border-color:#1D4F91;color:#1D4F91}

/* —— 时段卡片: grid auto-fit, 窄屏自动堆叠, 永不溢出 —— */
.periods{display:grid;grid-template-columns:repeat(auto-fit,minmax(196px,1fr));
 gap:12px;margin:14px 0 6px}
.pcard{border:1px solid;border-radius:14px;padding:14px 14px 12px}
.pcard .pname{font-size:15px;font-weight:700;margin:0 0 2px}
.pcard .ptime{font-size:23px;font-weight:800;letter-spacing:-.5px;margin:0 0 8px}
.pcard .plabel{font-size:12.5px;opacity:.8;margin:0 0 2px}
.pcard .pbest{font-size:16px;font-weight:700;margin:0}
.pcard .pprice{font-size:28px;font-weight:800;letter-spacing:-1px;margin:0 0 4px}
.pcard .phint{font-size:12.5px;opacity:.85;margin:6px 0 0}

/* —— 时间轴: 表格布局, 列宽按比例, 不依赖 flex 计算 —— */
.tl{width:100%;border-collapse:collapse;table-layout:fixed;margin:10px 0 4px}
.tl td{border:0;padding:0;height:34px;text-align:center;font-size:13px;font-weight:700;
 overflow:hidden;white-space:nowrap}
.tl td.gap{background:repeating-linear-gradient(45deg,#f0f1f4,#f0f1f4 5px,#e2e4ea 5px,#e2e4ea 10px);
 color:#8b93a3;font-weight:600;font-size:11px}
.tl2{width:100%;border-collapse:collapse;table-layout:fixed;margin:0 0 4px}
.tl2 td{border:0;padding:0;font-size:11px;color:#6b7280;text-align:left;
 overflow:hidden;white-space:nowrap}
.tlnote{font-size:13px;color:#6b7280;margin:0}

/* —— 提醒条目 —— */
.tips{margin:0;padding:0;list-style:none}
.tips li{background:#fff;border:1px solid #e3e6ec;border-left:4px solid #f0b429;
 border-radius:10px;padding:12px 14px;margin:0 0 10px;font-size:15.5px}
.tips li b{color:#b45309}

/* —— 表格(明细): 两列窄表, 绝不撑破容器 —— */
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:10px 0 0;max-width:100%}
table.d{border-collapse:collapse;width:100%;table-layout:fixed;font-size:14px}
table.d th,table.d td{border:1px solid #e3e6ec;padding:8px 10px;text-align:left;vertical-align:top}
table.d thead th{background:#f0f2f5;font-weight:700;white-space:nowrap}
table.d td.p{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap}
table.d td.c{text-align:center}

/* —— 折叠区: 折叠时内容彻底退出布局(防止内部宽表撑破页面) —— */
details{margin:14px 0 0;border:1px solid #e3e6ec;border-radius:12px;background:#fff;overflow:hidden}
details:not([open]) .dbody{display:none}
details summary{cursor:pointer;padding:13px 16px;font-weight:700;font-size:15.5px;
 background:#fafbfc;list-style:none}
details summary::-webkit-details-marker{display:none}
details summary::before{content:"▸ ";color:#6b7280}
details[open] summary::before{content:"▾ "}
details .dbody{padding:4px 16px 16px}
code{background:#f0f2f5;border-radius:4px;padding:1px 5px;font-size:13px}
footer{max-width:880px;margin:26px auto 0;color:#8b93a3;font-size:12.5px;
 border-top:1px solid #e3e6ec;padding-top:12px;line-height:1.6}
@media print{
  body{background:#fff;padding:0;font-size:12pt}
  .card,details{break-inside:avoid}
  .citynav{display:none}
}
@media (max-width:520px){
  h1{font-size:24px} h2{font-size:19px}
  .pcard .pprice{font-size:24px} .pcard .ptime{font-size:20px}
}
"""


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def period_of(t: str, periods: list[dict]) -> dict | None:
    m = to_min(t)
    for p in periods:
        if to_min(p["start"]) <= m < to_min(p["end"]):
            return p
    return None


def fmt_span(a: str, b: str) -> str:
    """07:14 -> 10:15 显示为 7:14–10:15 (去掉前导零, 普通人更好读)。"""
    def trim(x: str) -> str:
        return f"{int(x[:2])}:{x[3:]}" if x[:2].startswith("0") else x
    return f"{trim(a)}–{trim(b)}"


def best_in_period(grid: dict, basket: list[dict], slots: list[str],
                   p: dict, top: int = 1) -> list[tuple[str, int]]:
    """某时段内最便宜的若干个可售商品(按价格升序)。"""
    found: dict[str, int] = {}
    for t in slots:
        if not (to_min(p["start"]) <= to_min(t) < to_min(p["end"])):
            continue
        row = grid.get(t) or {}
        for it in basket:
            cell = row.get(it["code"]) or {}
            if "price" in cell:
                prev = found.get(it["name"])
                if prev is None or cell["price"] < prev:
                    found[it["name"]] = cell["price"]
    return sorted(found.items(), key=lambda x: x[1])[:top]


def render_timeline(periods: list[dict], business_start: str, business_end: str) -> tuple[str, list[str]]:
    """按真实时长比例画一条时间轴; 返回 (HTML, 真空带说明列表)。"""
    if not periods:
        return "", []
    start = min(to_min(periods[0]["start"]), to_min(business_start or "00:00"))
    end = max(to_min(periods[-1]["end"]), to_min(business_end or "23:59"))
    total = max(end - start, 1)

    segs: list[tuple[str, int, int, str | None]] = []  # (kind, from, to, period_name)
    cur = start
    for p in periods:
        a, b = to_min(p["start"]), to_min(p["end"])
        if a > cur:
            segs.append(("gap", cur, a, None))
        segs.append(("p", a, b, p["name"]))
        cur = b
    if cur < end:
        segs.append(("gap", cur, end, None))

    cells, ticks, notes = [], [], []
    for kind, a, b, name in segs:
        w = (b - a) / total * 100
        if kind == "gap":
            mins = b - a
            cells.append(f'<td class="gap" style="width:{w:.3f}%" title="{a // 60:02d}:{a % 60:02d}'
                         f'–{b // 60:02d}:{b % 60:02d}">{"空档 " + str(mins) + "分" if w > 12 else ""}</td>')
            ticks.append(f'<td style="width:{w:.3f}%"></td>')  # 空档不标刻度, 避免文字挤压
            notes.append(f"{a // 60:02d}:{a % 60:02d}–{b // 60:02d}:{b % 60:02d}（{mins} 分钟）")
        else:
            bg, fg, bd, _ = PERIOD_STYLE.get(name or "", ("#f1f2f5", "#333", "#ddd", ""))
            cells.append(f'<td style="width:{w:.3f}%;background:{bg};color:{fg}'
                         f';border:1px solid {bd}">{escape(name or "")}</td>')
            ticks.append(f'<td style="width:{w:.3f}%">{a // 60:02d}:{a % 60:02d}</td>')
    # 末尾补上最后一个结束时刻, 与首刻度呼应
    if segs:
        ticks.append(f'<td style="width:0;text-align:right">{end // 60:02d}:{end % 60:02d}</td>')
        cells.append('<td style="width:0;padding:0;border:0"></td>')
    html = (f'<table class="tl"><tr>{"".join(cells)}</tr></table>'
            f'<table class="tl2"><tr>{"".join(ticks)}</tr></table>')
    return html, notes


def render_city(city: dict, idx: int) -> str:
    slots = city["slots"]
    basket = city["basket"]
    periods = city.get("periods") or []
    grid_all = city.get("grid") or {}
    store = city.get("store") or {}
    # 主渠道: 到店自提(普通人最常用的方式)
    pickup = None
    for ch in city.get("channels") or []:
        if ch["id"] == "pickup":
            pickup = ch
    grid = grid_all.get((pickup or {"id": "pickup"})["id"]) or {}

    biz_s = store.get("businessStart") or "00:00"
    biz_e = store.get("businessEnd") or "23:59"

    out: list[str] = []
    out.append(f'<section class="card" id="city{idx}">')
    out.append(f'<h2 style="margin-top:0">{escape(city["city"])} '
               f'<span style="font-weight:400;font-size:15px;color:#6b7280">'
               f'{escape(store.get("name", ""))}</span></h2>')
    out.append(f'<p class="sub">门店营业 {escape(fmt_span(biz_s, biz_e))} · '
               f'{escape(store.get("address") or "")} · '
               f'数据日期 {escape(str(SURFACE.get("targetDate", "")))}</p>')

    # ---- 四个时段卡片 ----
    out.append("<h3>一天分四段，各段最便宜的一口</h3>")
    out.append('<div class="periods">')
    for p in periods:
        bg, fg, bd, icon = PERIOD_STYLE.get(p["name"], ("#f1f2f5", "#333", "#ddd", "🍟"))
        best = best_in_period(grid, basket, slots, p, top=1)
        price_html = (f'<p class="pprice num">¥{best[0][1] / 100:.2f}</p>'
                      f'<p class="pbest">{escape(best[0][0])}</p>'
                      if best else '<p class="pprice" style="font-size:17px">—</p>'
                                   '<p class="pbest">该时段无在售商品</p>')
        out.append(
            f'<div class="pcard" style="background:{bg};color:{fg};border-color:{bd}">'
            f'<p class="pname">{icon} {escape(p["name"])}</p>'
            f'<p class="ptime num">{escape(fmt_span(p["start"], p["end"]))}</p>'
            f'<p class="plabel">这一档最便宜的一口</p>'
            f'{price_html}'
            f'<p class="phint">过了 {escape(p["end"])} 这一口就点不到了</p>'
            f"</div>")
    out.append("</div>")

    # ---- 时间轴 ----
    tl, gap_notes = render_timeline(periods, biz_s, biz_e)
    if tl:
        out.append("<h3>把一天摊平看</h3>")
        out.append(tl)
        if gap_notes:
            out.append('<p class="tlnote">灰色斜纹 = <b>空档</b>：上一档已经收、下一档还没开，'
                       "这段时间两种都点不到 —— " + "、".join(escape(x) for x in gap_notes) + "。</p>")
        else:
            out.append('<p class="tlnote">这一天各档之间紧挨着，没有空档。</p>')

    # ---- 给普通人的提醒 ----
    tips: list[str] = []
    if periods:
        first_open = periods[0]["start"]
        if biz_s and to_min(first_open) > to_min(biz_s):
            wait = to_min(first_open) - to_min(biz_s)
            tips.append(f"门店 {escape(biz_s)} 就开门了，但 <b>{escape(first_open)}</b> 才开早餐档 —— "
                        f"早到的这 {wait} 分钟，其实点不到东西。")
    if len(periods) >= 2:
        # 检查菜单是否整批切换: 早档商品在午档是否几乎全灭
        a, b = periods[0], periods[1]
        names_a = {n for n, _ in best_in_period(grid, basket, slots, a, top=99)}
        names_b = {n for n, _ in best_in_period(grid, basket, slots, b, top=99)}
        if names_a and names_b:
            overlap = len(names_a & names_b) / min(len(names_a), len(names_b))
            if overlap < 0.25:
                tips.append(f"<b>{escape(a['name'])}和{escape(b['name'])}卖的不是同一份菜单</b>："
                            f"{escape(a['name'])}在售的 {len(names_a)} 样里，只有 {len(names_a & names_b)} 样"
                            f"能撑到{escape(b['name'])}档 —— 是整批换掉，不是慢慢下架。")
    if gap_notes:
        tips.append("一天里有 <b>" + "、".join(escape(x.split("（")[0]) for x in gap_notes) +
                    "</b> 这样的空档，正好卡在两档中间。只是晚到十几分钟，可能两档都吃不上。")
    floors = []
    for p in periods:
        best = best_in_period(grid, basket, slots, p, top=1)
        if best:
            floors.append((p["name"], best[0][1]))
    if len(floors) >= 2:
        lo = min(floors, key=lambda x: x[1])
        hi = max(floors, key=lambda x: x[1])
        if hi[1] > lo[1]:
            tips.append(f"想省钱就挑时段：<b>{escape(lo[0])}档</b>最便宜的一口只要 "
                        f"¥{lo[1] / 100:.2f}，而<b>{escape(hi[0])}档</b>最便宜也要 "
                        f"¥{hi[1] / 100:.2f}，一顿差 ¥{(hi[1] - lo[1]) / 100:.2f}。")
    if tips:
        out.append("<h3>几个实在的提醒</h3><ul class=\"tips\">")
        out.extend(f"<li>{t}</li>" for t in tips)
        out.append("</ul>")

    # ---- 明细(折叠, 给想深挖的人) ----
    out.append("<details><summary>这一天的完整时刻表（每个时段能点什么、多少钱）</summary><div class=\"dbody\">")
    for p in periods:
        best = best_in_period(grid, basket, slots, p, top=5)
        if not best:
            continue
        rows = "".join(f'<tr><td>{escape(n)}</td><td class="p">¥{v / 100:.2f}</td></tr>'
                       for n, v in best)
        out.append(f'<h3 style="font-size:15px">{escape(p["name"])} '
                   f'{escape(fmt_span(p["start"], p["end"]))} · 最便宜的 5 样</h3>'
                   f'<div class="tw"><table class="d"><thead><tr><th>商品</th>'
                   f'<th style="width:110px">价格</th></tr></thead><tbody>{rows}</tbody></table></div>')
    out.append("</div></details>")
    out.append("</section>")
    return "".join(out)


def main() -> int:
    global SURFACE
    if not SURFACE_PATH.exists():
        print(f"未找到 {SURFACE_PATH}。先运行 survey.py(或 make_demo.py 生成演示数据)。")
        return 1
    SURFACE = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    is_demo = bool(SURFACE.get("isDemo"))
    badge = ('<span class="tag demo">示例价格 · 非真实数据</span>' if is_demo
             else '<span class="tag">✓ 真实价格 · 逐笔实测</span>')

    cities = SURFACE.get("cities") or []
    n_points = sum(len(v) for c in cities for g in (c.get("grid") or {}).values() for v in g.values())
    n_cities = len(cities)

    nav = "".join(f'<a href="#city{i}">{escape(c["city"])}</a>' for i, c in enumerate(cities))
    body = "".join(render_city(c, i) for i, c in enumerate(cities))

    gen = escape(str(SURFACE.get("generatedAt", datetime.now().isoformat(timespec="seconds"))))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>麦当劳几点最便宜 · 一天四档，各档最便宜的一口</title>
<style>{CSS}</style></head><body>
<div class="wrap">
<h1>麦当劳几点最便宜 {badge}</h1>
<p class="lead">麦当劳一天分成四段卖，每段的菜单不一样，最便宜的一口也不一样。
这一页把 {n_cities} 座城市各一家门店、全天 {n_points} 次逐笔问价的结果摊开给你看——
<b>几点能点什么、多少钱，一眼查得到。</b></p>
<div class="citynav">{nav}</div>
{body}
<details><summary>这些数字是怎么来的？</summary><div class="dbody">
<p>价格不是估的，也不是抄菜单牌的。程序按每半小时一个时刻，把当天从开门到打烊
逐格向麦当劳的订餐系统问价（相当于在 App 里选好商品、选好取餐时间后看到的实付金额），
问回来的数字原样记下，一共 {n_points} 笔。</p>
<p>整条链路是<b>只读</b>的：只问价，不下单、不领券、不碰任何支付环节。
所以页面上不会出现一张真实订单，也不会动你账号里的任何东西。</p>
<p>时段边界（早餐/午餐/下午茶/夜市各自的起止时刻）同样取自门店返回的排期，
不是我们自己划的。不同门店的营业时间不同，这一档的开档时刻也会差很多。</p>
<p class="sub">技术实现、接口调用链与复现方式见仓库 <code>MCP_INTEGRATION.md</code>。</p>
</div></details>
<footer>
生成时间 {gen} · 数据日期 {escape(str(SURFACE.get("targetDate", "")))} · 共 {n_points} 次问价<br>
本项目为 2026 麦当劳程序员创意开发大赛参赛作品，非麦当劳官方产品。价格随门店与日期变动，
下单前请以麦当劳 App 实际显示为准。
</footer>
</div></body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB, 完全自包含, 双击即开)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
