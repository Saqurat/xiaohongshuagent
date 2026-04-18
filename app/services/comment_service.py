"""
comment_service.py
评论自动回复服务：
1. 通过 MCP 获取笔记列表和评论列表
2. LLM 判断是否需要回复并生成回复内容
3. 通过 MCP 回复评论
4. 防重记录在 replied_comments.json
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings
from app.models.schemas import CommentReplyRecord
from app.services.mcp_client_service import call_tool

REPLIED_FILE = Path("data/raw/replied_comments.json")

COMMENT_PROMPT_TEMPLATE = """你是一个小红书博主，人设：{audience}。
笔记标题：{note_title}
笔记正文摘要：{note_desc}

以下是一条评论内容：
评论人：{comment_user_nickname}
评论内容：{comment_content}

请判断是否需要回复这条评论。

回复原则：
- 有实质问题（求链接/求教程/问价格/问细节）→ 回复
- 有转化意图（问在哪买/怎么联系/多少钱）→ 回复
- 情绪共鸣点（分享类似经历/表达认同）→ 回复
- 纯表情/无意义灌水（"哈哈哈"单独出现）→ 不回复
- 广告/无关内容 → 不回复

回复要求：
- 每条回复不超过 30 字
- 语气自然，像真实博主回复粉丝

