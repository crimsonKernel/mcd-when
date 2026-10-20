"""
render_report.py — 把 data/surface.json 渲染为「一问一答」的离线页面

设计原则(2026-10-20 问答式重构):
  * 不给用户看全貌, 只给「他那一刻的答案」 —— 先问城市 + 几点去, 再输出结果
  * 默认打开即出答案(按浏览器本地时间定位), 不要求任何操作
  * 想看全貌的人自己展开底部的完整时刻表, 不主动塞给他
  * 浅色底 + 大字号 + 单栏 820px, 手机可读可打印
  * 排版防错乱: 全局 box-sizing; 卡片 grid auto-fit; 表格 table-layout:fixed;
    折叠 details 内容 display:none(根治窄屏溢出); 数字 tabular-nums; JS 不参与布局

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
TOP_PER_SLOT = 6      # 某一时刻展示的"能点什么"条数
TOP_PER_PERIOD = 8    # 完整时刻表里每档展示条数

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
.wrap{max-width:820px;margin:0 auto}
h1{font-size:28px;line-height:1.35;margin:0 0 8px;letter-spacing:-.2px}
p{margin:0 0 12px}
a{color:#1D4F91}
.lead{font-size:16px;color:#3d4450;margin:0 0 16px}
.num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
.sub{color:#6b7280;font-size:14px;margin:0}
.card{background:#fff;border:1px solid #e3e6ec;border-radius:14px;padding:18px;margin:0 0 14px}

/* —— 提问区 —— */
.q{background:#fff;border:1px solid #e3e6ec;border-radius:14px;padding:16px 18px;margin:0 0 14px}
.qrow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 12px}
.qrow:last-child{margin-bottom:0}
.qlab{font-size:14px;color:#6b7280;flex:0 0 100%;font-weight:700}
.chip{display:inline-block;padding:7px 15px;border:1px solid #d7dbe3;border-radius:20px;
 background:#fff;color:#1f2329;font-size:15px;cursor:pointer;line-height:1.4}
.chip:hover{border-color:#1D4F91;color:#1D4F91}
.chip.on{background:#1D4F91;border-color:#1D4F91;color:#fff;font-weight:700}
select{font:inherit;font-size:16px;padding:8px 12px;border:1px solid #d7dbe3;border-radius:10px;
 background:#fff;color:#1f2329;max-width:100%}
button.now{font:inherit;font-size:15px;padding:8px 16px;border:1px solid #d7dbe3;
 border-radius:10px;background:#f0f2f5;color:#1f2329;cursor:pointer}
button.now:hover{border-color:#1D4F91;color:#1D4F91}

/* —— 答案区 —— */
.state{font-size:15px;font-weight:700;padding:10px 14px;border-radius:10px;margin:0 0 14px}
.state.ok{background:#e6f4ea;color:#14622c;border:1px solid #b7e1c4}
.state.gap{background:#fff4ce;color:#8a6100;border:1px solid #f0d999}
.state.closed{background:#f1f2f5;color:#5b6472;border:1px solid #dfe2e8}
.big{font-size:14.5px;color:#6b7280;margin:0 0 2px}
.ansprice{font-size:44px;font-weight:800;letter-spacing:-1.5px;line-height:1.15;margin:0;
 color:#14622c;font-variant-numeric:tabular-nums}
.ansname{font-size:19px;font-weight:700;margin:0 0 4px}
.anshint{font-size:13.5px;color:#6b7280;margin:6px 0 0}
ul.can{margin:14px 0 0;padding:0;list-style:none;border-top:1px solid #eef0f4}
ul.can li{display:flex;justify-content:space-between;gap:12px;padding:9px 2px;
 border-bottom:1px solid #eef0f4;font-size:15px}
ul.can li span.n{flex:1;min-width:0}
ul.can li span.p{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.more{font-size:13px;color:#6b7280;margin:10px 0 0}

/* —— 表格(明细) —— */
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:10px 0 0;max-width:100%}
table.d{border-collapse:collapse;width:100%;table-layout:fixed;font-size:14px}
table.d th,table.d td{border:1px solid #e3e6ec;padding:8px 10px;text-align:left;vertical-align:top}
table.d thead th{background:#f0f2f5;font-weight:700;white-space:nowrap}
table.d td.p{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap}

/* —— 折叠区 —— */
details{margin:12px 0 0;border:1px solid #e3e6ec;border-radius:12px;background:#fff;overflow:hidden}
details:not([open]) .dbody{display:none}
details summary{cursor:pointer;padding:13px 16px;font-weight:700;font-size:15px;
 background:#fafbfc;list-style:none}
details summary::-webkit-details-marker{display:none}
details summary::before{content:"▸ ";color:#6b7280}
details[open] summary::before{content:"▾ "}
details .dbody{padding:4px 16px 16px}
details h3{font-size:15px;margin:16px 0 6px}
code{background:#f0f2f5;border-radius:4px;padding:1px 5px;font-size:13px}
footer{max-width:820px;margin:24px auto 0;color:#8b93a3;font-size:12.5px;
 border-top:1px solid #e3e6ec;padding-top:12px;line-height:1.6}
@media print{
  body{background:#fff;padding:0;font-size:12pt}
  .q{display:none}
  details{break-inside:avoid}
}
@media (max-width:520px){
  h1{font-size:23px}
  .ansprice{font-size:36px}
}
"""

