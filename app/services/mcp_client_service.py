"""
mcp_client_service.py
使用 MCP Python SDK（Streamable HTTP 传输）作为 MCP Client，
调用本地小红书 MCP 服务（xiaohongshu-mcp）的工具。

小红书 MCP 服务端点：http://localhost:18060/mcp
传输协议：Streamable HTTP（mcp-go v0.7.0 官方 SDK）

可用工具（部分）：
  - check_login_status   检查登录状态
  - get_login_qrcode     获取登录二维码
  - publish_content      发布图文内容  ← 核心
  - list_feeds           获取首页 feeds
  - search_feeds         搜索内容
"""

import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.core.config import settings
from app.models.schemas import XHSMCPToolArgs, SendPublishResponse


async def call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    通用 MCP 工具调用。

    Args:
        tool_name:  工具名称，如 "publish_content"
        arguments:  工具参数字典

    Returns:
        工具调用结果（解析后的 dict）
    """
    try:
        async with streamablehttp_client(settings.xhs_mcp_endpoint) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
    except ExceptionGroup as eg:
        # Unwrap ExceptionGroup from anyio TaskGroup
        raise ExceptionGroup("MCP call failed", eg.exceptions) from eg
    except BaseException as e:
        raise

    # result.content 是 list[TextContent | ImageContent | ...]
    # publish_content 返回 TextContent，内容是 JSON 字符串
    if result.content:
        first = result.content[0]
        if hasattr(first, "text"):
            try:
                return json.loads(first.text)
            except json.JSONDecodeError:
                return {"raw": first.text}
    return {}


async def check_login_status() -> dict[str, Any]:
    """检查小红书登录状态，返回 {logged_in: bool, username: str}"""
    return await call_tool("check_login_status", {})


async def list_mcp_tools() -> list[str]:
    """列出 MCP 服务端注册的所有工具名称（调试用）"""
    async with streamablehttp_client(settings.xhs_mcp_endpoint) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
    return [t.name for t in tools_result.tools]


async def publish_via_mcp(args: XHSMCPToolArgs) -> SendPublishResponse:
    """
    通过 MCP 协议调用 publish_content 工具发布图文内容。

    Args:
        args: XHSMCPToolArgs，字段名与 MCP 工具参数一致（小写）

    Returns:
        SendPublishResponse
    """
    # 构造参数字典，排除 None 和空列表的可选字段
    tool_args: dict[str, Any] = {
        "title": args.title,
        "content": args.content,
        "images": args.images,
        "is_original": args.is_original,
        "visibility": args.visibility,
    }
    if args.tags:
        tool_args["tags"] = args.tags
    if args.schedule_at:
        tool_args["schedule_at"] = args.schedule_at
    if args.products:
        tool_args["products"] = args.products

    try:
        result = await call_tool("publish_content", tool_args)
    except ExceptionGroup as eg:
        # Unwrap anyio TaskGroup exceptions
        msgs = [str(ex) for ex in eg.exceptions]
        return SendPublishResponse(
            success=False,
            message=f"MCP 调用异常 (TaskGroup): {'; '.join(msgs)}",
            mode="mcp",
        )
    except Exception as e:
        return SendPublishResponse(
            success=False,
            message=f"MCP 调用异常: {e}",
            mode="mcp",
        )

    # XHS MCP 工具不一定返回 {"success": true}，
    # 只要调用未抛异常且返回内容不含明确错误标志，即视为成功
    raw_text = result.get("raw", "")
    has_error = result.get("success") is False or "error" in raw_text.lower() or "失败" in raw_text
    success = not has_error if raw_text else result.get("success", True)
    message = result.get("message") or raw_text or "发布成功"

    return SendPublishResponse(
        success=success,
        message=message,
        mode="mcp",
        data=result.get("data"),
    )