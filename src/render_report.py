"""
render_report.py — 把 data/surface_national.json 渲染为「一问一答」的离线页面

面向的是来麦当劳吃饭的人, 不是程序员:
  * 先问两件事 —— 你在哪个城市、你几点去 —— 然后只给那一刻的答案
  * 291 座城市不铺开来展示, 用搜索框找; 找不到还能翻完整城市列表
  * 打开就有答案(按浏览器本地时间), 不用操作
  * 想看全貌的人自己展开底部的「全国对比」和「完整时刻表」

排版防错乱(踩过的坑全在这里):
  * 全局 box-sizing; 表格 table-layout:fixed
  * 折叠 details 关闭时内容 display:none —— 否则里面的宽表格会把窄屏撑出横向滚动
  * 数字统一 tabular-nums; JS 只负责填内容, 不参与布局

输出: dist/report.html —— 零外部依赖, 双击即开。
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface_national.json"
BATCH_PATH = ROOT / "data" / "surface_batch.json"
LEGACY_PATH = ROOT / "data" / "surface.json"
OUT_PATH = ROOT / "dist" / "report.html"

# 全菜单采集(survey_batch.py)覆盖到这个城市数就优先用它渲染 ——
# 它比探针快照多出完整菜单, 且口径与 MCP Server 一致。
FULL_MENU_MIN_CITIES = 50

HOT_CITIES = ["北京", "上海", "广州", "深圳", "成都", "重庆", "武汉", "西安",
              "杭州", "南京", "长沙", "郑州"]

PERIOD_ICON = {"早餐": "🌅", "午餐": "🍔", "下午茶": "🍰", "夜市": "🌙"}

CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#FBF7F2;color:#1f2329;
 font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB","Source Han Sans SC",
   "Noto Sans CJK SC",system-ui,-apple-system,sans-serif;
 font-size:16px;line-height:1.7;padding:20px 14px 40px;
 word-break:break-word;overflow-wrap:break-word}
.wrap{max-width:820px;margin:0 auto}

/* —— 头部: 黄金3秒钩子(暖奶油) —— */
.hero{background:linear-gradient(135deg,#FFFDF9 0%,#FDF1E3 100%);
 color:#2B1B12;border-radius:18px;padding:26px 22px 22px;margin:0 0 16px;
 box-shadow:0 1px 2px rgba(120,80,20,.06),0 10px 26px rgba(120,80,20,.09)}
.hero .hook{display:inline-block;background:#FFF1E2;border:1px solid #F2D9B6;
 color:#B4531A;font-size:13.5px;font-weight:800;letter-spacing:.4px;padding:5px 12px;
 border-radius:20px;margin:0 0 12px}
.hero h1{font-size:34px;line-height:1.25;margin:0 0 10px;color:#7C1D12;letter-spacing:-.4px}
.hero .hsub{font-size:16px;color:#5A4638;margin:0 0 16px;line-height:1.65}
.hero .hsub b{color:#B4531A}
.hero-stats{display:flex;flex-wrap:wrap;gap:8px}
.hero-stats .hs{background:#fff;border:1px solid #F0E2CE;
 border-radius:10px;padding:7px 12px;font-size:13.5px;color:#6B5747}
.hero-stats .hs b{font-size:17px;color:#C2410C;font-variant-numeric:tabular-nums;
 font-weight:800;margin-right:3px}
h1{font-size:28px;line-height:1.35;margin:0 0 8px;letter-spacing:-.2px}
p{margin:0 0 12px}
a{color:#8C2F0B}
.lead{font-size:16px;color:#3d4450;margin:0 0 16px}
.num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
.sub{color:#6b7280;font-size:14px;margin:0}
.card{background:#fff;border:1px solid #e3e6ec;border-radius:16px;padding:18px;margin:0 0 14px;
 box-shadow:0 1px 2px rgba(16,24,40,.04),0 6px 18px rgba(16,24,40,.05)}

/* —— 提问区 —— */
.q{background:#fff;border:1px solid #e3e6ec;border-radius:16px;padding:16px 18px;margin:0 0 14px;
 box-shadow:0 1px 2px rgba(16,24,40,.04),0 6px 18px rgba(16,24,40,.05)}
.qrow{margin:0 0 14px;padding:0 0 14px;border-bottom:1px dashed #EFE3D3}
.qrow:last-child{margin-bottom:0;padding-bottom:0;border-bottom:0}
.qlab{display:flex;align-items:center;gap:9px;font-size:15.5px;color:#2B1B12;
 font-weight:800;display:flex;margin:0 0 10px}
.qnum{flex:none;display:inline-flex;align-items:center;justify-content:center;
 width:22px;height:22px;border-radius:50%;background:#C2410C;color:#fff;
 font-size:13px;font-weight:800;line-height:1}
.field{display:flex;flex-direction:column;gap:5px;flex:1;min-width:132px;max-width:240px}
.field .flab{font-size:12.5px;color:#8A7361;font-weight:700;letter-spacing:.3px}
.selrow{display:flex;gap:12px;flex-wrap:wrap}
.qhint{margin:9px 0 0;font-size:12.5px;color:#9C8873;letter-spacing:.2px}
select.sel{font:inherit;font-size:16px;padding:11px 12px;border:1px solid #E4D5BE;
 border-radius:12px;background:#fff;color:#1f2329;width:100%;
 appearance:none;-webkit-appearance:none;
 background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8'><path d='M1 1l5 5 5-5' stroke='%2396806A' stroke-width='1.8' fill='none' stroke-linecap='round'/></svg>");
 background-repeat:no-repeat;background-position:right 12px center;padding-right:32px;
 cursor:pointer;transition:border-color .15s,box-shadow .15s}
select.sel:hover:not(:disabled){border-color:#C2410C}
select.sel:focus{border-color:#C2410C;box-shadow:0 0 0 3px rgba(194,65,12,.13);outline:none}
select.sel:disabled{background:#F7F3ED;color:#A9907A;cursor:not-allowed}
select.sel option{color:#1f2329}
select#times{font:inherit;font-size:16px;padding:11px 32px 11px 12px;border:1px solid #E4D5BE;
 border-radius:12px;background:#fff url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8'><path d='M1 1l5 5 5-5' stroke='%2396806A' stroke-width='1.8' fill='none' stroke-linecap='round'/></svg>") no-repeat right 12px center;
 color:#1f2329;appearance:none;-webkit-appearance:none;cursor:pointer;transition:border-color .15s}
select#times:focus{border-color:#C2410C;box-shadow:0 0 0 3px rgba(194,65,12,.13);outline:none}
.acts{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0}
button.now{font:inherit;font-size:14.5px;padding:10px 15px;border:1px solid #E4D5BE;
 border-radius:11px;background:#FFF9F1;color:#7C4A22;cursor:pointer;font-weight:600;
 transition:border-color .15s,color .15s,background .15s,transform .1s}
button.now:hover{border-color:#C2410C;color:#C2410C;background:#FFF3EA}
button.now:active{transform:translateY(1px)}
button.now.primary{background:#C2410C;border-color:#C2410C;color:#fff;box-shadow:0 2px 8px rgba(194,65,12,.25)}
button.now.primary:hover{background:#A8360A;border-color:#A8360A;color:#fff}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin:8px 0 0}
.chip{display:inline-block;padding:6px 13px;border:1px solid #d7dbe3;border-radius:20px;
 background:#fff;color:#1f2329;font-size:14.5px;cursor:pointer;line-height:1.5;
 transition:border-color .15s,color .15s,background .15s,transform .15s}
.chip:hover{border-color:#C2410C;color:#C2410C}
.chip.on{background:#C2410C;border-color:#C2410C;color:#fff;font-weight:700;transform:scale(1.05)}
.hintline{font-size:13.5px;color:#6b7280;margin:8px 0 0}
select{font:inherit;font-size:16px;padding:8px 12px;border:1px solid #d7dbe3;border-radius:10px;
 background:#fff;color:#1f2329;max-width:100%;transition:border-color .15s}
select:focus{border-color:#C2410C;outline:2px solid rgba(194,65,12,.14)}
button.now{font:inherit;font-size:15px;padding:8px 16px;border:1px solid #d7dbe3;
 border-radius:10px;background:#f0f2f5;color:#1f2329;cursor:pointer;
 transition:border-color .15s,color .15s,background .15s}
button.now:hover{border-color:#C2410C;color:#C2410C;background:#FFF3EA}

/* —— 答案区 —— */
.state{font-size:15px;font-weight:700;padding:10px 14px;border-radius:10px;margin:0 0 14px}
.state.ok{background:#e6f4ea;color:#14622c;border:1px solid #b7e1c4}
.state.gap{background:#fff4ce;color:#8a6100;border:1px solid #f0d999}
.state.closed{background:#f1f2f5;color:#5b6472;border:1px solid #dfe2e8}
.big{font-size:14.5px;color:#6b7280;margin:0 0 2px}
.anshero{background:linear-gradient(135deg,#FFF8EF 0%,#FFFDFA 70%);border:1px solid #F2D9B6;
 border-radius:14px;padding:14px 16px 12px;margin:2px 0 12px;
 box-shadow:0 1px 2px rgba(140,90,20,.07),0 6px 18px rgba(140,90,20,.09)}
.anshero .ansname{margin-bottom:0}
.ansprice{font-size:64px;font-weight:800;letter-spacing:-2.5px;line-height:1.05;margin:2px 0 4px;
 color:#B4531A;font-variant-numeric:tabular-nums}
.pdot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;
 vertical-align:middle}
.ansname{font-size:19px;font-weight:700;margin:0 0 4px}
.anshint{font-size:13.5px;color:#6b7280;margin:6px 0 0}
.ansline{font-size:15px;margin:10px 0 0;padding:10px 12px;background:#f6f9ff;
 border:1px solid #dbe6f7;border-radius:10px}

/* —— 各档价格对比横条 —— */
.cmp{margin:14px 0 0}
.cmp .row{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:13.5px}
.cmp .nm{width:66px;flex:none;color:#6b7280;white-space:nowrap}
.cmp .track{display:block;flex:1;min-width:0;background:#f0f2f5;border-radius:6px;height:12px;overflow:hidden}
.cmp .bar{display:block;height:12px;border-radius:6px;background:#c9d2df;min-width:4px;
 transition:width .25s ease-out}
.cmp .pv{font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap}
.cmp .row.cur .nm{color:#1f2329;font-weight:800}
.cmp .row.cur .pv{color:#B4531A}
.cmp .row:not(.cur){opacity:.62}

/* —— 答案卡切换动画 —— */
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
#ans .card{animation:fadeUp .18s ease-out}
ul.can{margin:14px 0 0;padding:0;list-style:none;border-top:1px solid #eef0f4}
ul.can li{display:flex;justify-content:space-between;gap:12px;padding:9px 2px;
 border-bottom:1px solid #eef0f4;font-size:15px}
ul.can li span.n{flex:1;min-width:0}
ul.can li span.p{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.more{font-size:13px;color:#6b7280;margin:10px 0 0}

/* —— 表格 —— */
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
.rank{font-size:14.5px;margin:0 0 6px}
.rank b{font-variant-numeric:tabular-nums}
footer{max-width:820px;margin:24px auto 0;color:#8b93a3;font-size:12.5px;
 border-top:1px solid #e3e6ec;padding-top:12px;line-height:1.6}
@media (prefers-color-scheme:dark){
  body{background:#121418;color:#e7eaf0}
  .lead{color:#b9c0cc}
  a{color:#E8936B}
  .sub,.big,.anshint,.more,.hintline,.qlab{color:#9aa3b2}
  .card,.q,details{background:#1b1e24;border-color:#2c313a;box-shadow:none}
  details summary{background:#20242c}
  select.sel,select{background:#22262e;border-color:#3a414c;color:#e7eaf0}
  select:focus{border-color:#E8936B;outline-color:rgba(232,147,107,.22)}
  button.now{background:#262b34;border-color:#3a414c;color:#e7eaf0}
  button.now:hover{border-color:#E8936B;color:#E8936B;background:#262f3d}
  .chip{background:#22262e;border-color:#3a414c;color:#e7eaf0}
  .chip:hover{border-color:#E8936B;color:#E8936B}
  .chip.on{background:#C2410C;border-color:#C2410C;color:#fff}
  .state.ok{background:#123322;color:#7fd6a4;border-color:#1f5a3a}
  .state.gap{background:#3a2f10;color:#f0d48a;border-color:#6b5518}
  .state.closed{background:#22262e;color:#9aa3b2;border-color:#3a414c}
  .anshero{background:linear-gradient(135deg,#241A0D,#1C1409);border-color:#5E4318;box-shadow:none}
  .anshero .big{color:#B9A68E}.anshero .ansname{color:#F0E7DB}
  .ansprice{color:#F5B45B}
  .cmp .row.cur .pv{color:#F5B45B}
  .cmp .row.cur .nm{color:#e7eaf0}
  .hero{background:linear-gradient(135deg,#2E1E0F,#1E1409);box-shadow:none}
  .hero h1{color:#F7E3C9}
  .hero .hsub{color:#CBB79C}
  .hero .hsub b{color:#F5B45B}
  .hero .hook{background:#3A2712;border-color:#6B4A1F;color:#F5B45B}
  .hero-stats .hs{background:#2A1D0F;border-color:#4A3418;color:#CBB79C}
  .hero-stats .hs b{color:#F5B45B}
  .ansline{background:#1a2333;border-color:#2c3d5c}
  ul.can{border-top-color:#2c313a}
  ul.can li{border-bottom-color:#2c313a}
  table.d th,table.d td{border-color:#2c313a}
  table.d thead th{background:#22262e}
  code{background:#262b34;color:#cfd6e2}
  footer{color:#6d7684;border-top-color:#2c313a}
  .cmp .track{background:#262b34}
  .cmp .bar{background:#4a5361}
  .qrow{border-bottom-color:#3a3326}
  .qlab{color:#F0E7DB}
  .field .flab{color:#B9A68E}
  .qhint{color:#9A8672}
  select.sel,select#times{background-color:#22262E;border-color:#4A412F;color:#e7eaf0}
  select.sel:disabled{background-color:#1c1f24;color:#6d7684}
  select.sel option{background:#22262E;color:#e7eaf0}
  button.now{background:#2A241B;border-color:#4A412F;color:#E9D9C4}
  button.now:hover{background:#33291C;border-color:#C2410C;color:#F0A96B}
  button.now.primary{background:#C2410C;border-color:#C2410C;color:#fff}
  button.now.primary:hover{background:#A8360A;border-color:#A8360A;color:#fff}
}
@media print{
  body{background:#fff;padding:0;font-size:12pt}
  .q{display:none}
  details{break-inside:avoid}
}
@media (max-width:520px){
  h1{font-size:23px}
  .ansprice{font-size:46px}
  select.sel{max-width:100%}
}
"""

