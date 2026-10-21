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
