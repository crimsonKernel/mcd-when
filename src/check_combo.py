"""check_combo.py — 预算搭配器的无头浏览器实测

check_layout.py 只管「有没有溢出」, 不管「交互是不是坏的」。
预算搭配器是纯前端逻辑(查表 + 渲染), 光看 HTML 源码证明不了它能跑,
所以照它的办法: 注入一段脚本, 用 Chrome headless 加载, 把结果写进 <title> 带出来。

验三件事:
  1. 页面加载无 JS 报错(有错则 title 里带 ERROR:)
  2. 预算 chips 默认就渲染出答案(不是空白的)
  3. 点 chip / 填金额 / 预算不足 三条路径都对

用法: python src/check_combo.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "dist" / "report.html"

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
  setTimeout(function () {
    var out = [];
    try {
      var box = document.getElementById("budgetBox");
      if (!box) { out.push("NO_BUDGET_BOX"); }
      else {
        // 1) 默认渲染
        var o = document.getElementById("bout");
        out.push("default:" + (o && o.innerHTML.length > 30 ? "OK" : "EMPTY"));
        // 2) 点一个 chip(¥50)
        var chips = box.querySelectorAll(".bchip");
        if (chips.length) {
          chips[chips.length - 1].click();
          out.push("chip50:" + (o.innerHTML.indexOf("件") >= 0 ? "OK" : "BAD"));
        }
        // 3) 填一个非档位金额
        var inp = document.getElementById("bin");
        inp.value = "23";
        document.getElementById("bgo").click();
        out.push("custom23:" + (o.innerHTML.indexOf("按就近的低档") >= 0 ? "OK" : "BAD"));
        // 4) 预算不足路径: 切到北京 + 午餐档 + 填 6 元
        var provs = document.getElementById("provSel");
        if (provs) {
          for (var i = 0; i < provs.options.length; i++) {
            if (provs.options[i].value === "北京") { provs.selectedIndex = i; break; }
          }
          fire(provs, "change");
          setTimeout(function () {
            var c2 = document.getElementById("citySel");
            for (var j = 0; j < c2.options.length; j++) {
              if (c2.options[j].value === "北京") { c2.selectedIndex = j; break; }
            }
            fire(c2, "change");
            var tm = document.getElementById("times");
            for (var k = 0; k < tm.options.length; k++) {
              if (tm.options[k].value === "12:00") { tm.selectedIndex = k; break; }
            }
            fire(tm, "change");
            var i2 = document.getElementById("bin");
            i2.value = "6";
            document.getElementById("bgo").click();
            var o2 = document.getElementById("bout");
            out.push("gap:" + (o2.innerHTML.indexOf("吃不到") >= 0 ? "OK" : "BAD"));
            if (errs.length) out.push("ERROR:" + errs.join("|"));
            document.title = "PROBE2 " + out.join(" ");
          }, 400);
          return;
        }
        var tm0 = document.getElementById("times");
        for (var k0 = 0; k0 < tm0.options.length; k0++) {
          if (tm0.options[k0].value === "12:00") { tm0.selectedIndex = k0; break; }
        }
        fire(tm0, "change");
        var i3 = document.getElementById("bin");
        i3.value = "6";
        document.getElementById("bgo").click();
        var o3 = document.getElementById("bout");
        out.push("gap:" + (o3.innerHTML.indexOf("吃不到") >= 0 ? "OK" : "BAD"));
      }
    } catch (e) {
      out.push("EX:" + e.message);
    }
    if (errs.length) out.push("ERROR:" + errs.join("|"));
    document.title = "PROBE " + out.join(" ");
  }, 900);
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
    if not REPORT.exists():
        print(f"缺少 {REPORT}, 先跑 src/render_report.py")
        return 1

    html = REPORT.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp()) / "probe.html"
    tmp.write_text(html.replace("</body>", PROBE + "</body>"), encoding="utf-8")

    r = subprocess.run(
        [str(exe), "--headless", "--disable-gpu", "--no-sandbox",
         "--virtual-time-budget=4000", "--dump-dom",
         f"file:///{tmp.as_posix()}"],
        capture_output=True, text=True, timeout=90,
    )
    m = re.search(r"<title>(.*?)</title>", r.stdout, re.S)
    title = (m.group(1).strip() if m else "")
    print("实测结果:", title or "(未取到 title)")
    ok = ("PROBE" in title or "PROBE2" in title) and "ERROR" not in title and "BAD" not in title \
        and "EX:" not in title and "EMPTY" not in title
    print("结论:", "通过" if ok else "有问题, 需要看")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