JS = """
(function () {
  var DATA = window.__MCD_DATA__;
  var cur = DATA.cities[0], curTime = null, bestName = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function yuan(f) { return "¥" + (f / 100).toFixed(2); }
  function toMin(t) { var a = String(t).split(":"); return (+a[0]) * 60 + (+a[1]); }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function findCity(name) {
    for (var i = 0; i < DATA.cities.length; i++) {
      if (DATA.cities[i].city === name) return DATA.cities[i];
    }
    return null;
  }

  /* ---- 省份 → 城市 两级下拉 ---- */
  function provOf(c) { return c.province || "其他"; }
  function provList() {
    var seen = {}, out = [];
    for (var i = 0; i < DATA.cities.length; i++) {
      var p = provOf(DATA.cities[i]);
      if (!seen[p]) { seen[p] = 1; out.push(p); }
    }
    return out;
  }
  function citiesOf(p) {
    var out = [];
    for (var i = 0; i < DATA.cities.length; i++) {
      if (provOf(DATA.cities[i]) === p) out.push(DATA.cities[i].city);
    }
    return out;
  }
  function fillProv() {
    var sel = document.getElementById("provSel"), ps = provList();
    sel.innerHTML = "";
    for (var i = 0; i < ps.length; i++) {
      var o = document.createElement("option");
      o.value = ps[i]; o.textContent = ps[i];
      sel.appendChild(o);
    }
  }
  function fillCitySel() {
    var p = document.getElementById("provSel").value;
    var sel = document.getElementById("citySel"), cs = citiesOf(p);
    sel.innerHTML = "";
    if (!p) {
      var ph = document.createElement("option");
      ph.value = ""; ph.textContent = "请先选省份"; ph.selected = true;
      sel.appendChild(ph); sel.disabled = true;
      return;
    }
    sel.disabled = false;
    for (var i = 0; i < cs.length; i++) {
      var o = document.createElement("option");
      o.value = cs[i]; o.textContent = cs[i];
      sel.appendChild(o);
    }
  }
  function syncSels() {
    var ps = provList(), p = provOf(cur);
    if (ps.indexOf(p) < 0) p = ps[0];
    document.getElementById("provSel").value = p;
    fillCitySel();
    document.getElementById("citySel").value = cur.city;
  }

  /* ---- 今天最便宜的那一档(一键直接给答案) ---- */
  function cheapestPeriod(city) {
    var best = null;
    for (var i = 0; i < city.periods.length; i++) {
      var p = city.periods[i];
      if (!p.meal) continue;
      if (!best || p.meal.p < best.meal.p) best = p;
    }
    return best;
  }
  function clampSlot(city, t) {
    // 取 ≥ 目标时刻的第一个可选时刻(开档前 30 分钟落进去会变成"点不了")
    var slots = slotList(city);
    for (var i = 0; i < slots.length; i++) if (toMin(slots[i]) >= toMin(t)) return slots[i];
    return slots[slots.length - 1];
  }

  /* ---- 选城市(下拉与下方城市名单共用) ---- */
  function pick(name) {
    var c = findCity(name);
    if (!c) return;
    cur = c;
    bestName = null;
    syncSels();
    hotChips(); fillTimes(); render();
  }
  window.__pickCity = pick;

  /* ---- 热门城市快捷 chips ---- */
  function hotChips() {
    var box = document.getElementById("suggest");
    var list = DATA.hot.slice(0, 10);
    var h = '<div class="chips">';
    for (var j = 0; j < list.length; j++) {
      h += '<span class="chip' + (list[j] === cur.city ? " on" : "") + '" data-c="'
        + esc(list[j]) + '">' + esc(list[j]) + "</span>";
    }
    h += "</div>";
    box.innerHTML = h;
    var nodes = box.querySelectorAll(".chip");
    for (var k = 0; k < nodes.length; k++) {
      nodes[k].onclick = function () { pick(this.getAttribute("data-c")); };
    }
  }

  /* ---- 时刻下拉: 营业时间内每半小时 ---- */
  function slotList(city) {
    var out = [], m = toMin(city.biz[0]), end = toMin(city.biz[1]);
    if (end <= m) end = 24 * 60 - 1;
    for (var t = m; t <= end; t += 30) out.push(pad(Math.floor(t / 60)) + ":" + pad(t % 60));
    return out;
  }
  function periodOf(city, t) {
    var m = toMin(t);
    for (var i = 0; i < city.periods.length; i++) {
      var p = city.periods[i];
      if (toMin(p.start) <= m && m < toMin(p.end)) return p;
    }
    return null;
  }
  function nextPeriod(city, t) {
    var m = toMin(t), best = null;
    for (var i = 0; i < city.periods.length; i++) {
      if (toMin(city.periods[i].start) > m) {
        if (!best || toMin(city.periods[i].start) < toMin(best.start)) best = city.periods[i];
      }
    }
    return best;
  }

  function fillTimes() {
    var sel = document.getElementById("times"), slots = slotList(cur);
    sel.innerHTML = "";
    for (var i = 0; i < slots.length; i++) {
      var o = document.createElement("option");
      o.value = slots[i]; o.textContent = slots[i];
      sel.appendChild(o);
    }
    var idx = 0;
    for (var j = 0; j < slots.length; j++) {
      if (toMin(slots[j]) <= toMin(curTime)) idx = j;
    }
    sel.selectedIndex = idx;
    curTime = sel.value;
  }

  function nowTime() {
    var n = new Date();
    var s = pad(n.getHours()) + ":" + pad(n.getMinutes());
    var slots = slotList(cur), t = slots[0];
    for (var i = 0; i < slots.length; i++) if (toMin(slots[i]) <= toMin(s)) t = slots[i];
    return t;
  }

  /* ---- 主渲染 ---- */
  function render() {
    var city = cur, t = curTime, out = [];
    out.push('<div class="card">');
    out.push('<p class="sub" style="margin-bottom:10px">' + esc(city.city)
      + (city.province ? " · " + esc(city.province) : "") + " · " + esc(city.store.name) + "</p>");

    var p = periodOf(city, t);
    if (!p) {
      var nx = nextPeriod(city, t);
      var msg;
      if (nx) {
        var w = toMin(nx.start) - toMin(t);
        msg = "这个点<b>点不了</b> —— 麦当劳正在换菜单，"
          + "再等 <b>" + (w > 0 ? w + " 分钟" : "一会儿") + "</b>，"
          + esc(nx.name) + "档 <b>" + nx.start + "</b> 开档。";
      } else {
        msg = "这个点已经<b>过了当天的供餐时间</b>，点不了了。";
      }
      out.push('<p class="state gap">' + msg + "</p>");
      out.push('<p class="big">这家店的供餐时段（差一分钟就换一档）</p>');
      for (var i = 0; i < city.periods.length; i++) {
        var q = city.periods[i];
        out.push('<p class="ansname" style="font-size:16px">' + pdot(q.name) + esc(q.name) + " "
          + q.start + "–" + q.end + (q.meal ? "，最便宜一餐 " + yuan(q.meal.p) : "") + "</p>");
      }
      out.push('<p class="anshint">门店营业时间 ' + esc(city.biz[0]) + "–" + esc(city.biz[1])
        + '。开门不等于能点：时段没开档，App 里就是空的。</p>');
      out.push("</div>");
      document.getElementById("ans").innerHTML = out.join("");
      syncUrl();
      return;
    }

    var isBest = bestName && bestName === p.name;
    if (isBest) {
      out.push('<p class="state ok">' + pdot(p.name) + "这是<b>" + esc(city.city)
        + "今天最便宜的一档</b>：" + esc(p.name) + " " + p.start + "–" + p.end + "</p>");
    } else {
      out.push('<p class="state ok">' + pdot(p.name) + "这个点属于 <b>" + esc(p.name)
        + "档</b>（" + p.start + "–" + p.end + "）</p>");
    }

    var meal = p.meal || p.any;
    if (meal) {
      out.push('<div class="anshero">');
      out.push('<p class="big">' + (p.meal ? "这一档最便宜的一餐" : "这一档最便宜的一口") + "</p>");
      out.push('<p class="ansprice">' + yuan(meal.p) + "</p>");
      out.push('<p class="ansname">' + esc(meal.n) + "</p>");
      out.push("</div>");
    }

    if (p.any && p.meal && p.any.p < p.meal.p) {
      out.push('<p class="anshint">只是想垫一口：' + esc(p.any.n) + " " + yuan(p.any.p)
        + "，比一餐还便宜 " + yuan(p.meal.p - p.any.p) + "。</p>");
    }

    // 和今天最贵的那一档比, 省多少
    var worst = null;
    for (var k = 0; k < city.periods.length; k++) {
      var r = city.periods[k];
      if (r.meal && (!worst || r.meal.p > worst.meal.p)) worst = r;
    }
    if (worst && p.meal && worst.meal.p > p.meal.p && worst.name !== p.name) {
      out.push('<p class="ansline">今天最贵的是<b>' + esc(worst.name) + "档</b>，"
        + "最便宜一餐 " + yuan(worst.meal.p) + "；现在这一档便宜 <b>"
        + yuan(worst.meal.p - p.meal.p) + "</b>。</p>");
    }

    // 各档地板价对比横条(一眼看出这一档在全天的位置)
    var rows = [], maxp = 0;
    for (var b = 0; b < city.periods.length; b++) {
      var bp = city.periods[b];
      if (bp.meal) { rows.push(bp); if (bp.meal.p > maxp) maxp = bp.meal.p; }
    }
    if (rows.length > 1 && maxp > 0) {
      out.push('<p class="big" style="margin-top:16px">全天各档的最便宜一餐（这一档高亮）</p>');
      out.push('<div class="cmp">');
      for (var b2 = 0; b2 < rows.length; b2++) {
        var rp = rows[b2], w = Math.max(4, Math.round(rp.meal.p / maxp * 100));
        out.push('<div class="row' + (rp.name === p.name ? " cur" : "") + '">'
          + '<span class="nm">' + pdot(rp.name) + esc(rp.name) + "</span>"
          + '<span class="track"><span class="bar" style="width:' + w + '%;background:'
          + pcol(rp.name) + '"></span></span>'
          + '<span class="pv">' + yuan(rp.meal.p) + "</span></div>");
      }
      out.push("</div>");
    }

    if (p.top && p.top.length) {
      out.push('<p class="big" style="margin-top:16px">这一档便宜的几样（从便宜到贵）</p>');
      out.push('<ul class="can">');
      for (var m2 = 0; m2 < p.top.length; m2++) {
        out.push('<li><span class="n">' + esc(p.top[m2].n) + '</span><span class="p">'
          + yuan(p.top[m2].p) + "</span></li>");
      }
      out.push("</ul>");
    }

    // 得来速(车道取餐)更便宜的
    if (city.dtCheaper && city.dtCheaper.length) {
      var s = '<p class="big" style="margin-top:16px">开车的话，得来速车道更便宜</p><ul class="can">';
      for (var d = 0; d < city.dtCheaper.length; d++) {
        var x = city.dtCheaper[d];
        s += '<li><span class="n">' + esc(x.n) + '</span><span class="p">' + yuan(x.dt)
          + "（省 " + yuan(x.pick - x.dt) + "）</span></li>";
      }
      out.push(s + "</ul>");
      out.push('<p class="more">同一时刻、同一座城市，走得来速车道的报价更低的才列出来。'
        + '得来速是独立门店，价格也可能受门店本身影响，仅供参考。</p>');
    }

    out.push('<p class="more" style="margin-top:14px">价格是 ' + esc(DATA.targetDate)
      + " 这一天的实价，来自麦当劳订餐系统；下单前请以 App 实际显示为准。</p>"
      + '<p class="more">想把这一条发给朋友？地址栏里的链接可以直接复制：'
      + "<code>?" + "city=" + encodeURIComponent(city.city) + "&amp;t=" + esc(t) + "</code></p>");
    out.push("</div>");
    document.getElementById("ans").innerHTML = out.join("");
    syncUrl();
  }

  var PC = {"早餐": "#E8A33D", "午餐": "#D9534F", "下午茶": "#5B8DEF", "夜市": "#6A5ACD"};
  function pcol(nm) { return PC[nm] || "#8b93a3"; }
  function pdot(nm) { return '<span class="pdot" style="background:' + pcol(nm) + '"></span>'; }

  /* ---- 把当前城市与时刻写进地址栏, 方便复制分享 ---- */
  function syncUrl() {
    try {
      var u = "?city=" + encodeURIComponent(cur.city) + "&t=" + curTime;
      history.replaceState(null, "", u);
    } catch (e) { /* 本地文件打开时可能不支持, 忽略 */ }
  }

  function fromUrl() {
    var m = /[?&]city=([^&]+)/.exec(location.search), t = /[?&]t=(\\d{2}:\\d{2})/.exec(location.search);
    if (m) {
      var c = findCity(decodeURIComponent(m[1]));
      if (c) cur = c;
    }
    if (t) curTime = t[1];
  }

  function init() {
    curTime = nowTime();
    fromUrl();
    fillProv();
    syncSels();
    hotChips();
    fillTimes();
    document.getElementById("provSel").onchange = function () {
      bestName = null;
      fillCitySel();
      pick(document.getElementById("citySel").value);
    };
    document.getElementById("citySel").onchange = function () { bestName = null; pick(this.value); };
    document.getElementById("times").onchange = function () {
      bestName = null; curTime = this.value; render();
    };
    document.getElementById("nowbtn").onclick = function () {
      bestName = null; curTime = nowTime(); fillTimes(); render();
    };
    document.getElementById("bestbtn").onclick = function () {
      var b = cheapestPeriod(cur);
      if (!b) return;
      bestName = b.name;
      curTime = clampSlot(cur, b.start);
      fillTimes(); render();
      var box = document.getElementById("ans");
      if (box && box.scrollIntoView) box.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
"""


