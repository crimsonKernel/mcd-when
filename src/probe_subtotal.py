"""一次性探针: 搞清 calculate-price 的 productList[].subtotal 到底是什么。

用法: python src/probe_subtotal.py
只读, 不改任何数据文件。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mcd_client import McdMcpClient  # noqa: E402
from survey_national import load_env  # noqa: E402


def main() -> int:
    load_env()
    import os
    token = os.environ.get("MCD_TOKEN") or os.environ.get("MCD_MCP_TOKEN") or ""
    if not token:
        print("缺少 MCD_TOKEN(见 .env)")
        return 2
    client = McdMcpClient(token)

    # 上海一家已知门店(与 surface_batch.json 里同一家)
    store = "1450657"
    be_type, order_type = 1, 1
    when = "2026-10-22 12:00"

    # 单商品: 看 data.price 与 productList[].subtotal 的关系
    def call(items, when):
        return client.call_tool("calculate-price", {
            "beType": be_type, "orderType": order_type, "storeCode": store,
            "items": items,
            "reservationDate": when,
        })

    for when in ["2026-10-22 12:30", "2026-10-22 11:00", "2026-10-22 19:00"]:
        r = call([{"productCode": "9900011872", "quantity": 1}], when)
        if r.get("success"):
            print(f"=== 单商品 9900011872 @ {when} ===")
            print(json.dumps(r, ensure_ascii=False, indent=1)[:1500])
            break
        print(f"({when} 失败: {r.get('code')} {r.get('message')})")
    else:
        return 3

    # 同商品重复 3 次: 看 subtotal 是否随数量线性
    triple = call([{"productCode": "9900011872", "quantity": 3}], when)
    print("=== 同商品 quantity=3 ===")
    print(json.dumps(triple, ensure_ascii=False, indent=1)[:1200])

    # 三个不同商品: 看 productList 顺序与 subtotal 是否为累计
    codes = ["9900011872", "9900011873", "507409"]
    multi = call([{"productCode": c, "quantity": 1} for c in codes], when)
    print("=== 三个不同商品 ===")
    print(json.dumps(multi, ensure_ascii=False, indent=1)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
