"""combo_precompute.py — 预计算「预算内怎么点最饱」的全国搭配表

为什么预计算而不是在网页里现算:
  全量菜单嵌进页面要 5.6 MB(387 城 × 平均 369 个(城,档,商品)三元组),
  页面会从 648 KB 涨到 6 MB, 「双击即开」的优势就没了。
  而商品名在全国高度重复(全国就两千来个品名),
  所以用「全局名称表 + 预算阶梯预计算」能把体积压到 1 MB 左右,
  且打开页面瞬间出结果, 不需要客户端算背包。

预算阶梯: 顾客想的是「我有 20 块」这种整数, 不是 ¥17.5。
  非阶梯内的金额由前端向下取到最近的一档(见 render_report.py)。

产出: data/combos.json  (被 render_report.py 内嵌进 dist/report.html)

用法:
    python src/combo_precompute.py            # 增量(已有则跳过)
    python src/combo_precompute.py --force    # 重算
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from combo import best_combo, candidates  # noqa: E402

BATCH_PATH = ROOT / "data" / "surface_batch.json"
PROBE_PATH = ROOT / "data" / "surface_national.json"
OUT_PATH = ROOT / "data" / "combos.json"

# 预算阶梯(分)。¥5 以下不当饭, 所以最低档 ¥10
BUDGETS_FEN = [1000, 1500, 2000, 2500, 3000, 4000, 5000]


def load_cities() -> list[dict]:
    """与 render_report.py 相同的取数逻辑: 全菜单为主, 探针补齐。"""
    batch = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
    cities = list(batch.get("cities") or [])
    if PROBE_PATH.exists():
        probe = json.loads(PROBE_PATH.read_text(encoding="utf-8"))
        have = {c.get("city") for c in cities}
        cities += [c for c in (probe.get("cities") or [])
                   if c.get("city") not in have]
    return cities


def build() -> dict:
    cities = load_cities()
    names: list[str] = []          # 全局名称表
    name_idx: dict[str, int] = {}

    def idx(nm: str) -> int:
        if nm not in name_idx:
            name_idx[nm] = len(names)
            names.append(nm)
        return name_idx[nm]

    out: dict[str, dict] = {}
    n_combos = 0
    for c in cities:
        city = c.get("city")
        if not city:
            continue
        per: dict[str, dict] = {}
        for p in c.get("periods") or []:
            pname = p["name"]
            cands = candidates(c, pname)
            if not cands:
                continue
            # 最便宜的一顿(单品对照)
            meals = [x for x in cands if x["kind"] == "meal"]
            cheapest = min(meals or cands, key=lambda x: x["price_fen"])
            entry: dict = {"best": [idx(cheapest["name"]), cheapest["price_fen"]]}

            ladder: dict[str, dict] = {}
            for b in BUDGETS_FEN:
                usable = [x for x in cands if x["price_fen"] <= b]
                if not usable:
                    continue
                total, picked, has_meal = best_combo(usable, b)
                if not has_meal:
                    # 这一档预算吃不到一顿正经饭 —— 不出搭配,
                    # 由前端用 entry["best"] 提示「还差多少钱」
                    continue
                ladder[str(b)] = {
                    "t": total,
                    "i": [[idx(x["name"]), x["price_fen"]] for x in picked],
                }
                n_combos += 1
            entry["b"] = ladder
            per[pname] = entry
        if per:
            out[city] = per

    return {
        "generatedAt": (json.loads(BATCH_PATH.read_text(encoding="utf-8"))
                        .get("generatedAt", "")),
        "budgets": BUDGETS_FEN,
        "names": names,
        "cities": out,
        "stats": {
            "cities": len(out),
            "combos": n_combos,
            "unique_names": len(names),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="预计算全国预算搭配表")
    ap.add_argument("--force", action="store_true", help="已有文件也重算")
    args = ap.parse_args()

    if OUT_PATH.exists() and not args.force:
        print(f"已有 {OUT_PATH}, 用 --force 重算。")
        return 0

    blob = build()
    OUT_PATH.write_text(json.dumps(blob, ensure_ascii=False,
                                   separators=(",", ":")), encoding="utf-8")
    s = blob["stats"]
    size = OUT_PATH.stat().st_size
    print(f"写出 {OUT_PATH}  ({size/1024:.0f} KB)")
    print(f"  {s['cities']} 城 · {s['combos']} 个搭配 · "
          f"{s['unique_names']} 个唯一商品名")
    print(f"  预算阶梯: {'/'.join('¥%d' % (b//100) for b in blob['budgets'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