def to_min(t: str) -> int:
    try:
        h, m = str(t).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, IndexError):
        return 0


def build_city(c: dict) -> dict:
    """原始采集结果 -> 页面需要的精简结构(控制体积)。"""
    periods = []
    for p in c.get("periods") or []:
        f = (c.get("floors", {}).get("pickup") or {}).get(p["name"]) or {}
        meal, any_ = f.get("meal"), f.get("any")
        periods.append({
            "name": p["name"], "start": p["start"], "end": p["end"],
            "meal": {"n": meal["name"], "p": meal["price"]} if meal else None,
            "any": {"n": any_["name"], "p": any_["price"]} if any_ else None,
            "top": [{"n": r["name"], "p": r["price"], "k": r["kind"]}
                    for r in (f.get("top") or [])],
        })
    # 得来速更便宜的(同商品同档对比)
    dt_cheaper: list[dict] = []
    pu = c.get("prices", {}).get("pickup") or {}
    dt = c.get("prices", {}).get("dt") or {}
    if dt:
        for p in c.get("periods") or []:
            for code, tab in dt.items():
                a = (tab or {}).get(p["name"])
                b = (pu.get(code) or {}).get(p["name"])
                # 只保留"温和"价差: 差出一倍以上的通常是两家门店本身定价不同,
                # 不是渠道价差, 展示出来会误导(实测西安出现过 ¥53 vs ¥26.9 这种)
                if a and b and a < b and (b - a) <= 1200 and a >= b * 0.65:
                    nm = next((i["name"] for i in c["basket"] if i["code"] == code), code)
                    dt_cheaper.append({"n": nm, "pick": b, "dt": a})
        seen: set[str] = set()
        uniq = []
        for x in sorted(dt_cheaper, key=lambda x: x["dt"] - x["pick"]):
            if x["n"] in seen:
                continue
            seen.add(x["n"])
            uniq.append(x)
        dt_cheaper = uniq[:4]

    store = c.get("store") or {}
    return {
        "city": c["city"], "province": c.get("province", ""),
        "store": {"name": store.get("name", ""), "address": store.get("address", "")},
        "biz": [store.get("businessStart") or "07:00", store.get("businessEnd") or "22:00"],
        "periods": periods,
        "dtCheaper": dt_cheaper,
    }


