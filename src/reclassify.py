"""reclassify.py — 不重采, 只按最新分类规则重算本地数据的 kind 与 floors。

用途: classify() 的词表修好之后, 不需要再花 78 分钟重跑 3.6 万次核价 ——
价格数据( prices )本来就是对的, 错的只是"这个商品算不算一顿饭"这个标签,
以及由标签推导出来的各档地板价( floors )。本脚本在本地重算这两样。

用法:
    python src/reclassify.py                     # 全菜单数据 + 探针快照都重算
    python src/reclassify.py --file data/surface_batch.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_national import MIN_FOOD_PRICE, classify  # noqa: E402

TARGETS = ["data/surface_batch.json", "data/surface_national.json"]


def recompute(city: dict) -> tuple[int, int]:
    """重算单城: 返回 (改动数, 商品数)"""
    basket = city.get("basket") or []
    prices = (city.get("prices") or {})
    changed = 0
    for it in basket:
        new = classify(it.get("name") or it.get("code", ""), it.get("category") or "")
        if new != it.get("kind"):
            changed += 1
        it["kind"] = new
    kind_of = {it["code"]: it.get("kind") for it in basket}
    name_of = {it["code"]: it.get("name") for it in basket}

    for ch in ("pickup", "dt"):
        tab = prices.get(ch) or {}
        if not tab:
            continue
        floors = city.setdefault("floors", {}).setdefault(ch, {})
        for p in city.get("periods") or []:
            pname = p["name"]
            rows = []
            for code, by_period in tab.items():
                v = (by_period or {}).get(pname)
                if v is None or v < MIN_FOOD_PRICE:
                    continue
                k = kind_of.get(code) or "side"
                if k == "extra":
                    continue
                rows.append({"name": name_of.get(code, code), "price": v,
                             "kind": k, "code": code})
            rows.sort(key=lambda r: r["price"])
            meal = next((r for r in rows if r["kind"] == "meal"), None)
            any_ = next((r for r in rows if r["kind"] in ("meal", "side")), None)
            floors[pname] = {"meal": meal, "any": any_, "top": rows[:5]}
    return changed, len(basket)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append")
    args = ap.parse_args()
    files = args.file or TARGETS

    for rel in files:
        path = ROOT / rel
        if not path.exists():
            print(f"跳过(不存在): {rel}")
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        cities = d["cities"] if isinstance(d, dict) else d
        tot_changed = tot_items = 0
        for c in cities:
            ch, n = recompute(c)
            tot_changed += ch
            tot_items += n
        path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{rel}: {len(cities)} 城 / {tot_items} 商品, 其中 {tot_changed} 个分类被改正")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
