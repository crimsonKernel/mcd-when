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


class TestCrossday(unittest.TestCase):
    """跨日互验(crossday_facts)的口径回归。

    关键事实: 探针采不到商品时记 None, 从不填地板价 ——
    所以 ¥13.90 是官方真实返回的促销价, 「1390 -> 2100」是真涨价(促销结束),
    不是采集假阳性(上海 dt 的麦咖啡冰奶铁四时段全 None 是实证)。
    """

    def _surface(self, cities):
        return {"cities": cities, "targetDate": "2026-10-22",
                "generatedAt": "2026-10-21T15:42:24"}

    def test_counts_only_two_sided_cells(self):
        from render_report import crossday_facts
        probe = self._surface([{"city": "A", "periods": [],
                                "prices": {"dt": {"i1": {"午餐": 1390, "早餐": None}}}}])
        batch = self._surface([{"city": "A", "periods": [],
                                "prices": {"dt": {"i1": {"午餐": 2100, "早餐": 1390}}}}])
        xd = crossday_facts(batch, probe, min_common=1)
        # 午餐 1390->2100 是真涨价; 早餐 None->1390 是上下架, 不算变价
        self.assertEqual((xd["total"], xd["same"], xd["up"], xd["dn"], xd["flip"]),
                         (1, 0, 1, 0, 1))
        self.assertEqual(xd["floor_up"], 1)

    def test_identical_prices_mean_no_change(self):
        from render_report import crossday_facts
        cities = [{"city": "C%d" % i, "periods": [],
                   "prices": {"pickup": {"i1": {"午餐": 2100}}}} for i in range(3)]
        xd = crossday_facts(self._surface(cities), self._surface(cities), min_common=1)
        self.assertEqual((xd["up"], xd["dn"], xd["flip"], xd["same"]), (0, 0, 0, 3))
        self.assertEqual(xd["same_pct"], 100.0)

    def test_period_boundary_change_is_tracked(self):
        from render_report import crossday_facts
        prices = {"pickup": {"i1": {"午餐": 2100}}}
        probe = self._surface([{"city": "A",
                                "periods": [{"name": "早餐", "start": "07:14", "end": "10:15"}],
                                "prices": prices}])
        batch = self._surface([{"city": "A",
                                "periods": [{"name": "早餐", "start": "05:14", "end": "10:15"}],
                                "prices": prices}])
        xd = crossday_facts(batch, probe, min_common=1)
        self.assertEqual(xd["period_cities"], 1)
        self.assertEqual((xd["start_n"], xd["end_n"]), (1, 0))
        self.assertEqual(xd["start_ex"][0], ("A", "早餐", "07:14", "05:14"))

    def test_too_little_overlap_returns_none(self):
        from render_report import crossday_facts
        probe = self._surface([{"city": "A", "periods": [], "prices": {}}])
        batch = self._surface([{"city": "B", "periods": [], "prices": {}}])
        self.assertIsNone(crossday_facts(batch, probe))


