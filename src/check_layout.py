"""check_layout.py — 排版零溢出体检(窄屏错乱的根治办法是"先测再发")

做法: 复制一份 dist/report.html, 在末尾注入一段体检脚本, 用 Chrome headless
按四个视口加载它, 脚本把溢出元素写进 <title>, --dump-dom 把 title 带出来。

为什么要注入而不是眼看: 折叠区(details)里藏着的宽表格, 即使收起也会参与布局,
肉眼看不出, 手机一打开就横向滚动 —— 上一版就是这么翻车的。

用法: python src/check_layout.py
"""

from __future__ import annotations

import re
import shutil
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

# (名字, 窗口宽, 窗口高, 缩放) —— Chrome headless 有最小视口, 用缩放等效出真窄屏
VIEWPORTS = [
    ("手机 375", 750, 1400, 2),
    ("小屏 320", 640, 1200, 2),
    ("平板 768", 768, 1200, 1),
    ("桌面 1280", 1280, 1000, 1),
]

PROBE = """
<script>
(function(){
  function run(){
    var bad = [];
    var de = document.documentElement;
    if (de.scrollWidth > de.clientWidth + 1) bad.push("PAGE:" + de.scrollWidth + ">" + de.clientWidth);
    var els = document.querySelectorAll("body *");
    for (var i = 0; i < els.length; i++) {
      var el = els[i], cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      if (cs.overflowX === "auto" || cs.overflowX === "scroll") continue;
      if (el.scrollWidth > el.clientWidth + 2) {
        bad.push((el.className || el.tagName) + ":" + el.scrollWidth + ">" + el.clientWidth);
      }
    }
    // 连折叠区一起测: 全部展开
    var ds = document.querySelectorAll("details");
    for (var j = 0; j < ds.length; j++) ds[j].open = true;
    for (var k = 0; k < els.length; k++) {
      var e2 = els[k], c2 = getComputedStyle(e2);
      if (c2.display === "none" || c2.overflowX === "auto" || c2.overflowX === "scroll") continue;
      if (e2.scrollWidth > e2.clientWidth + 2) {
        bad.push("open:" + (e2.className || e2.tagName));
      }
    }
    document.title = bad.length ? ("OVERFLOW|" + bad.slice(0, 8).join(" ; ")) : "OK";
  }
  if (document.readyState === "complete") run();
  else window.addEventListener("load", function(){ setTimeout(run, 300); });
})();
</script>
"""


def find_chrome() -> Path | None:
    for p in CHROME_CANDIDATES:
        if p.exists():
            return p
    return None


def main() -> int:
    if not REPORT.exists():
        print(f"未找到 {REPORT}, 先跑 render_report.py")
        return 1
    chrome = find_chrome()
    if not chrome:
        print("未找到 Chrome/Edge。")
        return 1

    html = REPORT.read_text(encoding="utf-8")
    tmpdir = Path(tempfile.mkdtemp(prefix="mcdwhen_layout_"))
    probe = tmpdir / "check.html"
    probe.write_text(html.replace("</body>", PROBE + "</body>"), encoding="utf-8")

    ok_all = True
    for name, w, h, scale in VIEWPORTS:
        cmd = [
            str(chrome), "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--window-size={w},{h}", f"--force-device-scale-factor={scale}",
            "--virtual-time-budget=4000", "--dump-dom", probe.as_uri(),
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=90).stdout
        except subprocess.TimeoutExpired:
            print(f"[{name}] 超时")
            ok_all = False
            continue
        m = re.search(r"<title>(.*?)</title>", out, re.S)
        title = m.group(1).strip() if m else "(未取到 title)"
        if title == "OK":
            print(f"[{name}] ✓ 无横向溢出")
        else:
            ok_all = False
            print(f"[{name}] ✗ {title[:300]}")
    shutil.rmtree(tmpdir, ignore_errors=True)
    print("\n结论:", "全部视口通过" if ok_all else "存在溢出, 需要修")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
