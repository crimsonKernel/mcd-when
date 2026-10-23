"""mcp_server.py — 麦当劳这个点卖什么 · 本地 MCP Server

把我们已经采到的全国数据集(388 城 / 36200 次真实问价)包成标准 MCP 工具,
让任何支持 MCP 的 AI 客户端(WorkBuddy / Claude Code / Cursor / Cherry Studio)
直接用自然语言问「这个点麦当劳卖什么、多少钱、¥X 能凑多饱」。

数据层保留了「哪档最便宜 / 全国排名」这类工具(cheapest_period / city_ranking),
它们是数据事实, 不是产品问题 —— 站点 1.2 起不拿「几点最便宜」当问题,
但数据接口照旧提供, 由 AI 客户端自行决定怎么用。

设计原则(与 static 页一致):
  取数交给数据, 算术交给代码, 表达交给 Agent。
  本 Server 不调用任何写操作, 全部答案来自本地数据集或用户自己的 Token
  对官方 MCP 的只读调用。

传输: stdio, 换行分隔的 JSON-RPC 2.0(MCP 标准 stdio transport)。
依赖: 纯 Python 标准库, 3.10+。

用法:
    # 1) 直接以 MCP Server 方式启动(由客户端拉起)
    python src/mcp_server.py

    # 2) 手动自测: 发一行 JSON-RPC 进去
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python src/mcp_server.py

客户端配置见 mcp-when-config.example.json。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
NATIONAL_PATH = DATA_DIR / "surface_national.json"
BATCH_PATH = DATA_DIR / "surface_batch.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from combo import best_combo, candidates, menu_of  # noqa: E402

SERVER_NAME = "mcd-when"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

# 数据源优先级: 全菜单采集(修 bug 后重跑的那份) > 全国探针快照
FULL_MENU_MIN_CITIES = 50


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_dataset() -> dict[str, Any]:
    """返回 {meta, cities:{city: record}, menu_source}"""
    national = _load(NATIONAL_PATH) or {}
    batch = _load(BATCH_PATH) or {}
    cities: dict[str, Any] = {}
    for c in national.get("cities") or []:
        if c.get("city"):
            cities[c["city"]] = c
    menu_source = "probe"
    if len(batch.get("cities") or []) >= FULL_MENU_MIN_CITIES:
        for c in batch["cities"]:
            if c.get("city"):
                cities[c["city"]] = c
        menu_source = "full"
    meta = {
        "generatedAt": (batch.get("generatedAt") if menu_source == "full"
                        else national.get("generatedAt")) or "未知",
        "targetDate": (batch.get("targetDate") if menu_source == "full"
                       else national.get("targetDate")) or "未知",
        "cities": len(cities),
        "menuSource": menu_source,
        "dataSource": (batch if menu_source == "full" else national).get(
            "dataSource", "麦当劳中国官方 MCP"),
    }
    return {"meta": meta, "cities": cities, "menu_source": menu_source}


def _fen(yuan: float) -> int:
    return int(round(yuan * 100))


def _yuan(fen: int) -> str:
    return "¥%.2f" % (fen / 100)


def _to_min(t: str) -> int:
    try:
        h, m = str(t).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, IndexError):
        return 0


# ---------------------------------------------------------------- 工具实现

def tool_cheapest_period(ds: dict, args: dict) -> dict:
    city = (args.get("city") or "").strip()
    if not city:
        raise ValueError("city 不能为空")
    c = ds["cities"].get(city)
    if c is None:                       # 支持「上海/上海市」这类写法
        for k in ds["cities"]:
            if k.startswith(city) or city.startswith(k):
                c = ds["cities"][k]
                city = k
                break
    if c is None:
        raise ValueError(
            f"没有「{city}」的数据。已覆盖 {ds['meta']['cities']} 座城市, "
            f"可用 city_ranking 看全国榜单。")

    floors = (c.get("floors") or {}).get("pickup") or {}
    rows = []
    for p in c.get("periods") or []:
        f = floors.get(p["name"]) or {}
        meal, any_ = f.get("meal"), f.get("any")
        rows.append({
            "period": p["name"], "start": p["start"], "end": p["end"],
            "cheapest_meal": ({"name": meal["name"], "price_fen": meal["price"],
                               "price": _yuan(meal["price"])} if meal else None),
            "cheapest_any": ({"name": any_["name"], "price_fen": any_["price"],
                              "price": _yuan(any_["price"])} if any_ else None),
        })
    best = None
    for r in rows:
        cand = r["cheapest_meal"] or r["cheapest_any"]
        if cand and (best is None or cand["price_fen"] < best["price_fen"]):
            best = {"period": r["period"], **cand}
    return {
        "city": city,
        "province": c.get("province", ""),
        "store": (c.get("store") or {}).get("name", ""),
        "business_hours": [(c.get("store") or {}).get("businessStart") or "07:00",
                           (c.get("store") or {}).get("businessEnd") or "22:00"],
        "periods": rows,
        "cheapest": best,
        "data_generated_at": ds["meta"]["generatedAt"],
    }


def tool_city_ranking(ds: dict, args: dict) -> dict:
    period = (args.get("period") or "").strip() or None
    limit = int(args.get("limit") or 10)
    rows = []
    for name, c in ds["cities"].items():
        floors = (c.get("floors") or {}).get("pickup") or {}
        if period:
            f = floors.get(period) or {}
            meal = f.get("meal") or f.get("any")
            if not meal:
                continue
            rows.append({"city": name, "province": c.get("province", ""),
                         "item": meal["name"], "price_fen": meal["price"],
                         "price": _yuan(meal["price"])})
        else:
            best = None
            for p in c.get("periods") or []:
                f = floors.get(p["name"]) or {}
                m = f.get("meal") or f.get("any")
                if m and (best is None or m["price"] < best["price_fen"]):
                    best = {"period": p["name"], "item": m["name"],
                            "price_fen": m["price"]}
            if best:
                rows.append({"city": name, "province": c.get("province", ""),
                             "period": best["period"], "item": best["item"],
                             "price_fen": best["price_fen"],
                             "price": _yuan(best["price_fen"])})
    rows.sort(key=lambda r: r["price_fen"])
    return {
        "period": period or "全天最便宜时段",
        "ranking": rows[:limit],
        "total_cities": len(rows),
        "data_generated_at": ds["meta"]["generatedAt"],
    }


def _menu_of(c: dict) -> dict[str, dict[str, Any]]:
    """商品码 -> {name, category, kind, periods, prices:{时段: 分}}"""
    return menu_of(c)


def tool_city_menu(ds: dict, args: dict) -> dict:
    city = (args.get("city") or "").strip()
    period = (args.get("period") or "").strip() or None
    c = ds["cities"].get(city)
    if c is None:
        for k in ds["cities"]:
            if k.startswith(city) or city.startswith(k):
                c = ds["cities"][k]
                city = k
                break
    if c is None:
        raise ValueError(f"没有「{city}」的数据")
    menu = _menu_of(c)
    items = []
    for code, m in menu.items():
        if period and period not in (m["periods"] or [period]):
            continue
        if not m["prices"]:
            continue
        price = m["prices"].get(period) if period else min(m["prices"].values())
        items.append({"code": code, "name": m["name"], "kind": m["kind"],
                      "category": m["category"],
                      "periods": sorted(m["prices"].keys()),
                      "price_fen": price, "price": _yuan(price)})
    items.sort(key=lambda x: x["price_fen"])
    return {
        "city": city, "period": period or "各时段最低价",
        "menu_source": ds["meta"]["menuSource"],
        "item_count": len(items),
        "items": items,
        "note": ("full=全菜单采集; probe=12 个探针商品的采样, "
                 "完整菜单需先跑 src/survey_batch.py --force"),
    }


def tool_combo_under_budget(ds: dict, args: dict) -> dict:
    """预算内最「饱」的搭配: 在可选商品里做 0/1 背包, 最大化件数, 并列时取更省钱的。"""
    city = (args.get("city") or "").strip()
    budget = args.get("budget_yuan")
    period = (args.get("period") or "").strip() or None
    if budget is None:
        raise ValueError("budget_yuan 不能为空(单位: 元, 如 20)")
    limit = _fen(float(budget))
    c = ds["cities"].get(city)
    if c is None:
        for k in ds["cities"]:
            if k.startswith(city) or city.startswith(k):
                c = ds["cities"][k]
                city = k
                break
    if c is None:
        raise ValueError(f"没有「{city}」的数据")

    cands = [x for x in candidates(c, period) if x["price_fen"] <= limit]
    if not cands:
        return {"city": city, "budget": _yuan(limit), "combo": [],
                "note": "该条件下没有可预算内可售商品"}

    # 0/1 背包。「有主食」是硬约束: 预算装不下主食时返回空,
    # 由调用方说「预算不够吃一顿正经饭」, 而不是拿两个冰淇淋冒充一顿午饭。
    best_k, picked, has_meal = best_combo(cands, limit)
    if not has_meal:
        # 注意从「未按预算过滤」的候选里找最便宜主食, 否则提示不了还差多少钱
        all_cands = candidates(c, period)
        meals = [x for x in all_cands if x["kind"] == "meal"]
        cheapest = min(meals, key=lambda x: x["price_fen"]) if meals else None
        return {
            "city": city, "period": period or "不限时段", "budget": _yuan(limit),
            "combo": [], "total_fen": 0, "total": _yuan(0),
            "insufficient": True,
            "cheapest_single": ({"name": cheapest["name"],
                                 "price": _yuan(cheapest["price_fen"])}
                                if cheapest else None),
            "note": (f"{_yuan(limit)} 在这个时段吃不到一顿正经饭"
                     + (f", 最便宜的一餐是 {cheapest['name']} "
                        f"{_yuan(cheapest['price_fen'])}"
                        f"(还差 {_yuan(cheapest['price_fen'] - limit)})"
                        if cheapest else "")),
            "menu_source": ds["meta"]["menuSource"],
        }
    combo = [{"name": x["name"], "kind": x["kind"],
              "price_fen": x["price_fen"],
              "price": _yuan(x["price_fen"])} for x in picked]
    # 也给出"最便宜的一顿"作为对照
    meals = [x for x in cands if x["kind"] == "meal"]
    cheapest = min(meals, key=lambda x: x["price_fen"]) if meals else min(
        cands, key=lambda x: x["price_fen"])
    return {
        "city": city, "period": period or "不限时段", "budget": _yuan(limit),
        "combo": combo,
        "total_fen": best_k, "total": _yuan(best_k),
        "saved_vs_budget": _yuan(limit - best_k),
        "cheapest_single": {"name": cheapest["name"],
                            "price": _yuan(cheapest["price_fen"])},
        "menu_source": ds["meta"]["menuSource"],
    }


def tool_data_freshness(ds: dict, args: dict) -> dict:
    m = ds["meta"]
    return {
        "data_generated_at": m["generatedAt"],
        "data_target_date": m["targetDate"],
        "cities": m["cities"],
        "menu_source": m["menuSource"],
        "data_source": m["dataSource"],
        "note": ("快照数据。麦当劳的标价跨天 98.1% 一致(387 城 12552 个单元格实测), "
                 "但促销价会变(实测麦咖啡冰奶铁中杯曾从 ¥13.90 回到 ¥21.00); "
                 "需要最新价时请用你自己的 MCD_MCP_TOKEN 调官方 MCP。"),
    }


TOOLS = [
    {
        "name": "cheapest_period",
        "description": ("查一座城市麦当劳全天哪个时段最便宜: 各时段开场/收场时间、"
                        "该时段最便宜的一餐、以及全天最便宜时刻。基于全国 388 城真实问价快照。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名, 如 上海/拉萨/三明"},
            },
            "required": ["city"],
        },
        "handler": tool_cheapest_period,
    },
    {
        "name": "city_ranking",
        "description": ("全国比价榜: 哪座城市麦当劳最便宜。可指定时段(早餐/午餐/下午茶/夜市), "
                        "不指定则按各城全天最便宜时段排名。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "时段名, 可留空"},
                "limit": {"type": "integer", "description": "返回前 N 名, 默认 10"},
            },
        },
        "handler": tool_city_ranking,
    },
    {
        "name": "city_menu",
        "description": ("拉一座城市某时段的在售菜单和价格(按价格升序)。"
                        "menu_source=full 时为全菜单, probe 时为探针采样。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "period": {"type": "string", "description": "早餐/午餐/下午茶/夜市, 可留空"},
            },
            "required": ["city"],
        },
        "handler": tool_city_menu,
    },
    {
        "name": "combo_under_budget",
        "description": ("预算内怎么点最「像一顿饭」: 给定城市+时段+预算(元), 用 0/1 背包"
                        "在本地菜单数据里求「保证有主食的前提下件数最多」的搭配, "
                        "并给出最便宜的单品作对照。零 Token, 纯本地计算。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "budget_yuan": {"type": "number", "description": "预算, 单位元, 如 20"},
                "period": {"type": "string", "description": "时段, 可留空"},
            },
            "required": ["city", "budget_yuan"],
        },
        "handler": tool_combo_under_budget,
    },
    {
        "name": "data_freshness",
        "description": "数据集元信息: 采集时间、目标日期、覆盖城市数、菜单数据完整度。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_data_freshness,
    },
]


# ---------------------------------------------------------------- JSON-RPC

def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(req_id: Any, result: Any) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id,
           "error": {"code": code, "message": message}})


def handle(ds: dict, msg: dict) -> None:
    method = msg.get("method")
    req_id = msg.get("id")

    if req_id is None:                    # 通知, 不应答
        return
    if method == "initialize":
        _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    elif method == "ping":
        _result(req_id, {})
    elif method == "tools/list":
        _result(req_id, {"tools": [
            {k: v for k, v in t.items() if k != "handler"} for t in TOOLS]})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            _error(req_id, -32602, f"未知工具: {name}")
            return
        try:
            data = tool["handler"](ds, args)
            _result(req_id, {"content": [
                {"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}],
                "isError": False})
        except Exception as e:            # noqa: BLE001
            _result(req_id, {"content": [
                {"type": "text", "text": f"错误: {e}"}], "isError": True})
    else:
        _error(req_id, -32601, f"不支持的方法: {method}")


def main() -> int:
    ds = load_dataset()
    sys.stderr.write(
        f"[{SERVER_NAME}] 数据集就绪: {ds['meta']['cities']} 城, "
        f"菜单完整度={ds['meta']['menuSource']}, "
        f"采集于 {ds['meta']['generatedAt']}\n")
    sys.stderr.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _error(None, -32700, "JSON 解析失败")
            continue
        handle(ds, msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
