"""
mcd_client.py — 麦当劳 MCP Server 最小客户端（零依赖，仅标准库）

协议: Streamable HTTP (MCP spec 2025-03-26)
端点: https://mcp.mcd.cn
认证: Authorization: Bearer <MCD_MCP_TOKEN>

设计原则:
  1. 零第三方依赖 —— clone 下来就能跑, 不用 pip install 任何东西
  2. 自动处理 SSE / JSON 两种响应形态
  3. 自动维护 Mcp-Session-Id
  4. 内置限流退避 (官方限制: 600 次/分钟, 超限返回 429)
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from typing import Any

MCP_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "mcd-when", "version": "0.1.0"}


class McdMcpError(RuntimeError):
    """麦当劳 MCP 调用错误(含 HTTP 状态码与 RPC 错误码)。"""


class McdMcpClient:
    def __init__(self, token: str, url: str = MCP_URL, timeout: float = 30.0,
                 min_interval: float = 0.12, max_retries: int = 4):
        if not token:
            raise McdMcpError("缺少 MCP Token。请先设置环境变量 MCD_MCP_TOKEN")
        self.url = url
        self.timeout = timeout
        self.min_interval = min_interval      # 两次请求最小间隔(秒), 600/min 的安全余量
        self.max_retries = max_retries
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._session_id: str | None = None
        self._next_id = 1
        self._last_call_at = 0.0
        self._initialized = False

    # ---------- 底层 ----------

    def _throttle(self):
        delta = time.monotonic() - self._last_call_at
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last_call_at = time.monotonic()

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """发送一条 JSON-RPC 消息。notification 返回 None。"""
        self._throttle()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    sid = resp.headers.get("Mcp-Session-Id")
                    if sid:
                        self._session_id = sid
                    if resp.status == 202 or "id" not in payload:  # notification / 无响应体
                        return None
                    ctype = resp.headers.get("Content-Type", "")
                    raw = resp.read().decode("utf-8")
                    return self._parse_body(ctype, raw)
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 429:
                    wait = float(e.headers.get("Retry-After", 2 ** attempt))
                    time.sleep(min(wait, 30))
                    continue
                if e.code == 401:
                    raise McdMcpError("401: MCP Token 无效、过期或未提供。"
                                      "请到 https://open.mcd.cn/mcp 控制台重新激活。") from e
                if e.code >= 500:
                    time.sleep(min(2 ** attempt, 15))
                    continue
                raise McdMcpError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                time.sleep(min(2 ** attempt, 15))
        raise McdMcpError(f"请求失败, 已重试 {self.max_retries} 次: {last_err}")

    @staticmethod
    def _parse_body(ctype: str, raw: str) -> dict[str, Any]:
        """兼容 application/json 与 text/event-stream 两种返回。"""
        if "text/event-stream" in ctype:
            # 取 SSE 流中最后一个携带 JSON-RPC result/error 的 data 帧
            result: dict[str, Any] | None = None
            for frame in raw.split("\n\n"):
                for line in frame.splitlines():
                    if line.startswith("data:"):
                        try:
                            obj = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if "result" in obj or "error" in obj:
                            result = obj
            if result is None:
                raise McdMcpError(f"SSE 流中未找到 JSON-RPC 响应: {raw[:400]}")
            return result
        return json.loads(raw)

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        self._next_id += 1
        if params is not None:
            msg["params"] = params
        resp = self._post(msg)
        if resp is None:
            raise McdMcpError(f"{method}: 服务端未返回响应")
        if "error" in resp:
            err = resp["error"]
            raise McdMcpError(f"{method}: RPC {err.get('code')} {err.get('message')}")
        return resp.get("result")

    # ---------- 会话 ----------

    def connect(self) -> None:
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    # ---------- 高层 API ----------

    def list_tools(self) -> list[dict[str, Any]]:
        """返回全部工具的 name / description / inputSchema。"""
        self.connect()
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self._rpc("tools/list", params)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """调用工具, 返回结构化结果(优先 structuredContent, 否则解析 content 文本中的 JSON)。"""
        self.connect()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            raise McdMcpError(f"{name}: 工具返回错误: {json.dumps(result.get('content'), ensure_ascii=False)[:400]}")
        if "structuredContent" in result:
            return result["structuredContent"]
        for block in result.get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"text": text}
        return result
