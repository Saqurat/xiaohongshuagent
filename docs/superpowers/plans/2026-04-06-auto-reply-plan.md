# 自动回复评论功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增评论自动回复功能，通过 MCP 获取笔记评论，由 LLM 判断是否回复并生成内容，最后提交回复并记录到飞书。

**Architecture:** 利用现有的 `mcp_client_service.call_tool()` 获取笔记和评论列表，调用 LLM（MiniMax）判断评论是否需要回复并生成回复内容，通过 `reply_comment_in_feed` 提交回复，防重记录在 `data/raw/replied_comments.json`。

**Tech Stack:** FastAPI / MCP / MiniMax LLM / 飞书多维表格 / Pydantic

---

## 文件结构

```
app/
  services/
    comment_service.py         # 新增：评论服务核心逻辑
  api/
    routes_comment.py         # 新增：API 路由
  models/
    schemas.py               # 修改：新增 CommentReplyRecord 模型

app/core/
  config.py                  # 修改：新增 FEISHU_REPLY_TABLE_ID / COMMENT_MAX_NOTES 配置

.env                          # 修改：新增配置项

tests/app/services/          # 新增：测试目录
  test_comment_service.py
```

---

## Task 1: 新增配置项

**Files:**
- Modify: `app/core/config.py`
- Modify: `.env`

- [ ] **Step 1: 更新 Settings 类，添加评论回复相关配置**

文件路径: `app/core/config.py`

在 `Settings` 类中添加：

```python
# 自动回复配置
feishu_reply_table_id: str = ""      # 回复记录表 ID
comment_max_notes: int = 3            # 每次最多处理的笔记数
comment_check_interval: int = 2      # 定时任务间隔（小时）
```

- [ ] **Step 2: 更新 .env 文件（勿提交，仅本地）**

在 `.env` 末尾添加：

```env
# 自动回复（可选）
FEISHU_REPLY_TABLE_ID=
COMMENT_MAX_NOTES=3
COMMENT_CHECK_INTERVAL=2
```

- [ ] **Step 3: 提交**

```bash
git add app/core/config.py && git commit -m "feat(comment): 新增评论回复相关配置"
```

---

## Task 2: 新增 Pydantic 模型

**Files:**
- Modify: `app/models/schemas.py`

- [ ] **Step 1: 在 schemas.py 末尾添加 CommentReplyRecord 模型**

```python
class CommentReplyRecord(BaseModel):
    """单条评论回复记录"""
    note_title: str = Field("", description="笔记标题")
    note_url: str = Field("", description="笔记链接")
    comment_id: str = Field("", description="评论 ID")
    comment_user: str = Field("", description="评论人昵称")
    comment_content: str = Field("", description="评论内容")
    comment_time: str = Field("", description="评论时间")
    reply_content: str = Field("", description="AI 生成的回复内容")
    reply_time: str = Field("", description="回复提交时间")
    status: str = Field("已回复", description="状态：已回复/无需回复/回复失败")


class CommentAutoReplyRequest(BaseModel):
    note_ids: Optional[List[str]] = Field(None, description="指定笔记 ID 列表，None 表示处理最近笔记")
    max_notes: int = Field(3, description="每次最多处理笔记数")
    audience: str = Field("大学生女性", description="账号人设，用于 LLM 生成")


class CommentAutoReplyResponse(BaseModel):
    success: bool
    processed_notes: int = 0
    replied: int = 0
    skipped: int = 0
    failed: int = 0
    message: str = ""
    records: List[CommentReplyRecord] = []


class ReplyRecordQuery(BaseModel):
    note_id: Optional[str] = Field(None, description="按笔记 ID 筛选")
```

- [ ] **Step 2: 提交**

```bash
git add app/models/schemas.py && git commit -m "feat(comment): 新增 CommentReplyRecord 等数据模型"
```

---

## Task 3: 核心服务 comment_service.py

**Files:**
- Create: `app/services/comment_service.py`

**依赖：** `mcp_client_service.call_tool()`, `app.core.config.settings`, `app.models.schemas.CommentReplyRecord`

- [ ] **Step 1: 创建基础框架（函数签名和常量）**

