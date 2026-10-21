# MCP Server 实跑记录（真实返回，非手写）

由 `src/mcp_server.py` 直接产出。任何支持 MCP 的客户端（WorkBuddy / Claude Code / Cursor）都能用自然语言问到这些答案，**零 Token**。

## initialize

```json
{
 "protocolVersion": "2024-11-05",
 "capabilities": {
  "tools": {
   "listChanged": false
  }
 },
 "serverInfo": {
  "name": "mcd-when",
  "version": "1.0.0"
 }
}
```

## cheapest_period(上海)

```json
{
 "city": "上海",
 "province": "上海",
 "store": "麦当劳上海闸北虬江路永兴汇餐厅",
 "business_hours": [
  "07:00",
  "23:00"
 ],
 "periods": [
  {
   "period": "早餐",
   "start": "07:14",
   "end": "10:15",
   "cheapest_meal": {
    "name": "芝芝火腿扒堡组合",
    "price_fen": 990,
    "price": "¥9.90"
   },
   "cheapest_any": {
    "name": "灰焰圆筒",
    "price_fen": 500,
    "price": "¥5.00"
   }
  },
  {
   "period": "午餐",
   "start": "10:44",
   "end": "14:15",
   "cheapest_meal": {
    "name": "冰浓浓黑巧中杯",
    "price_fen": 1390,
    "price": "¥13.90"
   },
   "cheapest_any": {
    "name": "灰焰圆筒",
    "price_fen": 500,
    "price": "¥5.00"
   }
  },
  {
   "period": "下午茶",
   "start": "14:44",
   "end": "16:45",
   "cheapest_meal": {
    "name": "冰浓浓黑巧中杯",
    "price_fen": 1390,
    "price": "¥13.90"
   },
   "cheapest_any": {
    "name": "灰焰圆筒",
    "price_fen": 500,
    "price": "¥5.00"
   }
  },
  {
   "period": "夜市",
   "start": "17:14",
   "end": "21:45",
   "cheapest_meal": {
    "name": "冰浓浓黑巧中杯",
    "price_fen": 1390,
    "price": "¥13.90"
   },
   "cheapest_any": {
    "name": "灰焰圆筒",
    "price_fen": 500,
    "price": "¥5.00"
   }
  }
 ],
 "cheapest": {
  "period": "早餐",
  "name": "芝芝火腿扒堡组合",
  "price_fen": 990,
  "price": "¥9.90"
 },
 "data_generated_at": "2026-10-21T14:39:43"
}
```

## city_ranking(午餐, top5)

```json
{
 "period": "午餐",
 "ranking": [
  {
   "city": "西安",
   "province": "陕西",
   "item": "派",
   "price_fen": 950,
   "price": "¥9.50"
  },
  {
   "city": "北京",
   "province": "北京",
   "item": "蘸酱炸鸡",
   "price_fen": 1190,
   "price": "¥11.90"
  },
  {
   "city": "天津",
   "province": "天津",
   "item": "蘸酱炸鸡",
   "price_fen": 1190,
   "price": "¥11.90"
  },
  {
   "city": "深圳",
   "province": "广东",
   "item": "蘸酱炸鸡",
   "price_fen": 1190,
   "price": "¥11.90"
  },
  {
   "city": "乌鲁木齐",
   "province": "新疆",
   "item": "蘸酱炸鸡",
   "price_fen": 1190,
   "price": "¥11.90"
  }
 ],
 "total_cities": 386,
 "data_generated_at": "2026-10-21T14:39:43"
}
```

## combo_under_budget(上海, ¥25, 午餐)

```json
{
 "city": "上海",
 "period": "午餐",
 "budget": "¥25.00",
 "combo": [
  {
   "name": "灰焰圆筒",
   "kind": "side",
   "price_fen": 500,
   "price": "¥5.00"
  },
  {
   "name": "圆筒冰淇淋",
   "kind": "side",
   "price_fen": 500,
   "price": "¥5.00"
  },
  {
   "name": "苹果片一袋(60g)",
   "kind": "side",
   "price_fen": 700,
   "price": "¥7.00"
  },
  {
   "name": "咖啡阿芙佳朵",
   "kind": "side",
   "price_fen": 750,
   "price": "¥7.50"
  }
 ],
 "total_fen": 2450,
 "total": "¥24.50",
 "saved_vs_budget": "¥0.50",
 "cheapest_single": {
  "name": "冰浓浓黑巧中杯",
  "price": "¥13.90"
 },
 "menu_source": "full"
}
```

## data_freshness()

```json
{
 "data_generated_at": "2026-10-21T14:39:43",
 "data_target_date": "2026-10-22",
 "cities": 388,
 "menu_source": "full",
 "data_source": "麦当劳中国官方 MCP (https://mcp.mcd.cn) calculate-price 批量返回, 单位: 分",
 "note": "快照数据。麦当劳的标价跨天基本稳定, 但促销价会变(实测麦咖啡冰奶铁中杯曾从 ¥13.90 回到 ¥21.00); 需要最新价时请用你自己的 MCD_MCP_TOKEN 调官方 MCP。"
}
```
