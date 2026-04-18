"""
test_comment_service.py
评论服务单元测试：防重文件读写 + LLM 解析逻辑
"""

import json
import pytest
import tempfile
import os

from app.services.comment_service import (
    _load_replied_set,
    _save_replied,
)


# ---------------------------------------------------------------------------
# 防重文件测试
# ---------------------------------------------------------------------------

def test_load_replied_set_empty(tmp_path):
    """无文件时返回空集合"""
    # 临时替换 REPLIED_FILE
    from app.services import comment_service
    original = comment_service.REPLIED_FILE
    comment_service.REPLIED_FILE = tmp_path / "replied_empty.json"
    try:
        result = _load_replied_set()
        assert result == set()
    finally:
        comment_service.REPLIED_FILE = original


def test_save_and_load_single(tmp_path):
    """保存一条后能正确读取"""
    from app.services import comment_service
    original = comment_service.REPLIED_FILE
    comment_service.REPLIED_FILE = tmp_path / "replied_single.json"
    try:
        _save_replied("comment_001")
        loaded = _load_replied_set()
        assert "comment_001" in loaded
    finally:
        comment_service.REPLIED_FILE = original


def test_save_duplicate_no_duplication(tmp_path):
    """重复保存同一 ID 不会产生重复"""
    from app.services import comment_service
    original = comment_service.REPLIED_FILE
    comment_service.REPLIED_FILE = tmp_path / "replied_dup.json"
    try:
        _save_replied("comment_002")
        _save_replied("comment_002")
        loaded = _load_replied_set()
        assert list(loaded).count("comment_002") == 1
    finally:
        comment_service.REPLIED_FILE = original


def test_save_multiple_ids(tmp_path):
    """保存多条ID"""
    from app.services import comment_service
    original = comment_service.REPLIED_FILE
    comment_service.REPLIED_FILE = tmp_path / "replied_multi.json"
    try:
        _save_replied("c1")
        _save_replied("c2")
        _save_replied("c3")
        loaded = _load_replied_set()
        assert len(loaded) == 3
        assert loaded == {"c1", "c2", "c3"}
    finally:
        comment_service.REPLIED_FILE = original


# ---------------------------------------------------------------------------
# LLM 输出解析测试
# ---------------------------------------------------------------------------

def test_llm_output_parse_reply_yes():
    """解析 LLM 输出：判断=是"""
    import asyncio

    async def fake_llm(prompt):
        return """判断: 是
回复内容: 谢谢关注！最近在整理~"""

    async def run():
        from app.services.comment_service import _llm_should_reply
        should_reply, text = await _llm_should_reply(
            comment_content="已关注，等更新！",
            comment_user="粉丝A",
            note_title="测试标题",
            note_desc="测试正文",
            audience="大学生女性",
        )
        assert should_reply is True
        assert "谢谢关注" in text

    from app.services import comment_service
    original = comment_service._call_minimax_llm
    comment_service._call_minimax_llm = fake_llm
    try:
        asyncio.run(run())
    finally:
        comment_service._call_minimax_llm = original


def test_llm_output_parse_reply_no():
    """解析 LLM 输出：判断=否"""
    import asyncio

    async def fake_llm(prompt):
        return """判断: 否
回复内容:"""

    async def run():
        from app.services.comment_service import _llm_should_reply
        should_reply, text = await _llm_should_reply(
            comment_content="哈哈哈笑死我了",
            comment_user="路人B",
            note_title="测试",
            note_desc="",
            audience="大学生女性",
        )
        assert should_reply is False
        assert text == ""

    from app.services import comment_service
    original = comment_service._call_minimax_llm
    comment_service._call_minimax_llm = fake_llm
    try:
        asyncio.run(run())
    finally:
        comment_service._call_minimax_llm = original