直接输出以下格式，不要解释：
判断: 是/否
回复内容: （仅当判断为"是"时填写，否则留空）
"""

_MINIMAX_TIMEOUT = 60


# ---------------------------------------------------------------------------
# 防重
# ---------------------------------------------------------------------------

def _load_replied_set() -> set[str]:
    if not REPLIED_FILE.exists():
        return set()
    try:
        with open(REPLIED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("replied_ids", []))
    except Exception:
        return set()


def _save_replied(comment_id: str):
    REPLIED_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"replied_ids": [], "last_updated": ""}
    if REPLIED_FILE.exists():
        try:
            with open(REPLIED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data.setdefault("replied_ids", [])
    if comment_id not in data["replied_ids"]:
        data["replied_ids"].append(comment_id)
    data["last_updated"] = datetime.now().isoformat()
    with open(REPLIED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

async def _call_minimax_llm(prompt: str) -> str:
    """直接调用 MiniMax Chat API，返回原始文本。"""
    api_key = settings.openai_api_key
    base_url = settings.openai_base_url or "https://api.minimaxi.com/v1"
    model = settings.openai_model

    async with httpx.AsyncClient(timeout=_MINIMAX_TIMEOUT) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _llm_should_reply(
    comment_content: str,
    comment_user: str,
    note_title: str,
    note_desc: str,
    audience: str,
) -> tuple[bool, str]:
    """
    调用 LLM 判断是否需要回复及生成回复内容。
    返回 (需要回复, 回复内容)。
    """
    # 切片需要在 format 之前计算，.format() 不支持 {var[:N]} 语法
    note_desc_part = note_desc[:200] if note_desc else ""
    prompt = COMMENT_PROMPT_TEMPLATE.format(
        audience=audience,
        note_title=note_title,
        note_desc=note_desc_part,
        comment_user_nickname=comment_user,
        comment_content=comment_content,
    )

    try:
        response_text = await _call_minimax_llm(prompt)
    except Exception as e:
        print(f"[CommentService] LLM 调用失败: {e}")
        return False, ""

    should_reply = False
    reply_text = ""
    for line in response_text.strip().splitlines():
        if line.startswith("判断:"):
            should_reply = "是" in line
        elif line.startswith("回复内容:"):
            reply_text = line.split("回复内容:", 1)[1].strip()

    return should_reply, reply_text


# ---------------------------------------------------------------------------
# MCP 交互
# ---------------------------------------------------------------------------

async def _get_user_profile() -> dict:
    """获取当前登录用户信息（昵称等）"""
    try:
        return await call_tool("user_profile", {})
    except Exception as e:
        print(f"[CommentService] 获取用户信息失败: {e}")
        return {}


async def _get_feeds() -> list[dict]:
    """获取笔记列表"""
    try:
        result = await call_tool("list_feeds", {})
        return result.get("feeds", [])
    except Exception as e:
        print(f"[CommentService] 获取笔记列表失败: {e}")
        return []


async def _get_feed_detail(feed_id: str, xsec_token: str) -> dict:
    """获取笔记详情（含正文描述）"""
    try:
        return await call_tool("get_feed_detail", {
            "feed_id": feed_id,
            "xsec_token": xsec_token,
        })
    except Exception as e:
        print(f"[CommentService] 获取笔记详情失败 feed_id={feed_id}: {e}")
        return {}


async def _fetch_comments(feed_id: str, xsec_token: str) -> list[dict]:
    """获取笔记一级评论列表（排除楼中楼）"""
    detail = await _get_feed_detail(feed_id, xsec_token)
    comments = detail.get("data", {}).get("comments", {}).get("list", [])
    # 只取一级评论（无子评论）
    return [
        c for c in comments
        if not c.get("subCommentCount") or c["subCommentCount"] in ("", "0")
    ]


async def _reply_comment(
    comment_id: str,
    feed_id: str,
    xsec_token: str,
    content: str,
) -> bool:
    """提交单条评论回复，返回是否成功。"""
    try:
        result = await call_tool("reply_comment_in_feed", {
            "comment_id": comment_id,
            "feed_id": feed_id,
            "xsec_token": xsec_token,
            "content": content,
        })
        # 只要不明确失败就算成功
        return result.get("success") is not False and "error" not in str(result).lower()
    except Exception as e:
        print(f"[CommentService] 回复失败 comment_id={comment_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

async def auto_reply_comments(
    note_ids: Optional[list[str]] = None,
    max_notes: int = 3,
    audience: str = "大学生女性",
) -> dict:
    """
    执行评论自动回复主流程。

    Returns:
        dict含: success, processed_notes, replied, skipped, failed, message, records
    """
    # 1. 获取用户昵称（用于 LLM 人设）
    profile = await _get_user_profile()
    nickname = profile.get("nickname", "博主")

    # 2. 获取笔记列表
    feeds = await _get_feeds()
    if not feeds:
        return {
            "success": True, "message": "无笔记可处理",
            "processed_notes": 0, "replied": 0, "skipped": 0, "failed": 0, "records": [],
        }

    # 3. 过滤指定笔记或取最近的
    if note_ids:
        feeds = [f for f in feeds if f.get("id") in note_ids]
    feeds = feeds[:max_notes]

    # 4. 加载已回复记录
    replied_set = _load_replied_set()

    replied_count = 0
    skipped_count = 0
    failed_count = 0
    records: list[CommentReplyRecord] = []

    for feed in feeds:
        feed_id = feed.get("id", "")
        xsec_token = feed.get("xsecToken", "")
        note_card = feed.get("noteCard", {})
        note_title = note_card.get("displayTitle", "")

        # 获取正文描述（用于 LLM 判断）
        detail = await _get_feed_detail(feed_id, xsec_token)
        note_desc = detail.get("data", {}, {}).get("note", {}).get("desc", "")

        # 获取评论
        comments = await _fetch_comments(feed_id, xsec_token)

        for comment in comments:
            comment_id = comment.get("id", "")
            if not comment_id or comment_id in replied_set:
                skipped_count += 1
                continue

            comment_user = comment.get("userInfo", {}).get("nickname", "匿名用户")
            comment_content = comment.get("content", "")
            comment_time_ms = comment.get("createTime", 0)

            # LLM 判断
            should_reply, reply_content = await _llm_should_reply(
                comment_content=comment_content,
                comment_user=comment_user,
                note_title=note_title,
                note_desc=note_desc,
                audience=audience,
            )

            if not should_reply or not reply_content:
                _save_replied(comment_id)
                skipped_count += 1
                continue

            # 提交回复
            ok = await _reply_comment(comment_id, feed_id, xsec_token, reply_content)
            _save_replied(comment_id)

            if ok:
                replied_count += 1
            else:
                failed_count += 1

            records.append(CommentReplyRecord(
                note_title=note_title,
                note_url=f"https://www.xiaohongshu.com/explore/{feed_id}",
                comment_id=comment_id,
                comment_user=comment_user,
                comment_content=comment_content,
                comment_time=(
                    datetime.fromtimestamp(comment_time_ms / 1000).strftime("%Y-%m-%d %H:%M")
                    if comment_time_ms else ""
                ),
                reply_content=reply_content,
                reply_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
                status="已回复" if ok else "回复失败",
            ))

            # 控制并发节奏
            await asyncio.sleep(1)

    message = f"处理 {len(feeds)} 篇笔记，回复 {replied_count} 条，跳过 {skipped_count} 条，失败 {failed_count} 条"

    # 飞书写入（如果配置了表 ID）
    if settings.feishu_reply_table_id and records:
        try:
            await _sync_records_to_feishu(records)
        except Exception as e:
            print(f"[CommentService] 飞书写入失败: {e}")

    return {
        "success": True,
        "processed_notes": len(feeds),
        "replied": replied_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "message": message,
        "records": records,
    }


async def _sync_records_to_feishu(records: list[CommentReplyRecord]):
    """将回复记录写入飞书多维表格。"""
    from app.services.feishu_service import _get_tenant_access_token, _create_record, _get_table_fields

    token = await _get_tenant_access_token()
    field_map = await _get_table_fields(token, settings.feishu_reply_table_id)

    FIELD_MAP = {
        "笔记标题": "note_title",
        "笔记链接": "note_url",
        "评论内容": "comment_content",
        "评论人": "comment_user",
        "评论时间": "comment_time",
        "回复内容": "reply_content",
        "回复时间": "reply_time",
        "处理状态": "status",
    }

    for rec in records:
        fields = {}
        raw = {
            "笔记标题": rec.note_title,
            "笔记链接": rec.note_url,
            "评论内容": rec.comment_content,
            "评论人": rec.comment_user,
            "评论时间": rec.comment_time,
            "回复内容": rec.reply_content,
            "回复时间": rec.reply_time,
            "处理状态": rec.status,
        }
        for display_name, value in raw.items():
            if not value:
                continue
            if display_name not in field_map:
                continue
            fname = field_map[display_name]["field_name"]
            ftype = field_map[display_name].get("type")

            # 日期字段转时间戳
            if ftype == 5 and isinstance(value, str):
                for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        value = int(datetime.strptime(value, fmt).timestamp())
                        break
                    except ValueError:
                        continue
            # URL 字段转对象
            elif ftype == 15 and isinstance(value, str):
                value = {"link": value, "text": value}

            fields[fname] = value

        if fields:
            await _create_record(token, settings.feishu_reply_table_id, fields)
