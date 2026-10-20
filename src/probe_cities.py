"""probe_cities.py — 全国城市门店探测(铺开前的第一步, 最便宜的一次扫描)

目的: 在正式普查之前先回答「哪些城市真的有麦当劳、门店几点开门、官方时段是什么」。
每座城市只需 1 次 query-nearby-stores —— 230 座城市也就 230 次调用。

产出 data/cities-probe.json, 供 survey_national.py 决定采集顺序与采样区间。

用法:
    python src/probe_cities.py --limit 20        # 先探 20 座(按优先级)
    python src/probe_cities.py                   # 全量
    python src/probe_cities.py --city 苏州 --city 义乌
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from cities_cn import city_meta, extra_cities, prioritized, tier  # noqa: E402
from mcd_client import McdMcpClient, McdMcpError, RateLimiter  # noqa: E402
from survey import parse_periods  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_PATH = DATA_DIR / "cities-probe.json"

PERIOD_RE = re.compile(r"(早餐|午餐|下午茶|夜市)\((\d{2}:\d{2})至(\d{2}:\d{2})\)")

_write_lock = threading.Lock()


def load_env() -> None:
    """从 .env 读取 MCD_MCP_TOKEN(该文件已被 .gitignore 排除)。"""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def hhmm_to_min(t: str | None) -> int | None:
    if not t or ":" not in t:
        return None
    try:
        h, m = t.split(":")[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def probe_one(client: McdMcpClient, city: str, target_date: str) -> dict[str, Any]:
    """探测单座城市。城市名失败时自动尝试「X市」变体。"""
    meta = city_meta().get(city, {})
    base: dict[str, Any] = {
        "city": city,
        "province": meta.get("province", ""),
        "region": meta.get("region", ""),
        "tier": tier(city),
        "ok": False,
    }
    stores: list[dict[str, Any]] = []
    used_name = city
    for variant in (city, f"{city}市"):
        try:
            r = client.call_tool("query-nearby-stores",
                                 {"beType": 1, "searchType": 2, "city": variant, "keyword": "麦当劳"})
            stores = (r.get("data") or []) if r.get("success") else []
        except McdMcpError:
            stores = []
        if stores:
            used_name = variant
            break
    if not stores:
        base["error"] = "未找到门店"
        return base

    # 营业时间分布: 选「最常见的营业时段」作为本城代表, 避免恰好抽中 24h 店或商场店
    spans = Counter()
    for s in stores:
        st, en = s.get("businessStartTime"), s.get("businessEndTime")
        if st and en:
            spans[(st, en)] += 1
    common = spans.most_common(1)[0][0] if spans else (None, None)
    h24 = sum(1 for (a, b) in spans if a in ("00:00", "0:00") or (b in ("23:59", "00:00") and a in ("00:00", "0:00")))
    rep = None
    for s in stores:
        if (s.get("businessStartTime"), s.get("businessEndTime")) == common:
            rep = s
            break
    rep = rep or stores[0]

    starts = [hhmm_to_min(s.get("businessStartTime")) for s in stores]
    ends = [hhmm_to_min(s.get("businessEndTime")) for s in stores]
    starts = [x for x in starts if x is not None]
    ends = [x for x in ends if x is not None]

    periods: list[dict[str, str]] = []
    for s in stores[:8]:                      # 时段各家略有差异, 取第一份有值的
        periods = parse_periods(s, target_date)
        if periods:
            break

    # 候选门店(不只是代表那一家): 实测有门店返回「600056 餐厅不支持预约」,
    # 只留一家的话这座城市就废了 —— 采集时按这个列表依次重试
    candidates = []
    for s in stores[:8]:
        if not s.get("storeCode"):
            continue
        candidates.append({
            "code": s.get("storeCode"), "name": s.get("storeName"),
            "address": s.get("address"),
            "businessStart": s.get("businessStartTime"),
            "businessEnd": s.get("businessEndTime"),
            "options": s.get("reservationTimeOptions"),
        })

    base.update({
        "ok": True,
        "queryName": used_name,
        "storeCount": len(stores),
        "candidates": candidates,
        "store": {
            "code": rep.get("storeCode"),
            "name": rep.get("storeName"),
            "address": rep.get("address"),
            "businessStart": rep.get("businessStartTime"),
            "businessEnd": rep.get("businessEndTime"),
        },
        "periods": periods,
        "openStats": {
            "earliest": f"{min(starts) // 60:02d}:{min(starts) % 60:02d}" if starts else None,
            "latestEnd": f"{max(ends) // 60:02d}:{max(ends) % 60:02d}" if ends else None,
            "h24Like": h24,
            "spanTop": {"start": common[0], "end": common[1], "count": spans[common] if spans else 0},
            "sample": len(stores),
        },
    })
    return base


def save(results: dict[str, dict[str, Any]], target_date: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    prev: dict[str, Any] = {}
    if OUT_PATH.exists():
        try:
            prev = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    merged = {c["city"]: c for c in prev.get("cities", [])}
    merged.update(results)
    cities = sorted(merged.values(), key=lambda c: (c.get("tier", 9), c.get("city", "")))
    payload = {
        "project": "麦当劳几点最便宜 (mcd-when)",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "targetDate": target_date,
        "dataSource": "麦当劳中国官方 MCP query-nearby-stores",
        "total": len(cities),
        "ok": sum(1 for c in cities if c.get("ok")),
        "cities": cities,
    }
    tmp = OUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT_PATH)
    return OUT_PATH


def main() -> int:
    ap = argparse.ArgumentParser(description="全国城市门店探测")
    ap.add_argument("--city", action="append", help="指定城市, 可多次")
    ap.add_argument("--limit", type=int, default=0, help="只探前 N 座(按优先级)")
    ap.add_argument("--workers", type=int, default=4, help="并发线程数")
    ap.add_argument("--extra", action="store_true", help="只探第二批百强县(增量)")
    args = ap.parse_args()

    load_env()
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        print("缺少 MCD_MCP_TOKEN(放 .env 即可)。")
        return 1

    cities = args.city or (extra_cities() if args.extra else prioritized())
    if args.extra:                       # 已探过的不再重复
        if OUT_PATH.exists():
            done = {c["city"] for c in json.loads(OUT_PATH.read_text(encoding="utf-8")).get("cities", [])}
            cities = [c for c in cities if c not in done]
    if args.limit:
        cities = cities[: args.limit]
    print(f"待探测城市 {len(cities)} 座, 并发 {args.workers}")

    limiter = RateLimiter(per_minute=480)
    boot = McdMcpClient(token, limiter=limiter)
    now = boot.call_tool("now-time-info")
    d = now.get("data") or {}
    today = d.get("date") or datetime.now().strftime("%Y-%m-%d")
    target_date = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"服务端今天 {today} -> 目标日期 {target_date}")

    results: dict[str, dict[str, Any]] = {}
    done = 0
    t0 = time.time()

    def work(city: str) -> tuple[str, dict[str, Any]]:
        c = McdMcpClient(token, limiter=limiter)          # 每线程独立会话, 共享限流
        return city, probe_one(c, city, target_date)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(work, c): c for c in cities}
        for fut in as_completed(futs):
            city, res = fut.result()
            results[city] = res
            done += 1
            if res.get("ok"):
                st = res["store"]
                print(f"[{done}/{len(cities)}] {res['city']}({res['province']}) "
                      f"{res['storeCount']}店 代表:{st['name']} {st['businessStart']}-{st['businessEnd']} "
                      f"| " + " ".join(f"{p['name']}{p['start']}-{p['end']}" for p in res.get("periods", [])))
            else:
                print(f"[{done}/{len(cities)}] {res['city']} × {res.get('error')}")
            if done % 10 == 0 or done == len(cities):
                with _write_lock:
                    save(results, target_date)

    out = save(results, target_date)
    ok = sum(1 for r in results.values() if r.get("ok"))
    print(f"\n探测完成 {ok}/{len(results)} 座城市有门店 -> {out} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
