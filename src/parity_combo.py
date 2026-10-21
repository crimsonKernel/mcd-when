"""parity_combo.py — JS 背包 vs Python 背包 逐分对拍

前端 knap() 是 src/combo.py 的 JS 移植。两边算出不一样,
「同一个问题两个入口两个答案」, 产品立刻就失信。
所以这里把页面里的 JS 函数抠出来, 在 node 里跑同一批 (城, 档, 预算, 锚点),
和 Python best_combo 的结果逐个比对。

用法: python src/parity_combo.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from combo import best_combo  # noqa: E402

NODE = "C:/Users/xueyihan/.workbuddy/binaries/node/versions/22.22.2-6/node.exe"


def extract_js(html: str) -> str:
    """从页面里抠出 knap / periodMenu / findCity 等, 拼成一个可跑的 node 脚本。"""
    m = re.search(r"<script>window\.__MCD_DATA__ = (\{.*?\});</script>", html, re.S)
    if not m:
        raise SystemExit("找不到数据块")
    data = m.group(1)
    # knap 函数体
    km = re.search(r"(function knapInner\(menu, limitFen\) \{.*?\n  \})", html, re.S)
    kw = re.search(r"(function knap\(menu, limitFen, anchorItem\) \{.*?\n  \})", html, re.S)
    if not km or not kw:
        raise SystemExit("找不到背包函数")
    pm = re.search(r"(function periodMenu\(city, period\) \{.*?\n  \})", html, re.S)
    fc = re.search(r"(function findCity\(name\) \{.*?\n  \})", html, re.S)
    return (
        "var DATA = __DATA__;\n"
        "var MN = DATA.mn || [];\n"
        + (fc.group(1) if fc else "") + "\n"
        + (pm.group(1) if pm else "") + "\n"
        + km.group(1) + "\n"
        + kw.group(1) + "\n"
        + """
var out = [];
var CASES = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
for (var i = 0; i < CASES.length; i++) {
  var c = CASES[i];
  var city = findCity(c.city);
  var menu = city ? periodMenu(city, c.period) : [];
  var anchorItem = null;
  if (c.anchor) {
    anchorItem = {ni: c.anchor[0], pf: c.anchor[1], k: c.anchor[2]};
  }
  var r = knap(menu, c.budget, anchorItem);
  // 菜单项是数组 [ni, price, kind], 锚点是 {ni, pf, k} —— 两种都要认
  // 按 (价格, 名称下标) 排: 同价商品在不同回溯顺序下会换位,
  // 只按价格排会把「同一批货不同顺序」误判成不一致
  out.push({total: r.total, hasMeal: r.hasMeal,
            items: r.items.map(function (x) {
                    return Array.isArray(x) ? [x[0], x[1], x[2]] : [x.ni, x.pf, x.k];
                  }).sort(function (a, b) {
                    return a[1] - b[1] || a[0] - b[0];
                  })});
}
console.log(JSON.stringify(out));
"""
    ).replace("__DATA__", data)


def main() -> int:
    html = (ROOT / "dist" / "report.html").read_text(encoding="utf-8")
    js = extract_js(html)

    # 用例: 覆盖不同城市/时段/预算/锚点
    cases = []
    for city in ["北京", "上海", "拉萨", "贵阳", "哈尔滨", "如皋", "三明"]:
        for period in ["早餐", "午餐", "下午茶", "夜市"]:
            for budget in [1000, 1500, 2000, 2500, 3000, 5000, 8000]:
                cases.append({"city": city, "period": period, "budget": budget})
    # 锚点用例: 从页面数据里取每城午餐最贵的几件当锚点
    data = json.loads(re.search(r"window\.__MCD_DATA__ = (\{.*?\});",
                                html, re.S).group(1))
    for city in ["北京", "上海", "拉萨"]:
        rec = next((c for c in data["cities"] if c["city"] == city), None)
        if not rec:
            continue
        per = next((p for p in rec["periods"] if p["name"] == "午餐"), None)
        if not per or not per.get("menu"):
            continue
        menu = per["menu"]
        for pick in [menu[0], menu[len(menu) // 2], menu[-1]]:
            cases.append({"city": city, "period": "午餐", "budget": 3000,
                          "anchor": pick})
    # 预算不足用例
    cases.append({"city": "北京", "period": "午餐", "budget": 600})
    cases.append({"city": "拉萨", "period": "午餐", "budget": 800})

    tmp = Path(tempfile.mkdtemp())
    case_file = tmp / "cases.json"
    case_file.write_text(json.dumps(cases), encoding="utf-8")
    js_file = tmp / "knap.js"
    js_file.write_text(js, encoding="utf-8")

    r = subprocess.run([NODE, str(js_file), str(case_file)],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print("node 运行失败:", r.stderr[:800])
        return 1
    js_res = json.loads(r.stdout)

    # Python 侧重算
    batch = json.loads((ROOT / "data" / "surface_batch.json").read_text(encoding="utf-8"))
    nat = json.loads((ROOT / "data" / "surface_national.json").read_text(encoding="utf-8"))
    cities = {c["city"]: c for c in batch["cities"]}
    for c in nat["cities"]:
        cities.setdefault(c["city"], c)

    bad = 0
    for case, jr in zip(cases, js_res):
        rec = cities.get(case["city"])
        if not rec:
            continue
        anchor = None
        if case.get("anchor"):
            ni, pf, k = case["anchor"]
            anchor = {"name": data["mn"][ni], "kind": {0: "side", 1: "meal", 2: "extra"}[k],
                      "price_fen": pf}
        cands = [x for x in _cands(rec, case["period"]) if x["price_fen"] <= case["budget"]]
        total, picked, ok = best_combo(cands, case["budget"], anchor)
        py = {"total": total if ok else 0, "hasMeal": ok,
              "items": sorted([[data["mn"].index(x["name"]), x["price_fen"],
                                0 if x["kind"] == "side" else 1] for x in picked],
                              key=lambda z: (z[1], z[0]))}
        if py != jr:
            bad += 1
            if bad <= 5:
                print(f"不一致: {case['city']}/{case['period']}/¥{case['budget']/100}"
                      f"{' 锚点=' + data['mn'][case['anchor'][0]] if case.get('anchor') else ''}")
                print("  py:", py)
                print("  js:", jr)

    print(f"对拍 {len(cases)} 个用例, 不一致 {bad} 个")
    return 1 if bad else 0


def _cands(rec, period):
    pu = (rec.get("prices") or {}).get("pickup") or {}
    basket = {i["code"]: i for i in (rec.get("basket") or [])}
    out = []
    for code, it in basket.items():
        p = (pu.get(code) or {}).get(period)
        if not isinstance(p, int) or p < 500:
            continue
        if it.get("kind") not in ("meal", "side"):
            continue
        out.append({"name": it.get("name") or code, "kind": it.get("kind"),
                    "price_fen": p})
    return out


if __name__ == "__main__":
    raise SystemExit(main())
