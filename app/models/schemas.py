from pydantic import BaseModel, Field
from typing import List, Optional


class HealthResponse(BaseModel):
    status: str = "ok"
    app_name: str
    version: str


class NoteItem(BaseModel):
    title: str = Field(..., description="Note title")
    content: str = Field(..., description="Note content")
    likes: int = 0
    favorites: int = 0
    comments: int = 0
    tags: List[str] = []
    author: Optional[str] = None
    publish_time: Optional[str] = None
    url: Optional[str] = None
    content_type: Optional[str] = None
    keyword_used: Optional[str] = None


class AnalyzeRequest(BaseModel):
    items: List[NoteItem]


class ScoredNoteItem(NoteItem):
    viral_score: float


class TitleFeatureStats(BaseModel):
    average_title_length: float
    titles_with_numbers: int
    titles_with_recommendation_words: int
    titles_with_question_marks: int


class AnalyzeResponse(BaseModel):
    total_count: int
    top_notes: List[ScoredNoteItem]
    top_keywords: List[str]
    top_tags: List[str]
    title_feature_stats: TitleFeatureStats
    title_patterns: List[str]
    insight_points: List[str]
    summary: str


class TopicItem(BaseModel):
    title: str
    reason: str


class TopicGenerateRequest(BaseModel):
    summary: str
    top_keywords: List[str]
    top_tags: List[str]
    title_patterns: List[str]
    insight_points: List[str]
    audience: str = "大学生女性"
    count: int = 10


class TopicGenerateResponse(BaseModel):
    topics: List[TopicItem]


class ContentGenerateRequest(BaseModel):
    topic: str
    reason: str
    audience: str = "大学生女性"
    tone: str = "真实分享"
    count: int = 3


class ContentItem(BaseModel):
    title: str
    body: str
    hashtags: List[str]
    cta: str
    image_suggestion: str
    content_type: str


class ContentGenerateResponse(BaseModel):
    contents: List[ContentItem]


class AgentRunRequest(BaseModel):
    audience: str = "大学生女性"
    tone: str = "真实分享"
    topic_count: int = 3
    content_count_per_topic: int = 2
    items: Optional[List[NoteItem]] = None  # inject crawled notes directly


class AgentGeneratedTopicWithContents(BaseModel):
    topic: TopicItem
    contents: List[ContentItem]


class AgentRunResponse(BaseModel):
    analysis_summary: str
    top_keywords: List[str]
    top_tags: List[str]
    title_patterns: List[str]
    insight_points: List[str]
    results: List[AgentGeneratedTopicWithContents]


class SearchCrawlRequest(BaseModel):
    keywords: List[str] = Field(..., min_length=1, description="搜索关键词列表，至少填一个")
    topic_words: List[str] = Field(default_factory=list, description="话题词列表，正文/标题至少包含其中一个；为空则不过滤")
    min_comments: int = Field(0, ge=0, description="评论数最小值（>=）")
    min_likes: int = Field(0, ge=0, description="点赞数最小值（>=）")
    min_favorites: int = Field(0, ge=0, description="收藏数最小值（>=）")
    target_count: int = Field(20, ge=1, description="目标采集条数")
    content_type: str = "图文"


LocalSiteNoteCard = NoteItem  # backward-compat alias


class SearchCrawlResponse(BaseModel):
    target_count: int
    count: int
    used_keywords: List[str]
    items: List[NoteItem]


# ── 图片生成 ──────────────────────────────────────────────────────────────────

class ImageGenerateRequest(BaseModel):
    content: ContentItem
    topic: TopicItem
    image_count: int = Field(1, ge=1, le=4, description="生成图片数量，1-4 张")


class ImageGenerateResponse(BaseModel):
    image_paths: List[str] = Field(..., description="本地图片绝对路径列表")


# ── XHS MCP 发布格式 ───────────────────────────────────────────────────────────

class XHSPublishPayload(BaseModel):
    """直接对应小红书 MCP 服务 POST /api/v1/publish 的请求体"""
    Title: str = Field(..., max_length=20, description="标题，最多 20 字")
    Content: str = Field(..., description="正文 + CTA")
    ImagePaths: List[str] = Field(..., min_length=1, description="本地图片路径，至少 1 张")
    Tags: List[str] = Field(default_factory=list, description="话题标签（不含 #），最多 10 个")
    IsOriginal: bool = True
    Visibility: str = Field("公开可见", description="公开可见 / 仅自己可见 / 仅互关好友可见")


class XHSMCPToolArgs(BaseModel):
    """
    对应 xiaohongshu-mcp publish_content 工具的参数（MCP 协议层，字段名全小写）。
    与 XHSPublishPayload（REST API 层，PascalCase）区分使用。
    """
    title: str = Field(..., max_length=20, description="标题，最多 20 字")
    content: str = Field(..., description="正文 + CTA")
    images: List[str] = Field(..., min_length=1, description="本地图片路径，至少 1 张")
    tags: List[str] = Field(default_factory=list, description="话题标签（不含 #），最多 10 个")
    is_original: bool = True
    visibility: str = Field("公开可见", description="公开可见 / 仅自己可见 / 仅互关好友可见")
    schedule_at: Optional[str] = Field(None, description="定时发布 ISO8601，如 2025-01-01T10:00:00")
    products: List[str] = Field(default_factory=list, description="商品关键词")


class PreparePublishRequest(BaseModel):
    content: ContentItem
    topic: TopicItem
    image_count: int = Field(1, ge=1, le=4)
    is_original: bool = True
    visibility: str = "公开可见"
    mode: str = Field("mcp", description="调用模式：mcp（MCP 协议）或 rest（HTTP REST API）")


class PreparePublishResponse(BaseModel):
    rest_payload: XHSPublishPayload
    mcp_args: XHSMCPToolArgs
    image_paths: List[str]


class SendPublishRequest(BaseModel):
    payload: XHSPublishPayload
    mode: str = Field("mcp", description="调用模式：mcp 或 rest")


class SendPublishResponse(BaseModel):
    success: bool
    message: str
    mode: str = "mcp"
    data: Optional[dict] = None


class AgentPublishRequest(BaseModel):
    """直接把 /agent/run 的完整输出传进来，指定要发布哪条内容"""
    agent_result: AgentRunResponse
    result_index: int = Field(0, description="选第几个话题，从 0 开始")
    content_index: int = Field(0, description="选第几条内容，从 0 开始")
    image_count: int = Field(1, ge=1, le=4)
    is_original: bool = True
    visibility: str = "公开可见"
    mode: str = "mcp"


# ── 飞书同步 ──────────────────────────────────────────────────────────────────

class FeishuSyncRequest(BaseModel):
    """把已生成的内容（对齐 MCP 参数）同步到飞书多维表格，与发布流程完全独立"""
    mcp_args: XHSMCPToolArgs
    content_type: str = Field("", description="内容类型（测评/清单/教程/避雷/分享）")


class FeishuSyncFromAgentRequest(BaseModel):
    """直接把 /agent/run 结果 + 图片路径传入，同步到飞书"""
    agent_result: AgentRunResponse
    result_index: int = Field(0, description="选第几个话题，从 0 开始")
    content_index: int = Field(0, description="选第几条内容，从 0 开始")
    image_paths: List[str] = Field(..., description="已生成的本地图片路径列表")
    is_original: bool = True
    visibility: str = "公开可见"


class FeishuSyncResponse(BaseModel):
    success: bool
    message: str


class FeishuCrawledSyncRequest(BaseModel):
    items: List[NoteItem]