```python
import json
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.models.schemas import CommentReplyRecord
from app.services.mcp_client_service import call_tool

REPLIED_FILE = Path("data/raw/replied_comments.json")

COMMENT_PROMPT_TEMPLATE = """你是一个小红书博主，昵称「{nickname}」，人设：{audience}。
笔记标题：{note_title}
笔记正文摘要：{note_desc[:200] if note_desc else ''}

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
    if comment_id not in data.get("replied_ids", []):
        data.setdefault("replied_ids", []).append(comment_id)
    data["last_updated"] = datetime.now().isoformat()
    with open(REPLIED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def _call_llm_should_reply(
    comment_content: str,
    comment_user: str,
    note_title: str,
    note_desc: str,
    audience: str,
    nickname: str,
) -> tuple[bool, str]:
    """
    调用 LLM 判断是否需要回复并生成回复内容。
    返回 (需要回复, 回复内容)。
    """
    prompt = COMMENT_PROMPT_TEMPLATE.format(
        nickname=nickname,
        audience=audience,
        note_title=note_title,
        note_desc=note_desc,
        comment_user_nickname=comment_user,
        comment_content=comment_content,
    )
    # 使用现有 LLM 调用方式（复用 content_service 的 chain 模式）
    from app.services.content_service import _call_minimax_raw
    response_text = await _call_minimax_raw(prompt)

    # 解析 LLM 输出
    should_reply = False
    reply_text = ""
    for line in response_text.strip().splitlines():
        if line.startswith("判断:"):
            should_reply = "是" in line
        elif line.startswith("回复内容:"):
            reply_text = line.split("回复内容:", 1)[1].strip()

    return should_reply, reply_text


async def _fetch_comments_from_feed(feed_id: str, xsec_token: str) -> list[dict]:
    """获取指定笔记的一级评论列表（排除 subComments）"""
    try:
        result = await call_tool("get_feed_detail", {
            "feed_id": feed_id,
            "xsec_token": xsec_token,
        })
        comments = result.get("data", {}).get("comments", {}).get("list", [])
        # 只取一级评论（不包含楼中楼）
        return [c for c in comments if not c.get("subCommentCount") or c.get("subCommentCount") == "0"]
    except Exception as e:
        print(f"[CommentService] 获取评论失败 feed_id={feed_id}: {e}")
        return []


async def _get_user_profile() -> dict:
    """获取当前登录用户信息（昵称等）"""
    try:
        return await call_tool("user_profile", {})
    except Exception:
        return {}


async def _reply_single_comment(
    comment_id: str,
    feed_id: str,
    xsec_token: str,
    reply_content: str,
) -> bool:
    """对单条评论提交回复，返回是否成功"""
    try:
        result = await call_tool("reply_comment_in_feed", {
            "comment_id": comment_id,
            "feed_id": feed_id,
            "xsec_token": xsec_token,
            "content": reply_content,
        })
        return result.get("success") is not False and "error" not in str(result).lower()
    except Exception as e:
        print(f"[CommentService] 回复失败 comment_id={comment_id}: {e}")
        return False
```

- [ ] **Step 2: 实现 auto_reply_comments 主函数**

