# 自动回复评论功能设计

## 1. 背景与目标

通过 MCP 协议调用小红书 MCP 服务，定时或手动获取自己笔记下的评论，由 LLM 判断是否需要回复并自动生成回复内容，实现评论自动化管理。

## 2. 核心流程

```
触发（定时/手动）
    │
    ▼
list_feeds                          获取最近 N 篇笔记
    │
    ▼
过滤：排除已处理过的笔记            （用 replied_comments.json 追踪进度）
    │
    ▼
get_feed_detail                     逐篇获取评论列表
    │
    ▼
LLM 判断每条评论是否需要回复
   输入：评论内容 + 笔记主题 + 账号人设
   输出：是否回复（bool）+ 回复内容（str，不超过 30 字）
    │
    ▼
reply_comment_in_feed               提交回复
    │
    ▼
记录到飞书表                        审核追踪
```

## 3. 模块设计

### 3.1 comment_service.py

**公开函数：**

```python
async def auto_reply_comments(
    note_ids: list[str] | None = None,  # None = 处理所有最近笔记
    max_notes: int = 3,                  # 每次最多处理笔记数
    audience: str = "大学生女性",         # 人设，用于 LLM 生成
) -> dict:
    """执行自动回复主流程"""
```

**内部函数：**

```python
async def _should_reply(comment: dict, note: dict, audience: str) -> tuple[bool, str | None]:
    """
    LLM 判断是否需要回复及生成回复内容。
    返回 (需要回复, 回复内容)。
    """

async def _fetch_comments_from_feed(feed_id: str, xsec_token: str) -> list[dict]:
    """获取指定笔记的评论列表"""

def _load_replied_set() -> set[str]:
    """从 replied_comments.json 加载已回复评论 ID 集合"""

def _save_replied(comment_id: str):
    """追加记录一条已回复评论 ID"""

async def _reply_to_feeds(feeds: list, audience: str) -> dict:
    """对一组笔记执行回复"""
```

### 3.2 routes_comment.py

**API 端点：**

```
POST /comment/auto-reply
  Body: { note_ids?: string[], max_notes?: int, audience?: string }
  Response: { success: bool, processed_notes: int, replied: int, skipped: int, message: str }

GET /comment/reply-records
  查询已回复记录（可按笔记 ID 筛选）
```

### 3.3 replied_comments.json

记录结构：

```json
{
  "replied_ids": ["comment_id_1", "comment_id_2", ...],
  "last_updated": "2026-04-06T12:00:00+08:00"
}
```

文件路径：`data/raw/replied_comments.json`

## 4. LLM 判断标准

### 4.1 判断 Prompt

```
你是一个小红书博主，昵称「{nickname}」，人设：{audience}。
笔记标题：{note_title}
笔记正文摘要：{note_desc[:200]}

以下是一条评论内容：
评论人：{comment_user_nickname}
评论内容：{comment_content}

请判断是否需要回复这条评论。

回复原则：
- 有实质问题（求链接/求教程/问价格/问细节）→ 回复
- 有转化意图（问在哪买/怎么联系/多少钱）→ 回复
- 情绪共鸣点（分享类似经历/表达认同）→ 回复
- 纯表情/无意义灌水（"哈哈哈"单独出现）→ 不回复
- 已在楼中楼回复过的类似问题 → 不重复回复
- 广告/无关内容 → 不回复

回复要求：
- 每条回复不超过 30 字
- 语气自然，像真实博主回复粉丝
- 不要过度营销，保持真诚

直接输出以下格式，不要解释：
判断: 是/否
回复内容: （仅当判断为"是"时填写，否则留空）
```

### 4.2 回复示例

| 评论 | 判断 | 回复 |
|------|------|------|
| "学长，这个岗位校招入口在哪呀？" | 是 | "校招的话可以关注官网和Boss直聘，我主页有写过~" |
| "哈哈哈太真实了" | 否 | （空） |
| "已关注，等更新！" | 是（酌情） | "谢谢关注！最近在整理下一期~" |
| "求求求链接🔗" | 是 | "我主页置顶有！可以看看~" |

## 5. 飞书记录表结构

新增一张表 `FEISHU_REPLY_TABLE_ID`，字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| 笔记标题 | 文本 | 对应笔记的标题 |
| 笔记链接 | URL | 笔记详情页 |
| 评论内容 | 多行文本 | 用户原始评论 |
| 评论人 | 文本 | 评论者昵称 |
| 评论时间 | 日期 | 评论发布时间 |
| 回复内容 | 多行文本 | AI 生成的回复 |
| 回复时间 | 日期 | 回复提交时间 |
| 处理状态 | 文本 | 已回复/无需回复/回复失败 |

## 6. 定时任务

通过外部定时器触发（如 Windows 任务计划程序、Railway cron 等），调用：

```bash
curl -X POST http://127.0.0.1:8000/comment/auto-reply \
  -H "Content-Type: application/json" \
  -d '{"max_notes": 3}'
```

建议频率：每 2 小时 1 次，避免过于频繁。

## 7. 错误处理

- MCP 服务不可用：记录错误日志，跳过该笔记，继续处理其他笔记
- 单条评论回复失败：记录并跳过，不阻塞整批处理
- LLM 判断超时：默认不回复，记录跳过
- 重复评论检测：基于评论 ID 精确去重，已回复的不再处理

## 8. 配置项

新增 `.env` 配置：

```
# 自动回复（可选）
FEISHU_REPLY_TABLE_ID=       # 回复记录表 ID
COMMENT_MAX_NOTES=3          # 每次最多处理笔记数
COMMENT_CHECK_INTERVAL=2     # 定时任务间隔（小时）
```
