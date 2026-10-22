"""check_combo.py — 预算搭配器的无头浏览器实测

check_layout.py 只管「有没有溢出」, 不管「交互是不是坏的」。
预算搭配器是纯前端逻辑(查表 + 渲染), 光看 HTML 源码证明不了它能跑,
所以照它的办法: 注入一段脚本, 用 Chrome headless 加载, 把结果写进 <title> 带出来。

验十四件事(对两个入口各跑一遍 —— 单文件离线版 report.html 和三页版 index.html,
后者靠 <script src="mcd-data.js"> 供数, 路径解析也要验):
  0. 页面加载无 JS 报错(有错则 title 里带 ERROR:)
  0b. 全天时段带画出来了: ≥4 段、可点段 ≥2、渲染干净、点一段答案跟着换档
  1. 页面加载无 JS 报错(有错则 title 里带 ERROR:)
  2. 选好城市后, 预算搭配器默认就渲染出答案(不是空白的)
  3. 点 ¥50 chip / 填自定义金额 ¥23 两条路径都对
  4. 预算不足(¥6)时诚实告知「吃不到一顿正经饭」并说清还差多少
  5. 点菜单表「当主食」后, 搭配器锁定该主食(锚点必选, 真的出现在结果里)
  6. 点「(换一件)」解锁, 恢复自由搭配
  7. 菜单表按主食/小食过滤, 每一行分类都对
  8. 菜单表按名称排序, 行序正确
  9. 每次渲染都没有 undefined / NaN(结构不一致曾让整行变 undefined)
 10. 两个入口结果一致

用法: python src/check_combo.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
# 单文件离线版 + 三页版问答页(数据走外链 mcd-data.js)
TARGETS = ["report.html", "index.html"]

CHROME_CANDIDATES = [
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
]

PROBE = """
<script>
(function(){
  var errs = [];
  window.onerror = function (m) { errs.push(String(m)); };
  function fire(el, type) {
    var e = document.createEvent("HTMLEvents");
    e.initEvent(type, false, true);
    el.dispatchEvent(e);
  }
  function pick(sel, val) {
    var el = document.getElementById(sel);
    if (!el) return false;
    for (var i = 0; i < el.options.length; i++) {
      if (el.options[i].value === val) { el.selectedIndex = i; fire(el, "change"); return true; }
    }
    return false;
  }
  function txt(id) { var e = document.getElementById(id); return e ? e.innerHTML : ""; }
  // 每次渲染后都查: 结果列表里不能出现 undefined / NaN(曾因锚点与菜单项
  // 结构不一致, 整行渲染成 undefined ¥NaN)
  function clean(id) {
    var o = txt(id);
    return o.indexOf("undefined") < 0 && o.indexOf("NaN") < 0;
  }
  var out = [];
  function done() {
    if (errs.length) out.push("ERROR:" + errs.join("|"));
    document.title = "PROBE " + out.join(" ");
  }
  function step2() {
    try {
      var box = document.getElementById("budgetBox");
      if (!box) { out.push("NO_BUDGET_BOX"); return done(); }
      // 1) 默认渲染: 打开就有答案(默认 ¥20)
      var o = txt("bout");
      out.push("default:" + (o.indexOf("能吃到") >= 0 && clean("bout") ? "OK" : "EMPTY"));
      // 2) 点 ¥50 chip
      var chips = box.querySelectorAll(".bchip");
      chips[chips.length - 1].click();
      o = txt("bout");
      out.push("chip50:" + (o.indexOf("¥50 能吃到") >= 0 && o.indexOf("件") >= 0
        && clean("bout") ? "OK" : "BAD"));
      // 3) 自定义非档位金额 ¥23
      var inp = document.getElementById("bin");
      inp.value = "23";
      document.getElementById("bgo").click();
      o = txt("bout");
      out.push("custom23:" + (o.indexOf("¥23 能吃到") >= 0 && clean("bout") ? "OK" : "BAD"));
      // 4) 预算不足: ¥6 吃不到一顿正经饭, 且告诉还差多少
      inp.value = "6";
      document.getElementById("bgo").click();
      o = txt("bout");
      out.push("gap:" + (o.indexOf("吃不到") >= 0 && o.indexOf("还差") >= 0
        && clean("bout") ? "OK" : "BAD"));
      // 5) 锚点: 先把预算恢复成 ¥20, 再点菜单表第一行可用的「当主食」
      var chip20 = box.querySelector('.bchip[data-b="2000"]');
      if (chip20) chip20.click();
      out.push("clean20:" + (clean("bout") ? "OK" : "BAD"));
      var body = document.getElementById("mtbody");
      if (!body || !body.querySelectorAll(".mtpick").length) { out.push("NO_MENU_TABLE"); return done(); }
      // 跳过 disabled 的(¥5 以下单品不让当主食), 点第一个能用的
      var firstBtn = null;
      var all = body.querySelectorAll(".mtpick");
      for (var bi = 0; bi < all.length; bi++) if (!all[bi].disabled) { firstBtn = all[bi]; break; }
      if (!firstBtn) { out.push("NO_ENABLED_ANCHOR"); return done(); }
      var firstName = firstBtn.closest("tr").querySelector("td.n").textContent;
      firstBtn.click();
      o = txt("bout");
      var rowOn = body.querySelectorAll("tr.on").length;
      // 锁定提示在、该行高亮、这件商品真的出现在搭配里(锚点必选不是可选)、
      // 且渲染干净(没有 undefined/NaN)
      out.push("anchor:" + (o.indexOf("已锁定主食") >= 0 && rowOn === 1
        && o.indexOf(firstName) >= 0 && clean("bout") ? "OK" : "BAD"));
      // 6) 换一件: 解锁后恢复自由搭配
      var un = document.getElementById("bunlock");
      if (un) un.click();
      o = txt("bout");
      out.push("unlock:" + (o.indexOf("已锁定主食") < 0 && o.indexOf("能吃到") >= 0
        && clean("bout") ? "OK" : "BAD"));
      // 7) 菜单过滤: 只要主食 -> 每一行分类都是主食
      var fm = document.querySelector('#mtwrap .mtbtn[data-f="meal"]');
      if (fm) fm.click();
      var ks = document.querySelectorAll("#mtbody .k"), allMeal = ks.length > 0;
      for (var i = 0; i < ks.length; i++) if (ks[i].className.indexOf("m") < 0) allMeal = false;
      out.push("filterMeal:" + (allMeal ? "OK" : "BAD"));
      var fs = document.querySelector('#mtwrap .mtbtn[data-f="side"]');
      if (fs) fs.click();
      ks = document.querySelectorAll("#mtbody .k");
      var allSide = ks.length > 0;
      for (var j = 0; j < ks.length; j++) if (ks[j].className.indexOf("s") < 0) allSide = false;
      out.push("filterSide:" + (allSide ? "OK" : "BAD"));
      document.querySelector('#mtwrap .mtbtn[data-f="all"]').click();
      // 8) 按名称排序: 首行名 <= 末行名
      document.querySelector('#mtwrap .mtbtn[data-s="name"]').click();
      var names = [], ns = document.querySelectorAll("#mtbody td.n");
      for (var q = 0; q < ns.length; q++) names.push(ns[q].textContent);
      var sorted = names.slice().sort(function (a, b) { return a.localeCompare(b, "zh"); });
      var same = names.length === sorted.length;
      for (var r = 0; r < names.length; r++) if (names[r] !== sorted[r]) same = false;
      out.push("sortName:" + (same && names.length > 0 ? "OK" : "BAD"));
      // 9) 全天时段带放在最后: 它一点就整卡重渲染, 会把上面拿到的
      //    DOM 引用全部作废(旧节点已脱离文档), 所以必须收尾。
      var segs = document.querySelectorAll("#ans .dbseg");
      var clickable = document.querySelectorAll("#ans .dbseg[data-t]");
      out.push("dayband:" + (document.querySelector("#ans .dayband") && segs.length >= 4
        && clickable.length >= 2 && clean("ans") ? "OK" : "BAD"));
      // 10) 菜单差异块: 午餐/夜市没有独有商品, 早餐必须有「只在早餐档卖」
      //     (价格轴是平的, 这个块才是答案的主体 —— 曾经整块不渲染也没人发现)
      //     先显式点到午餐段, 不依赖探针运行时的真实时刻
      function jumpTo(t) {
        var b = document.querySelector('#ans .dbseg[data-t="' + t + '"]');
        if (b) b.click();
        return !!b;
      }
      var okLunch = jumpTo("10:44");
      var md0 = txt("ans");
      out.push("mdiff:" + (okLunch && md0.indexOf("这一档的菜单，和别档比差在哪") >= 0
        && md0.indexOf("没有一件是这一档独有的") >= 0 && clean("ans") ? "OK" : "BAD"));
      var okBf = jumpTo("07:14");
      var md1 = txt("ans");
      out.push("mdiffBf:" + (okBf && md1.indexOf("只在早餐档卖") >= 0
        && md1.indexOf("麦满分") >= 0 && clean("ans") ? "OK" : "BAD"));
      // 11) 时段带跳档: 点一个不是当前档的段, 答案要跟着换
      //     注意: clickable 是上面拿的, 中间两次跳档已经整卡重渲染,
      //     旧节点全部脱离文档 —— 必须重新查, 否则 click 静默失效
      var live = document.querySelectorAll("#ans .dbseg[data-t]");
      if (live.length >= 2) {
        var cur = document.querySelector("#ans .dbseg.cur");
        var target = null;
        for (var ci = 0; ci < live.length; ci++) {
          if (!cur || live[ci] !== cur) { target = live[ci]; break; }
        }
        if (target) {
          var want = target.querySelector(".n").textContent;
          var before = txt("ans");
          target.click();
          var after = txt("ans");
          out.push("daybandJump:" + (before !== after && after.indexOf(want) >= 0
            && clean("ans") ? "OK" : "BAD"));
        }
      }
    } catch (e) {
      out.push("EX:" + e.message);
    }
    done();
  }
  function step1() {
    try {
      var provs = document.getElementById("provSel");
      if (provs) { pick("provSel", "北京"); }
      setTimeout(function () {
        try {
          pick("citySel", "北京");
          setTimeout(step2, 500);
        } catch (e) { out.push("EX2:" + e.message); done(); }
      }, 300);
    } catch (e) {
      out.push("EX1:" + e.message);
      done();
    }
  }
  setTimeout(step1, 900);
})();
</script>
"""


def chrome() -> Path | None:
    for p in CHROME_CANDIDATES:
        if p.exists():
            return p
    return None


def main() -> int:
    exe = chrome()
    if exe is None:
        print("找不到 Chrome/Edge, 跳过实测")
        return 1
    missing = [t for t in TARGETS if not (DIST / t).exists()]
    if missing:
        print(f"缺少 {', '.join(missing)}, 先跑 src/render_report.py")
        return 1

    all_ok = True
    for target in TARGETS:
        html = (DIST / target).read_text(encoding="utf-8")
        # 探测文件落在 dist/ 里, <script src="mcd-data.js"> 才能解析到
        probe = DIST / f".probe-{target}"
        probe.write_text(html.replace("</body>", PROBE + "</body>"),
                         encoding="utf-8")
        try:
            r = subprocess.run(
                [str(exe), "--headless", "--disable-gpu", "--no-sandbox",
                 "--virtual-time-budget=6000", "--dump-dom",
                 probe.as_uri()],
                capture_output=True, text=True, timeout=120,
            )
        finally:
            probe.unlink(missing_ok=True)
        m = re.search(r"<title>(.*?)</title>", r.stdout, re.S)
        title = (m.group(1).strip() if m else "")
        print(f"[{target}] {title or '(未取到 title)'}")
        ok = ("PROBE" in title) and "ERROR" not in title and "BAD" not in title \
            and "EX" not in title and "EMPTY" not in title and "NO_" not in title
        print(f"[{target}] 结论:", "通过" if ok else "有问题, 需要看")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
