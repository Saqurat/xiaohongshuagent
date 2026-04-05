"""
image_service.py
调用阿里百炼 qwen-image-2.0-pro 生成图片，保存到本地，返回文件路径列表。
"""

import asyncio
import time
from pathlib import Path

import httpx

from app.core.config import settings
from app.models.schemas import ContentItem, TopicItem


def _build_image_prompt(topic: TopicItem, content: ContentItem) -> str:
    """
    将话题信息和内容中的 image_suggestion 整合成图片生成 prompt。
    """
    return (
        f"Topic: {topic.title}. "
        f"Visual concept: {content.image_suggestion}. "
        f"Style: warm, lifestyle, authentic, bright colors, suitable for a Chinese female audience aged 18-28. "
        f"No text overlay. Square composition 1:1."
    )


async def generate_images(
    topic: TopicItem,
    content: ContentItem,
    image_count: int = 1,
) -> list[str]:
    """
    调用阿里百炼 qwen-image-2.0-pro 生成图片，保存到本地，返回绝对路径列表。

    Args:
        topic: 话题信息，提供主题背景
        content: 生成的内容，其中 image_suggestion 作为视觉参考
        image_count: 生成图片数量，1-4 张

    Returns:
        本地图片文件的绝对路径列表
    """
    prompt = _build_image_prompt(topic, content)

    # 确保输出目录存在
    output_dir = Path(settings.image_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.image_api_key}",
    }
    payload = {
        "model": settings.image_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": {
            "size": settings.image_size,
            "n": image_count,
            "watermark": False,
        },
    }

    async def _do_request():
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                settings.image_base_url,
                headers=headers,
                json=payload,
            )
            if response.status_code == 429:
                return None, response
            response.raise_for_status()
            return response.json(), None

    # 重试 3 次，间隔 10s / 30s / 60s
    data, err = None, None
    for attempt, wait in enumerate([10, 30, 60], start=0):
        data, err = await _do_request()
        if data is not None:
            break
        print(f"[Image] 限流 (429)，{wait}s 后重试第 {attempt+2} 次…")
        await asyncio.sleep(wait)
    if data is None:
        raise RuntimeError(f"图片生成限流，重试 3 次后仍失败")

    # 阿里百炼返回格式：data.output.choices[].message.content[].image
    choices = data.get("output", {}).get("choices", [])
    if not choices:
        raise ValueError(f"阿里百炼图片响应无 choices: {data}")

    saved_paths: list[str] = []
    ts = int(time.time())

    for idx, choice in enumerate(choices):
        content_list = choice.get("message", {}).get("content", [])
        if not content_list:
            raise ValueError(f"choice[{idx}] 无 message.content: {choice}")
        image_url = content_list[0].get("image")
        if not image_url:
            raise ValueError(f"choice[{idx}] 无 image URL: {choice}")

        # 下载图片
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()

        file_path = output_dir / f"{ts}_{idx}.png"
        file_path.write_bytes(resp.content)
        saved_paths.append(str(file_path.resolve()))

    return saved_paths