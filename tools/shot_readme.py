"""重新生成 README 里的实拍截图(界面改版后旧图已与线上不符)。

两个坑, 都踩过:
1) 无头 Chrome 新模式下 prefers-color-scheme 默认是 dark —— 把深色分支的媒体查询
   替换成永不匹配的 `not all`, 才拿到稳定的浅色渲染。
2) 一旦让页面滚动(window.scrollTo / scrollIntoView), --screenshot 就只吐出
   一张空白图(5868 字节)。所以「只要答案卡」的构图不用滚动, 改用注入 CSS 把
   hero 和提问卡藏掉, 让答案卡落在首屏。
另外本机如果已经开着 Chrome, 必须给独立的 --user-data-dir, 否则截图静默变 0 字节。
"""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
IMG = ROOT / "images"
CHROME_CANDIDATES = [
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
]
EXE = next((p for p in CHROME_CANDIDATES if p.exists()), None)
LIGHT = "(prefers-color-scheme:dark)"


def render(name: str, src: str, probe: str = "", size=(1280, 900),
           light: bool = True, hide_top: bool = False, budget: str = "9000"):
    if EXE is None:
        print("找不到 Chrome/Edge, 跳过截图")
        return
    html = (DIST / src).read_text(encoding="utf-8")
    if light:
        html = html.replace(LIGHT, "not all")
    head = ('<style>.wrap>.nav,.wrap>.hero,#sec-answer>.q{display:none!important}'
            '.wrap{padding-top:10px}</style>' if hide_top else "")
    # 探针必须落在 dist/ 里, <script src="mcd-data.js"> 才解析得到
    tmp = (DIST / f".shot-{name}.html").resolve()
    tmp.write_text(html.replace("</head>", head + "</head>")
                        .replace("</body>", probe + "</body>"), encoding="utf-8")
    dst = (IMG / name).resolve()
    prof = Path(tempfile.mkdtemp()) / "prof"
    try:
        subprocess.run(
            [str(EXE), "--headless", "--disable-gpu", "--no-sandbox",
             f"--user-data-dir={prof.as_posix()}",
             f"--virtual-time-budget={budget}", "--hide-scrollbars",
             f"--window-size={size[0]},{size[1]}",
             f"--screenshot={dst.as_posix()}", tmp.as_uri()],
            capture_output=True, text=True, timeout=240)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"{name}: {dst.stat().st_size if dst.exists() else 0} bytes "
          f"({size[0]}x{size[1]})")


# 选城市 + 选时刻的探针(早餐/午餐两档各来一张)
PICK = """
<script>
(function(){
  function fire(el,t){var e=document.createEvent("HTMLEvents");e.initEvent(t,false,true);el.dispatchEvent(e);}
  function pick(sel,val){var el=document.getElementById(sel);if(!el)return false;
    for(var i=0;i<el.options.length;i++) if(el.options[i].value===val){el.selectedIndex=i;fire(el,"change");return true;}
    return false;}
  setTimeout(function(){
    if(!pick("provSel","__PROV__")) return;
    setTimeout(function(){
      if(!pick("citySel","__CITY__")) return;
      setTimeout(function(){
        var tm=document.getElementById("times");
        for(var k=0;k<tm.options.length;k++) if(tm.options[k].value==="__T__"){tm.selectedIndex=k;fire(tm,"change");break;}
      },400);
    },300);
  },1100);
})();
</script>"""


def pick(prov, city, t):
    return PICK.replace("__PROV__", prov).replace("__CITY__", city).replace("__T__", t)


if __name__ == "__main__":
    IMG.mkdir(exist_ok=True)
    # 问答页首屏(新叙事 hero)
    render("page-index.png", "index.html", size=(1280, 660))
    # 桌面端整页: hero + 提问 + 答案卡(含全天时段带和菜单差异块)
    render("usage-desktop.png", "index.html", pick("北京", "北京", "12:00"),
           size=(1280, 2300))
    # 手机端: 只要答案卡那一屏(早餐档, 能看见「只在早餐档卖」的麦满分清单)
    render("usage-mobile.png", "index.html", pick("北京", "北京", "07:30"),
           size=(390, 844), hide_top=True)
    # 全国榜单页
    render("page-rank.png", "rank.html", size=(1280, 900))
    # 方法与合规页
    render("page-how.png", "how.html", size=(1280, 900))
