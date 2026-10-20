"""
render_card.py — 生成 README 首图用的卡片页 (dist/card.html), 再由浏览器截图成 images/heatmap.png

与 report.html 同一套「大众版」视觉: 浅色底、大字号、说人话。
首图只放一座代表城市(默认第一个), 聚焦: 四个时段卡片 + 一天时间轴。

截图方法见 README(Chrome/Edge headless 均可)。
"""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_report import PERIOD_STYLE, best_in_period, fmt_span, render_timeline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface.json"
OUT_PATH = ROOT / "dist" / "card.html"


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
    periods = city.get("periods") or []
    grid = (city.get("grid") or {}).get("pickup") or {}
    slots = city["slots"]
    basket = city["basket"]
    store = city.get("store") or {}
    n_points = sum(len(v) for c in cities for g in (c.get("grid") or {}).values() for v in g.values())
    is_demo = bool(surface.get("isDemo"))

    cards = []
    for p in periods:
        bg, fg, bd, icon = PERIOD_STYLE.get(p["name"], ("#f1f2f5", "#333", "#ddd", "🍟"))
        best = best_in_period(grid, basket, slots, p, top=1)
        price = f"¥{best[0][1] / 100:.2f}" if best else "—"
        name = escape(best[0][0]) if best else "无在售商品"
        cards.append(
            f'<div class="pc" style="background:{bg};color:{fg};border-color:{bd}">'
            f'<div class="pn">{icon} {escape(p["name"])}</div>'
            f'<div class="pt">{escape(fmt_span(p["start"], p["end"]))}</div>'
            f'<div class="pp">{price}</div>'
            f'<div class="pi">{name}</div>'
            f"</div>")

    tl, gap_notes = render_timeline(periods, store.get("businessStart") or "00:00",
                                    store.get("businessEnd") or "23:59")
    badge = "示例价格" if is_demo else "✓ 真实价格 · 逐笔实测"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>card</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f6f7f9;display:flex;align-items:center;justify-content:center;
 min-height:100vh;font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif}}
.card{{width:1180px;background:#fff;border:1px solid #e3e6ec;border-radius:22px;
 padding:34px 40px 30px;box-shadow:0 10px 34px rgba(20,30,60,.07)}}
h1{{font-size:38px;margin:0 0 6px;letter-spacing:-.5px;color:#1f2329}}
.sub{{font-size:16px;color:#6b7280;margin:0 0 4px}}
.badge{{display:inline-block;background:#e6f4ea;color:#1a7f37;border:1px solid #b7e1c4;
 border-radius:20px;padding:2px 12px;font-size:13px;font-weight:700;vertical-align:middle}}
.badge.demo{{background:#fff4ce;color:#8a6100;border-color:#f0d999}}
.row{{display:flex;gap:14px;margin:22px 0 8px}}
.pc{{flex:1;border:1px solid;border-radius:16px;padding:16px 18px 14px}}
.pn{{font-size:15px;font-weight:700}}
.pt{{font-size:22px;font-weight:800;letter-spacing:-.5px;margin:2px 0 8px;
 font-variant-numeric:tabular-nums}}
.pp{{font-size:34px;font-weight:800;letter-spacing:-1px;font-variant-numeric:tabular-nums}}
.pi{{font-size:14.5px;font-weight:600;margin-top:2px}}
.tl{{width:100%;border-collapse:collapse;table-layout:fixed;margin:14px 0 2px}}
.tl td{{border:0;padding:0;height:32px;text-align:center;font-size:13.5px;font-weight:700;
 overflow:hidden;white-space:nowrap}}
.tl td.gap{{background:repeating-linear-gradient(45deg,#f0f1f4,#f0f1f4 5px,#e2e4ea 5px,#e2e4ea 10px);
 color:#8b93a3;font-weight:600;font-size:11px}}
.tl2{{width:100%;border-collapse:collapse;table-layout:fixed}}
.tl2 td{{border:0;padding:0;font-size:11.5px;color:#6b7280;white-space:nowrap;overflow:hidden}}
.foot{{display:flex;justify-content:space-between;align-items:baseline;margin-top:12px}}
.note{{font-size:13px;color:#6b7280;margin:0}}
.src{{font-size:12px;color:#9aa1ad;margin:0}}
</style></head><body>
<div class="card">
  <h1>麦当劳几点最便宜 <span class="badge{' demo' if is_demo else ''}">{badge}</span></h1>
  <p class="sub">一天分四段卖，每段菜单不一样、最便宜的一口也不一样 ——
  {len(cities)} 座城市 · 全天 {n_points} 次逐笔问价</p>
  <div class="row">{''.join(cards)}</div>
  {tl}
  <div class="foot">
    <p class="note">灰色斜纹 = 空档：上一档已收、下一档未开，两种都点不到。
    示例门店：{escape(city["city"])} · {escape(store.get("name", ""))}</p>
    <p class="src">价格逐笔取自麦当劳订餐系统实时问价 · 只读采集 · 非官方产品</p>
  </div>
</div>
</body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} (用 Chrome headless 截图: --window-size=1280,720)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
