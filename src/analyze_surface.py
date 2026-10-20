"""analyze_surface.py — 分析既有普查数据, 回答三个决定"能否全国铺开"的问题:

  Q1 同一商品的价格在一天内是否恒定?        (若恒定 -> 不必逐时刻核价)
  Q2 同一商品的价格在上海/北京/广州...是否一致?(若一致 -> 全国只需采时段与可售性)
  Q3 自提 vs 得来速 是否有价差?             (若同价 -> 全国普查可只跑自提, 省一半调用)

用法: python src/analyze_surface.py
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE = ROOT / "data" / "surface.json"


def main() -> int:
    s = json.loads(SURFACE.read_text(encoding="utf-8"))
    cities = s["cities"]
    print(f"目标日期 {s['targetDate']} | 已采城市 {len(cities)}: "
          f"{', '.join(c['city'] for c in cities)}\n")

    # ---------- Q1 价格是否随时段变动 ----------
    print("=== Q1 同一商品在一天内是否出现多个价格 ===")
    for c in cities:
        grid = c["grid"]["pickup"]
        names = {b["code"]: b["name"] for b in c["basket"]}
        multi = 0
        for code in names:
            vals = set()
            for t in grid:
                cell = grid[t].get(code) or {}
                if cell.get("price") is not None:
                    vals.add(cell["price"])
            if len(vals) > 1:
                multi += 1
                if multi <= 5:
                    print(f"  [{c['city']}] {names[code]} {sorted(vals)}")
        print(f"  {c['city']}: {multi}/{len(names)} 个商品价格随时段变动")

    # ---------- Q2 价格是否全国统一 ----------
    print("\n=== Q2 同一商品在不同城市的价格是否一致 ===")
    tab: dict[str, dict[str, int]] = collections.defaultdict(dict)
    names: dict[str, str] = {}
    for c in cities:
        for b in c["basket"]:
            names[b["code"]] = b["name"]
        grid = c["grid"]["pickup"]
        for b in c["basket"]:
            vals = {grid[t][b["code"]]["price"] for t in grid
                    if (grid[t].get(b["code"]) or {}).get("price") is not None}
            if vals:
                # 若 Q1 成立, vals 只会有 1 个值
                tab[b["code"]][c["city"]] = min(vals)
    diff = 0
    shown = 0
    for code, per in tab.items():
        if len(set(per.values())) > 1:
            diff += 1
            if shown < 15:
                shown += 1
                print(f"  {names.get(code, code)}: " +
                      " ".join(f"{k}={v}" for k, v in per.items()))
    print(f"  跨城价格不一致的商品: {diff}/{len(tab)}")
    common = [c for c, per in tab.items() if len(per) >= len(cities)]
    print(f"  五城都采到的商品: {len(common)}")

    # ---------- Q3 自提 vs 得来速 ----------
    print("\n=== Q3 自提 vs 得来速 ===")
    for c in cities:
        if "dt" not in c["grid"]:
            continue
        same = diffp = pu_only = dt_only = 0
        for t in c["grid"]["pickup"]:
            pu = c["grid"]["pickup"][t]
            dt = c["grid"]["dt"].get(t, {})
            for code, cell in pu.items():
                a = cell.get("price")
                b = (dt.get(code) or {}).get("price")
                if a is not None and b is not None:
                    if a == b:
                        same += 1
                    else:
                        diffp += 1
                        if diffp <= 3:
                            print(f"    价差 [{c['city']} {t}] {code}: 自提 {a} vs 得来速 {b}")
                elif a is not None:
                    pu_only += 1
                elif b is not None:
                    dt_only += 1
        print(f"  {c['city']}: 同价 {same} | 价差 {diffp} | 仅自提可售 {pu_only} | 仅得来速可售 {dt_only}")

    # ---------- 时段与营业时间 ----------
    print("\n=== 各城时段边界与门店营业时间 ===")
    for c in cities:
        st = c["store"]
        print(f"  {c['city']}: 门店 {st['businessStart']}-{st['businessEnd']} | " +
              " ".join(f"{p['name']}{p['start']}-{p['end']}" for p in c["periods"]))

    # ---------- 各时段地板价 ----------
    print("\n=== 各时段地板价(自提) ===")
    for c in cities:
        grid = c["grid"]["pickup"]
        floors: dict[str, tuple[int, str]] = {}
        for p in c["periods"]:
            best: tuple[int, str] | None = None
            for t in grid:
                if p["start"] <= t <= p["end"]:
                    for b in c["basket"]:
                        cell = grid[t].get(b["code"]) or {}
                        v = cell.get("price")
                        if v is not None and (best is None or v < best[0]):
                            best = (v, b["name"])
            if best:
                floors[p["name"]] = best
        print(f"  {c['city']}: " + " | ".join(
            f"{k} ¥{v[0] / 100:.2f} ({v[1]})" for k, v in floors.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