JS = """
(function () {
  var DATA = window.__MCD_DATA__;
  var ci = 0, curTime = null;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function yuan(f) { return "¥" + (f / 100).toFixed(2); }
  function toMin(t) { var a = t.split(":"); return (+a[0]) * 60 + (+a[1]); }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  function nearestSlot(city, t) {
    var best = null;
    for (var i = 0; i < city.slots.length; i++) {
      if (toMin(city.slots[i].t) <= toMin(t)) best = city.slots[i];
    }
    return best || city.slots[0];
  }

  function periodOf(city, t) {
    var m = toMin(t);
    for (var i = 0; i < city.periods.length; i++) {
      var p = city.periods[i];
      if (toMin(p.start) <= m && m < toMin(p.end)) return p;
    }
    return null;
  }

  function renderCities() {
    var box = document.getElementById("cities");
    box.innerHTML = "";
    DATA.cities.forEach(function (c, i) {
      var b = document.createElement("span");
      b.className = "chip" + (i === ci ? " on" : "");
      b.textContent = c.city;
      b.onclick = function () { ci = i; renderCities(); fillTimes(); render(); };
      box.appendChild(b);
    });
  }

  function fillTimes() {
    var sel = document.getElementById("times");
    var city = DATA.cities[ci];
    sel.innerHTML = "";
    city.slots.forEach(function (s) {
      var o = document.createElement("option");
      o.value = s.t;
      o.textContent = s.t + (s.n === 0 ? "（点不到）" : "");
      sel.appendChild(o);
    });
    var idx = 0;
    for (var i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === curTime) { idx = i; break; }
    }
    sel.selectedIndex = idx;
    curTime = sel.value;
  }

  function render() {
    var city = DATA.cities[ci];
    var slot = nearestSlot(city, curTime);
    var per = periodOf(city, curTime);
    var out = [];

    out.push('<div class="card">');
    out.push('<p class="sub" style="margin-bottom:10px">' + esc(city.city) +
             " · " + esc(city.store.name) + "</p>");

    if (slot.n === 0) {
      var later = null;
      for (var i = 0; i < city.slots.length; i++) {
        if (city.slots[i].n > 0 && toMin(city.slots[i].t) > toMin(slot.t)) {
          later = city.slots[i]; break;
        }
      }
      var msg = "这个时刻点不到东西";
      if (later) {
        var wait = toMin(later.t) - toMin(curTime);
        msg += (wait > 0 ? " —— 再等 <b>" + wait + " 分钟</b>，到 " + later.t + " 才有得点。"
                         : " —— 到 " + later.t + " 才有得点。");
      } else {
        msg += "（已过当天最后的供餐时刻）。";
      }
      out.push('<p class="state closed">' + msg + "</p>");
      if (city.periods.length) {
        out.push('<p class="big">这家的供餐时段是</p>');
        city.periods.forEach(function (p) {
          out.push('<p class="ansname" style="font-size:16px">' + esc(p.name) + " " +
                   p.start + "–" + p.end + "，最便宜一口 " + yuan(p.floorPrice) + "</p>");
        });
      }
      out.push("</div>");
      document.getElementById("ans").innerHTML = out.join("");
      return;
    }

    if (per) {
      out.push('<p class="state ok">现在属于 <b>' + esc(per.name) + "档</b>（" +
               per.start + "–" + per.end + "），这一刻能点 " + slot.n + " 样。</p>");
    } else {
      var nxt = null;
      for (var j = 0; j < city.periods.length; j++) {
        if (toMin(city.periods[j].start) > toMin(curTime)) { nxt = city.periods[j]; break; }
      }
      out.push('<p class="state gap">这个时刻卡在两档中间的<b>空档</b>里' +
               (nxt ? " —— 下一档 <b>" + esc(nxt.name) + "</b> " + nxt.start +
                      " 开始，还有 <b>" + (toMin(nxt.start) - toMin(curTime)) + " 分钟</b>。" : "。") +
               "此刻能点的按下档开始前的菜单算。</p>");
    }

    var b = slot.top[0];
    out.push('<p class="big">这一刻最便宜的一口</p>');
    out.push('<p class="ansprice">' + yuan(b.p) + "</p>");
    out.push('<p class="ansname">' + esc(b.n) + "</p>");

    var most = slot.top[slot.top.length - 1];
    if (most && most.p > b.p) {
      out.push('<p class="anshint">同一时刻最贵的一口是 ' + esc(most.n) + " " + yuan(most.p) +
               "，差 " + yuan(most.p - b.p) + "。</p>");
    }

    if (slot.top.length > 1) {
      out.push('<p class="big" style="margin-top:16px">这一刻还能点的（从便宜到贵）</p>');
      out.push('<ul class="can">');
      slot.top.forEach(function (x) {
        out.push('<li><span class="n">' + esc(x.n) + '</span><span class="p">' +
                 yuan(x.p) + "</span></li>");
      });
      out.push("</ul>");
      out.push('<p class="more">只列这一刻在售的 ' + slot.n + " 样里最便宜的 " +
               slot.top.length + " 样。</p>");
    }
    out.push("</div>");
    document.getElementById("ans").innerHTML = out.join("");
  }

  function nowSlot() {
    var n = new Date();
    var s = pad(n.getHours()) + ":" + pad(n.getMinutes());
    var slots = DATA.cities[ci].slots;
    var t = slots[0].t;
    for (var i = 0; i < slots.length; i++) {
      if (toMin(slots[i].t) <= toMin(s)) t = slots[i].t;
    }
    return t;
  }

  function init() {
    curTime = nowSlot();
    renderCities();
    fillTimes();
    document.getElementById("times").onchange = function (e) {
      curTime = e.target.value; render();
    };
    document.getElementById("nowbtn").onclick = function () {
      curTime = nowSlot(); fillTimes(); render();
    };
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
"""


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def cheapest_map(grid: dict, basket: list[dict], slots: list[str],
                 lo: str, hi: str) -> dict[str, int]:
    """在 [lo, hi) 时刻范围内, 每个商品取最低价。"""
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
    return items