```python
async def auto_reply_comments(
    note_ids: Optional[list[str]] = None,
    max_notes: int = 3,
    audience: str = "大学生女性",
) -> dict:
    """
    执行自动回复主流程。

    返回 dict 含:
      success, processed_notes, replied, skipped, failed, message, records
    """
    # 1. 获取当前用户信息（用于 LLM 人设）
    profile = await _get_user_profile()
    nickname = profile.get("nickname", "博主")

    # 2. 获取笔记列表
    try:
        feeds_result = await call_tool("list_feeds", {})
    except Exception as e:
        return {"success": False, "message": f"获取笔记列表失败: {e}", "processed_notes": 0, "replied": 0, "skipped": 0, "failed": 0, "records": []}

    feeds = feeds_result.get("feeds", [])
    if not feeds:
        return {"success": True, "message": "无笔记可处理", "processed_notes": 0, "replied": 0, "skipped": 0, "failed": 0, "records": []}

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
        note_card = feed.get("noteCard", {})
        feed_id = feed.get("id")
        xsec_token = feed.get("xsecToken", "")
        note_title = note_card.get("displayTitle", "")
        user_info = note_card.get("user", {})
        note_desc = ""  # get_feed_detail 里才有

        # 获取笔记详情（含正文描述）
        try:
            detail_result = await call_tool("get_feed_detail", {
                "feed_id": feed_id,
                "xsec_token": xsec_token,
            })
            note_desc = detail_result.get("data", {}).get("note", {}).get("desc", "")
        except Exception:
            pass

        # 获取评论列表
        comments = await _fetch_comments_from_feed(feed_id, xsec_token)

        for comment in comments:
            comment_id = comment.get("id", "")
            if not comment_id or comment_id in replied_set:
                skipped_count += 1
                continue

            comment_user = comment.get("userInfo", {}).get("nickname", "匿名用户")
            comment_content = comment.get("content", "")

            # LLM 判断是否回复
            should_reply, reply_content = await _call_llm_should_reply(
                comment_content=comment_content,
                comment_user=comment_user,
                note_title=note_title,
                note_desc=note_desc,
                audience=audience,
                nickname=nickname,
            )

            if not should_reply or not reply_content:
                skipped_count += 1
                _save_replied(comment_id)  # 也记录，避免重复查询
                continue

            # 提交回复
            ok = await _reply_single_comment(comment_id, feed_id, xsec_token, reply_content)
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
                comment_time=datetime.fromtimestamp(comment.get("createTime", 0) / 1000).strftime("%Y-%m-%d %H:%M") if comment.get("createTime") else "",
                reply_content=reply_content,
                reply_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
                status="已回复" if ok else "回复失败",
            ))

    return {
        "success": True,
        "processed_notes": len(feeds),
        "replied": replied_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "message": f"处理 {len(feeds)} 篇笔记，回复 {replied_count} 条，跳过 {skipped_count} 条，失败 {failed_count} 条",
        "records": records,
    }
```

- [ ] **Step 3: 确认 content_service 有可复用的 _call_minimax_raw 函数**

如果不存在，创建它：

```python
async def _call_minimax_raw(prompt: str) -> str:
    """直接调用 LLM，返回原始文本（不解析 JSON）。"""
    from app.services.content_service import _MINIMAX_MODEL, _MINIMAX_API_KEY, _MINIMAX_BASE_URL
    import httpx
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{_MINIMAX_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {_MINIMAX_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": _MINIMAX_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
```

从 `content_service.py` 顶部读取 `_MINIMAX_MODEL` 等常量定义（需要从 settings 读取）。

- [ ] **Step 4: 提交**

```bash
git add app/services/comment_service.py && git commit -m "feat(comment): 新增评论自动回复核心服务"
```

---

## Task 4: API 路由

**Files:**
- Create: `app/api/routes_comment.py`
- Modify: `app/main.py`

- [ ] **Step 1: 创建 routes_comment.py**

```python
import traceback
from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    CommentAutoReplyRequest,
    CommentAutoReplyResponse,
    ReplyRecordQuery,
)
from app.services.comment_service import auto_reply_comments

router = APIRouter(prefix="/comment", tags=["Comment"])


@router.post("/auto-reply", response_model=CommentAutoReplyResponse)
async def auto_reply(request: CommentAutoReplyRequest):
    """
    触发评论自动回复流程。

    - 按 note_ids 指定笔记，或处理最近笔记
    - 对每条评论调用 LLM 判断是否回复
    - 回复内容写入 replied_comments.json 防重
    - 回复记录通过 response 返回
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reply-records")
async def get_reply_records(
    note_id: str | None = None,
):
    """
    查询已回复记录（支持按笔记 ID 筛选）。
    读取 replied_comments.json，返回已处理过的评论 ID 列表。
    """
    from app.services.comment_service import _load_replied_set
    replied = _load_replied_set()
    return {"total": len(replied), "replied_ids": list(replied)}


@router.get("/login-status")
async def check_comment_login():
    """检查小红书 MCP 登录状态"""
    from app.services.mcp_client_service import check_login_status
    return await check_login_status()
```

- [ ] **Step 2: 在 main.py 中注册路由**

