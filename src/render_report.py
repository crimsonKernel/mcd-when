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
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface_national.json"
BATCH_PATH = ROOT / "data" / "surface_batch.json"
LEGACY_PATH = ROOT / "data" / "surface.json"
OUT_DIR = ROOT / "dist"
OUT_PATH = OUT_DIR / "report.html"

# 全菜单采集(survey_batch.py)覆盖到这个城市数就优先用它渲染 ——
# 它比探针快照多出完整菜单, 且口径与 MCP Server 一致。
FULL_MENU_MIN_CITIES = 50

HOT_CITIES = ["北京", "上海", "广州", "深圳", "成都", "重庆", "武汉", "西安",
              "杭州", "南京", "长沙", "郑州"]

PERIOD_ICON = {"早餐": "🌅", "午餐": "🍔", "下午茶": "🍰", "夜市": "🌙"}

# 单文件离线版专用: 城市名单里的 chips 也能点(静态区复用 __pickCity)。
# 三页版的榜单页 chips 是深链, 不需要这段。
CHIPS_SCRIPT = """
<script>
(function(){
  var nodes = document.querySelectorAll(".citylist .chip");
  for (var i = 0; i < nodes.length; i++) {
    nodes[i].onclick = function () {
      window.__pickCity(this.getAttribute("data-c"));
      window.scrollTo(0, 0);
    };
  }
})();
</script>
"""

CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#FBF7F2;color:#1f2329;
 font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB","Source Han Sans SC",
   "Noto Sans CJK SC",system-ui,-apple-system,sans-serif;
 font-size:16px;line-height:1.7;padding:20px 14px 40px;
 word-break:break-word;overflow-wrap:break-word}
.wrap{max-width:820px;margin:0 auto}

/* —— 顶部导航(三页版) —— */
.nav{display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin:0 0 14px;
 padding:8px 10px;background:#fff;border:1px solid #e3e6ec;border-radius:14px;
 box-shadow:0 1px 2px rgba(16,24,40,.04)}
.nav .brand{font-weight:800;color:#7C1D12;font-size:14.5px;margin-right:6px;
 white-space:nowrap}
