"""
feishu_service.py
将 AI 生成的小红书笔记（含本地图片路径）同步到飞书多维表格。

字段名从飞书 API 动态获取，自动映射到 XHSMCPToolArgs 各项。
无需硬编码表头名称。
"""

import httpx
from datetime import datetime
from typing import List

from app.core.config import settings
from app.models.schemas import XHSMCPToolArgs, NoteItem


async def _get_tenant_access_token() -> str:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json={
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret,
        })
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: {data}")
    return data["tenant_access_token"]


async def _create_record(token: str, table_id: str, fields: dict) -> dict:
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps"
        f"/{settings.feishu_app_token}/tables/{table_id}/records"
    )
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"fields": fields},
        )
    return resp.json()


async def _get_table_fields(token: str, table_id: str) -> dict[str, dict]:
    """
    获取飞书多维表格的字段列表，返回 {字段名: 字段信息} 映射。
    字段信息包含 type（用于判断日期字段）和 ui_type。
    """
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps"
        f"/{settings.feishu_app_token}/tables/{table_id}/fields"
    )
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
        )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书表字段失败: {data}")
    # 返回 {字段名: {"type": int, "ui_type": str, ...}}
    return {f["field_name"]: f for f in data.get("data", {}).get("items", [])}


def _build_fields(args: XHSMCPToolArgs, field_map: dict[str, dict], content_type: str = "") -> dict:
    """
    将 XHSMCPToolArgs 转成飞书多维表格字段。
    field_map 是 {显示名: 显示名}，从 _get_table_fields 获取。
    """
    # 定义内容字段 -> 值 的映射
    raw_fields: dict[str, object] = {
        "标题":     args.title,
        "正文":     args.content,
        "标签":     " | ".join(args.tags) if args.tags else "",
        "图片路径": " | ".join(args.images),
        "是否原创": "是" if args.is_original else "否",
        "可见性":   args.visibility,
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if content_type:
        raw_fields["内容类型"] = content_type

    # 映射到实际字段名，检测日期字段做时间戳转换
    fields: dict = {}
    for display_name, value in raw_fields.items():
        if value == "":
            continue
        matched_field_name: str | None = None
        matched_field_info: dict | None = None
        if display_name in field_map:
            matched_field_name = field_map[display_name]["field_name"]
            matched_field_info = field_map[display_name]
        else:
            for fname, finfo in field_map.items():
                if display_name in fname or fname in display_name:
                    matched_field_name = finfo["field_name"]
                    matched_field_info = finfo
                    break

        if matched_field_name and matched_field_info:
            ftype = matched_field_info.get("type")
            # Feishu Date 字段 type=5，需传 Unix 时间戳（秒）
            if ftype == 5 and isinstance(value, str):
                try:
                    value = int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())
                except ValueError:
                    try:
                        value = int(datetime.strptime(value, "%Y-%m-%d").timestamp())
                    except ValueError:
                        pass
            # Feishu URL 字段 type=15（ui_type=Url），需传 {link, text} 对象
            elif ftype == 15 and isinstance(value, str):
                value = {"link": value, "text": value}
            fields[matched_field_name] = value

    return fields


async def sync_to_feishu(
    args: XHSMCPToolArgs,
    content_type: str = "",
) -> dict:
    """
    把一条 AI 生成的笔记同步到飞书多维表格。

    Args:
        args:         XHSMCPToolArgs，与发布到小红书的参数完全一致
        content_type: 内容类型（测评/清单/教程/避雷/分享），来自 ContentItem

    Returns:
        {"success": bool, "message": str}
    """
    if not settings.feishu_app_id or not settings.feishu_publish_table_id:
        return {"success": False, "message": "飞书配置未填写（FEISHU_APP_ID / FEISHU_PUBLISH_TABLE_ID）"}

    try:
        token = await _get_tenant_access_token()
        field_map = await _get_table_fields(token, settings.feishu_publish_table_id)
        fields = _build_fields(args, field_map, content_type)
        result = await _create_record(token, settings.feishu_publish_table_id, fields)
    except Exception as e:
        return {"success": False, "message": f"飞书同步异常: {e}"}

    if result.get("code") == 0:
        return {"success": True, "message": "飞书同步成功"}
    print(f"[Feishu] 同步失败，完整响应: {result}")
    return {"success": False, "message": f"飞书同步失败: {result}"}


async def sync_crawled_notes_to_feishu(notes: List[NoteItem]) -> dict:
    """
    将爬取到的笔记批量同步到飞书爬虫数据表（FEISHU_TABLE_ID）。
    字段与 CrawlData_to_FeishiList.py 保持一致。
    """
    if not settings.feishu_app_id or not settings.feishu_table_id:
        return {"success": False, "message": "飞书配置未填写（FEISHU_APP_ID / FEISHU_TABLE_ID）"}

    def _build_crawl_fields(note: NoteItem, field_map: dict[str, dict]) -> dict:
        raw_fields: dict = {
            "标题": note.title or "",
            "作者": note.author or "",
            "正文": note.content or "",
            "链接": note.url or "",
            "点赞数": note.likes,
            "评论数": note.comments,
            "收藏数": note.favorites,
            "标签": " | ".join(note.tags) if note.tags else "",
            "发布时间": note.publish_time or "",
            "内容类型": note.content_type or "",
        }
        # 映射到实际字段名，检测日期字段做时间戳转换
        fields: dict = {}
        for display_name, value in raw_fields.items():
            if value == "" or value is None:
                continue
            matched_field_name: str | None = None
            matched_field_info: dict | None = None
            if display_name in field_map:
                matched_field_name = field_map[display_name]["field_name"]
                matched_field_info = field_map[display_name]
            else:
                for fname, finfo in field_map.items():
                    if display_name in fname or fname in display_name:
                        matched_field_name = finfo["field_name"]
                        matched_field_info = finfo
                        break
            if matched_field_name and matched_field_info:
                ftype = matched_field_info.get("type")
                if ftype == 5 and isinstance(value, str):
                    try:
                        # 优先尝试完整时间格式
                        value = int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())
                    except ValueError:
                        try:
                            # 回退：仅日期格式（发布时间没有时间部分）
                            value = int(datetime.strptime(value, "%Y-%m-%d").timestamp())
                        except ValueError:
                            pass
                elif ftype == 15 and isinstance(value, str):
                    # URL 类型（ui_type=Url, type=15）需要 {link, text} 对象格式
                    value = {"link": value, "text": value}
                fields[matched_field_name] = value
        return fields

    try:
        token = await _get_tenant_access_token()
        field_map = await _get_table_fields(token, settings.feishu_table_id)
    except Exception as e:
        return {"success": False, "message": f"获取飞书 token 失败: {e}"}

    success_count, fail_count = 0, 0
    for note in notes:
        try:
            fields = _build_crawl_fields(note, field_map)
            if not fields:
                # 打印 field_map 中可用的字段名，方便排查
                available = list(field_map.keys())
                print(f"[Feishu] 字段映射为空，跳过: title={str(note.title)[:30]}, available_fields={available}")
                fail_count += 1
                continue
            result = await _create_record(token, settings.feishu_table_id, fields)
            if result.get("code") == 0:
                success_count += 1
            else:
                print(f"[Feishu] 写入失败 ({str(note.title)[:20]}): {result}")
                fail_count += 1
        except Exception as e:
            print(f"[Feishu] 写入异常 ({str(note.title)[:20] if note.title else 'N/A'}): {e}")
            fail_count += 1

    return {
        "success": fail_count == 0,
        "message": f"同步完成：成功 {success_count} 条，失败 {fail_count} 条",
    }