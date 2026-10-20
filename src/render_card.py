"""
render_card.py — 生成 README 首图用的卡片页 (dist/card.html), 再由浏览器截图成 images/heatmap.png

首图体现产品的「问答式」形态: 顶部的城市/时间选择条 + 一张答案卡 + 一天四档速览。
自包含(不 import render_report), 与 report.html 共用同一套浅色大众视觉。
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface.json"
OUT_PATH = ROOT / "dist" / "card.html"

PERIOD_STYLE = {
    "早餐":   ("#FFF2D9", "#8A5300", "#F0C987", "🌅"),
    "午餐":   ("#FFE6D6", "#A64400", "#F2B48A", "🍔"),
    "下午茶": ("#EFE6FF", "#5B3BA8", "#C9B6F5", "🍰"),
    "夜市":   ("#DDEAFF", "#1D4F91", "#A9C6F2", "🌙"),
}


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def fmt_span(a: str, b: str) -> str:
    def trim(x: str) -> str:
        return f"{int(x[:2])}:{x[3:]}" if x[:2].startswith("0") else x
    return f"{trim(a)}–{trim(b)}"


def cheapest(grid: dict, basket: list[dict], slots: list[str],
             lo: str, hi: str, top: int = 1) -> list[tuple[str, int]]:
    items: dict[str, int] = {}
    for t in slots:
        if not (to_min(lo) <= to_min(t) < to_min(hi)):
            continue
        row = grid.get(t) or {}
        for it in basket:
            cell = row.get(it["code"]) or {}
            if "price" in cell:
                prev = items.get(it["name"])
                if prev is None or cell["price"] < prev:
                    items[it["name"]] = cell["price"]
    return sorted(items.items(), key=lambda x: x[1])[:top]


def render_timeline(periods: list[dict], biz_start: str, biz_end: str) -> str:
    if not periods:
        return ""
    start = min(to_min(periods[0]["start"]), to_min(biz_start or "00:00"))
    end = max(to_min(periods[-1]["end"]), to_min(biz_end or "23:59"))
    total = max(end - start, 1)
    segs: list[tuple[str, int, int, str | None]] = []
    cur = start
    for p in periods:
        a, b = to_min(p["start"]), to_min(p["end"])
        if a > cur:
            segs.append(("gap", cur, a, None))
        segs.append(("p", a, b, p["name"]))
        cur = b
    if cur < end:
        segs.append(("gap", cur, end, None))
    cells, ticks = [], []
    for kind, a, b, name in segs:
        w = (b - a) / total * 100
        if kind == "gap":
            cells.append(f'<td class="gap" style="width:{w:.3f}%"></td>')
            ticks.append(f'<td style="width:{w:.3f}%"></td>')
        else:
            bg, fg, bd, _ = PERIOD_STYLE.get(name or "", ("#f1f2f5", "#333", "#ddd", ""))
            cells.append(f'<td style="width:{w:.3f}%;background:{bg};color:{fg};'
                         f'border:1px solid {bd}">{escape(name or "")}</td>')
            ticks.append(f'<td style="width:{w:.3f}%">{a // 60:02d}:{a % 60:02d}</td>')
    ticks.append(f'<td style="width:0;text-align:right">{end // 60:02d}:{end % 60:02d}</td>')
    cells.append('<td style="width:0;padding:0;border:0"></td>')
    return (f'<table class="tl"><tr>{"".join(cells)}</tr></table>'
            f'<table class="tl2"><tr>{"".join(ticks)}</tr></table>')


def main() -> int:
    if not SURFACE_PATH.exists():
        print(f"未找到 {SURFACE_PATH}。先运行 survey.py。")
        return 1
    surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    cities = surface.get("cities") or []
    if not cities:
        print("surface.json 里没有城市数据。")
        return 1
    city = cities[0]
    store = city.get("store") or {}
    periods = city.get("periods") or []
    slots = city["slots"]
    basket = city["basket"]
    grid = (city.get("grid") or {}).get("pickup") or {}
    n_points = sum(len(v) for c in cities for g in (c.get("grid") or {}).values() for v in g.values())
    is_demo = bool(surface.get("isDemo"))

    # 答案卡: 取午餐档作示范(信息量最饱满的时段)
    demo_p = next((p for p in periods if p["name"] == "午餐"), periods[min(1, len(periods) - 1)])
    demo_t = next((t for t in slots if to_min(demo_p["start"]) <= to_min(t) < to_min(demo_p["end"])),
                  slots[len(slots) // 2])
    demo_items = cheapest(grid, basket, [demo_t], demo_p["start"], demo_p["end"], top=4)
    best = demo_items[0] if demo_items else ("—", 0)

    cards = []
    for p in periods:
        bg, fg, bd, icon = PERIOD_STYLE.get(p["name"], ("#f1f2f5", "#333", "#ddd", "🍟"))
        b1 = cheapest(grid, basket, slots, p["start"], p["end"], top=1)
        price = f"¥{b1[0][1] / 100:.2f}" if b1 else "—"
        name = escape(b1[0][0]) if b1 else "无在售商品"
        on = " on" if p["name"] == demo_p["name"] else ""
        cards.append(
            f'<div class="pc{on}" style="background:{bg};color:{fg};border-color:{bd}">'
            f'<div class="pn">{icon} {escape(p["name"])}</div>'
            f'<div class="pt">{escape(fmt_span(p["start"], p["end"]))}</div>'
            f'<div class="pp">{price}</div>'
            f'<div class="pi">{name}</div></div>')

    tl = render_timeline(periods, store.get("businessStart") or "00:00",
                         store.get("businessEnd") or "23:59")
    badge = "示例价格" if is_demo else "✓ 真实价格 · 逐笔实测"
    others = "　".join(escape(c["city"]) for c in cities[1:4])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>card</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f6f7f9;display:flex;align-items:center;justify-content:center;
 min-height:100vh;font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
 word-break:break-word}}
.card{{width:1180px;background:#fff;border:1px solid #e3e6ec;border-radius:22px;
 padding:32px 40px 28px;box-shadow:0 10px 34px rgba(20,30,60,.07)}}
h1{{font-size:36px;margin:0 0 6px;letter-spacing:-.5px;color:#1f2329}}
.sub{{font-size:15.5px;color:#6b7280;margin:0 0 16px}}
.badge{{display:inline-block;background:#e6f4ea;color:#1a7f37;border:1px solid #b7e1c4;
 border-radius:20px;padding:2px 12px;font-size:13px;font-weight:700;vertical-align:middle}}
.badge.demo{{background:#fff4ce;color:#8a6100;border-color:#f0d999}}
.qbar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;background:#fafbfc;
 border:1px solid #eceef3;border-radius:12px;padding:12px 14px;margin:0 0 16px}}
.qlab{{font-size:13px;color:#6b7280;font-weight:700}}
.chip{{padding:6px 14px;border:1px solid #d7dbe3;border-radius:20px;background:#fff;
 font-size:14.5px;color:#1f2329}}
.chip.on{{background:#1D4F91;border-color:#1D4F91;color:#fff;font-weight:700}}
.sel{{padding:6px 12px;border:1px solid #d7dbe3;border-radius:10px;background:#fff;font-size:14.5px}}
.two{{display:flex;gap:16px;align-items:stretch}}
.answer{{flex:0 0 340px;background:#f6fff9;border:1px solid #b7e1c4;border-radius:16px;
 padding:16px 18px}}
.st{{font-size:14px;font-weight:700;color:#14622c;margin:0 0 10px}}
.big{{font-size:13.5px;color:#6b7280;margin:0}}
.ansprice{{font-size:42px;font-weight:800;letter-spacing:-1.5px;color:#14622c;margin:0;
 font-variant-numeric:tabular-nums;line-height:1.15}}
.ansname{{font-size:17px;font-weight:700;margin:0 0 10px}}
ul{{margin:0;padding:0;list-style:none;border-top:1px solid #d9efe1}}
li{{display:flex;justify-content:space-between;gap:10px;padding:7px 0;
 border-bottom:1px solid #d9efe1;font-size:14px}}
li span.p{{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}}
.right{{flex:1;min-width:0}}
.row{{display:flex;gap:12px;margin:0 0 10px}}
.pc{{flex:1;border:1px solid;border-radius:14px;padding:12px 14px}}
.pc.on{{box-shadow:0 0 0 3px rgba(29,79,145,.18)}}
.pn{{font-size:14px;font-weight:700}}
.pt{{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums;margin:1px 0 6px}}
.pp{{font-size:26px;font-weight:800;letter-spacing:-1px;font-variant-numeric:tabular-nums}}
.pi{{font-size:13px;font-weight:600}}
.tl{{width:100%;border-collapse:collapse;table-layout:fixed;margin:4px 0 2px}}
.tl td{{border:0;padding:0;height:28px;text-align:center;font-size:12.5px;font-weight:700;
 overflow:hidden;white-space:nowrap}}
.tl td.gap{{background:repeating-linear-gradient(45deg,#f0f1f4,#f0f1f4 5px,#e2e4ea 5px,#e2e4ea 10px)}}
.tl2{{width:100%;border-collapse:collapse;table-layout:fixed}}
.tl2 td{{border:0;padding:0;font-size:11px;color:#6b7280;white-space:nowrap;overflow:hidden}}
.foot{{display:flex;justify-content:space-between;align-items:baseline;margin-top:10px;gap:16px}}
.note{{font-size:12.5px;color:#6b7280;margin:0}}
.src{{font-size:12px;color:#9aa1ad;margin:0;white-space:nowrap}}
</style></head><body>
<div class="card">
  <h1>麦当劳几点最便宜 <span class="badge{' demo' if is_demo else ''}">{badge}</span></h1>
  <p class="sub">选城市和几点去，只告诉你那一刻能点什么、最便宜的一口多少钱 ——
  {len(cities)} 座城市 · 全天 {n_points} 次逐笔问价</p>

  <div class="qbar">
    <span class="qlab">你在哪个城市</span>
    <span class="chip on">{escape(city["city"])}</span>
    <span class="chip">{others}</span>
    <span class="qlab">几点去</span>
    <span class="sel">{escape(demo_t)}</span>
  </div>

  <div class="two">
    <div class="answer">
      <p class="st">{escape(demo_p["name"])}档 {escape(demo_p["start"])}–{escape(demo_p["end"])}</p>
      <p class="big">这一刻最便宜的一口</p>
      <p class="ansprice">¥{best[1] / 100:.2f}</p>
      <p class="ansname">{escape(best[0])}</p>
      <ul>{"".join(f'<li><span>{escape(n)}</span><span class="p">¥{p / 100:.2f}</span></li>' for n, p in demo_items)}</ul>
    </div>
    <div class="right">
      <div class="row">{''.join(cards)}</div>
      {tl}
      <p class="note">灰色斜纹 = 空档：上一档已收、下一档未开，两种都点不到。</p>
    </div>
  </div>

  <div class="foot">
    <p class="note">示例门店：{escape(city["city"])} · {escape(store.get("name", ""))}</p>
    <p class="src">价格逐笔取自麦当劳订餐系统实时问价 · 只读采集 · 非官方产品</p>
  </div>
</div>
</body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} (截图: --window-size=1280,760)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
