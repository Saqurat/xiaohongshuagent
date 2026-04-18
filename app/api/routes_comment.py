import traceback

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    CommentAutoReplyRequest,
    CommentAutoReplyResponse,
)
from app.services.comment_service import auto_reply_comments

router = APIRouter(prefix="/comment", tags=["Comment"])


@router.post("/auto-reply", response_model=CommentAutoReplyResponse)
async def auto_reply(request: CommentAutoReplyRequest):
    """
    触发评论自动回复流程。

    - 按 note_ids 指定笔记，或处理最近 max_notes 篇笔记
    - 对每条评论调用 LLM 判断是否回复
    - 回复内容写入 replied_comments.json 防重
    - 回复记录通过 response 返回（后续可扩展写入飞书）
    """
    try:
        result = await auto_reply_comments(
            note_ids=request.note_ids,
            max_notes=request.max_notes,
            audience=request.audience,
        )
        return CommentAutoReplyResponse(**result)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e) or "Auto reply failed")


@router.get("/reply-records")
async def get_reply_records():
    """
    查询已回复评论记录。
    返回 replied_comments.json 中的所有评论 ID。
    """
    from app.services.comment_service import _load_replied_set
    replied = _load_replied_set()
    return {"total": len(replied), "replied_ids": list(replied)}


@router.get("/login-status")
async def check_login():
    """检查小红书 MCP 登录状态。"""
    from app.services.mcp_client_service import check_login_status
    return await check_login_status()