在 `from app.api.routes_feishu import router as feishu_router` 后添加：

```python
from app.api.routes_comment import router as comment_router
```

在 `app.include_router(feishu_router)` 后添加：

```python
app.include_router(comment_router)
```

- [ ] **Step 3: 提交**

```bash
git add app/api/routes_comment.py app/main.py && git commit -m "feat(comment): 新增评论回复 API 路由"
```

---

## Task 5: 飞书记录同步（可选）

**Files:**
- Modify: `app/services/comment_service.py`（在 auto_reply_comments 返回后）

- [ ] **Step 1: 在 auto_reply_comments 末尾追加飞书写入逻辑**

在成功返回前添加：

```python
    # 如果配置了飞书回复记录表，写入记录
    if settings.feishu_reply_table_id and records:
        from app.services.feishu_service import _get_tenant_access_token, _create_record, _get_table_fields
        try:
            token = await _get_tenant_access_token()
            field_map = await _get_table_fields(token, settings.feishu_reply_table_id)
            for rec in records:
                # 字段映射（参考 feishu_service._build_fields 逻辑）
                raw = {
                    "笔记标题": rec.note_title,
                    "笔记链接": rec.note_url,
                    "评论内容": rec.comment_content,
                    "评论人": rec.comment_user,
                    "回复内容": rec.reply_content,
                    "回复时间": rec.reply_time,
                    "处理状态": rec.status,
                }
                fields = {}
                for display_name, value in raw.items():
                    if display_name in field_map:
                        fname = field_map[display_name]["field_name"]
                        ftype = field_map[display_name].get("type")
                        if ftype == 5 and isinstance(value, str):
                            try:
                                value = int(datetime.strptime(value, "%Y-%m-%d %H:%M").timestamp())
                            except Exception:
                                pass
                        elif ftype == 15 and isinstance(value, str):
                            value = {"link": value, "text": value}
                        fields[fname] = value
                await _create_record(token, settings.feishu_reply_table_id, fields)
        except Exception as e:
            print(f"[CommentService] 飞书写入失败: {e}")
```

- [ ] **Step 2: 提交**

```bash
git add app/services/comment_service.py && git commit -m "feat(comment): 自动回复结果写入飞书记录表"
```

---

## Task 6: 单元测试

**Files:**
- Create: `tests/app/services/test_comment_service.py`

- [ ] **Step 1: 创建测试目录和文件**

```python
import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from app.services.comment_service import (
    _load_replied_set,
    _save_replied,
    REPLIED_FILE,
)


def test_load_replied_set_empty():
    # 清理测试文件
    if REPLIED_FILE.exists():
        REPLIED_FILE.unlink()
    result = _load_replied_set()
    assert result == set()


def test_save_and_load_replied():
    if REPLIED_FILE.exists():
        REPLIED_FILE.unlink()
    test_id = "test_comment_123"
    _save_replied(test_id)
    loaded = _load_replied_set()
    assert test_id in loaded


def test_save_duplicate_no_dupe():
    if REPLIED_FILE.exists():
        REPLIED_FILE.unlink()
    test_id = "dup_id"
    _save_replied(test_id)
    _save_replied(test_id)  # 重复保存
    loaded = _load_replied_set()
    assert list(loaded).count(test_id) == 1  # 不重复
```

- [ ] **Step 2: 运行测试验证**

```bash
cd /d/就业/xhs_content_agent-main && .venv/scripts/python -m pytest tests/app/services/test_comment_service.py -v
```

预期：3 个测试 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/ && git commit -m "test(comment): 新增评论服务单元测试"
```

---

## 完整提交流程

全部 Task 完成后执行：

```bash
cd /d/就业/xhs_content_agent-main
git push origin main
```

---

## 自检清单

| 检查项 | 状态 |
|--------|------|
| 配置项 config.py / .env | ✅ |
| Pydantic 模型 schemas.py | ✅ |
| 核心服务 comment_service.py | ✅ |
| API 路由 routes_comment.py | ✅ |
| main.py 注册新路由 | ✅ |
| 飞书写入（可选）| ✅ |
| 单元测试 | ✅ |
| 全部提交并推送 | ⬜ |
