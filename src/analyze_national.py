"""analyze_national.py — 全国普查跑完后, 把"能写进 README 的结论"算出来

用法: python src/analyze_national.py
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE = ROOT / "data" / "surface_national.json"


def yuan(f: int | None) -> str:
    return "—" if f is None else f"¥{f / 100:.2f}"


def main() -> int:
    s = json.loads(SURFACE.read_text(encoding="utf-8"))
    cities = s["cities"]
    print(f"目标日期 {s['targetDate']} | 城市 {len(cities)} | 问价 {sum(c.get('calls', 0) for c in cities)} 次\n")

    # ---- 覆盖 ----
    provs = Counter(c.get("province") for c in cities if c.get("province"))
    print(f"覆盖 {len(provs)} 个省级行政区: {', '.join(sorted(provs))}")

    # ---- 早餐档 ----
    with_bf = [c for c in cities if c.get("periods") and c["periods"][0]["name"] == "早餐"]
    no_bf = [c for c in cities if c not in with_bf]
    starts = Counter(c["periods"][0]["start"] for c in with_bf)
    print(f"\n有早餐档 {len(with_bf)} 城, 无早餐档(样本门店开档晚) {len(no_bf)} 城")
    print("早餐开档时刻分布(前 8):", starts.most_common(8))
    if no_bf:
        print("无早餐档城市示例:", "、".join(c["city"] for c in no_bf[:12]))

    # ---- 各档地板价 ----
    print("\n各档「最便宜一餐」价格分布:")
    for pname in ["早餐", "午餐", "下午茶", "夜市"]:
        vals = []
        for c in cities:
            m = (c.get("floors", {}).get("pickup") or {}).get(pname, {}).get("meal")
            if m:
                vals.append((m["price"], c["city"], m["name"]))
        if not vals:
            continue
        vals.sort()
        ps = [v[0] for v in vals]
        print(f"  {pname}: n={len(vals)} 最低 {yuan(ps[0])}({vals[0][1]}) "
              f"中位 {yuan(int(statistics.median(ps)))} 最高 {yuan(ps[-1])}({vals[-1][1]})")

    # ---- 早餐 vs 午餐 ----
    delta = []
    for c in with_bf:
        fl = c.get("floors", {}).get("pickup") or {}
        b = (fl.get("早餐") or {}).get("meal")
        lunch = (fl.get("午餐") or {}).get("meal")
        if b and lunch and lunch["price"] > b["price"]:
            delta.append((lunch["price"] - b["price"], c["city"], b["price"], lunch["price"]))
    delta.sort(reverse=True)
    if delta:
        print(f"\n早餐比午餐便宜的城市 {len(delta)}/{len(with_bf)}")
        for d, city, b, l in delta[:6]:
            print(f"  {city}: 早餐 {yuan(b)} -> 午餐 {yuan(l)}, 省 {yuan(d)}")
        print("  价差最小:", " ".join(f"{c}{yuan(d)}" for d, c, b, l in delta[-4:]))

    # ---- 得来速 ----
    dt_cities = [c for c in cities if c.get("dtStore")]
    cheaper = 0
    pairs = []
    for c in cities:
        pu, dt = c.get("prices", {}).get("pickup") or {}, c.get("prices", {}).get("dt") or {}
        for code, tab in dt.items():
            for pname, v in (tab or {}).items():
                b = (pu.get(code) or {}).get(pname)
                if v and b:
                    if v < b:
                        cheaper += 1
                    if v != b:
                        nm = next((i["name"] for i in c["basket"] if i["code"] == code), code)
                        pairs.append((b - v, c["city"], nm, b, v))
    print(f"\n有得来速门店的城市 {len(dt_cities)}; 得来速更便宜的格子 {cheaper} 个")
    pairs.sort(reverse=True)
    for d, city, nm, b, v in pairs[:5]:
        print(f"  {city} {nm}: 自提 {yuan(b)} -> 得来速 {yuan(v)} (省 {yuan(d)})")

    # ---- 各城营业时间 ----
    h24 = [c["city"] for c in cities
           if (c.get("store") or {}).get("businessStart") in ("00:00", "0:00")]
    print(f"\n样本门店 24 小时营业的城市 {len(h24)} 座: {'、'.join(h24[:10])}")

    # ---- 需要人工复核的异常 ----
    print("\n异常值(地板价明显偏离全国中位数, 建议复核):")
    for pname in ["早餐", "午餐"]:
        vals = []
        for c in cities:
            m = (c.get("floors", {}).get("pickup") or {}).get(pname, {}).get("meal")
            if m:
                vals.append((m["price"], c["city"], m["name"]))
        if len(vals) < 10:
            continue
        ps = sorted(v[0] for v in vals)
        med = ps[len(ps) // 2]
        odd = [v for v in vals if v[0] > med * 1.8 or v[0] < med * 0.55]
        for price, city, name in sorted(odd)[:8]:
            print(f"  {pname} {city} {yuan(price)} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
