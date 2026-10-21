"""survey_batch.py — 全国普查(批量核价版)

比 survey_national.py 更省力也更准, 因为它利用一个实测事实:

  calculate-price 的 items 是数组, 一次传几十个商品,
  返回的 productList 里带【每个商品的名称 + 单价】(productName / subtotal)。

  于是 "逐商品核价 + 逐商品取名称" 两步并成一次批量调用。

实测约束(2026-10-21 上海):
  - 一次全传 123 个会失败(含不可售/配件项); 分块 ~25 个稳妥
  - 混入不可售商品会导致【整批失败】—— 所以批次只放该档菜单里出现的商品
    (可售性直接由 query-meals 判定, 不需要试探)
  - 同一商品价格全天恒定(5 城 7000 点验证过) -> 每个商品只需在它出现的档批量核一次

成本: 每城 ≈ 2(门店) + 4(各档菜单) + 4档×4批(自提核价) + 4档×4批(得来速核价) ≈ 40 次,
但换来的是【全菜单】(100+ 个商品)的名称+价格, 而不是 20 个探针的采样。

用法:
    python src/survey_batch.py --city 上海           # 单城
    python src/survey_batch.py --limit 10            # 前 10 城
    python src/survey_batch.py                       # 全国(断点续跑)
    python src/survey_batch.py --resume              # 只补缺

产出: data/surface_batch.json(与 surface_national.json 同构, floors/top 兼容渲染层)
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
from mcd_client import McdMcpClient, McdMcpError, RateLimiter  # noqa: E402
from survey import parse_periods  # noqa: E402
from survey_national import (MIN_FOOD_PRICE, classify, load_env, log,  # noqa: E402
                             mid, hhmm)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROBE_PATH = DATA_DIR / "cities-probe.json"
OUT_PATH = DATA_DIR / "surface_batch.json"

READ_ONLY_TOOLS = {
    "now-time-info", "query-nearby-stores", "query-meals", "calculate-price",
}

DEFAULT_PERIODS = [
    {"name": "早餐", "start": "07:14", "end": "10:15"},
    {"name": "午餐", "start": "10:44", "end": "14:15"},
    {"name": "下午茶", "start": "14:44", "end": "16:45"},
    {"name": "夜市", "start": "17:14", "end": "21:45"},
]

BATCH = 25                  # 批量核价分块大小(实测一次全传 123 会失败)

_write_lock = threading.Lock()


def chunks(lst: list[Any], n: int) -> list[list[Any]]:
    return [lst[i:i + n] for i in range(0, len(lst), n)]


def batch_price(client: McdMcpClient, store_code: str, be_code: str | None,
                be_type: int, codes: list[str], when: str,
                counter: list[int]) -> dict[str, dict[str, Any]]:
    """批量核价: 一次调用拿回多个商品的名称+单价。

    单批失败(一般是混入不可售项)时降级为二分/逐个核价, 能救回多少算多少。
    返回 {code: {name, price}}。
    """
    out: dict[str, dict[str, Any]] = {}
    if not codes:
        return out

    def one_call(codes: list[str]) -> dict[str, Any] | None:
        args: dict[str, Any] = {
            "beType": be_type, "orderType": 1, "storeCode": store_code,
            "items": [{"productCode": c, "quantity": 1} for c in codes],
            "reservationDate": when,
        }
        if be_code:
            args["beCode"] = be_code
        counter[0] += 1
        try:
            r = client.call_tool("calculate-price", args)
            return r if r.get("success") else None
        except McdMcpError:
            return None

    def walk(codes: list[str]) -> None:
        r = one_call(codes)
        if r is not None:
            for item in (r.get("data") or {}).get("productList") or []:
                if item.get("productCode") and item.get("subtotal") is not None:
                    out[item["productCode"]] = {
                        "name": item.get("productName") or item["productCode"],
                        "price": item["subtotal"],
                    }
            return
        if len(codes) == 1:
            return                          # 单个失败 = 该商品此刻不可售, 跳过
        half = len(codes) // 2
        walk(codes[:half])                  # 二分找出坏苹果, 好的一半还能成批成交
        walk(codes[half:])

    for part in chunks(codes, BATCH):
        walk(part)
    return out


def survey_city(client: McdMcpClient, probe: dict[str, Any], target_date: str,
                with_dt: bool = True) -> dict[str, Any]:
    city = probe["city"]
    rep_code = (probe.get("store") or {}).get("code")
    cands: list[dict[str, Any]] = list(probe.get("candidates") or [])
    if not cands:
        cands = [{"code": rep_code, "name": (probe.get("store") or {}).get("name"),
                  "businessStart": (probe.get("store") or {}).get("businessStart"),
                  "businessEnd": (probe.get("store") or {}).get("businessEnd"),
                  "options": None}]
    cands.sort(key=lambda c: 0 if c.get("code") == rep_code else 1)
    counter = [0]

    # ---- 候选门店探活(谁能拉到菜单就用谁, 应对 600056 不支持预约) ----
    chosen = periods = None
    first_menu: tuple[str, list[str], list[str]] | None = None   # (档名, codes, 分类)
    for cand in cands[:5]:
        if not cand.get("code"):
            continue
        per = parse_periods({"reservationTimeOptions": cand.get("options")}, target_date) \
            if cand.get("options") else None
        per = per or probe.get("periods") or DEFAULT_PERIODS
        t = mid(per[0]["start"], per[0]["end"])
        try:
            r = client.call_tool("query-meals", {
                "beType": 1, "orderType": 1, "storeCode": cand["code"],
                "reservationDate": f"{target_date} {t}"})
            counter[0] += 1
        except McdMcpError:
            continue
        if r.get("success"):
            chosen, periods = cand, per
            cats = (r.get("data") or {}).get("categories") or []
            codes, names = [], []
            for cat in cats:
                for m in cat.get("meals") or []:
                    if m.get("code"):
                        codes.append(m["code"])
                        names.append(cat.get("name") or "")
            first_menu = (per[0]["name"], codes, names)
            break
    if chosen is None:
        raise McdMcpError(f"{city}: 候选门店均不支持预约取餐(600056)")
    store_code = chosen["code"]

    # ---- 得来速门店 ----
    dt: dict[str, Any] | None = None
    if with_dt:
        try:
            r = client.call_tool("query-nearby-stores",
                                 {"beType": 5, "searchType": 2,
                                  "city": probe.get("queryName") or city, "keyword": "麦当劳"})
            counter[0] += 1
            lst = (r.get("data") or []) if r.get("success") else []
            if lst and lst[0].get("beCode"):
                dt = {"label": "得来速", "beType": 5, "beCode": lst[0]["beCode"],
                      "storeCode": lst[0].get("storeCode"), "storeName": lst[0].get("storeName")}
        except McdMcpError:
            dt = None

    # ---- 各档菜单(第一次探活已拿到第一档, 复用) ----
    period_codes: dict[str, list[str]] = {}
    period_cats: dict[str, dict[str, str]] = {}
    if first_menu:
        period_codes[first_menu[0]] = first_menu[1]
        period_cats[first_menu[0]] = dict(zip(first_menu[1], first_menu[2]))
    for p in periods:
        if p["name"] in period_codes:
            continue
        t = mid(p["start"], p["end"])
        try:
            r = client.call_tool("query-meals", {
                "beType": 1, "orderType": 1, "storeCode": store_code,
                "reservationDate": f"{target_date} {t}"})
            counter[0] += 1
        except McdMcpError:
            continue
        if r.get("success"):
            cats = (r.get("data") or {}).get("categories") or []
            codes, cmap = [], {}
            for cat in cats:
                for m in cat.get("meals") or []:
                    if m.get("code"):
                        codes.append(m["code"])
                        cmap[m["code"]] = cat.get("name") or ""
            period_codes[p["name"]] = codes
            period_cats[p["name"]] = cmap

    if not period_codes:
        raise McdMcpError(f"{city}: 菜单拉取失败")

    # ---- 批量核价: 自提每档, 得来速每档(同一时刻, 可直接比价) ----
    names: dict[str, str] = {}
    kinds: dict[str, str] = {}
    cats_all: dict[str, str] = {}
    for pname, codes in period_codes.items():
        for code in codes:
            cats_all[code] = period_cats[pname].get(code, "")

    prices: dict[str, dict[str, dict[str, Any]]] = {"pickup": {}, "dt": {}}
    for p in periods:
        pname = p["name"]
        codes = period_codes.get(pname) or []
        if not codes:
            continue
        t = mid(p["start"], p["end"])
        got = batch_price(client, store_code, None, 1, codes, f"{target_date} {t}", counter)
        for code, v in got.items():
            prices["pickup"].setdefault(code, {})[pname] = v["price"]
            names[code] = v["name"]
        if dt:
            got2 = batch_price(client, store_code, dt["beCode"], 5, codes,
                               f"{target_date} {t}", counter)
            for code, v in got2.items():
                prices["dt"].setdefault(code, {})[pname] = v["price"]
                names.setdefault(code, v["name"])

    for code, nm in names.items():
        kinds[code] = classify(nm, cats_all.get(code, ""))

    # ---- 断崖证据: 开档前 1 分钟 / 真空带 ----
    edges: dict[str, Any] = {}
    first = periods[0]
    fm = max(hhmm(first["start"]) - 1, 0)
    edges["beforeOpenAt"] = f"{fm // 60:02d}:{fm % 60:02d}"
    fcodes = (period_codes.get(first["name"]) or [])[:1]
    if fcodes:
        v = batch_price(client, store_code, None, 1, fcodes,
                        f"{target_date} {edges['beforeOpenAt']}", counter)
        edges["beforeOpen"] = {"item": fcodes[0], "price": (v.get(fcodes[0]) or {}).get("price")}
    if len(periods) >= 2:
        gap = (hhmm(periods[0]["end"]) + hhmm(periods[1]["start"])) // 2
        edges["gapAt"] = f"{gap // 60:02d}:{gap % 60:02d}"
        probe_codes = (period_codes.get(periods[0]["name"]) or [])[:2]
        v = batch_price(client, store_code, None, 1, probe_codes,
                        f"{target_date} {edges['gapAt']}", counter)
        edges["gap"] = {c: (v.get(c) or {}).get("price") for c in probe_codes}

    # ---- 各档地板价(从全菜单算, 比探针采样准) ----
    floors: dict[str, dict[str, Any]] = {}
    for ch, tab in prices.items():
        if not tab:
            continue
        floors[ch] = {}
        for p in periods:
            rows = []
            for code, by_period in tab.items():
                v = by_period.get(p["name"])
                if v is None or v < MIN_FOOD_PRICE or kinds.get(code) == "extra":
                    continue
                rows.append({"name": names.get(code, code), "price": v,
                             "kind": kinds.get(code, "meal"), "code": code})
            rows.sort(key=lambda r: r["price"])
            meal = next((r for r in rows if r["kind"] == "meal"), None)
            floors[ch][p["name"]] = {
                "meal": meal, "any": rows[0] if rows else None, "top": rows[:8],
            }

    basket = [{"code": c, "name": names.get(c, c), "category": cats_all.get(c, ""),
               "kind": kinds.get(c, "meal"),
               "periods": [p["name"] for p in periods if c in (period_codes.get(p["name"]) or [])]}
              for c in names]

    return {
        "city": city, "province": probe.get("province", ""),
        "region": probe.get("region", ""), "tier": probe.get("tier", 3),
        "store": {"code": store_code, "name": chosen.get("name"),
                  "address": chosen.get("address"),
                  "businessStart": chosen.get("businessStart"),
                  "businessEnd": chosen.get("businessEnd")},
        "periods": periods, "openStats": probe.get("openStats", {}),
        "sampleStores": probe.get("storeCount"),
        "basket": basket, "prices": prices, "edges": edges, "floors": floors,
        "dtStore": dt, "calls": counter[0],
        "menuSizes": {k: len(v) for k, v in period_codes.items()},
        "fullMenu": True,
    }


def save(result: dict[str, Any], target_date: str, server_now: Any) -> None:
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
            "targetDate": target_date, "serverNow": server_now, "isDemo": False,
            "dataSource": "麦当劳中国官方 MCP (https://mcp.mcd.cn) calculate-price 批量返回, 单位: 分",
            "readOnlyGuarantee": sorted(READ_ONLY_TOOLS),
            "method": "按官方时段批量核价(全菜单, 非探针采样)",
            "total": len(cities), "cities": cities,
        }
        tmp = OUT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(OUT_PATH)


def main() -> int:
    ap = argparse.ArgumentParser(description="麦当劳几点最便宜 · 全国普查(批量核价版)")
    ap.add_argument("--city", action="append")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-dt", action="store_true")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    load_env()
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        print("缺少 MCD_MCP_TOKEN(放 .env 即可)。")
        return 1
    if not PROBE_PATH.exists():
        print("缺少 data/cities-probe.json, 先跑 probe_cities.py")
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
            log(f"[{done_n}/{len(ok_cities)}] {res['city']} {res['province']} ({res['calls']}次) "
                f"菜单{sum(res['menuSizes'].values())}项 | {summary}")

    print(f"\n完成 {done_n - len(failed)}/{len(ok_cities)} 座, 失败 {len(failed)}"
          + (f" ({', '.join(failed[:12])})" if failed else ""))
    print(f"总调用 {total_calls} 次, 耗时 {time.time() - t0:.0f}s -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
