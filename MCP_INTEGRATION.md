# MCP_INTEGRATION.md — 麦当劳 MCP 集成说明

## 使用的 MCP Server

| 项 | 值 |
|---|---|
| Server | 麦当劳中国官方 MCP Server |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP (MCP spec 2025-03-26) |
| 认证方式 | 请求头 `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| 限流 | 600 次/分钟/Token, 超限返回 429(脚本内置退避重试) |

客户端实现: `src/mcd_client.py`(零第三方依赖, 自动处理 SSE/JSON 双响应形态、
Mcp-Session-Id 会话保持、429 退避)。

## 使用的 Tool 清单与调用流程

### 普查主链路(survey.py, 一次运行 = 明天全天)

```
now-time-info                 校时: 以服务端时间为准, 目标日期 = 服务端明天
      │
query-nearby-stores           城市+关键词定位门店(beType=1 自提 / beType=5 得来速)
      │                        返回 reservationTimeOptions —— 官方时段边界, 直接入图
      │
query-meals (×锚点时刻)        在 6 个锚点时刻拉菜单, 圈定探针商品:
      │                        时段专属(早餐/下午茶/夜市/超值/随心配) + 全天常驻
      │
query-meal-detail (×商品)      按商品各自可售时段取名称与组成
      │
calculate-price (逐格)         31 时刻 × ~20 商品 × 2 渠道 逐格核价
      │                        reservationDate=明天各时刻; 失败=「不可售」, 这本身就是数据
      ▼
data/surface.json → render_report.py → dist/report.html
```

**关键机制**: `reservationDate` 允许指定未来任意时刻(格式 `yyyy-MM-dd HH:mm`),
因此不需要挂 7 天定时任务 —— 今天就能把明天从开门到打烊的每个时刻全部核价。

### 辅助链路

| Tool | 用途 |
|---|---|
| `query-meal-detail` | 核对套餐组成, 保证跨时段可比; 也在商品可售时段内取准确名称 |
| `tools/list`(discover.py) | 全量 35 个工具的 inputSchema 落盘, 官方未提供参数文档 |

### 写操作处理原则

`create-order` / `cancel-order` / `mall-create-order` / `auto-bind-coupons` /
`party-order-create` / `delivery-create-address` 等写工具 **本项目一律不调用**。
代码中以白名单形式硬性约束(见 `survey.py` 的 `READ_ONLY_TOOLS`),
从机制上保证采样过程不产生任何真实订单、不领取任何券、不写入任何账号数据。

## 真机验证过的接口行为(2026-10-20 实测)

- `query-nearby-stores` 需 **city + keyword 同时传**(searchType=2), 各城市返回 5 家门店
- 菜单按官方时段切换: 早餐商品在 10:15 后返回「已售罄或不可售」(code 60006)
- `reservationDate` 必须为未来时间(600053), 门店营业时间外被拒(600057)
- 外送(beType=2)必传 beCode(600048), 而 beCode 需个人收货地址派生 —— 本项目不采集外送
- 价格单位为 **分**(如 2600 = ¥26.00)
- `query-meals` 仅返回 code/tags, 名称需 `query-meal-detail`

## 业务价值

1. **发现隐性时段规则**: 官方时段边界(早餐 07:14–10:15 / 午餐 10:44–14:15 /
   下午茶 14:44–16:45 / 夜市 17:14–21:45)、菜单断崖与「菜单真空带」,
   官方未公开文档, 只有真机普查才能拍全。
2. **回答真问题**: 「现在去还买不买得到」「这个时段最便宜的吃法是什么」
   是高频真实决策。
3. **副产品公开**: `data/tool-schemas.json` 是全量工具的参数 schema
   (官方未提供参数文档), 随仓库公开, 供其他开发者参考。

## 合规说明

- Token 仅通过环境变量 `MCD_MCP_TOKEN` 注入, 仓库中不含任何凭证; `.env` 已加入 .gitignore
- 本项目为非官方参赛作品, 不商用、不付费分发、不暗示官方背书
- 调用频率受 `min_interval` 约束, 远低于 600 次/分钟的官方上限