def build_city_data(city: dict) -> dict:
    """把一城的原始网格压成问答所需的精简结构。"""
    slots = city["slots"]
    basket = city["basket"]
    periods = city.get("periods") or []
    grid = (city.get("grid") or {}).get("pickup") or {}
    store = city.get("store") or {}

    slot_out = []
    for t in slots:
        row = grid.get(t) or {}
        items: dict[str, int] = {}
        for it in basket:
            cell = row.get(it["code"]) or {}
            if "price" in cell:
                prev = items.get(it["name"])
                if prev is None or cell["price"] < prev:
                    items[it["name"]] = cell["price"]
        top = sorted(items.items(), key=lambda x: x[1])[:TOP_PER_SLOT]
        slot_out.append({"t": t, "n": len(items),
                         "top": [{"n": n, "p": p} for n, p in top]})

    period_out = []
    for p in periods:
        tops = sorted(cheapest_map(grid, basket, slots, p["start"], p["end"]).items(),
                      key=lambda x: x[1])[:TOP_PER_PERIOD]
        period_out.append({
            "name": p["name"], "start": p["start"], "end": p["end"],
            "floorName": tops[0][0] if tops else "",
            "floorPrice": tops[0][1] if tops else 0,
            "top": [{"n": n, "p": v} for n, v in tops],
        })

    return {
        "city": city["city"],
        "store": {"name": store.get("name", ""), "address": store.get("address", "")},
        "bizStart": store.get("businessStart") or "",
        "bizEnd": store.get("businessEnd") or "",
        "periods": period_out,
        "slots": slot_out,
    }


