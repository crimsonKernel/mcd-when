"""combo.py — 「预算内怎么点最饱」的核心算法

被两处共用:
  - src/mcp_server.py      的 combo_under_budget 工具(MCP 形态)
  - src/combo_precompute.py 的全国预计算(静态页形态)

抽成模块是为了让「同一个算法」有唯一实现: 网页上看到的搭配,
和 MCP 客户端问出来的搭配, 必须逐分不差。否则同一个问题两个答案,
产品立刻就失信了。

核心思路(与 mcp_server.py 原有实现完全一致):
  0/1 背包求件数最多, 但目标函数不是单纯件数 ——
  四个甜筒凑 ¥20 谁也不叫"一顿午饭"。
  所以排序键是 (有没有主食, 件数, -花费):
    1. 先保证有一口能当饭的(kind == "meal")
    2. 再尽量多件
    3. 花费相同则更便宜的排前面(在 best_k 选取时体现)

依赖: 纯标准库。
"""

from __future__ import annotations

from typing import Any

# 单品低于此价不当饭: 实测有 ¥2 的联名饼干、¥3 的蘸酱包会污染搭配
MIN_ITEM_FEN = 500

# 算得上一顿饭的分类
MEAL_KINDS = ("meal", "side")


def menu_of(city_record: dict) -> dict[str, dict[str, Any]]:
    """城市采集记录 -> {商品码: {name, category, kind, periods, prices}}"""
    out: dict[str, dict[str, Any]] = {}
    for it in city_record.get("basket") or []:
        code = it.get("code")
        if not code:
            continue
        tab = ((city_record.get("prices") or {}).get("pickup") or {}).get(code) or {}
        prices = {p: v for p, v in tab.items() if isinstance(v, int)}
        out[code] = {
            "name": it.get("name") or code,
            "category": it.get("category", ""),
            "kind": it.get("kind", ""),
            "periods": it.get("periods") or [],
            "prices": prices,
        }
    return out


def candidates(city_record: dict, period: str | None = None) -> list[dict]:
    """某时段可参与搭配的商品候选(已过滤价格/分类)。"""
    cands: list[dict] = []
    for code, m in menu_of(city_record).items():
        if m["kind"] not in MEAL_KINDS:
            continue                       # 配件/调味品不算一顿饭
        if period and period not in (m["periods"] or [period]):
            continue
        if not m["prices"]:
            continue
        p = m["prices"].get(period) if period else min(m["prices"].values())
        if p is None or p < MIN_ITEM_FEN:
            continue
        cands.append({"code": code, "name": m["name"],
                      "kind": m["kind"], "price_fen": p})
    return cands


def best_combo(cands: list[dict], limit_fen: int) -> tuple[int, list[dict], bool]:
    """0/1 背包: 预算内「最像一顿饭」的搭配。

    「有主食」是硬约束, 不是排序键:
      预算里装不下任何主食时, 宁可返回空, 也不返回「两个冰淇淋凑 ¥10」。
      调用方拿空结果去说「预算不够吃一顿正经饭」, 是诚实且有用的;
      拿两个冰淇淋冒充一顿午饭, 产品立刻就失信。

    约束内再最大化件数; 件数相同取更便宜的。

    返回 (实际花费分, 商品列表, 是否含主食)。无可行解时返回 (0, [], False)。
    """
    if limit_fen <= 0 or not cands:
        return 0, [], False

    # 防御性过滤: 正常由 candidates() 先筛过, 但直接调本函数时
    # 不该把酱包/配件算进"一顿饭"
    cands = [x for x in cands if x.get("kind") in MEAL_KINDS]
    if not cands:
        return 0, [], False

    cands = sorted(cands, key=lambda x: x["price_fen"])
    n = len(cands)
    NEG = (-1, -1)
    dp = [NEG] * (limit_fen + 1)
    pick: list[list[int]] = [[] for _ in range(limit_fen + 1)]
    dp[0] = (0, 0)
    for i, it in enumerate(cands):
        w = it["price_fen"]
        is_meal = 1 if it["kind"] == "meal" else 0
        for k in range(limit_fen, w - 1, -1):
            if dp[k - w][0] < 0:
                continue
            cand = (dp[k - w][0] or is_meal, dp[k - w][1] + 1)
            if cand > dp[k]:
                dp[k] = cand
                pick[k] = pick[k - w] + [i]
    # 只认含主食的解 —— 这是硬门槛, 不是优先级
    feasible = [k for k in range(limit_fen + 1) if dp[k][0] == 1]
    if not feasible:
        return 0, [], False
    best_k = max(feasible, key=lambda k: (dp[k][1], -k))
    return best_k, [cands[i] for i in pick[best_k]], True
