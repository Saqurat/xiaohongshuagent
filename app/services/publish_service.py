"""
publish_service.py
1. 将 ContentItem + 图片路径整合成两种格式：
   - XHSPublishPayload  (REST API 层，PascalCase 字段)
   - XHSMCPToolArgs     (MCP 协议层，小写字段)
2. 支持两种发布模式：
   - mode="mcp"   通过 MCP Streamable HTTP 协议调用 publish_content 工具
   - mode="rest"  直接调用 REST API POST /api/v1/publish
"""

import httpx

from app.core.config import settings
from app.models.schemas import (
    ContentItem,
    XHSPublishPayload,
    XHSMCPToolArgs,
    SendPublishResponse,
)


def _clean_tags(hashtags: list[str]) -> list[str]:
    """去除 # 前缀、去重、最多 10 个"""
    clean: list[str] = []
    seen: set[str] = set()
    for tag in hashtags:
        t = tag.lstrip("#").strip()
        if t and t not in seen:
            clean.append(t)
            seen.add(t)
        if len(clean) >= 10:
            break
    return clean


def build_xhs_payload(
    content: ContentItem,
    image_paths: list[str],
    is_original: bool = True,
    visibility: str = "公开可见",
) -> XHSPublishPayload:
    """
    组装 REST API 格式（PascalCase）的发布 payload。
    对应 POST /api/v1/publish。
    """
    return XHSPublishPayload(
        Title=content.title[:20],
        Content=f"{content.body}\n\n{content.cta}",
        ImagePaths=image_paths,
        Tags=_clean_tags(content.hashtags),
        IsOriginal=is_original,
        Visibility=visibility,
    )


def build_mcp_tool_args(
    content: ContentItem,
    image_paths: list[str],
    is_original: bool = True,
    visibility: str = "公开可见",
) -> XHSMCPToolArgs:
    """
    组装 MCP 协议格式（小写字段）的工具参数。
    对应 MCP 工具 publish_content 的参数结构。
    """
    return XHSMCPToolArgs(
        title=content.title[:20],
        content=f"{content.body}\n\n{content.cta}",
        images=image_paths,
        tags=_clean_tags(content.hashtags),
        is_original=is_original,
        visibility=visibility,
    )


async def send_via_rest(payload: XHSPublishPayload) -> SendPublishResponse:
    """
    REST 模式：直接 POST /api/v1/publish，跳过 MCP 协议层。
    适合不需要 MCP 协议的场景或调试。
    """
    url = f"{settings.xhs_mcp_url.rstrip('/')}/api/v1/publish"

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload.model_dump())

    if resp.status_code != 200:
        return SendPublishResponse(
            success=False,
            message=f"REST API 返回 HTTP {resp.status_code}: {resp.text}",
            mode="rest",
        )

    result = resp.json()
    return SendPublishResponse(
        success=result.get("success", False),
        message=result.get("message", ""),
        mode="rest",
        data=result.get("data"),
    )


async def send_to_xhs(
    content: ContentItem,
    image_paths: list[str],
    is_original: bool = True,
    visibility: str = "公开可见",
    mode: str = "mcp",
) -> SendPublishResponse:
    """
    统一发布入口，根据 mode 选择调用方式：
      mode="mcp"   → MCP Streamable HTTP 协议（推荐）
      mode="rest"  → 直接 REST API
    """
    if mode == "mcp":
        from app.services.mcp_client_service import publish_via_mcp
        mcp_args = build_mcp_tool_args(content, image_paths, is_original, visibility)
        return await publish_via_mcp(mcp_args)
    else:
        payload = build_xhs_payload(content, image_paths, is_original, visibility)
        return await send_via_rest(payload)