.nav a{display:inline-block;padding:6px 13px;border-radius:999px;font-size:14px;
 font-weight:700;color:#6B5747;text-decoration:none}
.nav a:hover{background:#FDF1E3;color:#B4531A}
.nav a.on{background:#C2410C;color:#fff}
.nav .dl{margin-left:auto;font-size:13px;font-weight:700;color:#8C2F0B}

/* —— 头部: 黄金3秒钩子(暖奶油) —— */
/* 光晕直接用背景渐变画, 不用伪元素: 伪元素的负 inset 会让 scrollWidth
   超出盒宽, 排版体检会判溢出(而且没有任何视觉收益)。 */
.hero{background:
  radial-gradient(120% 85% at 16% -12%, rgba(255,171,64,.30), rgba(255,171,64,0) 62%),
  radial-gradient(85% 65% at 102% 112%, rgba(194,65,12,.11), rgba(194,65,12,0) 70%),
  linear-gradient(135deg,#FFFDF9 0%,#FDF1E3 100%);
 color:#2B1B12;border-radius:18px;padding:26px 22px 22px;margin:0 0 16px;
 box-shadow:0 1px 2px rgba(120,80,20,.06),0 10px 26px rgba(120,80,20,.09)}
.hero .hook{display:inline-block;background:#FFF1E2;border:1px solid #F2D9B6;
 color:#B4531A;font-size:13.5px;font-weight:800;letter-spacing:.4px;padding:5px 12px;
 border-radius:20px;margin:0 0 12px}
.hero h1{font-size:34px;line-height:1.25;margin:0 0 10px;color:#7C1D12;letter-spacing:-.4px}
.hero .hsub{font-size:16px;color:#5A4638;margin:0 0 16px;line-height:1.65}
.hero .hsub b{color:#B4531A}
.hero .hsub2{display:block;margin-top:10px;font-size:13.5px;color:#7A6653}
.hero .hsub2 a{color:#B4531A;text-decoration:underline}
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
/* 价格数字做成暖色渐变: 全页只有一个东西值得被这样强调。
   用 @supports 兜底 —— 不支持 background-clip:text 的浏览器拿纯色, 不会看不见字。 */
@supports ((-webkit-background-clip:text) or (background-clip:text)){
  .ansprice{background:linear-gradient(135deg,#C2410C 0%,#E8890C 55%,#F5B45B 100%);
    -webkit-background-clip:text;background-clip:text;
    -webkit-text-fill-color:transparent;color:transparent}
}
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

/* —— 这一档的菜单和别档差在哪: 价格轴是平的, 差异全在这儿 —— */
.mdiff{margin:14px 0 0;padding:13px 15px;border:1px solid #E7DFD2;border-radius:13px;
 background:linear-gradient(180deg,#FCFBF8,#F8F6F1)}
.mdl{margin:0;font-size:14.5px;line-height:1.65;color:#3d4450}
.mdl b{color:#B4531A}
.mdl2{margin:8px 0 0;font-size:13px;color:#7A6653;line-height:1.6}
.mditems{margin:8px 0 0;font-size:13.5px;line-height:1.75;color:#5A4638}
.mditems::before{content:"🍔 ";filter:saturate(.9)}

/* —— 全天时段带: 把「今天四档」画成一条能点的时间轴 —— */.dayband{margin:0 0 16px;padding:13px 14px 12px;border:1px solid #F0E2CE;border-radius:14px;
 background:linear-gradient(180deg,#FFFDF8 0%,#FFF8EE 100%)}
.dbhead{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin:0 0 9px}
.dbhead .t{font-size:12.5px;font-weight:800;color:#8a6100;letter-spacing:.5px}
.dbhead .h{font-size:11.5px;color:#A9907A;white-space:nowrap}
.dbscroll{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch}
.dbtrack{position:relative;display:flex;height:58px;border-radius:10px;
 overflow:hidden;background:#F1E9DC;box-shadow:inset 0 1px 3px rgba(120,80,20,.13)}
/* 宽度按分钟数用 flex-grow 等比例分配, 不写死百分比 ——
   百分比在 flex 里和 min-width 会打架, 窄屏会把长文本挤成省略号。 */
.dbseg{position:relative;display:flex;flex-direction:column;justify-content:center;gap:1px;
 padding:4px 7px;min-width:58px;overflow:hidden;cursor:pointer;border:0;
 border-right:1px solid rgba(255,255,255,.5);color:#fff;text-align:left;font:inherit;
 transition:filter .18s ease,box-shadow .18s ease}
.dbseg:last-child{border-right:0}
.dbseg:hover{filter:brightness(1.08)}
.dbseg:active{filter:brightness(.96)}
.dbseg .n{font-size:12px;font-weight:800;line-height:1.2;white-space:nowrap;
 overflow:hidden;text-overflow:ellipsis}
.dbseg .p{font-size:12.5px;font-weight:800;line-height:1.2;font-variant-numeric:tabular-nums;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.96}
.dbseg .h{font-size:10.5px;line-height:1.15;font-variant-numeric:tabular-nums;opacity:.85;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dbseg.cur{box-shadow:inset 0 0 0 2px #7C1D12;z-index:1}
/* 真空带: 两档之间谁都点不到的那几分钟 —— 窄缝不贴文字,
   免得把「真空带很窄」这个事实用省略号糊掉。 */
.dbseg.gap{min-width:8px;padding:4px 2px;
 background:repeating-linear-gradient(45deg,#EFE6D8 0 6px,#E3D7C3 6px 12px);
 color:#8A7361;cursor:default}
.dbseg.gap .n{font-size:10px;font-weight:700;text-align:center;padding:0 1px}
.dbseg.empty{background:#E9DFCF;color:#8A7361;cursor:default}
.dblegend{display:flex;flex-wrap:wrap;gap:10px;margin:9px 0 0;font-size:11.5px;color:#9C8873}
.dblegend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;
 vertical-align:baseline}

/* —— 全局质感 —— */
::selection{background:#FFD9A8;color:#5A2A08}
:focus-visible{outline:2px solid #C2410C;outline-offset:2px;border-radius:6px}
.dbscroll::-webkit-scrollbar{height:6px}
.dbscroll::-webkit-scrollbar-thumb{background:#E0D2BE;border-radius:6px}
.dbscroll::-webkit-scrollbar-track{background:transparent}

/* —— 首屏入场: 分层落位 —— */
@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.wrap>.nav{animation:rise .45s cubic-bezier(.22,1,.36,1) both}
.wrap>.hero{animation:rise .55s .05s cubic-bezier(.22,1,.36,1) both}
.wrap>.q{animation:rise .55s .11s cubic-bezier(.22,1,.36,1) both}
.wrap>#sec-answer{animation:rise .55s .17s cubic-bezier(.22,1,.36,1) both}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.001s!important;transition-duration:.001s!important}
}

ul.can{margin:14px 0 0;padding:0;list-style:none;border-top:1px solid #eef0f4}
ul.can li{display:flex;justify-content:space-between;gap:12px;padding:9px 2px;
 border-bottom:1px solid #eef0f4;font-size:15px}
ul.can li span.n{flex:1;min-width:0}
ul.can li span.p{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.more{font-size:13px;color:#6b7280;margin:10px 0 0}

/* —— 预算搭配器: 「¥__ 能吃到最饱的」 —— */
.budget{margin:18px 0 0;padding:14px;border:1px solid #F2D9B6;border-radius:14px;
 background:linear-gradient(135deg,#FFFDF8 0%,#FFF9EF 100%)}
.budget .bq{font-size:14.5px;color:#8a6100;font-weight:700;margin:0 0 10px}
.bchips{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 10px}
.bchip{font:inherit;font-size:14px;font-weight:700;padding:7px 14px;border-radius:999px;
 border:1px solid #E8C89A;background:#fff;color:#8a6100;cursor:pointer;
 transition:all .15s ease;font-variant-numeric:tabular-nums}
.bchip:hover{border-color:#C2410C;color:#C2410C}
.bchip.on{background:#C2410C;border-color:#C2410C;color:#fff}
.brow{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.brow .blab{font-size:13px;color:#9C8873}
.bin{font:inherit;font-size:14px;width:82px;padding:7px 10px;border-radius:9px;
 border:1px solid #E8C89A;background:#fff;color:#1f2329;font-variant-numeric:tabular-nums}
.bin:focus{outline:none;border-color:#C2410C;box-shadow:0 0 0 3px rgba(194,65,12,.12)}
.bgo{font:inherit;font-size:14px;font-weight:700;padding:7px 15px;border-radius:9px;
 border:1px solid #C2410C;background:#C2410C;color:#fff;cursor:pointer;transition:all .15s ease}
.bgo:hover{background:#A8360A;border-color:#A8360A}
.bout{margin:12px 0 0;min-height:20px}
.bout .bhead{font-size:16px;font-weight:800;margin:0 0 8px;color:#1f2329}
.bout .bhead b{color:#B4531A;font-variant-numeric:tabular-nums}
.bout .btot{font-size:13.5px;color:#6b7280;margin:8px 0 0}
.bout .btot b{color:#14622c;font-variant-numeric:tabular-nums}
.bout .bgap{font-size:13.5px;color:#8a6100;margin:8px 0 0;padding:9px 11px;
 background:#FFF4CE;border:1px solid #F0D999;border-radius:9px}
.bout .bnote{font-size:12.5px;color:#9C8873;margin:8px 0 0}
.bout .btip{font-size:13px;color:#8a6100;margin:10px 0 0;padding:9px 11px;
 background:#FFF9EC;border:1px dashed #E8C89A;border-radius:9px}
.bout .btip b{color:#B4531A}
.bout .banchor{font-size:14px;font-weight:700;margin:0 0 10px;color:#1f2329;
 padding:9px 11px;background:#fff;border:1px solid #E8C89A;border-radius:9px}
.bout .banchor b{color:#B4531A}
.bout .banchor a{color:#5B8DEF;font-weight:400;font-size:12.5px;margin-left:4px}
ul.bcombo{margin:0;padding:0;list-style:none;border-top:1px solid #F0E2CC}
ul.bcombo li{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
 padding:9px 2px;border-bottom:1px solid #F0E2CC;font-size:15px}
ul.bcombo li .n{flex:1;min-width:0}
ul.bcombo li .k{font-size:11.5px;font-weight:700;padding:2px 7px;border-radius:999px;
 flex:none;margin-right:2px}
ul.bcombo li .k.m{background:#FDECEC;color:#B4322E}
ul.bcombo li .k.s{background:#EAF1FE;color:#3B6BC4}
ul.bcombo li .k.x{background:#F1F2F5;color:#6b7280}
ul.bcombo li .p{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}

/* —— 完整在售菜单表 —— */
.mtwrap{margin:20px 0 0}
.mthead{display:flex;justify-content:space-between;align-items:center;
 gap:10px;flex-wrap:wrap;margin-bottom:8px}
.mtctl{display:flex;gap:6px;flex-wrap:wrap}
.mtbtn{font:inherit;font-size:12.5px;font-weight:700;padding:5px 11px;border-radius:999px;
 border:1px solid #E3E6EC;background:#fff;color:#6b7280;cursor:pointer;transition:all .15s ease}
.mtbtn:hover{border-color:#C2410C;color:#C2410C}
.mtbtn.on{background:#1f2329;border-color:#1f2329;color:#fff}
.mtscroll{max-height:430px;overflow-y:auto;border:1px solid #E3E6EC;border-radius:12px;
 background:#fff}
table.mt{width:100%;border-collapse:collapse;font-size:14px}
table.mt thead th{position:sticky;top:0;background:#F6F7F9;text-align:left;
 padding:9px 10px;border-bottom:1px solid #E3E6EC;font-size:12.5px;color:#6b7280;
 white-space:nowrap;z-index:1}
table.mt td{padding:8px 10px;border-bottom:1px solid #F2F3F5;vertical-align:middle}
table.mt tbody tr:last-child td{border-bottom:none}
table.mt tbody tr:nth-child(even){background:#FCFCFD}
table.mt tbody tr:hover{background:#FFF8EE}
table.mt tbody tr.on{background:#FFF6E8}
table.mt tbody tr.on td:first-child{box-shadow:inset 3px 0 0 #C2410C}
table.mt td.p{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;
 white-space:nowrap}
table.mt td.a{text-align:right;white-space:nowrap}
table.mt .k{font-size:11px;font-weight:700;padding:2px 7px;border-radius:999px;
 white-space:nowrap}
table.mt .k.m{background:#FDECEC;color:#B4322E}
table.mt .k.s{background:#EAF1FE;color:#3B6BC4}
table.mt .k.x{background:#F1F2F5;color:#6b7280}
.mtpick{font:inherit;font-size:12px;font-weight:700;padding:4px 10px;border-radius:7px;
 border:1px solid #E8C89A;background:#FFFDF8;color:#8a6100;cursor:pointer;
 transition:all .15s ease;white-space:nowrap}
.mtpick:hover{border-color:#C2410C;color:#C2410C;background:#fff}
.mtnote{font-size:12.5px;color:#8a6100;margin:0 0 8px;padding:8px 11px;
 background:#FFF4CE;border:1px solid #F0D999;border-radius:9px}
@media (prefers-color-scheme:dark){
  .budget{background:#241F16;border-color:#4A412F}
  .budget .bq{color:#E9C46A}
  .bchip{background:#22262E;border-color:#4A412F;color:#E9D9C4}
  .bchip:hover{border-color:#C2410C;color:#F0A96B}
  .bchip.on{background:#C2410C;border-color:#C2410C;color:#fff}
  .brow .blab{color:#9A8672}
  .bin{background:#22262E;border-color:#4A412F;color:#e7eaf0}
  .bout .bhead{color:#e7eaf0}
  .bout .btot{color:#9aa3b2}
  .bout .bgap{background:#2A241B;border-color:#4A412F;color:#E9C46A}
  .bout .bnote{color:#9A8672}
  .bout .btip{background:#2A241B;border-color:#4A412F;color:#E9C46A}
  .bout .banchor{background:#22262E;border-color:#4A412F;color:#e7eaf0}
  .bout .banchor b{color:#F0A96B}
  .bout .banchor a{color:#9DBBF0}
  ul.bcombo{border-top-color:#3A332A}
  ul.bcombo li{border-bottom-color:#3A332A}
  ul.bcombo li .k.m{background:#3A2422;color:#F0A6A2}
  ul.bcombo li .k.s{background:#1F2A3A;color:#9DBBF0}
  ul.bcombo li .k.x{background:#2A2E36;color:#9aa3b2}
  .mtbtn{background:#22262E;border-color:#3A414D;color:#9aa3b2}
  .mtbtn:hover{border-color:#C2410C;color:#F0A96B}
  .mtbtn.on{background:#E9D9C4;border-color:#E9D9C4;color:#1f2329}
  .mtscroll{background:#1A1D23;border-color:#3A414D}
  table.mt thead th{background:#22262E;border-bottom-color:#3A414D;color:#9aa3b2}
  table.mt td{border-bottom-color:#262A31}
  table.mt tbody tr:hover{background:#22262E}
  table.mt tbody tr.on{background:#2E2818}
  table.mt .k.m{background:#3A2422;color:#F0A6A2}
  table.mt .k.s{background:#1F2A3A;color:#9DBBF0}
  table.mt .k.x{background:#2A2E36;color:#9aa3b2}
  .mtpick{background:#22262E;border-color:#4A412F;color:#E9D9C4}
  .mtpick:hover{border-color:#C2410C;color:#F0A96B;background:#2A241B}
  .mtnote{background:#2A241B;border-color:#4A412F;color:#E9C46A}
}
@media (max-width:520px){
  .budget{padding:12px}
  .bin{width:74px}
}

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
/* 榜单行: 序号做成一枚徽章, 行 hover 有反馈(纯 CSS, 榜单页零 JS) */
.rank{font-size:14.5px;margin:0 0 6px;padding:6px 10px;border-radius:9px;
 border:1px solid transparent;transition:background .15s,border-color .15s}
.rank:hover{background:#FFF8EE;border-color:#F2D9B6}
.rank b{font-variant-numeric:tabular-nums}
h3{position:relative;padding-left:11px;margin:22px 0 10px;font-size:16.5px}
h3::before{content:"";position:absolute;left:0;top:.28em;bottom:.28em;width:3px;
 border-radius:2px;background:linear-gradient(180deg,#F0A22E,#C2410C)}
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
  .ansprice{color:#F5B45B;background:none;-webkit-text-fill-color:#F5B45B}
  table.mt tbody tr:nth-child(even){background:#1A1D23}
  table.mt tbody tr:hover{background:#22262E}
  table.mt tbody tr.on td:first-child{box-shadow:inset 3px 0 0 #F5B45B}
  .cmp .row.cur .pv{color:#F5B45B}
  .cmp .row.cur .nm{color:#e7eaf0}
  .hero{background:linear-gradient(135deg,#2E1E0F,#1E1409);box-shadow:none}
  .hero h1{color:#F7E3C9}
  .hero .hsub{color:#CBB79C}
  .hero .hsub b{color:#F5B45B}
  .hero .hsub2{color:#B9A488}
  .hero .hsub2 a{color:#F5B45B}
  .hero .hook{background:#3A2712;border-color:#6B4A1F;color:#F5B45B}
  .hero-stats .hs{background:#2A1D0F;border-color:#4A3418;color:#CBB79C}
  .hero-stats .hs b{color:#F5B45B}
  .ansline{background:#1a2333;border-color:#2c3d5c}
  .dayband{background:linear-gradient(180deg,#241A0D,#1C1409);border-color:#4A3418}
  .dbhead .t{color:#F0C98A}
  .dbhead .h{color:#9A8672}
  .dbtrack{background:#191209;box-shadow:inset 0 1px 3px rgba(0,0,0,.5)}
  .dbseg{border-right-color:rgba(0,0,0,.45)}
  .dbseg.cur{box-shadow:inset 0 0 0 2px #F5B45B}
  .dbseg.gap{background:repeating-linear-gradient(45deg,#2A2216 0 6px,#221B12 6px 12px);
    color:#9A8672}
  .dbseg.empty{background:#241D14;color:#9A8672}
  .dblegend{color:#9A8672}
  .mdiff{background:#1B1810;border-color:#3A3324}
  .mdl{color:#c9c2b6}
  .mdl b{color:#F5B45B}
  .mdl2{color:#9A8672}
  .mditems{color:#CBB79C}
  .dbscroll::-webkit-scrollbar-thumb{background:#4A3418}
  .rank:hover{background:#241A0D;border-color:#4A3418}
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
  .hero{padding:20px 16px 18px}
  .hero h1{font-size:27px}
  .hero .hsub{font-size:15px}
  .dbtrack{height:52px}
  .dbseg{padding:3px 5px}
  .dbseg .n{font-size:11px}
  .dbseg .p{font-size:11.5px}
  .dbseg .h{display:none}
  .cmp .nm{width:56px}
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

  /* ---- 全天时段带: 按真实起止时刻画一条能点的时间轴 ----
     四档各占多宽是算出来的, 不是四等分 —— 「真空带很窄」这件事
     必须一眼看得出来, 所以缝隙也按分钟数等比例画。 */
  var DBCOL = { "早餐": "#D98324", "午餐": "#C2410C", "下午茶": "#B0479E", "夜市": "#3F5BA9" };
  function dbColor(name) { return DBCOL[name] || "#8A6D3B"; }
  function dayBand(city, t) {
    var ps = city.periods || [];
    if (!ps.length) return "";
    var b0 = toMin(city.biz[0]), b1 = toMin(city.biz[1]);
    if (b1 <= b0) b1 = 24 * 60 - 1;
    var span = b1 - b0;
    if (span <= 0) return "";
    var curP = periodOf(city, t), segs = [], cursor = b0;
    for (var i = 0; i < ps.length; i++) {
      var p = ps[i], s = Math.max(b0, toMin(p.start)), e = Math.min(b1, toMin(p.end));
      if (e <= s) continue;
      if (s > cursor) {   // 两档之间: 官方换菜单的空档
        segs.push({ gap: 1, from: cursor, to: s, mins: s - cursor });
      }
      segs.push({ p: p, from: s, to: e, mins: e - s });
      cursor = e;
    }
    if (cursor < b1) segs.push({ gap: 1, from: cursor, to: b1, mins: b1 - cursor });
    if (!segs.length) return "";
    var h = '<div class="dayband">'
      + '<div class="dbhead"><span class="t">今天这一路怎么走的</span>'
      + '<span class="h">宽度按分钟数 · 点一段就跳过去</span></div>'
      + '<div class="dbscroll"><div class="dbtrack">';
    for (var j = 0; j < segs.length; j++) {
      var g = segs[j];
      if (g.mins <= 0) continue;
      // 宽度 ∝ 分钟数: flex-grow 给分钟值, 剩余空间按它分
      var st = "flex:" + g.mins + " 1 0";
      if (g.gap) {
        var gm = g.mins >= 60
          ? Math.floor(g.mins / 60) + " 小时 " + (g.mins % 60) + " 分钟"
          : g.mins + " 分钟";
        // 窄缝不贴字: 省略号会把「真空带很窄」这个事实糊掉
        var label = g.mins >= 45 ? '<span class="n">真空带</span>' : "";
        h += '<div class="dbseg gap" style="' + st + '" title="菜单真空带 ' + gm
          + '，上一档已收、下一档没开" aria-label="菜单真空带 ' + gm + '">' + label + "</div>";
      } else {
        var pp = g.p, has = !!pp.meal;
        // 第三行放在售件数, 不放起止时间 —— 件数才能让人看出
        // 「后三档其实是同一套菜单」, 起止时间在 title 里
        var cnt = (pp.menu && pp.menu.length) ? pp.menu.length + " 件" : "";
        h += '<button type="button" class="dbseg' + (curP && curP.name === pp.name ? " cur" : "")
          + (has ? "" : " empty") + '" style="' + st + ';background:' + dbColor(pp.name)
          + '" data-t="' + esc(pp.start) + '" title="' + esc(pp.name) + " " + esc(pp.start)
          + "–" + esc(pp.end) + " · 在售 " + (cnt || "?") + " 件"
          + (has ? " · 最便宜一餐 ¥" + (pp.meal.p / 100).toFixed(2) : " · 这一档没有正餐")
          + '"><span class="n">' + esc(pp.name) + '</span>'
          + (has ? '<span class="p">¥' + (pp.meal.p / 100).toFixed(2) + "</span>"
                 : '<span class="p">无正餐</span>')
          + '<span class="h">' + esc(pp.start) + "</span></button>";      }
    }
    h += "</div></div>"
      + '<div class="dblegend"><span><i style="background:#D98324"></i>早餐</span>'
      + '<span><i style="background:#C2410C"></i>午餐</span>'
      + '<span><i style="background:#B0479E"></i>下午茶</span>'
      + '<span><i style="background:#3F5BA9"></i>夜市</span>'
      + '<span><i style="background:repeating-linear-gradient(45deg,#EFE6D8 0 3px,#E3D7C3 3px 6px)"></i>真空带</span>'
      + '<span class="dlg">段内数字：最便宜一餐 / 在售件数</span>'
      + "</div></div>";
    return h;
  }

  /* ---- 这一档的菜单, 和别的档比差在哪 ---- */
  function menuDiff(city, perName) {
    if (city.probe) return null;          // 探针城只采了 12 件, 比不出真相
    var mine = null, sets = [];
    for (var i = 0; i < city.periods.length; i++) {
      var q = city.periods[i], s = {};
      for (var k = 0; k < q.menu.length; k++) s[q.menu[k][0]] = 1;
      sets.push({ name: q.name, s: s });
      if (q.name === perName) mine = s;
    }
    if (!mine) return null;
    var only = [], miss = [], same = [];
    for (var idx in mine) {
      var inOther = false;
      for (var o = 0; o < sets.length; o++) {
        if (sets[o].name === perName) continue;
        if (sets[o].s[idx]) { inOther = true; break; }
      }
      if (!inOther) only.push(+idx);
    }
    for (var oi = 0; oi < sets.length; oi++) {
      if (sets[oi].name === perName) continue;
      for (var j in sets[oi].s) if (!mine[j]) miss.push(+j);
      // 逐件比对, 不拿件数当替身: 件数相同不代表菜单相同
      var identical = Object.keys(sets[oi].s).length === Object.keys(mine).length;
      if (identical) {
        for (var jj in sets[oi].s) if (!mine[jj]) { identical = false; break; }
      }
      if (identical) same.push(sets[oi].name);
    }
    var seen = {}, missU = [];
    for (var m = 0; m < miss.length; m++) if (!seen[miss[m]]) { seen[miss[m]] = 1; missU.push(miss[m]); }
    return { n: Object.keys(mine).length, only: only, miss: missU, same: same };
  }
  function bindDayBand() {
    var nodes = document.querySelectorAll("#ans .dbseg[data-t]");
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].onclick = function () {
        var t = this.getAttribute("data-t");
        if (!t) return;
        bestName = null;
        curTime = clampSlot(cur, t);
        fillTimes();
        render();
      };
    }
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
  function finish(out) {
    document.getElementById("ans").innerHTML = out.join("");
    bindDayBand();
    syncUrl();
  }
  function render() {
    var city = cur, t = curTime, out = [];
    out.push('<div class="card">');
    out.push('<p class="sub" style="margin-bottom:10px">' + esc(city.city)
      + (city.province ? " · " + esc(city.province) : "") + " · " + esc(city.store.name) + "</p>");

    // 全天时段带: 先给全貌, 再给这一档的细节
    out.push(dayBand(city, t));

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
      finish(out);
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

    // 这一档的菜单, 和别的档比差在哪 —— 价格轴是平的, 差异全在这儿
    var md = menuDiff(city, p.name);
    if (md) {
      out.push('<div class="mdiff">');
      out.push('<p class="big" style="margin-bottom:8px">这一档的菜单，和别档比差在哪</p>');
      if (md.only.length) {
        out.push('<p class="mdl">在售 <b>' + md.n + '</b> 件，其中 <b>' + md.only.length
          + '</b> 件<b>只在' + esc(p.name) + '档卖</b>：</p>');
        var shown = md.only.slice(0, 8).map(function (x) { return MN[x]; });
        out.push('<p class="mditems">' + shown.map(esc).join(" · ")
          + (md.only.length > 8 ? " …等 " + md.only.length + " 件" : "") + "</p>");
        if (md.miss.length) {
          out.push('<p class="mdl2">另有 <b>' + md.miss.length + '</b> 件在别的档有、'
            + '这一档买不到（下面完整菜单里也看不到它们）。</p>');
        }
      } else {
        // 后三档菜单完全相同 —— 这才是「官方切四档」的真相
        out.push('<p class="mdl">这一档在售 <b>' + md.n + '</b> 件，'
          + '<b>没有一件是这一档独有的</b>。'
          + (md.same.length ? '菜单和<b>' + md.same.map(esc).join("、") + '档</b>完全一样 —— '
             : "") + '官方把一天切成四档，但这几档卖的是同一套东西。</p>');
      }
      out.push("</div>");
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

    // 预算搭配器 —— 竞争对手的杀手锏是「怎么点最省」, 我们用 388 城真实数据回答
    out.push(budgetBox(cur.city, p.name));

    // 完整在售菜单: 可排序、可按主食/小食过滤、可点「当主食」喂给上面的搭配器
    out.push(menuTable(cur.city, p.name));

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
    finish(out);
    bindBudget(cur.city, p.name);
    bindMenuTable(cur.city, p.name);
  }

  var PC = {"早餐": "#E8A33D", "午餐": "#D9534F", "下午茶": "#5B8DEF", "夜市": "#6A5ACD"};
  function pcol(nm) { return PC[nm] || "#8b93a3"; }
  function pdot(nm) { return '<span class="pdot" style="background:' + pcol(nm) + '"></span>'; }

  /* ---- 预算搭配器: 「¥__ 能吃到最饱的」 ----
     数据就是页面里嵌的完整菜单(DATA.mn 名称表 + city.periods[i].menu),
     背包在前端现算 —— 全国只有 269 个商品名, 完整菜单嵌进来也只要 1.8MB,
     比「预计算搭配表」还小, 却换来三件事:
       1. 任意金额(不再受 ¥10~50 阶梯限制)
       2. 主动选主食: 点任一件当主食, 剩下的钱自动配最多小食
       3. 完整菜单浏览(见下方 menuTable)
     算法与 src/combo.py 完全一致: 有主食是硬约束, 约束内件数最多, 并列取更省。 */
  var MN = DATA.mn || [];
  var KIND_LABEL = ["小食", "主食", "配料"];
  var MAX_BUDGET_FEN = 10000;      // ¥100 封顶, 再高没有实际意义
  var BUDGET_PRESETS = [1000, 1500, 2000, 2500, 3000, 4000, 5000];

  /* 当前选中的「主食锚点」: {ni, pf} —— 名称下标 + 价格(分) */
  var anchor = null;

  function periodMenu(city, period) {
    for (var i = 0; i < city.periods.length; i++) {
      if (city.periods[i].name === period) return city.periods[i].menu || [];
    }
    return [];
  }

  /* 纯 0/1 背包(无锚点)。二维 DP ——
     一开始用「父指针回溯」(from[k]/took[k]), 是错的: dp[k-w] 可能在 dp[k]
     定稿之后才被改进, 回溯时会把同一件商品取三遍(实测 ¥80 北京早餐
     取出 3 个相同的 ¥10 主食)。Python 版存完整路径快照所以没错,
     这里用二维表 + 逐行回溯, 既正确又快。
     code = 有主食 ? 64+件数 : 件数; -1 = 不可达。比较 code 等价于
     比较 (有没有主食, 件数) 这个二元组。 */
  function knapInner(menu, limitFen) {
    var cands = [];
    for (var i = 0; i < menu.length; i++) {
      var m = menu[i];
      if (m[2] === 2) continue;                      // 配料不当饭
      if (m[1] < 500) continue;                      // ¥5 以下不当饭
      if (m[1] > limitFen) continue;
      cands.push(m);
    }
    if (!cands.length) return {total: 0, items: [], hasMeal: false};

    var n = cands.length, W = limitFen + 1;
    var dp = new Int8Array((n + 1) * W).fill(-1);
    dp[0] = 0;                                       // 前 0 件、容量 0
    for (var i2 = 0; i2 < n; i2++) {
      var w = cands[i2][1], im = cands[i2][2] === 1 ? 64 : 0;
      var rowOff = i2 * W, nextOff = (i2 + 1) * W;
      for (var k = 0; k <= limitFen; k++) {
        var best = dp[rowOff + k];                   // 不选第 i2 件
        if (k >= w) {
          var p = dp[rowOff + (k - w)];              // 选: 从前 i2 件、容量 k-w 转移
          if (p >= 0) {
            var cnt = p >= 64 ? p - 64 : p;
            // hasMeal 是布尔或, 不能相加: 64+64 会溢出 Int8(>127 回绕成负数,
            // 整条转移被当成不可达丢掉 —— 曾导致前端少算 2 件)
            var mealFlag = (p >= 64 || im) ? 64 : 0;
            var c = mealFlag + cnt + 1;
            if (c > best) best = c;                  // 严格大于: 并列时 prefer 不选
          }
        }
        dp[nextOff + k] = best;
      }
    }
    // 只认含主食的解 —— 硬门槛, 不是优先级; 件数相同取更便宜的总价
    var lastOff = n * W, bestK = -1, bestCode = -1;
    for (var k2 = 0; k2 <= limitFen; k2++) {
      var c2 = dp[lastOff + k2];
      if (c2 < 64) continue;
      if (c2 > bestCode) { bestCode = c2; bestK = k2; }
    }
    if (bestK < 0) return {total: 0, items: [], hasMeal: false};

    // 逐行回溯: dp[i][k] > dp[i-1][k] 才说明第 i-1 件被选了
    var items = [], kk = bestK;
    for (var i3 = n; i3 >= 1; i3--) {
      var cur = dp[i3 * W + kk], prev = dp[(i3 - 1) * W + kk];
      if (cur > prev) {
        items.push(cands[i3 - 1]);
        kk -= cands[i3 - 1][1];
      }
    }
    return {total: bestK, items: items, hasMeal: true};
  }

  /* 带锚点的搭配: 锚点是用户主动选的, **必选**。
     先预留它的价格, 剩余预算交给纯背包, 再拼回结果 ——
     若把锚点只是 unshift 进候选, 背包会挑更便宜的主食把它跳过,
     「我选它当主食」就落了空。 */
  function knap(menu, limitFen, anchorItem) {
    if (!anchorItem) return knapInner(menu, limitFen);
    // ¥5 门槛和配料排除, 和 knapInner 保持一致 —— 曾漏了 <500 检查,
    // 用户能锁定 ¥2 的联名饼干当"主食"
    if (anchorItem.k === 2 || anchorItem.pf < 500 || anchorItem.pf > limitFen) {
      return {total: 0, items: [], hasMeal: false};
    }
    // 只剔除**一份**锚点(同名同价): 实测全国有 511 条同名同价条目,
    // 全删会让用户锚定圆筒时另一份圆筒消失, 少算一件
    var rest = [], removed = false;
    for (var i = 0; i < menu.length; i++) {
      var m = menu[i];
      if (!removed && m[0] === anchorItem.ni && m[1] === anchorItem.pf) {
        removed = true;
        continue;
      }
      rest.push(m);
    }
    var sub = knapInner(rest, limitFen - anchorItem.pf);
    if (!sub.hasMeal && anchorItem.k !== 1) {
      return {total: 0, items: [], hasMeal: false};   // 锚点是小食, 凑不出主食
    }
    // 锚点也转成 [名称下标, 价格, 分类], 和菜单项同构 ——
    // 渲染端只认一种结构, 否则出现 undefined/¥NaN
    return {total: anchorItem.pf + sub.total,
            items: [[anchorItem.ni, anchorItem.pf, anchorItem.k]].concat(sub.items),
            hasMeal: true};
  }

  function comboHTML(cityName, period, budgetFen) {
    var city = findCity(cityName);
    if (!city) return '<p class="bnote">没有这座城市的菜单数据。</p>';
    var menu = periodMenu(city, period);
    if (!menu.length) return '<p class="bnote">这一档没有在售商品数据。</p>';

    var anchorItem = null;
    if (anchor && anchor.city === cityName && anchor.period === period) {
      if (anchor.pf < 500) {
        // ¥5 以下的单品不当一顿饭(和 knapInner 的门槛一致)。
        // 旧版本页面曾允许锁定 ¥2 饼干, 搭配里还渲染出 undefined/¥NaN
        anchor = null;
        return '<p class="bnote">¥5 以下的单品不当一顿饭，已取消这个主食选择。</p>';
      }
      anchorItem = {ni: anchor.ni, pf: anchor.pf, k: anchor.k};
    }
    var r = knap(menu, budgetFen, anchorItem);
    var s = "";

    if (anchorItem) {
      s += '<p class="banchor">已锁定主食：<b>' + esc(MN[anchorItem.ni]) + '</b> '
        + yuan(anchorItem.pf) + '<a href="javascript:void 0" id="bunlock">(换一件)</a></p>';
    }

    if (!r.hasMeal) {
      // 从菜单里找最便宜的主食, 告诉用户还差多少
      var cheap = null;
      for (var i = 0; i < menu.length; i++) {
        if (menu[i][2] === 1 && menu[i][1] >= 500) {
          if (!cheap || menu[i][1] < cheap[1]) cheap = menu[i];
        }
      }
      var gapTxt = cheap
        ? '最便宜的一餐是 ' + esc(MN[cheap[0]]) + ' ' + yuan(cheap[1])
          + '，还差 ' + yuan(cheap[1] - budgetFen)
        : '这一档没有正餐可卖';
      return s + '<p class="bgap">¥' + (budgetFen / 100).toFixed(2) + ' 在' + esc(period)
        + '档吃不到一顿正经饭 —— ' + gapTxt + '。</p>';
    }

    s += '<p class="bhead">¥' + (budgetFen / 100).toFixed(0) + ' 能吃到 <b>'
      + r.items.length + ' 件</b>，合计 ' + yuan(r.total) + '</p>';
    s += '<ul class="bcombo">';
    for (var j = 0; j < r.items.length; j++) {
      // 统一按数组 [名称下标, 价格, 分类] 取值 —— 曾把锚点做成
      // {ni,pf,k} 对象, 渲染时 it.ni 取不到, 整行变 undefined/¥NaN
      var it = r.items[j];
      s += '<li><span class="n"><span class="k ' + (it[2] === 1 ? "m" : "s") + '">'
        + KIND_LABEL[it[2]] + '</span>' + esc(MN[it[0]]) + '</span>'
        + '<span class="p">' + yuan(it[1]) + "</span></li>";
    }
    s += "</ul>";
    var left = budgetFen - r.total;
    s += '<p class="btot">一共 <b>' + yuan(r.total) + '</b>，还剩 ' + yuan(left)
      + (left > 0 ? "（再添点别的也行）" : "（刚好花完）") + "。</p>";

    // 和最便宜的单品正餐对比, 让"多花几块多几件"看得见
    var cheapestMeal = null;
    for (var i2 = 0; i2 < menu.length; i2++) {
      if (menu[i2][2] === 1 && menu[i2][1] >= 500 &&
          (!cheapestMeal || menu[i2][1] < cheapestMeal[1])) cheapestMeal = menu[i2];
    }
    if (cheapestMeal && r.items.length > 1) {
      s += '<p class="btot">单买最便宜的一餐只要 ' + esc(MN[cheapestMeal[0]]) + " "
        + yuan(cheapestMeal[1]) + "；多 " + yuan(r.total - cheapestMeal[1])
        + " 就能多吃 " + (r.items.length - 1) + " 件。</p>";
    }
    if (anchorItem && r.items.length === 1) {
      s += '<p class="bnote">剩下的钱不够再添一件（小食最低 ¥5）。</p>';
    }
    return s;
  }

  function budgetBox(cityName, period) {
    var chips = "";
    for (var i = 0; i < BUDGET_PRESETS.length; i++) {
      chips += '<button type="button" class="bchip" data-b="' + BUDGET_PRESETS[i]
        + '">¥' + (BUDGET_PRESETS[i] / 100) + "</button>";
    }
    return '<div class="budget" id="budgetBox">'
      + '<p class="bq">换个问法：我有 ¥__，这一档能吃到最饱的是什么？</p>'
      + '<div class="bchips" id="bchips">' + chips + "</div>"
      + '<div class="brow"><span class="blab">或自己填</span>'
      + '<input class="bin" id="bin" type="number" min="5" max="100" step="1"'
      + ' inputmode="numeric" placeholder="20" aria-label="预算, 单位元">'
      + '<button type="button" class="bgo" id="bgo">看看</button></div>'
      + '<p class="btip">想指定主食？到下方「这一档的全部在售」里点任一行的'
      + '<b>当主食</b>，剩下的钱会自动配最多小食。</p>'
      + '<div class="bout" id="bout"></div></div>';
  }

  var budgetCity = null, budgetPeriod = null;
  function bindBudget(cityName, period) {
    var box = document.getElementById("budgetBox");
    if (!box) return;
    var chips = box.querySelectorAll(".bchip"), inp = document.getElementById("bin"),
      out = document.getElementById("bout");
    budgetCity = cityName; budgetPeriod = period;

    // 「(换一件)」解锁链接: #bout 每次重写都会生成新节点,
    // 所以渲染完必须重新绑定 —— 曾在点过「当主食」后失效(点了没反应)
    function bindUnlock(fen) {
      var un = document.getElementById("bunlock");
      if (un) un.onclick = function () {
        anchor = null; show(fen); refreshMenuTable();
      };
    }

    function show(fen) {
      out.innerHTML = comboHTML(cityName, period, fen);
      inp.value = (fen / 100).toFixed(0);
      for (var i = 0; i < chips.length; i++) {
        chips[i].classList.toggle("on", +chips[i].getAttribute("data-b") === fen);
      }
      bindUnlock(fen);
    }
    for (var i = 0; i < chips.length; i++) {
      chips[i].onclick = (function (b) { return function () { show(b); }; })(
        +chips[i].getAttribute("data-b"));
    }
    function go() {
      var v = parseFloat(inp.value);
      if (!v || v <= 0) { out.innerHTML = '<p class="bnote">先填个金额。</p>'; return; }
      if (v * 100 > MAX_BUDGET_FEN) {
        out.innerHTML = '<p class="bnote">预算封顶 ¥100 —— 再高就不是"省钱"问题了。</p>';
        return;
      }
      show(Math.round(v * 100));
    }
    document.getElementById("bgo").onclick = go;
    inp.onkeydown = function (e) { if (e.key === "Enter") go(); };
    show(BUDGET_PRESETS[2]);            // 默认 ¥20, 打开就有答案
  }

  /* ---- 完整在售菜单表: 排序 + 过滤 + 「当主食」 ---- */
  var mtSort = "price", mtFilter = "all";      // price | name ; all | meal | side

  function menuRows(cityName, period) {
    var city = findCity(cityName);
    if (!city) return [];
    var menu = periodMenu(city, period).slice();
    if (mtFilter === "meal") menu = menu.filter(function (m) { return m[2] === 1; });
    // 「只要小食」就是小食: 酱包/配料(kind 2)不算, 混进来会误导
    else if (mtFilter === "side") menu = menu.filter(function (m) { return m[2] === 0; });
    if (mtSort === "price") menu.sort(function (a, b) { return a[1] - b[1]; });
    // 按中文习惯排(拼音序), 不是 UTF-16 码位序 —— 后者对用户是乱的
    else menu.sort(function (a, b) {
      return MN[a[0]].localeCompare(MN[b[0]], "zh");
    });
    return menu;
  }

  function menuTable(cityName, period) {
    var city = findCity(cityName), n = 0;
    if (city) n = periodMenu(city, period).length;
    if (!n) return "";
    var probeNote = (city && city.probe)
      ? '<p class="mtnote">这一城只采到 12 个采样商品（候选门店均不支持预约取餐），'
        + '菜单不完整，价格仅供参考。</p>' : "";
    return '<div class="mtwrap" id="mtwrap">'
      + '<div class="mthead"><p class="big" style="margin:0">这一档的全部在售'
      + '（' + n + ' 件，麦当劳订餐接口实价）</p>'
      + '<div class="mtctl">'
      + '<button type="button" class="mtbtn" data-f="all">全部</button>'
      + '<button type="button" class="mtbtn" data-f="meal">只要主食</button>'
      + '<button type="button" class="mtbtn" data-f="side">只要小食</button>'
      + '<button type="button" class="mtbtn mtsort" data-s="price">价格 ↑</button>'
      + '<button type="button" class="mtbtn mtsort" data-s="name">名称</button>'
      + "</div></div>" + probeNote
      + '<div class="mtscroll"><table class="mt"><thead><tr>'
      + '<th>商品</th><th>分类</th><th>价格</th><th></th>'
      // 单引号包裹, 别用 \" —— Python 普通字符串会把 \" 吃成 ",
      // JS 字符串当场截断, 整个页面脚本语法错误(菜单表曾因此全站挂掉)
      + '</tr></thead><tbody id="mtbody"></tbody></table></div></div>';
  }

  function refreshMenuTable() {
    var body = document.getElementById("mtbody");
    if (!body || !budgetCity) return;
    var rows = menuRows(budgetCity, budgetPeriod), s = "";
    for (var i = 0; i < rows.length; i++) {
      var m = rows[i];
      var isAnchor = anchor && anchor.city === budgetCity
        && anchor.period === budgetPeriod && anchor.ni === m[0] && anchor.pf === m[1];
      s += '<tr class="' + (isAnchor ? "on" : "") + '">'
        + '<td class="n">' + esc(MN[m[0]]) + "</td>"
        + '<td><span class="k ' + (m[2] === 1 ? "m" : (m[2] === 2 ? "x" : "s")) + '">'
        + KIND_LABEL[m[2]] + "</span></td>"
        + '<td class="p">' + yuan(m[1]) + "</td>"
        // ¥5 以下的单品不当一顿饭, 不让选成主食(和背包的门槛一致)
        + '<td class="a"><button type="button" class="mtpick" data-ni="' + m[0]
        + '" data-pf="' + m[1] + '" data-k="' + m[2] + '"'
        + (m[1] < 500 ? ' disabled title="¥5 以下的单品不当一顿饭"' : "")
        + ">" + (isAnchor ? "已选" : "当主食") + "</button></td></tr>";
    }
    body.innerHTML = s;
    var btns = body.querySelectorAll(".mtpick");
    for (var j = 0; j < btns.length; j++) {
      btns[j].onclick = (function (b) {
        return function () {
          var ni = +b.getAttribute("data-ni"), pf = +b.getAttribute("data-pf"),
            k = +b.getAttribute("data-k");
          if (anchor && anchor.ni === ni && anchor.pf === pf) {
            anchor = null;                      // 再点一次取消
          } else {
            anchor = {city: budgetCity, period: budgetPeriod, ni: ni, pf: pf, k: k};
          }
          // 搭配器与菜单表联动刷新
          var out = document.getElementById("bout");
          var inp = document.getElementById("bin");
          var fen = 2000;
          if (inp && inp.value) fen = Math.round(parseFloat(inp.value) * 100);
          if (!fen || fen <= 0) fen = 2000;
          if (out) {
            out.innerHTML = comboHTML(budgetCity, budgetPeriod, fen);
            // #bout 被重写, 「(换一件)」是新节点, 要重新绑定
            var un2 = document.getElementById("bunlock");
            if (un2) un2.onclick = function () {
              anchor = null;
              out.innerHTML = comboHTML(budgetCity, budgetPeriod, fen);
              refreshMenuTable();
            };
          }
          refreshMenuTable();
        };
      })(btns[j]);
    }
    // 控件高亮
    var fbs = document.querySelectorAll("#mtwrap .mtbtn[data-f]");
    for (var q = 0; q < fbs.length; q++) {
      fbs[q].classList.toggle("on", fbs[q].getAttribute("data-f") === mtFilter);
    }
    var sbs = document.querySelectorAll("#mtwrap .mtbtn[data-s]");
    for (var r = 0; r < sbs.length; r++) {
      sbs[r].classList.toggle("on", sbs[r].getAttribute("data-s") === mtSort);
    }
  }

  function bindMenuTable(cityName, period) {
    var wrap = document.getElementById("mtwrap");
    if (!wrap) return;
    refreshMenuTable();
    var fbs = wrap.querySelectorAll(".mtbtn[data-f]");
    for (var i = 0; i < fbs.length; i++) {
      fbs[i].onclick = (function (b) {
        return function () { mtFilter = b.getAttribute("data-f"); refreshMenuTable(); };
      })(fbs[i]);
    }
    var sbs = wrap.querySelectorAll(".mtbtn[data-s]");
    for (var j = 0; j < sbs.length; j++) {
      sbs[j].onclick = (function (b) {
        return function () { mtSort = b.getAttribute("data-s"); refreshMenuTable(); };
      })(sbs[j]);
    }
  }

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


KIND_CODE = {"side": 0, "meal": 1, "extra": 2}

# 全国商品名表 —— 实测全国只有 269 个唯一商品名,
# 所以完整菜单(14.4 万个「城×档×商品」三元组)用名称下标编码只要 1.8MB,
# 比"只嵌 top5 + 预计算搭配"的方案还小, 却换来完整菜单浏览 + 主动选主餐。
MENU_NAMES: list[str] = []
MENU_NAME_IDX: dict[str, int] = {}


def menu_name(nm: str) -> int:
    if nm not in MENU_NAME_IDX:
        MENU_NAME_IDX[nm] = len(MENU_NAMES)
        MENU_NAMES.append(nm)
    return MENU_NAME_IDX[nm]


def build_city(c: dict) -> dict:
    """原始采集结果 -> 页面需要的精简结构(控制体积)。"""
    periods = []
    basket = {i["code"]: i for i in (c.get("basket") or [])}
    pu = c.get("prices", {}).get("pickup") or {}
    for p in c.get("periods") or []:
        f = (c.get("floors", {}).get("pickup") or {}).get(p["name"]) or {}
        meal, any_ = f.get("meal"), f.get("any")
        # 完整在售菜单: [名称下标, 价格(分), 分类码], 按价格升序
        menu: list[list[int]] = []
        for code, it in basket.items():
            price = (pu.get(code) or {}).get(p["name"])
            if not isinstance(price, int):
                continue
            menu.append([menu_name(it.get("name") or code), price,
                         KIND_CODE.get(it.get("kind"), 0)])
        menu.sort(key=lambda x: x[1])
        periods.append({
            "name": p["name"], "start": p["start"], "end": p["end"],
            "meal": {"n": meal["name"], "p": meal["price"]} if meal else None,
            "any": {"n": any_["name"], "p": any_["price"]} if any_ else None,
            "menu": menu,
        })
    # 得来速更便宜的(同商品同档对比)
    dt_cheaper: list[dict] = []
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
        # 探针城只有 12 个采样商品, 菜单不完整 —— 页面要如实说
        "probe": not c.get("fullMenu", False),
    }


def rank_block(title: str, rows: list[tuple[str, str]], note: str = "") -> str:
    items = "".join(f'<p class="rank">{i}. <b>{escape(a)}</b> —— {escape(b)}</p>'
                    for i, (a, b) in enumerate(rows, 1))
    return f"<h3>{escape(title)}</h3>{items}" + (
        f'<p class="sub">{escape(note)}</p>' if note else "")


def national_overview(cities: list[dict], hf: dict | None = None) -> str:
    """全国对比: 开档时间 / 各档地板价 / 早餐溢价 / 菜单断层 —— 全是实测出来的地域差异。"""
    out = []
    # 最重要的全国结论放最前面: 价格轴是平的, 断层全在菜单构成上
    if hf and hf.get("full_n"):
        out.append(
            '<p class="big">价格轴是平的，断层在菜单</p>'
            f'<p class="sub">{hf["full_n"]} 座有完整四档的城市里，'
            f'<b>午餐和夜市的菜单 {hf["lunch_eq_night"]} 座完全相同</b>，'
            f'下午茶平均只多 {hf["tea_extra"]:g} 件学生专享；只有早餐是另一套菜单 —— '
            f'便宜 ¥{(hf["lf_med"] - hf["bf_med"]) / 100:.2f}，但少 {hf["bf_missing"]} 件，'
            f'换来 {hf["bf_only"]} 件只属于早晨的麦满分。'
            f'所以「几点最便宜」的答案永远是早上，这句话没有信息量；'
            f'真正该问的是「我这个点到店，有什么可吃」。</p>')
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


def all_cities_block(cities: list[dict], href_prefix: str = "") -> str:
    """按大区分组的完整城市列表(找不到自己城市时的兜底入口)。

    href_prefix 非空时(三页版), chips 是深链 —— 点下去直接带着
    ?city= 跳到问答页; 为空时(单文件版)是 span, 由页内 __pickCity 接管。
    """
    groups: dict[str, list[str]] = {}
    for c in cities:
        groups.setdefault(c.get("region") or "其他", []).append(c["city"])
    out = []
    for region in ["华北", "东北", "华东", "华中", "华南", "西南", "西北", "其他"]:
        if region not in groups:
            continue
        if href_prefix:
            chips = "".join(
                f'<a class="chip" href="{href_prefix}?city={quote(x)}">{escape(x)}</a>'
                for x in groups[region])
        else:
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

    def menu_of(c: dict, per: str) -> set:
        """这一档在售的商品名集合。"""
        basket = {i["code"]: i for i in (c.get("basket") or [])}
        pu = (c.get("prices") or {}).get("pickup") or {}
        out = set()
        for code, it in basket.items():
            if isinstance((pu.get(code) or {}).get(per), int):
                out.add(it.get("name") or code)
        return out

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

    # 菜单断层: 官方切四档, 但后三档的菜单是不是同一套?
    # 这是比「早餐更便宜」强得多的发现 —— 价格轴几乎是平的,
    # 真正的时段差异全在「这个点有什么可吃」上。
    full = [c for c in cities_raw
            if len([p for p in (c.get("periods") or []) if p.get("name")]) >= 4]
    lunch_eq_night = 0
    tea_extra = []
    bf_missing = []
    bf_only = []
    for c in full:
        m = {p["name"]: menu_of(c, p["name"]) for p in c["periods"]}
        if not (m.get("午餐") and m.get("夜市") and m.get("早餐")):
            continue
        if m["午餐"] == m["夜市"]:
            lunch_eq_night += 1
        if m.get("下午茶"):
            tea_extra.append(len(m["下午茶"] - m["午餐"]))
        bf_missing.append(len(m["午餐"] - m["早餐"]))
        bf_only.append(len(m["早餐"] - (m["午餐"] | m.get("下午茶", set())
                                        | m["夜市"])))
    n_full = max(1, len(bf_missing))

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0

    return {
        "gap": gap, "gap_city": gap_city, "gap_bf": gap_bf, "gap_lf": gap_lf,
        "bf_med": med(bf_all), "lf_med": med(lf_all),
        "bf_n": len(bf_all), "lf_n": len(lf_all),
        "cheaper_n": cheaper,
        # —— 菜单断层(新首屏主叙事) ——
        "full_n": len(bf_missing),
        "lunch_eq_night": lunch_eq_night,
        "tea_extra": round(avg(tea_extra), 1),
        "bf_missing": round(avg(bf_missing)),
        "bf_only": round(avg(bf_only)),
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

    # 完整菜单直接嵌页面(全国 269 个唯一商品名, 名称下标编码 1.8MB),
    # 不再用「预算阶梯预计算」——那样反而要多 0.5MB, 还限制了自由金额与选主食。
    payload = json.dumps({
        "cities": data,
        "hot": [c for c in HOT_CITIES if any(x["city"] == c for x in data)],
        "targetDate": surface.get("targetDate", ""),
        "mn": MENU_NAMES,
    }, ensure_ascii=False, separators=(",", ":"))

    n_cities = len(cities_raw)
    n_calls = sum(c.get("calls", 0) for c in cities_raw)
    gen = escape(str(surface.get("generatedAt", datetime.now().isoformat(timespec="seconds"))))
    target = escape(str(surface.get("targetDate", "")))
    hf = hero_facts(cities_raw)
    overview = national_overview(cities_raw, hf)

    # JS 失效时的静态兜底答案
    fb = data[0]
    fb_p = next((p for p in fb["periods"] if p["meal"]), fb["periods"][0] if fb["periods"] else None)
    fallback = ""
    if fb_p and fb_p.get("meal"):
        rows = "".join(f'<li><span class="n">'
                       f'{escape(MENU_NAMES[r[0]])}</span>'
                       f'<span class="p">¥{r[1] / 100:.2f}</span></li>'
                       for r in fb_p["menu"][:6])
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

    # —— 可组合区块: 三页版与单文件版共用同一批片段, 保证两边不漂移 ——
    def hero(hook: str, h1: str, hsub: str, stats: list[str]) -> str:
        st = "".join(f'<span class="hs">{s}</span>' for s in stats)
        return (f'<header class="hero"><p class="hook">{hook}</p><h1>{h1}</h1>'
                f'<p class="hsub">{hsub}</p>'
                f'<div class="hero-stats">{st}</div></header>')

    def nav(active: str, single: bool = False) -> str:
        """三页版导航; single=True(单文件离线版)时换成页内锚点。"""
        def href(k: str) -> str:
            if single:
                return {"answer": "#sec-answer", "rank": "#sec-rank",
                        "how": "#sec-how"}[k]
            return {"answer": "index.html", "rank": "rank.html",
                    "how": "how.html"}[k]
        links = "".join(
            f'<a href="{href(k)}"' + (' class="on"' if k == active else "")
            + f">{t}</a>"
            for k, t in [("answer", "问答"), ("rank", "全国榜单"),
                         ("how", "方法与合规")])
        dl = ("" if single else
              '<a class="dl" href="report.html" download>离线单文件版 ↓</a>')
        return (f'<nav class="nav"><span class="brand">🍔 麦当劳几点最便宜</span>'
                f"{links}{dl}</nav>")

    def shell(title: str, nav_html: str, body: str,
              data_tag: str, scripts: str = "") -> str:
        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{CSS}</style></head><body>
<div class="wrap">
{nav_html}
{body}
{foot}
</div>
{data_tag}
{scripts}
</body></html>"""

    foot = (f"<footer>生成时间 {gen} · 数据日期 {target} · 覆盖 {n_cities} 座城市 · "
            f"共 {n_calls} 次问价 · 取餐方式：到店自提（部分城市含得来速）<br>"
            f"样本为该城市门店中的一家，同城市不同门店的营业时间可能有差异。"
            f"本项目为 2026 麦当劳程序员创意开发大赛参赛作品，非麦当劳官方产品。"
            f"价格随门店与日期变动，下单前请以麦当劳 App 实际显示为准。</footer>")

    hero_answer = hero(
        f"官方把一天切成四档，但后三档卖的东西一模一样",
        "麦当劳几点最便宜",
        f"全国 {hf['full_n']} 座有完整四档的城市里，<b>午餐和夜市的菜单 "
        f"{hf['lunch_eq_night']} 座完全相同</b>，下午茶平均只多 "
        f"{hf['tea_extra']:g} 件；只有早餐是另一套菜单 —— 便宜 "
        f"¥{(hf['lf_med'] - hf['bf_med']) / 100:.2f}，但少 {hf['bf_missing']} 件，"
        f"换来 {hf['bf_only']} 件只属于早晨的麦满分。<br>"
        f"所以真正该问的不是「几点最便宜」（答案永远是早上），而是"
        f"<b>「我这个点到店，有什么可吃」</b>。选<b>城市</b>、选<b>几点去</b>，"
        f"直接告诉你那一刻的完整在售菜单、多少钱、能凑出几件。<br>"
        f"<span class=\"hsub2\">页面上的价格是 {target} 的实价快照（日内实测恒定）；"
        f"想查此刻的实时价格，一条命令自己采 —— 见<a href=\"how.html\">方法与合规页</a>。</span>",
        [f"<b>{n_cities}</b>座城市", f"<b>{n_calls}</b>次真实问价",
         f"数据日期 <b>{target}</b>", "不用注册 · 手机直接看"])

    q_widget = """<div class="q">
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
    <p class="qhint">没找到你的城市？去<a href="rank.html">全国榜单</a>页翻城市名单。</p>
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
</div>"""

    method_body = f"""
<div class="card">
<p class="big" style="margin-top:0">价格不是估的</p>
<p>程序对每座城市的样本门店，按<b>官方时段</b>（早餐/午餐/下午茶/夜市）
逐个向麦当劳订餐系统问价，相当于在 App 里选好商品、选好取餐时间后看到的实付金额，
问回来的数字原样记下。这一版一共问价 <b>{n_calls}</b> 次，覆盖 <b>{n_cities}</b> 座城市。</p>
<p class="big">为什么按档问价就够</p>
<p>先做了一次实测：同一商品在一天之内价格恒定，变化的是「这个时段卖不卖」。
所以按档问价即可覆盖全天，不必逐分钟地毯式轰炸。</p>
<p>全国跑完又拿到第二条规律，而且它比第一条更值得说：
在 {hf['full_n']} 座有完整四档的城市里，<b>午餐和夜市的菜单 {hf['lunch_eq_night']} 座完全相同</b>，
下午茶平均只多 {hf['tea_extra']:g} 件学生专享。真正只属于某一个时段的，是早餐 ——
它平均少 {hf['bf_missing']} 件，却另有 {hf['bf_only']} 件是别的档买不到的（清一色麦满分、脆薯饼、脆油条）。
换句话说，官方切了四档，但<b>价格轴几乎是平的</b>（四档最便宜的单品都是 ¥5 圆筒），
断层全在菜单构成上 —— 这也正是页面上要告诉你「这个点有什么可吃」，而不是只报一个最低价的原因。</p>
<p class="big">时段边界不是我们划的</p>
<p>早餐/午餐/下午茶/夜市各自的起止时刻取自门店返回的排期。不同城市开门时间不同，
开档时刻能差 4 个小时。</p>
<p class="big">「¥__ 能吃到最饱的」是怎么算的</p>
<p>0/1 背包在完整在售菜单上现算：<b>有主食是硬门槛</b>，不是优先级 ——
预算装不下主食时，宁可告诉你「吃不到一顿正经饭，最便宜的一餐 ¥13.90，还差 ¥3.90」，
也不拿两个冰淇淋凑数。你也可以点菜单里任一行的「当主食」，你选的那件必选进搭配。</p>
<p>同一个算法只有一份实现（<code>src/combo.py</code>）：网页端算的和 MCP 客户端问回来的
逐分一致，<code>src/parity_combo.py</code> 把页面里的 JS 抠出来逐分对拍（207 个用例零不一致）。</p>
<p class="big">整条链路是只读的</p>
<p>只问价，不下单、不领券、不碰支付环节；不采集任何个人凭证，
Token 只走环境变量。外送价依赖个人收货地址，属于用户私有配置，本项目不采集。</p>
<p class="big">同样的能力，两种入口</p>
<p>网页（零门槛，双击即开）+ 本地 MCP Server（5 个工具，零 Token，
AI 客户端用自然语言问）。实时个性查询（「我这店此刻买得到什么」）需要你自己的 Token，
脚本都在仓库里。</p>
<p class="big">为什么网页是快照，不是实时</p>
<p>采集这件事，我们最后交给了用户自己 —— 三个原因，每个都实测过：</p>
<p><b>一、量级不允许。</b>实时回答「此刻最便宜」，每次查询都要把这座城的全菜单重问一遍
（<code>now.py</code> 实测约 60 次调用）；官方限流 600 次/分钟/Token，
而这一版全国普查一共问价 {n_calls} 次 —— 按上限满速也要 60 分钟不间断，
还没算每次调用的网络往返。把这件事塞进每次页面打开：跑不动，也跑不起。</p>
<p><b>二、浏览器进不了官方系统的门。</b>订餐接口不接受网页直连：
带 Origin 的预检请求返回 403、响应里没有任何跨域许可头，WAF 直接把浏览器挡在门外。
把个人 Token 塞进前端页面既不安全，也不是这个赛题鼓励的用法。</p>
<p><b>三、快照在「今天」这个粒度上依然成立。</b>实测同一商品一天之内价格恒定，
变的只是「这个时段卖不卖」；而菜单结构（哪一档卖哪些东西）同样是按天稳定的。
所以快照 + 时段结构，回答「今天几点去、能吃到什么」没有失真。
失真的是<b>日期</b>：页面上的价格是 {target} 问回来的，过几天再看，答案是那天的。
真要查此刻，往下看一条命令。</p>
<p class="big">想查此刻的实时价格？一条命令</p>
<p>用自己的 Token 在本地跑，十几秒出结果，只读、不下单：</p>
<pre style="white-space:pre-wrap">export MCD_MCP_TOKEN=你的token
python src/now.py --city 上海        # 我这店此刻买得到什么、几块钱、下一档什么时候变</pre>
<p>它会自动校时 → 找你附近门店 → 按<b>当前时段</b>问价并现算背包 → 再对比下一时段，
全程只读。用法与字段含义见 <code>README.md</code> 与 <code>MCP_INTEGRATION.md</code>。
网页负责「全天规律」，这条命令负责「我现在该怎么办」。</p>
<p class="big">怎么复现</p>
<pre style="white-space:pre-wrap">git clone https://github.com/crimsonKernel/mcd-when.git
cd mcd-when
python src/render_report.py        # 用仓库里的快照渲染页面
python src/parity_combo.py         # JS 背包 vs Python 背包对拍
python src/check_combo.py          # 无头浏览器走 12 条交互路径
python -m unittest discover tests   # 41 项冒烟测试</pre>
<p class="big">合规声明</p>
<p>本项目为 2026 麦当劳程序员创意开发大赛参赛作品，<b>非麦当劳官方产品</b>，
与麦当劳官方无隶属、背书或赞助关系；「麦当劳 / McDonald's」是各自持有人的商标。
不含也不再分发任何麦当劳的 Logo、图片或商业素材。
价格随门店与日期变动，下单前请以麦当劳 App 实际显示为准。</p>
<p class="sub">技术实现与复现方式见仓库 <code>MCP_INTEGRATION.md</code>；
参赛声明见 <code>CONTEST_DECLARATION.md</code>。</p>
</div>"""

    # ① 问答页(Pages 根路径)
    index_html = shell(
        f"麦当劳几点最便宜 · 全国 {n_cities} 城，选城市和时刻直接给答案",
        nav("answer"),
        hero_answer + f'<div id="sec-answer">{q_widget}</div>'
        + f'<div id="ans">{fallback}</div>',
        '<script src="mcd-data.js"></script>',
        f"<script>{JS}</script>")

    # ② 全国榜单页(纯静态, 零 JS)
    rank_hero = hero(
        f"全国 {n_cities} 座城市、{n_calls} 次真实问价",
        "全国榜单",
        f"哪座城市早餐开得最早、哪座城市午餐最便宜、哪座城市吃早餐比午餐省得最多，"
        f"以及全国一致的菜单断层（午餐和夜市卖的是同一套东西）—— "
        f"全部是 {target} 这一天从麦当劳订餐系统问回来的实价，没有一个字是估的。"
        f"点城市名，直接带着它去<a href=\"index.html\">问答页</a>查时刻。",
        [f"<b>{n_cities}</b>座城市", f"<b>{n_calls}</b>次真实问价",
         "按官方时段核价", "点城市名直接去查"])
    rank_html = shell(
        f"全国榜单 · 麦当劳几点最便宜（{n_cities} 城实测）",
        nav("rank"),
        rank_hero
        + f'<div class="card"><p class="big" style="margin-top:0">全国对比</p>'
          f"{overview}</div>"
        + f'<div class="card"><p class="big" style="margin-top:0">'
          f"全国 {n_cities} 座城市名单</p>"
          f"{all_cities_block(cities_raw, href_prefix='index.html')}</div>",
        "", "")

    # ③ 方法与合规页(纯静态, 零 JS)
    how_hero = hero(
        "每一个数字都能复现",
        "这些数字是怎么来的",
        f"价格不是估的，是 {n_calls} 次真实问价问回来的；算法只有一份实现，"
        f"网页和 MCP 两个入口逐分一致。这一页把方法、边界和合规都说清楚。",
        [f"<b>{n_calls}</b>次真实问价", "链路只读",
         "网页 / MCP 双入口", "参赛作品 · 非官方"])
    how_html = shell(
        "方法与合规 · 麦当劳几点最便宜",
        nav("how"),
        how_hero + method_body, "", "")

    # ④ 单文件离线版(双击即开, 一切内嵌 —— 保持这个卖点不变)
    single_html = shell(
        f"麦当劳几点最便宜 · 全国 {n_cities} 城，选城市和时刻直接给答案",
        nav("answer", single=True),
        hero_answer + f'<div id="sec-answer">{q_widget}</div>'
        + f'<div id="ans">{fallback}</div>'
        + '<details id="sec-rank"><summary>看看全国：哪里早餐开得早、哪里午餐最便宜</summary>'
          f'<div class="dbody">{overview}</div></details>'
        + f'<details><summary>全国 {n_cities} 座城市名单</summary>'
          f'<div class="dbody">{all_cities_block(cities_raw)}</div></details>'
        + '<details id="sec-how"><summary>这些数字是怎么来的？</summary>'
          f'<div class="dbody">{method_body}</div></details>',
        f"<script>window.__MCD_DATA__ = {payload};</script>",
        f"<script>{JS}</script>" + CHIPS_SCRIPT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "mcd-data.js").write_text(
        "window.__MCD_DATA__ = " + payload + ";\n", encoding="utf-8")
    outputs = {"index.html": index_html, "rank.html": rank_html,
               "how.html": how_html, "report.html": single_html}
    for name, content in outputs.items():
        (OUT_DIR / name).write_text(content, encoding="utf-8")
    for name in outputs:
        p = OUT_DIR / name
        print(f"已生成 {p.name} ({p.stat().st_size // 1024} KB)")
    print(f"已生成 mcd-data.js ({(OUT_DIR / 'mcd-data.js').stat().st_size // 1024} KB)"
          f" · {n_cities} 城 · 三页版 + 单文件离线版")

    # 一次查完: 四个页面 + 外链数据(三页版靠 mcd-data.js 供数)
    return check_inline_js(*[OUT_DIR / n for n in outputs],
                           OUT_DIR / "mcd-data.js")


NODE = "C:/Users/xueyihan/.workbuddy/binaries/node/versions/22.22.2-6/node.exe"

# 产物自检: 页面里任何一段内联脚本语法错误, 整站就白屏 —— 而且
# 从 HTML 源码肉眼看不出来(Python 字符串把 \" 吃成 " 就会这样)。
# 外链的 mcd-data.js 也要查(三页版靠它供数, 坏了页面同样全废)。
# 所以渲染完必须用 node 逐块 new Function 校验, 有问题就让构建失败。
JS_CHECK = r"""
const fs = require('fs');
function check(file, label) {
  const src = fs.readFileSync(file, 'utf8');
  const blocks = label === 'js'
    ? [src]
    : [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  let bad = 0;
  blocks.forEach((s, i) => {
    try { new Function(s); }
    catch (e) { bad++; console.log(label + ' 脚本块 ' + i + ' 语法错误: ' + e.message); }
  });
  return bad;
}
let bad = 0;
for (let i = 2; i < process.argv.length; i++) {
  const f = process.argv[i];
  const label = f.endsWith('.js') ? 'js' : 'html';
  const n = check(f, label);
  if (n) { console.log('自检失败: ' + f); bad += n; }
}
process.exit(bad ? 1 : 0);
"""


def check_inline_js(*paths: Path) -> int:
    import subprocess
    import tempfile

    if not Path(NODE).exists():
        print("警告: 找不到 node, 跳过内联脚本语法自检")
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(JS_CHECK)
        probe = f.name
    try:
        r = subprocess.run([NODE, probe, *[str(p) for p in paths]],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stdout.strip())
            print("自检失败: 页面脚本有语法错误, 这次渲染不可用")
            return 1
        print(f"脚本语法自检通过({len(paths)} 个文件)")
        return 0
    except subprocess.TimeoutExpired:
        print("警告: 语法自检超时, 跳过")
        return 0
    finally:
        Path(probe).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
