"""
mcp_server.py
将整个 XHS 内容生成 + 发布流水线封装为 MCP Server，使用 stdio 传输。
可直接在 Claude Desktop / Cursor / Windsurf 等支持 MCP 的 AI 工具中注册使用。

运行方式（stdio，由 MCP 客户端自动启动）：
  python mcp_server.py

工具列表：
  - run_content_pipeline    分析样本数据 → 生成话题 → 生成内容文案
  - generate_xhs_images     根据话题 + 内容文案调用 gpt-image-1 生成图片
  - publish_to_xhs          生成图片并一键发布到小红书（需 XHS MCP 服务运行）
  - check_xhs_login         检查小红书登录状态
"""

import sys
import asyncio
from pathlib import Path

# 确保项目根目录在 Python 路径中（stdio 启动时工作目录可能不同）
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

from app.models.schemas import (
    AgentRunRequest,
    TopicItem,
    ContentItem,
)
from app.services.agent_service import run_agent_pipeline
from app.services.image_service import generate_images
from app.services.publish_service import send_to_xhs

mcp = FastMCP(
    name="XHS Content Agent",
    instructions=(
        "小红书内容生成与发布助手。"
        "可以分析爆款数据、生成话题和文案、用 AI 生成配图，并自动发布到小红书。"
        "发布功能需要本地已启动小红书 MCP 服务（localhost:18060）并完成扫码登录。"
    ),
)


@mcp.tool()
async def run_content_pipeline(
    audience: str = "大学生女性",
    tone: str = "真实分享",
    topic_count: int = 3,
    content_count_per_topic: int = 2,
) -> dict:
    """
    运行完整内容生成流水线：
    1. 加载样本数据并分析爆款规律
    2. 生成若干话题建议
    3. 每个话题生成多条内容文案

    Args:
        audience: 目标受众，默认"大学生女性"
        tone: 内容风格，如"真实分享""种草推荐""教程攻略"
        topic_count: 生成话题数量
        content_count_per_topic: 每个话题生成的内容条数

    Returns:
        包含 analysis_summary、topics 和 contents 的完整结果字典
    """
    request = AgentRunRequest(
        audience=audience,
        tone=tone,
        topic_count=topic_count,
        content_count_per_topic=content_count_per_topic,
    )
    result = await run_agent_pipeline(request)

    # 整理成便于 AI 阅读的格式
    output = {
        "analysis_summary": result.analysis_summary,
        "top_keywords": result.top_keywords,
        "top_tags": result.top_tags,
        "results": [],
    }
    for item in result.results:
        output["results"].append({
            "topic": {
                "title": item.topic.title,
                "reason": item.topic.reason,
            },
            "contents": [
                {
                    "title": c.title,
                    "body": c.body,
                    "hashtags": c.hashtags,
                    "cta": c.cta,
                    "image_suggestion": c.image_suggestion,
                    "content_type": c.content_type,
                }
                for c in item.contents
            ],
        })
    return output


@mcp.tool()
async def generate_xhs_images(
    topic_title: str,
    topic_reason: str,
    content_title: str,
    content_image_suggestion: str,
    content_body: str = "",
    content_hashtags: list[str] = [],
    content_cta: str = "",
    content_type: str = "分享",
    image_count: int = 1,
) -> dict:
    """
    根据话题和内容文案调用 gpt-image-1 生成小红书配图，保存到本地。

    Args:
        topic_title: 话题标题
        topic_reason: 话题选题理由
        content_title: 文案标题
        content_image_suggestion: 图片创意描述（来自 run_content_pipeline 的 image_suggestion）
        image_count: 生成图片数量，1-4 张

    Returns:
        image_paths: 本地图片文件的绝对路径列表
    """
    topic = TopicItem(title=topic_title, reason=topic_reason)
    content = ContentItem(
        title=content_title,
        body=content_body,
        hashtags=content_hashtags,
        cta=content_cta,
        image_suggestion=content_image_suggestion,
        content_type=content_type,
    )
    paths = await generate_images(topic=topic, content=content, image_count=image_count)
    return {"image_paths": paths, "count": len(paths)}


@mcp.tool()
async def publish_to_xhs(
    topic_title: str,
    topic_reason: str,
    content_title: str,
    content_body: str,
    content_hashtags: list[str],
    content_cta: str,
    content_image_suggestion: str,
    content_type: str = "分享",
    image_count: int = 1,
    is_original: bool = True,
    visibility: str = "公开可见",
) -> dict:
    """
    完整发布流程：生成配图 → 组装格式 → 发布到小红书。
    需要本地小红书 MCP 服务已启动（localhost:18060）并完成扫码登录。

    Args:
        topic_title: 话题标题
        topic_reason: 话题选题理由
        content_title: 发布标题（最多 20 字）
        content_body: 正文内容
        content_hashtags: 话题标签列表，如 ["#穿搭", "#日常"]
        content_cta: 互动引导语（Call to Action）
        content_image_suggestion: 图片创意描述
        content_type: 内容类型（测评/清单/教程/避雷/分享）
        image_count: 生成图片数量
        is_original: 是否声明原创
        visibility: 可见性（公开可见 / 仅自己可见 / 仅互关好友可见）

    Returns:
        success: 是否发布成功
        message: 返回信息
    """
    topic = TopicItem(title=topic_title, reason=topic_reason)
    content = ContentItem(
        title=content_title,
        body=content_body,
        hashtags=content_hashtags,
        cta=content_cta,
        image_suggestion=content_image_suggestion,
        content_type=content_type,
    )

    # 生成图片
    image_paths = await generate_images(topic=topic, content=content, image_count=image_count)

    # 发布（MCP 协议）
    result = await send_to_xhs(
        content=content,
        image_paths=image_paths,
        is_original=is_original,
        visibility=visibility,
        mode="mcp",
    )

    return {
        "success": result.success,
        "message": result.message,
        "image_paths": image_paths,
        "data": result.data,
    }


@mcp.tool()
async def check_xhs_login() -> dict:
    """
    检查本地小红书 MCP 服务的登录状态。
    返回是否已登录及用户名信息。
    """
    from app.services.mcp_client_service import check_login_status
    return await check_login_status()


if __name__ == "__main__":
    # stdio 模式启动，由 MCP 客户端（Claude Desktop / Cursor 等）自动调用
    mcp.run()