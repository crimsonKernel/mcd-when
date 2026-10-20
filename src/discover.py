"""
discover.py — 工具清单与参数 schema 勘探

官方 README 只有工具名和一句话描述, 没有参数文档。
本脚本把 tools/list 返回的完整 inputSchema 落盘到 data/tool-schemas.json,
这是后续一切调用的"地图", 也是对其他参赛者有价值的副产品(可随仓库公开, 不含任何敏感信息)。

用法:
    set MCD_MCP_TOKEN=你的token
    python src/discover.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcd_client import McdMcpClient, McdMcpError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "tool-schemas.json"


def main() -> int:
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    client = McdMcpClient(token)
    print("连接 https://mcp.mcd.cn ...")
    try:
        tools = client.list_tools()
    except McdMcpError as e:
        print(f"[失败] {e}")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "source": "https://mcp.mcd.cn (tools/list)",
        "toolCount": len(tools),
        "tools": [
            {
                "name": t.get("name"),
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            for t in tools
        ],
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已落盘 {len(tools)} 个工具的完整 schema -> {OUT.relative_to(ROOT)}")
    print()
    for t in tools:
        schema = t.get("inputSchema") or {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        params = ", ".join(
            f"{k}{'*' if k in required else ''}" for k in props
        ) or "(无参数)"
        print(f"  {t.get('name')}: {params}")
    print()
    print("注: * 为必填参数。完整类型/枚举/说明见 data/tool-schemas.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