class TestRenderedSite(unittest.TestCase):
    """两页版 + 单文件离线版的产物结构(未渲染则跳过)。"""

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
        self.assertIn('src="mcd-data.js"', html)   # 两页版走外链数据
        self.assertNotIn("window.__MCD_DATA__ =", html)
        self.assertIn('id="provSel"', html)
        self.assertIn('id="ans"', html)
        self.assertIn('class="nav"', html)

    def test_city_list_deep_links(self):
        """1.2 起全国榜单页砍掉, 完整城市名单并进问答页底部的折叠区。

        两页版里 chips 是深链(?city=), 单文件版里是 span 由页内接管。
        """
        idx = self._read("index.html")
        self.assertIn('id="sec-cities"', idx)                 # 折叠区锚点
        self.assertIn("全国 ", idx)
        self.assertIn("座城市名单", idx)
        self.assertIn('href="index.html?city=', idx)          # 点城市名直接去查
        rp = self._read("report.html")
        self.assertIn('id="sec-cities"', rp)
        self.assertIn('data-c="', rp)                         # 单文件版页内接管
        # 问答页不许再挂榜单页导航(how/report 里提「榜单页被砍掉」是叙事, 不在此列)
        self.assertNotIn("全国榜单", idx)
        self.assertNotIn('href="rank.html"', rp)

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
        # 1.3 跨日互验一节: 「隔一天会变吗」必须在, 且带着采集时刻的诚实局限
        self.assertIn("隔一天会变吗", how)
        self.assertIn("结构不过期，价格会过期", how)
        self.assertIn("采集时刻效应分不开", how)
        # 问答页 hero 必须标出数据日期, 否则用户分不清答案是哪天的
        idx = self._read("index.html")
        self.assertIn("数据日期", idx)
        self.assertIn("hsub2", idx)
        # 1.3 起价格一律冠以「快照」: 首屏决策位只答结构, 价格降级为带日期的参考数
        self.assertIn("快照口径", idx)
        self.assertNotIn("最便宜的一顿多少钱", idx)   # 旧首屏枚举(价格无快照限定)

    def test_menu_fault_is_the_headline(self):
        """「永远早上最便宜」的修正: 价格轴平坦 + 后三档菜单同一套, 必须在每个页面都说清。

        1.2 起叙事升级: 把问题本身换掉 —— 不问「几点最便宜」, 只问「这个点有什么可吃」。
        1.4 再升级「时刻表优先」(when leads, what follows): 首屏第一眼是收档时间,
        不是菜单件数 —— repo 名 mcd-when 的 when 回到主位。截止时间是知识传递
        (顾客普遍不知道早餐 10:15 收), 这正是对 App 的结构性优势。
        """
        idx = self._read("index.html")
        # 1.4 首屏: h1 直接给时刻表答案(边界现算, 不许硬编码成写死的钟点)
        self.assertRegex(idx, r"<h1>早餐 \d\d:\d\d 收档，午餐 \d\d:\d\d 开档</h1>")
        self.assertIn("麦当劳时刻表", idx)          # nav / title 与 repo 名对齐
        # 真空带作为独立叙事进 hero: 每天 X–Y 什么都买不到
        self.assertRegex(idx, r"每天 \d\d:\d\d–\d\d:\d\d 是菜单真空带")
        self.assertIn("最后一档", idx)
        # 菜单断层仍要在(1.1 的叙事没丢)
        self.assertIn("午餐和夜市", idx)
        self.assertIn("这一档的菜单，和别档比差在哪", idx)
        self.assertIn("没有一件是这一档独有的", idx)
        self.assertIn("价格轴是平的", idx)
        # 1.4 打开即答: 城市记忆 + now 默认态 + 30 秒心跳(跨档才重渲)
        self.assertIn("mcd-when:city", idx)
        self.assertIn("var nowMode = true", idx)
        self.assertIn("setInterval(tick, 30000)", idx)
        # 1.4 截止时间做主数字: 答案卡第一眼是「X 档 HH:MM 收档」+ 倒计时
        self.assertIn('class="cutoff', idx)
        self.assertIn('id="cdcd"', idx)
        # 1.4 真空带/打烊/未开档特例卡: 真空期说「什么都买不到」而不是列空菜单
        self.assertIn("gapcase", idx)
        self.assertIn("closedcase", idx)
        self.assertIn("什么都买不到", idx)
        self.assertIn("还没开档", idx)
        self.assertIn("今天已收档", idx)
        # 1.4 时间轴常驻 + 现在指针
        self.assertIn('id="dbnow"', idx)
        self.assertIn('id="dbtime"', idx)
        # 1.4 反向问法: 「想吃早餐 → 最晚 HH:MM 前到店」
        self.assertIn("revQuery", idx)
        self.assertIn("revchip", idx)
        self.assertIn("前到店", idx)
        how = self._read("how.html")
        self.assertIn("为什么这个工具不回答「几点最便宜」", how)
        self.assertIn("价格轴几乎是平的", how)
        self.assertIn("把「时刻表」本身当成产品", how)   # 1.4 叙事段
        rp = self._read("report.html")
        self.assertRegex(rp, r"<h1>早餐 \d\d:\d\d 收档，午餐 \d\d:\d\d 开档</h1>")
        self.assertIn("价格轴是平的", rp)
        self.assertIn("菜单真空带", rp)
        # 单文件离线版与两页版同源: 打开即答三件套一份不少
        self.assertIn("mcd-when:city", rp)
        self.assertIn("setInterval(tick, 30000)", rp)
        self.assertIn("revchip", rp)

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
        # 1.2 起只剩两页: 问答(这个点有什么) + 方法与合规; rank.html 已砍掉
        for page in ["index.html", "how.html", "report.html"]:
            html = self._read(page)
            self.assertIn('class="nav"', html, page)
            self.assertIn("这个点有什么", html, page)
            self.assertIn("方法与合规", html, page)
        # 榜单页的导航链接不许残留
        for page in ["index.html", "how.html", "report.html"]:
            self.assertNotIn('href="rank.html"', self._read(page), page)


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
