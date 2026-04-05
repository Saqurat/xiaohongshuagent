"""
routes_feishu.py
飞书多维表格同步路由，与发布流程完全独立。

  POST /feishu/sync              直接传 XHSMCPToolArgs 同步到飞书
  POST /feishu/sync-from-agent   传 agent/run 结果 + 图片路径同步到飞书
"""

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    FeishuSyncRequest,
    FeishuSyncFromAgentRequest,
    FeishuSyncResponse,
    FeishuCrawledSyncRequest,
    XHSMCPToolArgs,
)
from app.services.feishu_service import sync_to_feishu, sync_crawled_notes_to_feishu
from app.services.publish_service import build_mcp_tool_args

router = APIRouter(prefix="/feishu", tags=["Feishu"])


@router.post("/sync", response_model=FeishuSyncResponse, summary="同步笔记到飞书（直接传 MCP 参数）")
async def feishu_sync(req: FeishuSyncRequest) -> FeishuSyncResponse:
    """
    将一条笔记的 MCP 参数（与发布小红书时完全一致的字段）写入飞书多维表格。
    适合在 /publish/prepare 预览后手动决定是否归档。
    """
    result = await sync_to_feishu(req.mcp_args, req.content_type)
    return FeishuSyncResponse(**result)


@router.post("/sync-from-agent", response_model=FeishuSyncResponse, summary="同步笔记到飞书（从 agent/run 结果）")
async def feishu_sync_from_agent(req: FeishuSyncFromAgentRequest) -> FeishuSyncResponse:
    """
    直接把 /agent/run 的完整结果 + 已生成的图片路径传进来，组装 MCP 参数后同步到飞书。
    result_index / content_index 选择具体哪条内容，默认各取第 0 条。
    """
    results = req.agent_result.results
    if req.result_index >= len(results):
        raise HTTPException(status_code=400, detail=f"result_index 越界，共 {len(results)} 个话题")
    item = results[req.result_index]
    if req.content_index >= len(item.contents):
        raise HTTPException(status_code=400, detail=f"content_index 越界，共 {len(item.contents)} 条内容")

    content = item.contents[req.content_index]
    mcp_args = build_mcp_tool_args(
        content=content,
        image_paths=req.image_paths,
        is_original=req.is_original,
        visibility=req.visibility,
    )
    result = await sync_to_feishu(mcp_args, content.content_type)
    return FeishuSyncResponse(**result)


@router.post("/sync-crawled", response_model=FeishuSyncResponse, summary="批量同步爬取数据到飞书")
async def feishu_sync_crawled(req: FeishuCrawledSyncRequest) -> FeishuSyncResponse:
    """将爬取到的笔记列表批量写入飞书爬虫数据表（FEISHU_TABLE_ID）。"""
    result = await sync_crawled_notes_to_feishu(req.items)
    return FeishuSyncResponse(**result)