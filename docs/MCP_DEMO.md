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
   "name": "精选超值随心配",
   "kind": "meal",
   "price_fen": 1390,
   "price": "¥13.90"
  }
 ],
 "total_fen": 2390,
 "total": "¥23.90",
 "saved_vs_budget": "¥1.10",
 "cheapest_single": {
  "name": "精选超值随心配",
  "price": "¥13.90"
 },
 "menu_source": "full"
}
```

## city_ranking(午餐, top5)

```json
{
 "period": "午餐",
 "ranking": [
  {
   "city": "宁波",
   "province": "浙江",
   "item": "牛肉堡单品精选",
   "price_fen": 1350,
   "price": "¥13.50"
  },
  {
   "city": "昆明",
   "province": "云南",
   "item": "牛肉堡单品精选",
   "price_fen": 1350,
   "price": "¥13.50"
  },
  {
   "city": "济南",
   "province": "山东",
   "item": "牛肉堡单品精选",
   "price_fen": 1350,
   "price": "¥13.50"
  },
  {
   "city": "石家庄",
   "province": "河北",
   "item": "牛肉堡单品精选",
   "price_fen": 1350,
   "price": "¥13.50"
  },
  {
   "city": "西宁",
   "province": "青海",
   "item": "牛肉堡单品精选",
   "price_fen": 1350,
   "price": "¥13.50"
  }
 ],
 "total_cities": 386,
 "data_generated_at": "2026-10-21T15:42:24"
}
```

## data_freshness()

```json
{
 "data_generated_at": "2026-10-21T15:42:24",
 "data_target_date": "2026-10-22",
 "cities": 388,
 "menu_source": "full",
 "data_source": "麦当劳中国官方 MCP (https://mcp.mcd.cn) calculate-price 批量返回, 单位: 分",
 "note": "快照数据。麦当劳的标价跨天基本稳定, 但促销价会变(实测麦咖啡冰奶铁中杯曾从 ¥13.90 回到 ¥21.00); 需要最新价时请用你自己的 MCD_MCP_TOKEN 调官方 MCP。"
}
```
