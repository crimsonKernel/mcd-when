"""
patch_periods.py — 就地修正 surface.json 里各城市的 periods(官方时段表)

为什么需要它:
  reservationTimeOptions 按天返回, 「今天」那份只含尚未结束的时段。
  若在早餐档结束后启动普查, 采到的 periods 会缺早餐 —— 但 slots 仍覆盖全天,
  于是矩阵里有早餐数据、时段带和"各时段最优解"里却没有早餐。
  本脚本只对每城补调一次 query-nearby-stores(按普查目标日取时段表)并写回,
  不需要重新跑 7000 次核价。

用法:
  python src/patch_periods.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_client import McdMcpClient, McdMcpError  # noqa: E402
from survey import parse_periods  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SURFACE_PATH = ROOT / "data" / "surface.json"
KEYWORD = "麦当劳"


def main() -> int:
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        print("缺少 MCD_MCP_TOKEN。")
        return 1
    if not SURFACE_PATH.exists():
        print(f"未找到 {SURFACE_PATH}。")
        return 1

    surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    target = surface.get("targetDate") or ""
    client = McdMcpClient(token)
    changed = 0

    for city in surface.get("cities") or []:
        name = city["city"]
        want_code = str(city["store"]["code"])
        try:
            r = client.call_tool("query-nearby-stores", {
                "beType": 1, "searchType": 2, "city": name, "keyword": KEYWORD})
        except McdMcpError as e:
            print(f"[跳过] {name}: {e}")
            continue
        stores = r.get("data") or []
        store = next((s for s in stores if str(s.get("storeCode")) == want_code), None)
        if store is None:
            store = stores[0] if stores else None
        if store is None:
            print(f"[跳过] {name}: 未找到门店")
            continue
        old = city.get("periods") or []
        new = parse_periods(store, target)
        if new == old:
            print(f"[无变化] {name}: {' | '.join(p['name'] for p in new) or '(空)'}")
            continue
        city["periods"] = new
        changed += 1
        old_txt = " | ".join(p["name"] for p in old) or "(空)"
        new_txt = " | ".join(p["name"] + p["start"] + "-" + p["end"] for p in new)
        print(f"[已修正] {name}: {old_txt}  ->  {new_txt}")

    if changed:
        SURFACE_PATH.write_text(json.dumps(surface, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print(f"\n已写回 {SURFACE_PATH.name}({changed} 个城市修正)")
        print("下一步: python src/render_report.py")
    else:
        print("\n无需写回。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
