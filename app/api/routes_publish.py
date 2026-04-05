"""
routes_publish.py
发布相关路由：

  POST /publish/prepare     生成图片 + 组装两种格式 payload（不实际发布）
  POST /publish/send        发送已组装好的 payload（支持 mcp / rest 模式）
  POST /publish/run         一步完成：生成图片 → 组装 → 发布
  GET  /publish/tools       列出 MCP 服务端注册的所有工具（调试用）
  GET  /publish/login       检查小红书 MCP 登录状态
"""

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    PreparePublishRequest,
    PreparePublishResponse,
    SendPublishRequest,
    SendPublishResponse,
    AgentPublishRequest,
)
from app.services.image_service import generate_images
from app.services.publish_service import build_xhs_payload, build_mcp_tool_args, send_to_xhs

router = APIRouter(prefix="/publish", tags=["Publish"])


@router.post("/prepare", response_model=PreparePublishResponse, summary="生成图片并组装发布 payload")
async def prepare_publish(req: PreparePublishRequest) -> PreparePublishResponse:
    """
    1. 调用 gpt-image-1 生成图片，保存到本地
    2. 同时组装 REST payload（PascalCase）和 MCP tool args（小写）两种格式
    3. 返回结果，**不实际发布**（人工确认后再调 /publish/send 或 /publish/run）
    """
    try:
        image_paths = await generate_images(
            topic=req.topic,
            content=req.content,
            image_count=req.image_count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片生成失败: {e}")

    rest_payload = build_xhs_payload(
        content=req.content,
        image_paths=image_paths,
        is_original=req.is_original,
        visibility=req.visibility,
    )
    mcp_args = build_mcp_tool_args(
        content=req.content,
        image_paths=image_paths,
        is_original=req.is_original,
        visibility=req.visibility,
    )

    return PreparePublishResponse(
        rest_payload=rest_payload,
        mcp_args=mcp_args,
        image_paths=image_paths,
    )


@router.post("/send", response_model=SendPublishResponse, summary="发送 payload 到 XHS MCP 服务")
async def send_publish(req: SendPublishRequest) -> SendPublishResponse:
    """
    将 REST payload 发送到 XHS MCP 服务。
    - mode="mcp"  → 通过 MCP Streamable HTTP 协议（先将 PascalCase 转成小写参数）
    - mode="rest" → 直接调用 REST API /api/v1/publish
    """
    # 从 REST payload 反推 content 字段再走统一入口
    # 因为 SendPublishRequest 携带的是已组装好的 payload，直接发 REST 最直接
    try:
        if req.mode == "rest":
            from app.services.publish_service import send_via_rest
            return await send_via_rest(req.payload)
        else:
            # MCP 模式：将 PascalCase payload 转成 MCP tool args
            from app.services.mcp_client_service import publish_via_mcp
            from app.models.schemas import XHSMCPToolArgs
            mcp_args = XHSMCPToolArgs(
                title=req.payload.Title,
                content=req.payload.Content,
                images=req.payload.ImagePaths,
                tags=req.payload.Tags,
                is_original=req.payload.IsOriginal,
                visibility=req.payload.Visibility,
            )
            return await publish_via_mcp(mcp_args)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发布失败: {e}")


@router.post("/run", response_model=SendPublishResponse, summary="一步完成：生成图片 → 组装 → 发布")
async def run_publish(req: PreparePublishRequest) -> SendPublishResponse:
    """
    完整发布流程：
    1. gpt-image-1 生成图片
    2. 组装发布参数
    3. 根据 mode 选择 MCP 或 REST 发布

    mode 默认 "mcp"，推荐使用 MCP 协议。
    """
    try:
        image_paths = await generate_images(
            topic=req.topic,
            content=req.content,
            image_count=req.image_count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片生成失败: {e}")

    try:
        result = await send_to_xhs(
            content=req.content,
            image_paths=image_paths,
            is_original=req.is_original,
            visibility=req.visibility,
            mode=req.mode,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发布失败: {e}")

    if req.sync_feishu:
        mcp_args = build_mcp_tool_args(req.content, image_paths, req.is_original, req.visibility)
        result.feishu_sync = await sync_to_feishu(mcp_args, req.content.content_type)

    return result


@router.post("/run-from-agent", response_model=SendPublishResponse, summary="直接用 agent/run 的结果发布")
async def run_publish_from_agent(req: AgentPublishRequest) -> SendPublishResponse:
    """
    把 /agent/run 的完整返回直接传进来即可，无需手动拼字段。
    用 result_index 和 content_index 指定发布哪个话题下的哪条内容（默认各取第 0 条）。
    """
    results = req.agent_result.results
    if req.result_index >= len(results):
        raise HTTPException(status_code=400, detail=f"result_index 越界，共 {len(results)} 个话题")
    item = results[req.result_index]
    if req.content_index >= len(item.contents):
        raise HTTPException(status_code=400, detail=f"content_index 越界，共 {len(item.contents)} 条内容")

    topic = item.topic
    content = item.contents[req.content_index]

    try:
        image_paths = await generate_images(
            topic=topic,
            content=content,
            image_count=req.image_count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片生成失败: {e}")

    try:
        result = await send_to_xhs(
            content=content,
            image_paths=image_paths,
            is_original=req.is_original,
            visibility=req.visibility,
            mode=req.mode,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发布失败: {e}")

    return result


@router.get("/tools", summary="列出 MCP 服务端所有注册工具（调试用）")
async def list_tools() -> dict:
    """列出小红书 MCP 服务端注册的所有工具名称，用于调试确认连接正常。"""
    try:
        from app.services.mcp_client_service import list_mcp_tools
        tools = await list_mcp_tools()
        return {"tools": tools, "count": len(tools)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"连接 MCP 服务失败: {e}")


@router.get("/login", summary="检查小红书 MCP 登录状态")
async def check_login() -> dict:
    """通过 MCP 协议检查小红书是否已登录。"""
    try:
        from app.services.mcp_client_service import check_login_status
        return await check_login_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检查登录状态失败: {e}")