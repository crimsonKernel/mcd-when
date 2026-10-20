"""
survey.py — 全天价格普查(核心采集脚本)

真机验证后的设计(2026-10-20):
  1. 官方接口的 `reservationDate` 可以指定未来任意时刻 —— 所以不需要挂 7 天定时任务,
     今天就能把「明天全天」的菜单与价格全部跑完。
  2. 菜单按官方时段切换(早餐/午餐/下午茶/夜市, 见门店返回的 reservationTimeOptions),
     10:15→10:44 之间存在"菜单真空带"。
  3. 渠道: 到店自提(beType=1) + 得来速(beType=5, 需 beCode)。外送需用户地址, 本脚本不涉及。

流程:
  [1] 校时, 目标日期 = 服务端明天
  [2] 按城市搜门店(自提 + 得来速), 解析官方时段边界
  [3] 锚点时刻拉菜单(每时段中点 + 真空带), 圈定探针商品(时段专属 + 全天常驻)
  [4] query-meal-detail 取商品名
  [5] 逐时刻 × 逐商品 × 逐渠道 calculate-price(失败=不可售, 这本身就是数据)
  [6] 落盘 data/surface.json

用法:
    set MCD_MCP_TOKEN=你的token
    python src/survey.py --city 上海
    python src/survey.py --city 上海 --dry-run     # 只打印计划
    python src/survey.py --city 北京 --city 成都   # 多城市

安全设计:
  - 只读白名单硬约束, 绝不调用 create-order / auto-bind-coupons 等写操作
  - 所有价格均来自 calculate-price 实时返回, 本脚本不产生任何估算值
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from mcd_client import McdMcpClient, McdMcpError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config.json"

# 只读工具白名单 —— 本脚本只允许调用这些
READ_ONLY_TOOLS = {
    "now-time-info", "query-nearby-stores", "query-meals",
    "query-meal-detail", "calculate-price",
}

# 圈定探针商品的分类关键词(命中即纳入)
BASKET_CATEGORY_KEYWORDS = ["早餐", "下午茶", "夜市", "人气热卖", "超值", "随心配", "1+1"]
MAX_ITEMS = 20          # 探针商品上限(控制调用量)
SLOT_STEP_MIN = 30      # 时刻粒度(分钟)
ANCHOR_SLOTS = ["08:00", "10:30", "12:00", "15:30", "19:00", "21:00"]  # 菜单普查锚点


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))


# ---------- 解析工具 ----------

def parse_periods(store: dict[str, Any], target_date: str | None = None) -> list[dict[str, str]]:
    """从 reservationTimeOptions 解析官方时段边界。

    坑: reservationTimeOptions 按天返回, 而「今天」那份只含**尚未结束**的时段 ——
    早餐档一过它就从文本里消失。所以普查目标日若是明天, 必须明确按 target_date 取,
    否则会拿到一张残缺的时段表(表现为四城 periods 缺少早餐)。
    """
    opts = store.get("reservationTimeOptions") or []
    chosen = None
    if target_date:
        chosen = next((o for o in opts if o.get("date") == target_date), None)
    if chosen is None:
        chosen = next((o for o in opts if o.get("today") is False), opts[0] if opts else None)
    if chosen is None:
        return []
    text = chosen.get("reservationOptionText") or ""
    found = [{"name": m.group(1), "start": m.group(2), "end": m.group(3)}
             for m in re.finditer(r"(早餐|午餐|下午茶|夜市)\((\d{2}:\d{2})至(\d{2}:\d{2})\)", text)]
    return found or []


def hhmm_to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def build_slots(start_hhmm: str, end_hhmm: str) -> list[str]:
    """营业时间内的全部时刻(含端点, 半小时粒度)。跨零点门店按 23:59 截断。"""
    s, e = hhmm_to_min(start_hhmm), hhmm_to_min(end_hhmm)
    if e <= s:
        e = 23 * 60 + 59
    return [f"{m // 60:02d}:{m % 60:02d}" for m in range(s, e + 1, SLOT_STEP_MIN)]


def flatten_menu(meals_resp: dict[str, Any]) -> list[dict[str, Any]]:
    """菜单 -> [{code, category, tags}]。结构: data.categories[].meals[].code/tags。"""
    out: list[dict[str, Any]] = []
    data = meals_resp.get("data") or {}
    for cat in data.get("categories") or []:
        cat_name = (cat.get("name") or "").replace("\n", "/")
        for meal in cat.get("meals") or []:
            code = meal.get("code") or meal.get("productCode")
            if code:
                out.append({"code": str(code), "category": cat_name,
                            "tags": meal.get("tags") or []})
    return out


def select_basket(anchor_menus: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """从锚点菜单圈定探针商品: 分类关键词命中 + 全天常驻补充, 去重, 截断。
    记录每个商品首次出现的锚点时刻(firstSlot), 供按其可售时段查详情取名字。"""
    seen: dict[str, dict[str, Any]] = {}
    all_codes: dict[str, int] = {}
    for slot, items in sorted(anchor_menus.items()):
        for it in items:
            all_codes[it["code"]] = all_codes.get(it["code"], 0) + 1
    n_anchors = len(anchor_menus) or 1
    # 1) 时段/套餐类分类命中
    for slot, items in sorted(anchor_menus.items()):
        for it in items:
            if any(k in it["category"] for k in BASKET_CATEGORY_KEYWORDS):
                if it["code"] not in seen:
                    seen[it["code"]] = {**it, "slotsSeen": 1, "firstSlot": slot}
                else:
                    seen[it["code"]]["slotsSeen"] += 1
    # 2) 若还有余量, 补全天常驻商品(出现在全部锚点里的)
    for code, cnt in sorted(all_codes.items(), key=lambda x: -x[1]):
        if len(seen) >= MAX_ITEMS:
            break
        if code not in seen and cnt == n_anchors:
            for slot, items in sorted(anchor_menus.items()):
                hit = next((i for i in items if i["code"] == code), None)
                if hit:
                    seen[code] = {**hit, "slotsSeen": cnt, "firstSlot": slot}
                    break
    return list(seen.values())[:MAX_ITEMS]


# ---------- 主流程 ----------

def survey_city(client: McdMcpClient, city: str, target_date: str,
                dry_run: bool = False) -> dict[str, Any]:
    print(f"\n########## 城市: {city} ##########")

    print(f"[门店] query-nearby-stores (city={city}) ...")
    pickup = client.call_tool("query-nearby-stores",
                              {"beType": 1, "searchType": 2, "city": city, "keyword": "麦当劳"})
    stores = (pickup.get("data") or []) if pickup.get("success") else []
    if not stores:
        raise McdMcpError(f"{city}: 未找到门店 ({pickup.get('message')})")
    store = stores[0]
    print(f"  自提门店: {store['storeName']} ({store['storeCode']}) "
          f"营业 {store.get('businessStartTime')}-{store.get('businessEndTime')}")

    periods = parse_periods(store, target)
    if periods:
        print("  官方时段: " + " | ".join(f"{p['name']} {p['start']}-{p['end']}" for p in periods))

    # 得来速门店(独立门店, 带 beCode)
    dt_be_code, dt_store_name = None, None
    try:
        dtr = client.call_tool("query-nearby-stores",
                               {"beType": 5, "searchType": 2, "city": city, "keyword": "麦当劳"})
        dt_stores = (dtr.get("data") or []) if dtr.get("success") else []
        if dt_stores:
            dt_be_code = dt_stores[0].get("beCode")
            dt_store_name = dt_stores[0].get("storeName")
            print(f"  得来速门店: {dt_store_name} (beCode={dt_be_code})")
    except McdMcpError as e:
        print(f"  得来速不可用: {e}")

    slots = build_slots(store.get("businessStartTime", "07:00"),
                        store.get("businessEndTime", "22:00"))
    print(f"  采样时刻: {len(slots)} 个 ({slots[0]} ~ {slots[-1]})")

    # ---- 锚点菜单普查 ----
    print("[菜单] 锚点时刻拉菜单 ...")
    anchor_menus: dict[str, list[dict[str, Any]]] = {}
    for t in ANCHOR_SLOTS:
        if t not in slots:
            continue
        try:
            r = client.call_tool("query-meals", {
                "beType": 1, "orderType": 1, "storeCode": store["storeCode"],
                "reservationDate": f"{target_date} {t}"})
            if r.get("success"):
                anchor_menus[t] = flatten_menu(r)
                print(f"  {t}: {len(anchor_menus[t])} 项")
        except McdMcpError as e:
            print(f"  {t}: 失败 {e}")

    basket = select_basket(anchor_menus)
    print(f"[商品] 探针商品 {len(basket)} 个, 按各自可售时段取名称 query-meal-detail ...")
    for it in basket:
        at = it.get("firstSlot") or "12:00"
        try:
            d = client.call_tool("query-meal-detail", {
                "beType": 1, "orderType": 1, "storeCode": store["storeCode"],
                "code": it["code"], "reservationDate": f"{target_date} {at}"})
            name = (d.get("data") or {}).get("name")
            it["name"] = name or it["category"]
        except McdMcpError:
            it["name"] = it["category"]
        print(f"  {it['code']} {it['name']} [{it['category']}] tags={it['tags']}")

    channels = [{"id": "pickup", "label": "到店自提", "beType": 1, "orderType": 1, "beCode": None}]
    if dt_be_code:
        channels.append({"id": "dt", "label": "得来速", "beType": 5, "orderType": 1, "beCode": dt_be_code})

    n_calls = len(slots) * len(basket) * len(channels)
    print(f"[核价] {len(slots)} 时刻 x {len(basket)} 商品 x {len(channels)} 渠道 = {n_calls} 次调用")
    if dry_run:
        print("  --dry-run: 到此为止, 未发起核价请求。")
        return {"city": city, "store": store, "periods": periods, "slots": slots,
                "basket": basket, "channels": channels, "grid": {}, "dryRun": True}

    grid: dict[str, dict[str, dict[str, Any]]] = {}
    err_count = 0
    for ch in channels:
        grid[ch["id"]] = {}
        for t in slots:
            slot_cells: dict[str, Any] = {}
            for it in basket:
                args: dict[str, Any] = {
                    "beType": ch["beType"], "orderType": ch["orderType"],
                    "storeCode": store["storeCode"],
                    "items": [{"productCode": it["code"], "quantity": 1}],
                    "reservationDate": f"{target_date} {t}",
                }
                if ch["beCode"]:
                    args["beCode"] = ch["beCode"]
                try:
                    r = client.call_tool("calculate-price", args)
                    if r.get("success"):
                        d = r.get("data") or {}
                        slot_cells[it["code"]] = {"price": d.get("price")}
                    else:
                        slot_cells[it["code"]] = {"unavailable": r.get("message", "")[:80]}
                except McdMcpError as e:
                    slot_cells[it["code"]] = {"unavailable": str(e)[:80]}
                    err_count += 1
            grid[ch["id"]][t] = slot_cells
            avail = sum(1 for c in slot_cells.values() if "price" in c)
            print(f"  [{ch['label']} {t}] 可售 {avail}/{len(basket)}")
    if err_count:
        print(f"  (其中不可售/失败 {err_count} 格 —— 断崖与真空带就是从这里显形的)")

    return {
        "city": city, "store": {"code": store["storeCode"], "name": store["storeName"],
                                "address": store.get("address"),
                                "businessStart": store.get("businessStartTime"),
                                "businessEnd": store.get("businessEndTime")},
        "periods": periods, "slots": slots, "basket": basket,
        "channels": channels, "grid": grid, "dryRun": False,
    }


def save_surface(results: list[dict[str, Any]], target: str, server_now: Any) -> Path:
    """把当前已采集的城市合并落盘。同名城市覆盖, 其余保留(分批采集可累加)。
    每采完一个城市就调一次 —— 上次四城普查崩在最后写盘, 40 分钟数据全丢, 教训。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "surface.json"
    prev_cities: list[dict[str, Any]] = []
    if out.exists():
        try:
            prev_cities = json.loads(out.read_text(encoding="utf-8")).get("cities") or []
        except json.JSONDecodeError:
            prev_cities = []
    merged = {c["city"]: c for c in prev_cities}
    for c in results:
        merged[c["city"]] = c
    final_cities = [merged[k] for k in merged]
    surface = {
        "project": "麦当劳几点最便宜 (mcd-when)",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "targetDate": target,
        "serverNow": server_now,
        "isDemo": False,
        "dataSource": "麦当劳中国官方 MCP (https://mcp.mcd.cn) calculate-price 实时返回, 单位: 分",
        "readOnlyGuarantee": sorted(READ_ONLY_TOOLS),
        "cities": final_cities,
    }
    out.write_text(json.dumps(surface, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="麦当劳几点最便宜 · 全天价格普查(今天跑明天)")
    parser.add_argument("--city", action="append",
                        help="城市名, 可多次传入; 不传则用 config.json 的 defaultCities")
    parser.add_argument("--dry-run", action="store_true", help="只打印采样计划, 不发核价请求")
    args = parser.parse_args()

    cfg = load_config()
    cities = args.city or cfg.get("defaultCities") or ["上海"]

    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        print("缺少 MCD_MCP_TOKEN 环境变量。请先设置(建议放在 .env, 已被 gitignore)。")
        return 1
    client = McdMcpClient(token)

    print("[校时] now-time-info ...")
    now = client.call_tool("now-time-info")
    d = (now.get("data") or {})
    today = d.get("date") or datetime.now().strftime("%Y-%m-%d")
    target = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"  服务端今天 {today} -> 普查目标日期 {target}")

    results = []
    for city in args.city:
        try:
            results.append(survey_city(client, city, target, args.dry_run))
            if not args.dry_run:
                out = save_surface(results, target, d.get("formatted"))
                print(f"  [落盘] {city} 已写入 {out.name}")
        except McdMcpError as e:
            print(f"[跳过] {city}: {e}")

    if args.dry_run:
        return 0

    out = save_surface(results, target, d.get("formatted"))
    final_cities = json.loads(out.read_text(encoding="utf-8"))["cities"]
    total = sum(len(r["grid"].get(ch["id"], {}).get(t, {}))
                for r in final_cities for ch in r["channels"] for t in r["slots"])
    print(f"\n普查完成 -> {out} | 数据点 {total} | 城市 {len(final_cities)} "
          f"({', '.join(c['city'] for c in final_cities)})")
    print("下一步: python src/render_report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
