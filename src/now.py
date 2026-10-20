"""
now.py — 即时决策: 此刻这家店「最便宜能吃到什么」, 以及「再等多久进入下一个更便宜的时段」

定位: 矩阵回答「全天规律」, 这个脚本回答「我现在该怎么办」。
     README 的钩子需要一句「打开就能用」的回答, 就是它。

用法:
  python src/now.py --city 上海 [--keyword 麦当劳] [--json]

链路(全部只读):
  now-time-info        服务端当前时刻(校时)
  query-nearby-stores  城市+关键词 -> 门店 + 官方时段表(reservationTimeOptions)
  query-meals          当前时刻的可售菜单(预约时刻 = 当前 + PREP_MINUTES 分钟)
  calculate-price      对可售商品逐个核价, 找最便宜的一套
  query-meals          再对「下一时段开场时刻」取菜单, 找下一时段的最便宜吃法
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_client import McdMcpClient, McdMcpError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PREP_MINUTES = 10          # 预约时刻 = 当前 + 10 分钟(下单到取餐的缓冲)
MAX_PRICE_CHECK = 24       # 当前时段最多核价的商品数(控制调用量)
NEXT_SLOT_CHECK = 12       # 下一时段最多核价的商品数


PERIOD_RE = re.compile(r"([^\s(（,，]+)\s*[（(](\d{2}:\d{2})\s*至\s*(\d{2}:\d{2})[)）]")


def parse_periods(store: dict) -> tuple[list[dict], list[dict]]:
    """reservationTimeOptions 按日期分组, 时段在 reservationOptionText 文本里。
    返回 (今天时段, 明天时段)。"""
    today: list[dict] = []
    tomorrow: list[dict] = []
    for opt in (store.get("reservationTimeOptions") or []):
        text = opt.get("reservationOptionText") or ""
        parsed = [{"name": m.group(1), "start": m.group(2), "end": m.group(3)}
                  for m in PERIOD_RE.finditer(text)]
        if not parsed:
            continue
        if opt.get("today"):
            today = parsed
        elif not tomorrow:
            tomorrow = parsed
    return today, tomorrow


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def fmt_min(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def get_menu(client: McdMcpClient, store: dict, when: str) -> list[dict]:
    """取某时刻可售菜单, 摊平为 [{code, name, category}]。"""
    r = client.call_tool("query-meals", {
        "beType": 1, "orderType": 1,
        "storeCode": store["storeCode"], "reservationDate": when,
    })
    cats = (r.get("data") or {}).get("categories") or []
    out = []
    for cat in cats:
        for meal in (cat.get("meals") or []):
            out.append({"code": meal.get("code"), "name": meal.get("name"),
                        "category": cat.get("name")})
    return [m for m in out if m.get("code")]


def cheapest(client: McdMcpClient, store: dict, items: list[dict],
             when: str, limit: int) -> dict | None:
    """在 items 里逐个核价, 返回最便宜的可售商品(胜出者补一次详情拿名字)。"""
    best = None
    checked = 0
    for it in items:
        if checked >= limit:
            break
        checked += 1
        try:
            r = client.call_tool("calculate-price", {
                "beType": 1, "orderType": 1, "storeCode": store["storeCode"],
                "items": [{"productCode": it["code"], "quantity": 1}],
                "reservationDate": when,
            })
        except McdMcpError:
            continue
        if not r.get("success"):
            continue
        data = r.get("data") or {}
        price = data.get("totalPrice") or data.get("price")
        if isinstance(price, (int, float)) and (best is None or price < best["price"]):
            best = {**it, "price": int(price)}
    if best and not best.get("name"):
        try:
            d = client.call_tool("query-meal-detail", {
                "beType": 1, "orderType": 1, "storeCode": store["storeCode"],
                "code": best["code"], "reservationDate": when})
            best["name"] = (d.get("data") or {}).get("name") or best["code"]
        except McdMcpError:
            best["name"] = best["code"]
    return best


def run(city: str, keyword: str) -> dict:
    token = __import__("os").environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        raise SystemExit("未设置 MCD_MCP_TOKEN 环境变量。")
    client = McdMcpClient(token)

    # 1) 服务端校时
    now_info = client.call_tool("now-time-info", {})
    server_now = (now_info.get("data") or {}).get("formatted") or ""
    try:
        now_dt = datetime.strptime(server_now[:16], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        now_dt = datetime.now()
    cur_min = now_dt.hour * 60 + now_dt.minute

    # 2) 门店 + 官方时段表
    r = client.call_tool("query-nearby-stores", {
        "beType": 1, "searchType": 2, "city": city, "keyword": keyword})
    stores = r.get("data") or []
    if not stores:
        raise SystemExit(f"在「{city}」用关键词「{keyword}」没找到门店, 换个关键词试试。")
    store = stores[0]
    today_periods, tomorrow_periods = parse_periods(store)
    periods = today_periods

    # 3) 当前时段判定
    order_at = now_dt + timedelta(minutes=PREP_MINUTES)
    order_min = order_at.hour * 60 + order_at.minute
    cur_period = next((p for p in periods
                       if to_min(p["start"]) <= order_min < to_min(p["end"])), None)

    result: dict = {
        "city": city, "store": store.get("storeName"), "serverNow": now_dt.strftime("%H:%M"),
        "orderAt": order_at.strftime("%H:%M"), "periods": periods,
    }

    if cur_period is None:
        # 当前落在真空带或营业外: 今天找下一时段, 没了就跨到明天第一档
        nxt = next((p for p in periods if to_min(p["start"]) > order_min), None)
        nxt_date = now_dt.date()
        if nxt is None and tomorrow_periods:
            nxt = tomorrow_periods[0]
            nxt_date = (now_dt + timedelta(days=1)).date()
        result["state"] = "gap"
        result["next"] = nxt
        if nxt:
            wait = to_min(nxt["start"]) - order_min
            if nxt_date != now_dt.date():
                wait += 24 * 60
            result["waitMinutes"] = wait
            result["nextIsTomorrow"] = nxt_date != now_dt.date()
            when = f"{nxt_date} {nxt['start']}"
            menu = get_menu(client, store, when)
            best = cheapest(client, store, menu, when, NEXT_SLOT_CHECK)
            result["nextCheapest"] = best
        return result

    # 4) 当前时段最便宜
    when_now = order_at.strftime("%Y-%m-%d %H:%M")
    menu_now = get_menu(client, store, when_now)
    best_now = cheapest(client, store, menu_now, when_now, MAX_PRICE_CHECK)
    result["state"] = "open"
    result["period"] = cur_period
    result["cheapest"] = best_now

    # 5) 下一时段对比
    nxt = next((p for p in periods if to_min(p["start"]) >= to_min(cur_period["end"])), None)
    if nxt:
        wait = to_min(nxt["start"]) - order_min
        result["next"] = nxt
        result["waitMinutes"] = wait
        when = f"{now_dt.date()} {nxt['start']}"
        menu_nxt = get_menu(client, store, when)
        best_nxt = cheapest(client, store, menu_nxt, when, NEXT_SLOT_CHECK)
        result["nextCheapest"] = best_nxt
    return result


def human(result: dict) -> str:
    lines = [f"门店: {result['store']}({result['city']}) · 服务端时间 {result['serverNow']}"]
    if result["state"] == "gap":
        lines.append("现在正处「菜单真空带」—— 上一档已收, 下一档未开。")
        if result.get("next"):
            n = result["next"]
            day = "明天" if result.get("nextIsTomorrow") else "今天"
            lines.append(f"再等 {result['waitMinutes']} 分钟, {day}{n['name']}档 {n['start']} 开档。")
            b = result.get("nextCheapest")
            if b:
                lines.append(f"开档后最便宜的一口: {b['name']} ¥{b['price'] / 100:.2f}")
        return "\n".join(lines)

    p = result["period"]
    b = result.get("cheapest")
    lines.append(f"现在是{p['name']}档({p['start']}–{p['end']})。")
    if b:
        lines.append(f"此刻最便宜能吃到的: {b['name']} ¥{b['price'] / 100:.2f}")
    if result.get("next") and result.get("nextCheapest"):
        n, nb = result["next"], result["nextCheapest"]
        lines.append(f"{result['waitMinutes']} 分钟后进入{n['name']}档({n['start']}起), "
                     f"届时最便宜: {nb['name']} ¥{nb['price'] / 100:.2f}")
        if b and nb["price"] < b["price"]:
            save = (b["price"] - nb["price"]) / 100
            lines.append(f"👉 等 {result['waitMinutes']} 分钟, 立省 ¥{save:.2f}。")
        elif b and nb["price"] >= b["price"]:
            lines.append("👉 现在下单更划算, 下一档没有更便宜的选择。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="麦当劳几点最便宜 · 此刻决策")
    ap.add_argument("--city", required=True, help="城市名, 如 上海")
    ap.add_argument("--keyword", default="麦当劳", help="门店搜索关键词, 默认 麦当劳")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非人类可读文本")
    args = ap.parse_args()
    result = run(args.city, args.keyword)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(human(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
