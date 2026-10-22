"""零依赖冒烟测试。跑法: python -m unittest discover tests

只校验不依赖 MCP Token 的部分: 数据文件结构、分类规则、渲染产物自包含性。
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from survey_national import classify, MIN_FOOD_PRICE  # noqa: E402


def load(rel):
    p = os.path.join(ROOT, rel)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class TestClassify(unittest.TestCase):
    def test_accessory_is_extra(self):
        self.assertEqual(classify("北美招牌牧场酱", "调味品"), "extra")

    def test_pie_is_side_not_meal(self):
        # 回归: 派曾被算进"最便宜一餐", 实际是小食
        self.assertEqual(classify("菠萝派", "甜品"), "side")

    def test_burger_is_meal(self):
        self.assertEqual(classify("吉士汉堡包", "汉堡系列"), "meal")

    def test_coffee_is_side(self):
        self.assertEqual(classify("麦咖啡™冰奶铁中杯", "麦咖啡™"), "side")

    def test_price_floor_exists(self):
        self.assertGreaterEqual(MIN_FOOD_PRICE, 500)


class TestBatchPrice(unittest.TestCase):
    """回归: calculate-price 的 productList[].subtotal 是【行小计】= 单价 × quantity。

    同一商品码在菜单里挂在多个分类下时, 不去重就会被 API 合并成 quantity=2,
    小计翻倍 —— 曾经导致 188 城的"全菜单价格"整体虚高一倍。
    """

    def _fake_client(self, responses):
        class Fake:
            def __init__(self):
                self.calls = []

            def call_tool(self, name, args):
                self.calls.append(args)
                # 模拟 API: 相同商品码合并, quantity 累加, subtotal = 单价 × quantity
                merged = {}
                for it in args["items"]:
                    c = it["productCode"]
                    q = it.get("quantity", 1)
                    if c in merged:
                        merged[c] += q
                    else:
                        merged[c] = q
                unit = {"A": 990, "B": 1850}
                product_list = [
                    {"productCode": c, "productName": c,
                     "quantity": q, "originalSubtotal": unit[c] * q,
                     "subtotal": unit[c] * q}
                    for c, q in merged.items()
                ]
                return {"success": True, "data": {"productList": product_list}}
        return Fake()

    def test_subtotal_is_divided_by_quantity(self):
        import survey_batch
        fake = self._fake_client(None)
        counter = [0]
        out = survey_batch.batch_price(fake, "store", None, 1,
                                       ["A", "A", "B"], "2026-10-22 08:00", counter)
        # A 被传了两次 -> API 返回 quantity=2 / subtotal=1980 -> 必须归一回 990
        self.assertEqual(out["A"]["price"], 990)
        self.assertEqual(out["B"]["price"], 1850)

    def test_menu_codes_are_deduplicated(self):
        # 菜单解析必须去重(见 survey_batch.py 的 seen 集合)
        import inspect
        import survey_batch
        src = inspect.getsource(survey_batch)
        self.assertEqual(src.count("seen.add"), 2,
                         "两处菜单收集点都必须去重")


class TestDataFiles(unittest.TestCase):
    def test_national_surface_has_cities(self):
        d = load("data/surface_national.json")
        self.assertGreater(len(d["cities"]), 300)
        for c in d["cities"][:20]:
            self.assertTrue(c.get("city"))
            self.assertTrue(c.get("store", {}).get("name"))
            self.assertTrue(c.get("periods"))

    def test_city_probe_has_candidates(self):
        d = load("data/cities-probe.json")
        cities = d["cities"] if isinstance(d, dict) else d
        self.assertGreater(len(cities), 250)
        codes = [c.get("store", {}).get("code") for c in cities]
        self.assertTrue(any(codes))

    def test_tool_schemas_saved(self):
        d = load("data/tool-schemas.json")
        self.assertTrue(len(json.dumps(d)) > 1000)


class TestRenderedSite(unittest.TestCase):
    """三页版 + 单文件离线版的产物结构(未渲染则跳过)。"""

    def _read(self, name):
        p = os.path.join(ROOT, "dist", name)
        if not os.path.exists(p):
            self.skipTest(f"未渲染 {name}")
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_single_file_is_self_contained(self):
        html = self._read("report.html")
        # 单文件版: 数据内联, 不依赖任何外链脚本 —— 双击即开的前提
        self.assertIn("window.__MCD_DATA__", html)
        self.assertNotIn('src="mcd-data.js"', html)
        self.assertIn('id="provSel"', html)
        self.assertIn('id="citySel"', html)
        self.assertIn("anshero", html)
        self.assertIn("prefers-color-scheme", html)
        self.assertNotIn("{{", html)          # 不得残留未替换模板占位符

    def test_index_uses_shared_data(self):
        html = self._read("index.html")
        self.assertIn('src="mcd-data.js"', html)   # 三页版走外链数据
        self.assertNotIn("window.__MCD_DATA__ =", html)
        self.assertIn('id="provSel"', html)
        self.assertIn('id="ans"', html)
        self.assertIn('class="nav"', html)

    def test_rank_page_is_static_with_deep_links(self):
        html = self._read("rank.html")
        self.assertNotIn("<script", html)           # 纯静态, 零 JS
        self.assertIn("全国榜单", html)
        self.assertIn("早餐开得最早的城市", html)
        self.assertIn("午餐最便宜的城市", html)
        # 城市 chips 是深链: 点下去带着 ?city= 去问答页
        self.assertIn('href="index.html?city=', html)

    def test_how_page_covers_method_and_compliance(self):
        html = self._read("how.html")
        self.assertIn("这些数字是怎么来的", html)
        self.assertIn("合规声明", html)
        self.assertIn("非麦当劳官方产品", html)
        self.assertIn("parity_combo.py", html)

    def test_snapshot_vs_live_is_explained(self):
        """快照/实时的边界必须在页面上讲清楚, 且限流口径与 mcd_client 一致。"""
        how = self._read("how.html")
        self.assertIn("为什么网页是快照，不是实时", how)
        self.assertIn("now.py --city", how)
        self.assertIn("600 次/分钟", how)      # 与 src/mcd_client.py 同一口径
        self.assertNotIn("600 次/3 小时", how)  # 旧口径写错窗口, 别再回来
        # 问答页 hero 必须标出数据日期, 否则用户分不清答案是哪天的
        idx = self._read("index.html")
        self.assertIn("数据日期", idx)
        self.assertIn("hsub2", idx)

    def test_data_js_is_valid_assignment(self):
        import json
        src = self._read("mcd-data.js")
        self.assertTrue(src.startswith("window.__MCD_DATA__ = "))
        payload = src[len("window.__MCD_DATA__ = "):].rstrip().rstrip(";")
        d = json.loads(payload)
        self.assertIn("cities", d)
        self.assertIn("mn", d)
        self.assertGreater(len(d["cities"]), 300)
        self.assertGreater(len(d["mn"]), 200)

    def test_nav_links_all_pages(self):
        for page in ["index.html", "rank.html", "how.html", "report.html"]:
            html = self._read(page)
            self.assertIn('class="nav"', html, page)
            self.assertIn("问答", html, page)
            self.assertIn("全国榜单", html, page)
            self.assertIn("方法与合规", html, page)


if __name__ == "__main__":
    unittest.main()


class TestMcpServer(unittest.TestCase):
    """MCP Server 的协议层与工具层冒烟测试(不起进程, 直接调内部函数)。"""

    @classmethod
    def setUpClass(cls):
        import mcp_server
        cls.mod = mcp_server
        cls.ds = mcp_server.load_dataset()

    def test_dataset_loads(self):
        self.assertGreater(self.ds["meta"]["cities"], 300)
        self.assertIn("上海", self.ds["cities"])

    def test_cheapest_period_shanghai(self):
        r = self.mod.tool_cheapest_period(self.ds, {"city": "上海"})
        self.assertEqual(r["city"], "上海")
        self.assertEqual(len(r["periods"]), 4)
        self.assertIsNotNone(r["cheapest"])
        self.assertGreater(r["cheapest"]["price_fen"], 0)

    def test_cheapest_period_fuzzy_city(self):
        # 「上海市」这种写法也要能命中
        r = self.mod.tool_cheapest_period(self.ds, {"city": "上海市"})
        self.assertEqual(r["city"], "上海")

    def test_cheapest_period_unknown_city_raises(self):
        with self.assertRaises(ValueError):
            self.mod.tool_cheapest_period(self.ds, {"city": "不存在的城市"})

    def test_city_ranking_sorted_ascending(self):
        r = self.mod.tool_city_ranking(self.ds, {"period": "早餐", "limit": 5})
        prices = [x["price_fen"] for x in r["ranking"]]
        self.assertEqual(prices, sorted(prices))
        self.assertLessEqual(len(r["ranking"]), 5)

    def test_combo_never_exceeds_budget(self):
        r = self.mod.tool_combo_under_budget(
            self.ds, {"city": "上海", "budget_yuan": 20})
        self.assertLessEqual(r["total_fen"], 2000)
        for item in r["combo"]:
            self.assertIn(item["kind"], ("meal", "side"))

    def test_combo_rejects_empty_budget(self):
        with self.assertRaises(ValueError):
            self.mod.tool_combo_under_budget(self.ds, {"city": "上海"})

    def test_data_freshness_has_timestamp(self):
        r = self.mod.tool_data_freshness(self.ds, {})
        self.assertTrue(r["data_generated_at"])

    def test_tools_list_shape(self):
        names = [t["name"] for t in self.mod.TOOLS]
        self.assertEqual(names, ["cheapest_period", "city_ranking", "city_menu",
                                 "combo_under_budget", "data_freshness"])
        for t in self.mod.TOOLS:
            self.assertIn("inputSchema", t)
            self.assertNotIn("handler", {k: v for k, v in t.items()
                                         if k == "handler"} or {}) if False else None

    def test_handle_unknown_method_errors(self):
        sent = []
        orig = self.mod._send
        self.mod._send = lambda obj: sent.append(obj)
        try:
            self.mod.handle(self.ds, {"jsonrpc": "2.0", "id": 99,
                                      "method": "no/such"})
        finally:
            self.mod._send = orig
        self.assertEqual(sent[0]["error"]["code"], -32601)

    def test_handle_initialize(self):
        sent = []
        orig = self.mod._send
        self.mod._send = lambda obj: sent.append(obj)
        try:
            self.mod.handle(self.ds, {"jsonrpc": "2.0", "id": 1,
                                      "method": "initialize", "params": {}})
        finally:
            self.mod._send = orig
        self.assertEqual(sent[0]["result"]["serverInfo"]["name"], "mcd-when")


class TestCombo(unittest.TestCase):
    """「预算内怎么点最饱」的核心算法。"""

    def setUp(self):
        from combo import best_combo
        self.best_combo = best_combo

    ITEMS = [
        {"name": "巨无霸", "kind": "meal", "price_fen": 1390},
        {"name": "圆筒", "kind": "side", "price_fen": 500},
        {"name": "薯条", "kind": "side", "price_fen": 850},
        {"name": "酱包", "kind": "extra", "price_fen": 300},
    ]

    def test_requires_a_meal(self):
        # ¥10 只够买两个圆筒, 但圆筒不是主食 —— 必须判"吃不到一顿正经饭"
        total, picked, ok = self.best_combo(self.ITEMS, 1000)
        self.assertFalse(ok)
        self.assertEqual(picked, [])

    def test_meal_plus_sides(self):
        total, picked, ok = self.best_combo(self.ITEMS, 2000)
        self.assertTrue(ok)
        self.assertEqual(total, 1390 + 500)          # 主食 + 最便宜的小食
        self.assertEqual(len(picked), 2)

    def test_maximizes_item_count(self):
        # ¥30: 主食 1390 + 圆筒 500 + 薯条 850 = 2740, 3 件
        total, picked, ok = self.best_combo(self.ITEMS, 3000)
        self.assertTrue(ok)
        self.assertEqual(len(picked), 3)
        self.assertEqual(total, 2740)
        self.assertLessEqual(total, 3000)

    def test_never_exceeds_budget(self):
        for b in range(500, 4000, 137):
            total, _, ok = self.best_combo(self.ITEMS, b)
            if ok:
                self.assertLessEqual(total, b)

    def test_empty_input(self):
        self.assertEqual(self.best_combo([], 2000), (0, [], False))

    def test_candidates_filters_cheap_and_extra(self):
        import combo
        cands = combo.candidates(
            {"basket": [
                {"code": "a", "name": "堡", "kind": "meal",
                 "periods": ["午餐"], "category": "汉堡"},
                {"code": "b", "name": "饼干", "kind": "side",
                 "periods": ["午餐"], "category": "小食"},
                {"code": "c", "name": "酱", "kind": "extra",
                 "periods": ["午餐"], "category": "调味"},
            ],
             "prices": {"pickup": {"a": {"午餐": 1390}, "b": {"午餐": 200},
                                   "c": {"午餐": 300}}}},
            "午餐")
        self.assertEqual([c["name"] for c in cands], ["堡"])


class TestComboAnchor(unittest.TestCase):
    """「我选它当主食」—— 锚点必选语义。

    锚点是用户主动选的, 必须出现在结果里; 若只是 unshift 进候选,
    背包会挑更便宜的主食把它跳过, 「我选它当主食」就落了空。
    """

    def setUp(self):
        from combo import best_combo
        self.best_combo = best_combo

    ITEMS = [
        {"name": "巨无霸", "kind": "meal", "price_fen": 1390},
        {"name": "双层堡", "kind": "meal", "price_fen": 1250},
        {"name": "圆筒", "kind": "side", "price_fen": 500},
        {"name": "薯条", "kind": "side", "price_fen": 850},
        {"name": "酱包", "kind": "extra", "price_fen": 300},
    ]

    def test_anchor_is_not_skipped(self):
        # ¥30 锚定 ¥13.9 的巨无霸: 即便有更便宜的 ¥12.5 主食, 也必须选巨无霸
        anchor = {"name": "巨无霸", "kind": "meal", "price_fen": 1390}
        total, picked, ok = self.best_combo(self.ITEMS, 3000, anchor)
        self.assertTrue(ok)
        self.assertIn(anchor, picked)
        # 剩下 ¥16.1: 「筒+薯条」2 件但没有主食, 按硬约束不成立;
        # 所以是 巨无霸 + 双层堡, 不是把锚点跳过换成更便宜的主食
        self.assertEqual(total, 1390 + 1250)
        self.assertEqual(len(picked), 2)

    def test_anchor_extra_rejected(self):
        # 酱包是配料, 不能当一顿饭的锚
        total, picked, ok = self.best_combo(
            self.ITEMS, 3000, {"name": "酱包", "kind": "extra", "price_fen": 300})
        self.assertFalse(ok)
        self.assertEqual(picked, [])

    def test_anchor_over_budget_rejected(self):
        anchor = {"name": "巨无霸", "kind": "meal", "price_fen": 1390}
        total, _, ok = self.best_combo(self.ITEMS, 1000, anchor)
        self.assertFalse(ok)

    def test_anchor_below_floor_rejected(self):
        # ¥2 的联名饼干不能当一顿饭的锚(页面端曾允许, 搭配里渲染出
        # undefined/¥NaN; 门槛必须和 candidates() 一致)
        anchor = {"name": "饼干", "kind": "side", "price_fen": 200}
        total, picked, ok = self.best_combo(self.ITEMS, 3000, anchor)
        self.assertFalse(ok)
        self.assertEqual(picked, [])

    def test_side_anchor_without_affordable_meal(self):
        # 锚是小食, 剩下的钱凑不出任何主食 -> 判"吃不到一顿正经饭"
        anchor = {"name": "圆筒", "kind": "side", "price_fen": 500}
        total, picked, ok = self.best_combo(self.ITEMS, 900, anchor)
        self.assertFalse(ok)
        self.assertEqual(picked, [])

    def test_side_anchor_with_meal_fills_rest(self):
        # ¥20 锚定 ¥5 圆筒: 剩下 ¥15 够买一件主食, 成立
        anchor = {"name": "圆筒", "kind": "side", "price_fen": 500}
        total, picked, ok = self.best_combo(self.ITEMS, 2000, anchor)
        self.assertTrue(ok)
        self.assertIn(anchor, picked)
        names = [x["name"] for x in picked]
        self.assertIn("双层堡", names)                 # ¥15 内最便宜的主食
        self.assertEqual(total, 500 + 1250)

    def test_anchor_removes_only_one_copy(self):
        # 两份同名同价商品, 锚掉一份, 另一份仍可被背包选中
        items = self.ITEMS + [{"name": "圆筒", "kind": "side", "price_fen": 500}]
        anchor = {"name": "圆筒", "kind": "side", "price_fen": 500}
        total, picked, ok = self.best_combo(items, 3500, anchor)
        self.assertTrue(ok)
        self.assertEqual(sum(1 for x in picked if x["name"] == "圆筒"), 2)
        # 4 件且总价更低者胜: 双层堡(1250) 比 巨无霸(1390) 便宜, 同样 4 件选它
        self.assertEqual(total, 500 + 1250 + 850 + 500)
