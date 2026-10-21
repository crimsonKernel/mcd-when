"""survey_national.py — 全国普查(上百座城市)

相比最初的 survey.py, 这一版建立在一个**实测结论**之上, 调用量因此降了一个数量级:

  实测(5 城 7000 个数据点): 同一商品的价格在一天内恒定, 变的只是"这个时段卖不卖"。
    上海/北京/广州/成都/武汉 20 个探针商品, 0 个出现时段差价。

  所以不必再「31 个时刻 × 20 个商品」地毯式核价, 只要:
    [1] 每个时段拉一次菜单(query-meals) -> 该时段卖什么, 一次调用全知道
    [2] 每个商品在它出现的每个时段核一次价(calculate-price) -> 价格与可售性
  调用量从 ~1200 次/城 降到 ~90 次/城, 上百座城市才跑得动。

另外两处实测发现, 本脚本会把它们固化成数据:
  - 时段边界随门店走: 重庆门店 08:00 开门 -> 早餐 08:14 才开档; 东北多为 05:14。
  - 自提 vs 得来速存在真实价差(上海 270 格里 83 格不同, 且双向), 所以渠道仍然要采。

用法:
    python src/survey_national.py --limit 10         # 先跑 10 座(按优先级)
    python src/survey_national.py                    # 全量(后台跑)
    python src/survey_national.py --city 苏州 --city 义乌
    python src/survey_national.py --resume           # 断点续跑(跳过已采城市)

产出: data/surface_national.json(每采完一座城市立刻落盘, 崩了也不丢)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from cities_cn import city_meta  # noqa: E402
from mcd_client import McdMcpClient, McdMcpError, RateLimiter  # noqa: E402
from survey import flatten_menu, parse_periods  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROBE_PATH = DATA_DIR / "cities-probe.json"
OUT_PATH = DATA_DIR / "surface_national.json"

# 只读白名单(硬约束)
READ_ONLY_TOOLS = {
    "now-time-info", "query-nearby-stores", "query-meals",
    "query-meal-detail", "calculate-price",
}

BASKET_KEYWORDS = ["早餐", "下午茶", "夜市", "人气热卖", "超值", "随心配", "1+1"]
MAX_ITEMS = 20               # 探针商品上限(决定调用量)
PER_PERIOD_ITEMS = 6         # 每个时段至少要有这么多主食候选(否则该档地板价会被漏掉)

# 商品分三类 —— 这直接决定"最便宜"这个答案是不是一个能入口的东西
#   meal  正餐: 汉堡/卷/饭/粥/早餐组合/随心配/分享餐 ...      -> 主答案用
#   side  小食饮品: 咖啡/雪冰/麦旋风/薯条/派/炸鸡小份 ...     -> 副行"垫一口"
#   extra 配件: 蘸酱包/餐具/纸巾 ...                      -> 不参与任何排名
#
# 判错方向的代价是不对称的:
#   把饮品/小食判成正餐 -> 页面会告诉你"最便宜的一餐是热巧克力"(荒唐, 直接失信)
#   把正餐判成小食     -> 只是地板价偏高一点(保守, 可接受)
# 所以: 小食饮品词表要尽量全, 且两者都不命中时默认判 side(宁可少报, 不可错报)。
MEAL_WORDS = ["堡", "卷", "饭", "面", "粥", "麦满分", "组合", "套餐", "件套", "随心配",
              "分享餐", "多人餐", "双人餐", "亲子餐", "巨无霸", "麦香鱼", "板烧", "安格斯",
              "皇堡", "猪柳", "吉士", "双层", "鳕鱼", "牛柳", "鸡腿"]
SIDE_WORDS = ["派", "薯条", "薯格", "薯饼", "圆筒", "冰淇淋", "圣代", "麦旋风", "雪冰", "新地",
              "阿芙佳朵", "咖啡", "美式", "拿铁", "奶铁", "卡布", "摩卡", "玛奇朵", "红茶", "奶茶",
              "奶绿", "豆浆", "牛奶", "可乐", "雪碧", "果汁", "苹果汁", "怡泉", "纯悦", "玉米",
              "苹果片", "香肠", "芝士条", "油条", "糍粑", "饼干", "爆爆珠", "麦炫酷", "柠檬",
              "黄金橙", "柚", "茶", "饮料", "气泡", "可可", "黑巧", "抹茶", "燕麦", "椰奶",
              "酸奶", "冰糖葫芦", "百宝袋", "扭扭薯", "麦乐鸡", "鸡块", "鸡翅", "鸡排", "虾",
              "鸡柳", "小圆子", "饮品", "雪冻", "冰饮", "热饮", "苏打", "果肉", "椰果"]
# 分类文本里出现这些, 基本可确定不是一顿饭
SIDE_CATEGORY_HINTS = ["麦咖啡", "饮品", "饮料", "甜品", "小食", "雪冰", "麦旋风", "冰淇淋",
                       "圣代", "派", "薯", "饮料", "豆浆", "牛奶"]
EXCLUDE_SUFFIX = ["酱", "料", "勺", "叉", "纸巾", "吸管", "杯套"]
MIN_FOOD_PRICE = 500         # ¥5 以下一律视为配件(实测「北美招牌牧场酱」¥3 会污染地板价)


def classify(name: str, category: str) -> str:
    """把商品分成 meal / side / extra。名称优先, 分类兜底, 都不命中默认 side。"""
    n = (name or category or "").strip()
    cat = category or ""
    if any(n.endswith(s) for s in EXCLUDE_SUFFIX) and not any(
            w in n for w in ("堡", "卷", "鸡", "条", "块", "饭")):
        return "extra"
    if any(w in n for w in SIDE_WORDS):
        return "side"
    if any(h in cat for h in SIDE_CATEGORY_HINTS):
        return "side"
    if any(w in n for w in MEAL_WORDS):
        return "meal"
    return "side"          # 保守: 认不出是什么的一律不当正餐
DEFAULT_PERIODS = [
    {"name": "早餐", "start": "07:14", "end": "10:15"},
    {"name": "午餐", "start": "10:44", "end": "14:15"},
    {"name": "下午茶", "start": "14:44", "end": "16:45"},
    {"name": "夜市", "start": "17:14", "end": "21:45"},
]

_write_lock = threading.Lock()
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def hhmm(t: str) -> int:
    h, m = t.split(":")[:2]
    return int(h) * 60 + int(m)


def mid(start: str, end: str) -> str:
    """时段中点(对齐到 1 分钟)。"""
    m = (hhmm(start) + hhmm(end)) // 2
    return f"{m // 60:02d}:{m % 60:02d}"


def pick_basket(period_menus: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """按**时段**圈定探针。

    教训: 第一版是全局选 16 个, 结果早餐品类多的城市(上海)把名额占满,
    午餐档的「随心配/1+1」根本没进篮 -> 午餐地板价被一杯咖啡顶替。
    所以改成: 每个时段各自挑够候选, 再合并去重。
    """
    seen: dict[str, dict[str, Any]] = {}
    for pname, items in period_menus.items():
        meals = [it for it in items
                 if classify(it.get("category", ""), it.get("category", "")) != "extra"]
        # 该时段的"便宜档"分类优先(早餐/超值/随心配/1+1/小食), 其余主食补位
        cheap = [it for it in meals if any(k in (it.get("category") or "") for k in BASKET_KEYWORDS)]
        picked: list[dict[str, Any]] = []
        for it in cheap + meals:
            if len(picked) >= PER_PERIOD_ITEMS:
                break
            if any(p["code"] == it["code"] for p in picked):
                continue
            picked.append(it)
        for it in picked:
            if it["code"] not in seen:
                seen[it["code"]] = {**it, "firstPeriod": pname, "periods": [pname]}
            elif pname not in seen[it["code"]]["periods"]:
                seen[it["code"]]["periods"].append(pname)
    return list(seen.values())[:MAX_ITEMS]


def periods_of(probe: dict[str, Any], cand: dict[str, Any] | None, target_date: str) -> list[dict[str, str]]:
    """候选门店自己的时段表(每家可能不同), 拿不到就退回城市级那份。"""
    if cand and cand.get("options"):
        p = parse_periods({"reservationTimeOptions": cand["options"]}, target_date)
        if p:
            return p
    return probe.get("periods") or DEFAULT_PERIODS


def survey_city(client: McdMcpClient, probe: dict[str, Any], target_date: str,
                with_dt: bool = True) -> dict[str, Any]:
    city = probe["city"]
    rep_code = (probe.get("store") or {}).get("code")
    # 候选门店: 代表门店优先, 其余兜底 —— 实测有门店返回「600056 餐厅不支持预约」,
    # 只认一家的话整座城市就采不到
    cands: list[dict[str, Any]] = list(probe.get("candidates") or [])
    if not cands:
        cands = [{"code": rep_code, "name": (probe.get("store") or {}).get("name"),
                  "businessStart": (probe.get("store") or {}).get("businessStart"),
                  "businessEnd": (probe.get("store") or {}).get("businessEnd"),
                  "options": None}]
    cands.sort(key=lambda c: 0 if c.get("code") == rep_code else 1)
    calls = 0

    # ---- 0. 先给候选门店"探活": 谁能拉到菜单就用谁 ----
    chosen: dict[str, Any] | None = None
    periods: list[dict[str, str]] = []
    first_menu: tuple[str, list[dict[str, Any]]] | None = None
    for cand in cands[:5]:
        if not cand.get("code"):
            continue
        per = periods_of(probe, cand, target_date)
        t = mid(per[0]["start"], per[0]["end"])
        try:
            r = client.call_tool("query-meals", {
                "beType": 1, "orderType": 1, "storeCode": cand["code"],
                "reservationDate": f"{target_date} {t}"})
            calls += 1
        except McdMcpError:
            continue
        if r.get("success"):
            chosen, periods = cand, per
            first_menu = (per[0]["name"], flatten_menu(r))
            break
    if chosen is None:
        raise McdMcpError(f"{city}: 候选门店均不支持预约取餐(600056)")
    store = chosen
    store_code = store["code"]

    # ---- 1. 得来速门店(独立门店, 带 beCode) ----
    dt: dict[str, Any] | None = None
    if with_dt:
        try:
            r = client.call_tool("query-nearby-stores",
                                 {"beType": 5, "searchType": 2, "city": probe.get("queryName") or city,
                                  "keyword": "麦当劳"})
            calls += 1
            lst = (r.get("data") or []) if r.get("success") else []
            if lst and lst[0].get("beCode"):
                dt = {"label": "得来速", "beType": 5, "orderType": 1, "beCode": lst[0]["beCode"],
                      "storeCode": lst[0].get("storeCode"), "storeName": lst[0].get("storeName")}
        except McdMcpError:
            dt = None

    # ---- 2. 各时段菜单(一次调用拿到整档在售清单, 探活那一档直接复用) ----
    period_menus: dict[str, list[dict[str, Any]]] = {}
    if first_menu:
        period_menus[first_menu[0]] = first_menu[1]
    for p in periods:
        if p["name"] in period_menus:
            continue
        t = mid(p["start"], p["end"])
        try:
            r = client.call_tool("query-meals", {
                "beType": 1, "orderType": 1, "storeCode": store_code,
                "reservationDate": f"{target_date} {t}"})
            calls += 1
            if r.get("success"):
                period_menus[p["name"]] = flatten_menu(r)
        except McdMcpError:
            continue
    if not period_menus:
        raise McdMcpError(f"{city}: 菜单拉取失败")

    basket = pick_basket(period_menus)
    if not basket:
        raise McdMcpError(f"{city}: 探针商品为空")

    # ---- 3. 商品名(只在它首次出现的时段取详情) ----
    for it in basket:
        pname = it.get("firstPeriod")
        t = mid(next(p["start"] for p in periods if p["name"] == pname),
                next(p["end"] for p in periods if p["name"] == pname))
        try:
            d = client.call_tool("query-meal-detail", {
                "beType": 1, "orderType": 1, "storeCode": store_code,
                "code": it["code"], "reservationDate": f"{target_date} {t}"})
            calls += 1
            it["name"] = ((d.get("data") or {}).get("name")) or it["category"]
        except McdMcpError:
            it["name"] = it["category"]
        it["kind"] = classify(it["name"], it.get("category", ""))

    # ---- 4. 核价: 自提每档, 得来速首档(同时刻, 可直接比价) ----
    prices: dict[str, dict[str, dict[str, Any]]] = {"pickup": {}, "dt": {}}
    for it in basket:
        prices["pickup"][it["code"]] = {}
        if dt:
            prices["dt"][it["code"]] = {}

    def price_at(be_type: int, order_type: int, be_code: str | None,
                 code: str, when: str) -> int | None:
        args: dict[str, Any] = {
            "beType": be_type, "orderType": order_type, "storeCode": store_code,
            "items": [{"productCode": code, "quantity": 1}],
            "reservationDate": f"{target_date} {when}",
        }
        if be_code:
            args["beCode"] = be_code
        try:
            r = client.call_tool("calculate-price", args)
        except McdMcpError:
            return None
        return (r.get("data") or {}).get("price") if r.get("success") else None

    for p in periods:
        t = mid(p["start"], p["end"])
        codes = {i["code"] for i in period_menus.get(p["name"], [])}
        for it in basket:
            if it["code"] not in codes:
                continue
            v = price_at(1, 1, None, it["code"], t)
            calls += 1
            prices["pickup"][it["code"]][p["name"]] = v
            if dt:
                v2 = price_at(5, 1, dt["beCode"], it["code"], t)
                calls += 1
                prices["dt"][it["code"]][p["name"]] = v2

    # ---- 5. 两个"断崖"证据: 开档前 1 分钟 / 菜单真空带 ----
    edges: dict[str, Any] = {}
    first = periods[0]
    fm = max(hhmm(first["start"]) - 1, 0)
    edges["beforeOpenAt"] = f"{fm // 60:02d}:{fm % 60:02d}"
    first_code = next((i["code"] for i in period_menus.get(first["name"], [])), None)
    if first_code:
        edges["beforeOpen"] = {
            "item": next((i["name"] for i in basket if i["code"] == first_code), first_code),
            "price": price_at(1, 1, None, first_code, edges["beforeOpenAt"]),
        }
        calls += 1
    if len(periods) >= 2:
        gap = (hhmm(periods[0]["end"]) + hhmm(periods[1]["start"])) // 2
        edges["gapAt"] = f"{gap // 60:02d}:{gap % 60:02d}"
        codes = {i["code"] for i in period_menus.get(periods[0]["name"], [])}
        probe_codes = [i["code"] for i in basket if i["code"] in codes][:2]
        edges["gap"] = {c: price_at(1, 1, None, c, edges["gapAt"]) for c in probe_codes}
        calls += len(probe_codes)

    # ---- 6. 汇总各档地板价(主食 / 含小食 / 前 6 便宜) ----
    floors: dict[str, dict[str, Any]] = {}
    for ch, tab in prices.items():
        if not tab:
            continue
        floors[ch] = {}
        for p in periods:
            rows: list[dict[str, Any]] = []
            for it in basket:
                v = tab.get(it["code"], {}).get(p["name"])
                if v is None or v < MIN_FOOD_PRICE or it["kind"] == "extra":
                    continue      # 不可售 / 配件(蘸酱包这类)不参与"最便宜"
                rows.append({"name": it["name"], "price": v, "kind": it["kind"],
                             "code": it["code"]})
            rows.sort(key=lambda r: r["price"])
            meal = next((r for r in rows if r["kind"] == "meal"), None)
            floors[ch][p["name"]] = {
                "meal": meal,
                "any": rows[0] if rows else None,
                "top": rows[:6],
            }

    return {
        "city": city,
        "province": probe.get("province", ""),
        "region": probe.get("region", ""),
        "tier": probe.get("tier", 3),
        "store": {"code": store_code, "name": store.get("name"),
                  "address": store.get("address"),
                  "businessStart": store.get("businessStart"),
                  "businessEnd": store.get("businessEnd")},
        "periods": periods,
        "openStats": probe.get("openStats", {}),
        "sampleStores": probe.get("storeCount"),
        "basket": [{"code": i["code"], "name": i["name"], "category": i["category"],
                    "kind": i["kind"], "periods": i.get("periods", [])} for i in basket],
        "prices": prices,
        "edges": edges,
        "floors": floors,
        "dtStore": dt,
        "calls": calls,
        "menuSizes": {k: len(v) for k, v in period_menus.items()},
    }


def save(result: dict[str, Any], target_date: str, server_now: Any) -> None:
    """增量落盘: 每座城市采完立刻写入, 同名覆盖。"""
    with _write_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        prev: dict[str, Any] = {}
        if OUT_PATH.exists():
            try:
                prev = json.loads(OUT_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                prev = {}
        merged = {c["city"]: c for c in prev.get("cities", [])}
        merged[result["city"]] = result
        cities = sorted(merged.values(), key=lambda c: (c.get("tier", 9), c.get("city", "")))
        payload = {
            "project": "麦当劳几点最便宜 (mcd-when)",
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "targetDate": target_date,
            "serverNow": server_now,
            "isDemo": False,
            "dataSource": "麦当劳中国官方 MCP (https://mcp.mcd.cn) calculate-price 实时返回, 单位: 分",
            "readOnlyGuarantee": sorted(READ_ONLY_TOOLS),
            "method": "按官方时段核价(实测: 同一商品价格全天恒定, 变化的是可售时段)",
            "total": len(cities),
            "cities": cities,
        }
        tmp = OUT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(OUT_PATH)


def main() -> int:
    ap = argparse.ArgumentParser(description="麦当劳几点最便宜 · 全国普查")
    ap.add_argument("--city", action="append", help="指定城市, 可多次")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--no-dt", action="store_true", help="不采得来速渠道(省一半调用)")
    ap.add_argument("--resume", action="store_true", help="跳过已采集的城市")
    args = ap.parse_args()

    load_env()
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        print("缺少 MCD_MCP_TOKEN(放 .env 即可)。")
        return 1
    if not PROBE_PATH.exists():
        print("缺少 data/cities-probe.json, 请先跑: python src/probe_cities.py")
        return 1

    probe = json.loads(PROBE_PATH.read_text(encoding="utf-8"))
    ok_cities = [c for c in probe["cities"] if c.get("ok") and c.get("store", {}).get("code")]
    if args.city:
        ok_cities = [c for c in ok_cities if c["city"] in args.city]
    if args.resume and OUT_PATH.exists():
        done = {c["city"] for c in json.loads(OUT_PATH.read_text(encoding="utf-8"))["cities"]}
        ok_cities = [c for c in ok_cities if c["city"] not in done]
        print(f"断点续跑: 已完成 {len(done)} 座, 还剩 {len(ok_cities)} 座")
    if args.limit:
        ok_cities = ok_cities[: args.limit]
    if not ok_cities:
        print("没有待采集的城市。")
        return 0

    limiter = RateLimiter(per_minute=480)
    boot = McdMcpClient(token, limiter=limiter)
    now = boot.call_tool("now-time-info")
    d = now.get("data") or {}
    today = d.get("date") or datetime.now().strftime("%Y-%m-%d")
    target_date = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"服务端今天 {today} -> 普查目标日期 {target_date}")
    print(f"待采集 {len(ok_cities)} 座城市, 并发 {args.workers}\n")

    t0 = time.time()
    done_n = 0
    failed: list[str] = []
    total_calls = 0

    def work(p: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str]:
        c = McdMcpClient(token, limiter=limiter)
        try:
            return p["city"], survey_city(c, p, target_date, with_dt=not args.no_dt), ""
        except Exception as e:  # noqa: BLE001
            return p["city"], None, str(e)[:120]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(work, p): p for p in ok_cities}
        for fut in as_completed(futs):
            city, res, err = fut.result()
            done_n += 1
            if res is None:
                failed.append(city)
                log(f"[{done_n}/{len(ok_cities)}] {city} × {err}")
                continue
            total_calls += res["calls"]
            save(res, target_date, d.get("formatted"))
            fl = res["floors"].get("pickup", {})
            summary = " ".join(
                f"{k}{('¥%.2f' % (v['meal']['price'] / 100)) if (v and v.get('meal')) else '—'}"
                for k, v in fl.items())
            log(f"[{done_n}/{len(ok_cities)}] {res['city']} {res['province']} "
                f"({res['calls']}次) 门店{res['store']['businessStart']}-{res['store']['businessEnd']} "
                f"早{res['periods'][0]['start']} | {summary}")

    print(f"\n完成 {done_n - len(failed)}/{len(ok_cities)} 座, 失败 {len(failed)}"
          + (f" ({', '.join(failed[:10])})" if failed else ""))
    print(f"总调用 {total_calls} 次, 耗时 {time.time() - t0:.0f}s -> {OUT_PATH}")
    print("下一步: python src/render_report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
