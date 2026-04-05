"""
GeneratedNote_to_FeishuList.py
测试：将一条 AI 生成的笔记数据写入飞书内容发布表（FEISHU_PUBLISH_TABLE_ID）。
"""

import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

APP_ID     = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN  = os.getenv("FEISHU_APP_TOKEN")
TABLE_ID   = os.getenv("FEISHU_PUBLISH_TABLE_ID")   # 内容发布表


def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取 tenant_access_token 失败: {data}")
    return data["tenant_access_token"]


def create_record(token, fields):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json={"fields": fields}, timeout=20)
    return resp.status_code, resp.json()


# ── 测试数据（模拟一条 AI 生成的笔记） ──────────────────────────────────────
TEST_NOTE = {
    "title":       "测试标题：大学生必看的 3 个省钱技巧",
    "content":     "正文内容：这是一段测试正文，模拟 AI 生成的小红书笔记文案。\n\n快来点赞收藏！",
    "tags":        ["省钱", "大学生", "生活技巧"],
    "images":      ["data/output/images/test_image.png"],
    "is_original": True,
    "visibility":  "公开可见",
    "content_type": "真实分享",
}


def build_fields(note):
    fields = {
        "标题":     note.get("title", ""),
        "正文":     note.get("content", ""),
        "标签":     " | ".join(note.get("tags", [])),
        "图片路径": " | ".join(note.get("images", [])),
        "是否原创": "是" if note.get("is_original") else "否",
        "可见性":   note.get("visibility", ""),
        "内容类型": note.get("content_type", ""),
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # 去掉空字符串字段
    return {k: v for k, v in fields.items() if v != ""}


def main():
    print("=== 飞书内容发布表写入测试 ===")
    print(f"APP_TOKEN  : {APP_TOKEN}")
    print(f"TABLE_ID   : {TABLE_ID}")
    print()

    token = get_tenant_access_token()
    print("✅ tenant_access_token 获取成功\n")

    fields = build_fields(TEST_NOTE)
    print("即将写入的字段：")
    print(json.dumps(fields, ensure_ascii=False, indent=2))
    print()

    status_code, result = create_record(token, fields)
    print(f"HTTP 状态码: {status_code}")
    print(f"飞书返回：{json.dumps(result, ensure_ascii=False, indent=2)}")

    if status_code == 200 and result.get("code") == 0:
        print("\n✅ 写入成功！")
    else:
        print("\n❌ 写入失败，请根据上方飞书返回排查原因")


if __name__ == "__main__":
    main()