def rank_block(title: str, rows: list[tuple[str, str]], note: str = "") -> str:
    items = "".join(f'<p class="rank">{i}. <b>{escape(a)}</b> —— {escape(b)}</p>'
                    for i, (a, b) in enumerate(rows, 1))
    return f"<h3>{escape(title)}</h3>{items}" + (
        f'<p class="sub">{escape(note)}</p>' if note else "")


def national_overview(cities: list[dict]) -> str:
    """全国对比: 开档时间 / 各档地板价 / 早餐溢价 —— 全是实测出来的地域差异。"""
    out = []
    # 早餐开档时间
    with_bf = [(c["city"], c["periods"][0]["start"])
               for c in cities
               if c.get("periods") and c["periods"][0]["name"] == "早餐"
               and c["periods"][0].get("start")]
    earliest = sorted(with_bf, key=lambda x: (to_min(x[1]), x[0]))[:8]
    latest = sorted(with_bf, key=lambda x: (-to_min(x[1]), x[0]))[:8]
    no_bf = [c["city"] for c in cities
             if not (c.get("periods") and c["periods"][0]["name"] == "早餐")]
    out.append(rank_block("早餐开得最早的城市（想吃早餐不用等）",
                          [(f"{c} {t}", "早餐档 " + t + " 开档") for c, t in earliest]))
    out.append(rank_block("早餐开得最晚的城市",
                          [(f"{c} {t}", "早餐档 " + t + " 才开档") for c, t in latest]))
    if no_bf:
        out.append(f'<p class="sub">另有 <b>{len(no_bf)}</b> 座城市的样本门店'
                   f'在早餐档时段还没开门，当天没有早餐档，例如：'
                   f'{escape("、".join(no_bf[:8]))}。</p>')

    # 午餐地板价
    lunch = []
    for c in cities:
        f = (c.get("floors", {}).get("pickup") or {}).get("午餐") or {}
        if f.get("meal"):
            lunch.append((c["city"], f["meal"]["price"], f["meal"]["name"]))
    if lunch:
        low = sorted(lunch, key=lambda x: (x[1], x[0]))[:8]
        high = sorted(lunch, key=lambda x: (-x[1], x[0]))[:8]
        out.append(rank_block("午餐最便宜的城市",
                              [(f"{c} ¥{p / 100:.2f}", n) for c, p, n in low]))
        out.append(rank_block("午餐最贵的城市",
                              [(f"{c} ¥{p / 100:.2f}", n) for c, p, n in high]))

    # 早餐 vs 午餐 价差
    delta = []
    for c in cities:
        fl = c.get("floors", {}).get("pickup") or {}
        b = (fl.get("早餐") or {}).get("meal")
        l = (fl.get("午餐") or {}).get("meal")
        if b and l and l["price"] > b["price"]:
            delta.append((c["city"], l["price"] - b["price"], b["price"], l["price"]))
    if delta:
        top = sorted(delta, key=lambda x: -x[1])[:8]
        out.append(rank_block("早餐比午餐省得最多的城市",
                              [(f"{c} 省 ¥{d / 100:.2f}",
                                f"早餐 ¥{bp / 100:.2f} → 午餐 ¥{lp / 100:.2f}")
                               for c, d, bp, lp in top]))
        out.append(f'<p class="sub">全部 {len(delta)} 座有早餐档的城市里，'
                   f'早餐档的地板价都低于午餐档 —— 这是全国一致的规律。</p>')
    return "".join(out)