def render_full_table(city_raw: dict) -> str:
    """底部给想深挖的人: 各档能点什么(静态渲染, JS 失效也可读)。"""
    periods = city_raw.get("periods") or []
    grid = (city_raw.get("grid") or {}).get("pickup") or {}
    out = []
    for p in periods:
        tops = sorted(cheapest_map(grid, city_raw["basket"], city_raw["slots"],
                                   p["start"], p["end"]).items(),
                      key=lambda x: x[1])[:TOP_PER_PERIOD]
        if not tops:
            continue
        rows = "".join(f'<tr><td>{escape(n)}</td><td class="p">¥{v / 100:.2f}</td></tr>'
                       for n, v in tops)
        out.append(f'<h3>{escape(p["name"])} {escape(p["start"])}–{escape(p["end"])}</h3>'
                   f'<div class="tw"><table class="d"><thead><tr><th>商品</th>'
                   f'<th style="width:110px">价格</th></tr></thead><tbody>{rows}</tbody></table></div>')
    return "".join(out)


def main() -> int:
    global SURFACE
    if not SURFACE_PATH.exists():
        print(f"未找到 {SURFACE_PATH}。先运行 survey.py(或 make_demo.py 生成演示数据)。")
        return 1
    SURFACE = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    cities_raw = SURFACE.get("cities") or []
    if not cities_raw:
        print("surface.json 里没有城市数据。")
        return 1
    is_demo = bool(SURFACE.get("isDemo"))
    n_points = sum(len(v) for c in cities_raw for g in (c.get("grid") or {}).values() for v in g.values())
    n_cities = len(cities_raw)

    data = [build_city_data(c) for c in cities_raw]
    payload = json.dumps({"cities": data}, ensure_ascii=False, separators=(",", ":"))

    full = "".join(
        f'<details><summary>{escape(c["city"])} · '
        f'{escape((c.get("store") or {}).get("name", ""))} —— 完整时刻表</summary>'
        f'<div class="dbody">{render_full_table(c)}</div></details>'
        for c in cities_raw)

    gen = escape(str(SURFACE.get("generatedAt", datetime.now().isoformat(timespec="seconds"))))
    target = escape(str(SURFACE.get("targetDate", "")))
    badge = ('<span style="font-size:13px;font-weight:700;color:#8a6100">示例价格</span>' if is_demo
             else '<span style="font-size:13px;font-weight:700;color:#1a7f37">✓ 真实价格 · 逐笔实测</span>')

    # JS 失效时的静态兜底答案: 第一个城市的午餐档(JS 正常时会被替换)
    fb_city = cities_raw[0]
    fb_periods = fb_city.get("periods") or []
    fb_p = next((p for p in fb_periods if p["name"] == "午餐"),
                fb_periods[min(1, len(fb_periods) - 1)] if fb_periods else None)
    fb_grid = (fb_city.get("grid") or {}).get("pickup") or {}
    fallback_ans = ""
    if fb_p:
        tops = sorted(cheapest_map(fb_grid, fb_city["basket"], fb_city["slots"],
                                   fb_p["start"], fb_p["end"]).items(),
                      key=lambda x: x[1])[:6]
        rows = "".join(f'<li><span class="n">{escape(n)}</span>'
                       f'<span class="p">¥{v / 100:.2f}</span></li>' for n, v in tops)
        fallback_ans = (
            f'<div class="card"><p class="sub" style="margin-bottom:10px">'
            f'{escape(fb_city["city"])} · {escape((fb_city.get("store") or {}).get("name", ""))}</p>'
            f'<p class="state ok">{escape(fb_p["name"])}档（{escape(fb_p["start"])}–{escape(fb_p["end"])}）</p>'
            f'<p class="big">这一档最便宜的一口</p>'
            f'<p class="ansprice">¥{tops[0][1] / 100:.2f}</p>'
            f'<p class="ansname">{escape(tops[0][0])}</p>'
            f'<ul class="can">{rows}</ul>'
            f'<p class="more">想查别的城市或时刻？这个页面需要浏览器开启 JavaScript；'
            f'否则请直接展开下面的完整时刻表。</p></div>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>麦当劳几点最便宜 · 选城市和时刻，直接给你答案</title>
<style>{CSS}</style></head><body>
<div class="wrap">
<h1>麦当劳几点最便宜 {badge}</h1>
<p class="lead">选好 <b>城市</b> 和 <b>几点去</b>，只告诉你那一刻能点什么、最便宜的一口多少钱。
不用注册，不用装东西。</p>

<div class="q">
  <div class="qrow"><span class="qlab">1 · 你在哪个城市</span><span id="cities"></span></div>
  <div class="qrow"><span class="qlab">2 · 你几点去</span>
    <select id="times"></select>
    <button class="now" id="nowbtn" type="button">用现在这个时间</button>
  </div>
</div>

<div id="ans">{fallback_ans}</div>

<details><summary>想看全天的？展开完整时刻表（{n_cities} 座城市）</summary>
<div class="dbody">{full}</div></details>

<details><summary>这些数字是怎么来的？</summary><div class="dbody">
<p>价格不是估的。程序按每半小时一个时刻，把当天从开门到打烊逐格向麦当劳的订餐系统问价
（相当于在 App 里选好商品、选好取餐时间后看到的实付金额），问回来的数字原样记下，
一共 {n_points} 笔。</p>
<p>整条链路是<b>只读</b>的：只问价，不下单、不领券、不碰支付环节。</p>
<p>时段边界（早餐/午餐/下午茶/夜市各自的起止时刻）取自门店返回的排期，不是我们自己划的。
不同门店营业时间不同，这一档的开档时刻也会差很多。</p>
<p class="sub">技术实现与复现方式见仓库 <code>MCP_INTEGRATION.md</code>。</p>
</div></details>

<footer>
生成时间 {gen} · 数据日期 {target} · 共 {n_points} 次问价 · 取餐方式：到店自提<br>
本项目为 2026 麦当劳程序员创意开发大赛参赛作品，非麦当劳官方产品。价格随门店与日期变动，
下单前请以麦当劳 App 实际显示为准。
</footer>
</div>
<script>window.__MCD_DATA__ = {payload};</script>
<script>{JS}</script>
</body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB, 问答式, 双击即开)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
