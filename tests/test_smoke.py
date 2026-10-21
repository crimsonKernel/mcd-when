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


class TestRenderedReport(unittest.TestCase):
    def test_report_is_self_contained(self):
        p = os.path.join(ROOT, "dist", "report.html")
        if not os.path.exists(p):
            self.skipTest("未渲染报告")
        with open(p, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("window.__MCD_DATA__", html)
        self.assertIn('id="provSel"', html)
        self.assertIn('id="citySel"', html)
        self.assertIn("anshero", html)
        self.assertIn("prefers-color-scheme", html)
        # 不得残留未替换模板占位符
        self.assertNotIn("{{", html)


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


class TestComboBlob(unittest.TestCase):
    """data/combos.json 的结构完整性(前端直接消费这份数据)。"""

    @classmethod
    def setUpClass(cls):
        cls.blob = load("data/combos.json")

    def test_shape(self):
        self.assertIn("names", self.blob)
        self.assertIn("budgets", self.blob)
        self.assertIn("cities", self.blob)
        self.assertEqual(self.blob["budgets"],
                         [1000, 1500, 2000, 2500, 3000, 4000, 5000])

    def test_every_city_has_periods(self):
        self.assertGreater(len(self.blob["cities"]), 300)
        for city, per in self.blob["cities"].items():
            self.assertTrue(per, f"{city} 没有任何时段")
            for pname, e in per.items():
                self.assertIn("best", e)
                self.assertIn("b", e)

    def test_name_indices_all_valid(self):
        n = len(self.blob["names"])
        for city, per in self.blob["cities"].items():
            for pname, e in per.items():
                self.assertLess(e["best"][0], n, f"{city}/{pname} best 越界")
                for _b, lad in e["b"].items():
                    for pair in lad["i"]:
                        self.assertLess(pair[0], n, f"{city}/{pname} 名称下标越界")

    def test_no_combo_exceeds_its_budget(self):
        for city, per in self.blob["cities"].items():
            for pname, e in per.items():
                for b, lad in e["b"].items():
                    self.assertLessEqual(lad["t"], int(b),
                                         f"{city}/{pname}/¥{b} 超预算")

    def test_every_combo_has_at_least_one_item(self):
        for city, per in self.blob["cities"].items():
            for pname, e in per.items():
                for b, lad in e["b"].items():
                    self.assertTrue(lad["i"], f"{city}/{pname}/¥{b} 空搭配")