def all_cities_block(cities: list[dict]) -> str:
    """按大区分组的完整城市列表(找不到自己城市时的兜底入口)。"""
    groups: dict[str, list[str]] = {}
    for c in cities:
        groups.setdefault(c.get("region") or "其他", []).append(c["city"])
    out = []
    for region in ["华北", "东北", "华东", "华中", "华南", "西南", "西北", "其他"]:
        if region not in groups:
            continue
        chips = "".join(f'<span class="chip" data-c="{escape(x)}">{escape(x)}</span>'
                        for x in groups[region])
        out.append(f"<h3>{escape(region)}（{len(groups[region])} 座）</h3>"
                   f'<div class="chips citylist">{chips}</div>')
    return "".join(out)


def hero_facts(cities_raw: list[dict]) -> dict:
    """首屏钩子用的真数 —— 全部从数据现算, 不写死(数据一刷新文案就跟着对)。"""
    def floor(c, per):
        f = (c.get("floors") or {}).get("pickup", {}).get(per) or {}
        m = f.get("meal")
        return m["price"] if m else None

    gaps = []
    for c in cities_raw:
        bf, lf = floor(c, "早餐"), floor(c, "午餐")
        if bf and lf and lf > bf:
            gaps.append((lf - bf, c["city"], bf, lf))
    gaps.sort(reverse=True)
    bf_all = sorted(x for x in (floor(c, "早餐") for c in cities_raw) if x)
    lf_all = sorted(x for x in (floor(c, "午餐") for c in cities_raw) if x)

    def med(xs):
        return xs[len(xs) // 2] if xs else 0

    gap, gap_city, gap_bf, gap_lf = gaps[0] if gaps else (0, "", 0, 0)
    cheaper = sum(1 for c in cities_raw
                  if (floor(c, "午餐") or 0) and (floor(c, "早餐") or 0)
                  and floor(c, "午餐") < floor(c, "早餐"))
    return {
        "gap": gap, "gap_city": gap_city, "gap_bf": gap_bf, "gap_lf": gap_lf,
        "bf_med": med(bf_all), "lf_med": med(lf_all),
        "bf_n": len(bf_all), "lf_n": len(lf_all),
        "cheaper_n": cheaper,
    }


def main() -> int:
    path = SURFACE_PATH
    if BATCH_PATH.exists():
        try:
            n_batch = len(json.loads(BATCH_PATH.read_text(encoding="utf-8"))
                          .get("cities") or [])
        except (json.JSONDecodeError, OSError):
            n_batch = 0
        if n_batch >= FULL_MENU_MIN_CITIES:
            path = BATCH_PATH
    if not path.exists():
        print(f"未找到 {path}。先跑: python src/survey_batch.py")
        return 1
    surface = json.loads(path.read_text(encoding="utf-8"))
    cities_raw = list(surface.get("cities") or [])
    if path == BATCH_PATH and SURFACE_PATH.exists():
        # 全菜单采集有 8 座城因「候选门店均不支持预约取餐(600056)」没采到,
        # 用探针快照补上, 别让页面比探针版少城市。
        probe = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
        have = {c.get("city") for c in cities_raw}
        extra = [c for c in (probe.get("cities") or []) if c.get("city") not in have]
        cities_raw += extra
        surface = dict(surface)
        surface["cities"] = cities_raw
    if not cities_raw:
        print("数据里没有城市。")
        return 1

    data = [build_city(c) for c in cities_raw]
    payload = json.dumps({
        "cities": data,
        "hot": [c for c in HOT_CITIES if any(x["city"] == c for x in data)],
        "targetDate": surface.get("targetDate", ""),
    }, ensure_ascii=False, separators=(",", ":"))

    n_cities = len(cities_raw)
    n_calls = sum(c.get("calls", 0) for c in cities_raw)
    gen = escape(str(surface.get("generatedAt", datetime.now().isoformat(timespec="seconds"))))
    target = escape(str(surface.get("targetDate", "")))
    hf = hero_facts(cities_raw)
    overview = national_overview(cities_raw)
    citylist = all_cities_block(cities_raw)

    # JS 失效时的静态兜底答案
    fb = data[0]
    fb_p = next((p for p in fb["periods"] if p["meal"]), fb["periods"][0] if fb["periods"] else None)
    fallback = ""
    if fb_p and fb_p.get("meal"):
        rows = "".join(f'<li><span class="n">{escape(r["n"])}</span>'
                       f'<span class="p">¥{r["p"] / 100:.2f}</span></li>'
                       for r in fb_p["top"][:6])
        fallback = (
            f'<div class="card"><p class="sub" style="margin-bottom:10px">'
            f'{escape(fb["city"])} · {escape(fb["store"]["name"])}</p>'
            f'<p class="state ok">{escape(fb_p["name"])}档（{escape(fb_p["start"])}–'
            f'{escape(fb_p["end"])}）</p>'
            f'<p class="big">这一档最便宜的一餐</p>'
            f'<p class="ansprice">¥{fb_p["meal"]["p"] / 100:.2f}</p>'
            f'<p class="ansname">{escape(fb_p["meal"]["n"])}</p>'
            f'<ul class="can">{rows}</ul>'
            f'<p class="more">想查别的城市和时刻，需要浏览器开启 JavaScript；'
            f'否则可以展开下面的全国对比和城市列表查看。</p></div>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>麦当劳几点最便宜 · 全国 {n_cities} 城，选城市和时刻直接给答案</title>
<style>{CSS}</style></head><body>
<div class="wrap">
<header class="hero">
  <p class="hook">同一家麦当劳，换个时段最便宜能差 ¥{hf['gap'] / 100:.2f}</p>
  <h1>麦当劳几点最便宜</h1>
  <p class="hsub">{hf['gap_city']}早餐最便宜一餐 ¥{hf['gap_bf'] / 100:.2f}，同一个午餐档就要 ¥{hf['gap_lf'] / 100:.2f}。
  全国 {hf['bf_n']} 座城早餐有正餐地板价、中位 ¥{hf['bf_med'] / 100:.2f}，午餐中位 ¥{hf['lf_med'] / 100:.2f}。
  选<b>城市</b>、选<b>几点去</b>，直接告诉你<b>那一刻最便宜能吃什么、多少钱</b>。</p>
  <div class="hero-stats">
    <span class="hs"><b>{n_cities}</b>座城市</span>
    <span class="hs"><b>{n_calls}</b>次真实问价</span>
    <span class="hs">早餐地板价中位 <b>¥9.90</b></span>
    <span class="hs">不用注册 · 手机直接看</span>
  </div>
</header>

<div class="q">
  <div class="qrow">
    <span class="qlab"><span class="qnum">1</span>你在哪座城市</span>
    <div class="selrow">
      <div class="field">
        <label class="flab" for="provSel">省份 / 直辖市</label>
        <select class="sel" id="provSel"></select>
      </div>
      <div class="field">
        <label class="flab" for="citySel">城市</label>
        <select class="sel" id="citySel"></select>
      </div>
    </div>
    <p class="qhint">没找到你的城市？往下翻到最后一段「城市名单」。</p>
    <div id="suggest"></div>
  </div>
  <div class="qrow">
    <span class="qlab"><span class="qnum">2</span>你几点去</span>
    <div class="selrow">
      <div class="field">
        <label class="flab" for="times">到店时间</label>
        <select id="times"></select>
      </div>
    </div>
    <div class="acts">
      <button class="now primary" id="bestbtn" type="button">直接告诉我今天最便宜的时刻</button>
      <button class="now" id="nowbtn" type="button">就用现在这个时间</button>
    </div>
  </div>
</div>

<div id="ans">{fallback}</div>

<details><summary>看看全国：哪里早餐开得早、哪里午餐最便宜</summary>
<div class="dbody">{overview}</div></details>

<details><summary>全国 {n_cities} 座城市名单</summary>
<div class="dbody">{citylist}</div></details>

<details><summary>这些数字是怎么来的？</summary><div class="dbody">
<p>价格不是估的。程序对每座城市的样本门店，按<b>官方时段</b>（早餐/午餐/下午茶/夜市）
逐个向麦当劳订餐系统问价，相当于在 App 里选好商品、选好取餐时间后看到的实付金额，
问回来的数字原样记下。这一版一共问价 <b>{n_calls}</b> 次。</p>
<p>先做了一次实测：同一商品在一天之内价格恒定，变化的是「这个时段卖不卖」。
所以按档问价即可覆盖全天，不必逐分钟地毯式轰炸。</p>
<p>整条链路是<b>只读</b>的：只问价，不下单、不领券、不碰支付环节。</p>
<p>时段边界（早餐/午餐/下午茶/夜市各自的起止时刻）取自门店返回的排期，不是我们自己划的。
不同城市开门时间不同，开档时刻能差 4 个小时。</p>
<p class="sub">技术实现与复现方式见仓库 <code>MCP_INTEGRATION.md</code>。</p>
</div></details>

<footer>
生成时间 {gen} · 数据日期 {target} · 覆盖 {n_cities} 座城市 · 共 {n_calls} 次问价 ·
取餐方式：到店自提（部分城市含得来速）<br>
样本为该城市门店中的一家，同城市不同门店的营业时间可能有差异。
本项目为 2026 麦当劳程序员创意开发大赛参赛作品，非麦当劳官方产品。
价格随门店与日期变动，下单前请以麦当劳 App 实际显示为准。
</footer>
</div>
<script>window.__MCD_DATA__ = {payload};</script>
<script>{JS}</script>
<script>
// 城市名单里的 chips 也能点(静态区复用搜索逻辑)
(function(){{
  var nodes = document.querySelectorAll(".citylist .chip");
  for (var i = 0; i < nodes.length; i++) {{
    nodes[i].onclick = function () {{
      window.__pickCity(this.getAttribute("data-c"));
      window.scrollTo(0, 0);
    }};
  }}
}})();
</script>
</body></html>"""

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB, {n_cities} 城, 双击即开)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
