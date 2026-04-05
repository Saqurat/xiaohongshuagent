import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
TABLE_ID = os.getenv("FEISHU_TABLE_ID")

JSON_PATH = r"D:\AI agent\xhs_content_agent\data\raw\test_crawl_result.json"


def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": APP_ID,
        "app_secret": APP_SECRET
    }

    resp = requests.post(url, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise Exception(f"获取 tenant_access_token 失败: {data}")

    return data["tenant_access_token"]


def create_record(token, fields):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "fields": fields
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    return resp.status_code, resp.json()


def safe_str(value):
    if value is None:
        return ""
    return str(value).strip()


def safe_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def build_fields(item):
    # 直接按你的 JSON 字段来取
    title = safe_str(item.get("title"))
    author = safe_str(item.get("author"))
    content = safe_str(item.get("content"))
    link = safe_str(item.get("url"))
    publish_time = safe_str(item.get("publish_time"))
    content_type = safe_str(item.get("content_type"))

    likes = safe_int(item.get("likes"))
    comments = safe_int(item.get("comments"))
    favorites = safe_int(item.get("favorites"))

    tags = item.get("tags", [])
    if isinstance(tags, list):
        tags_text = ", ".join([safe_str(tag) for tag in tags if safe_str(tag)])
    else:
        tags_text = safe_str(tags)

    # 这里字段名必须和飞书表头完全一致
    fields = {
        "标题": title,
        "作者": author,
        "正文": content,
        "链接": link,          # 你的“链接”列现在是文本类型
        "点赞数": likes,
        "评论数": comments,
        "收藏数": favorites,   # 注意这里写“收藏数”，不要写“收藏量”
        "标签": tags_text,     # 建议飞书里的“标签”列也用文本类型
        "发布时间": publish_time,
        "内容类型": content_type
    }

    # 去掉空值
    cleaned_fields = {}
    for k, v in fields.items():
        if v is None:
            continue
        if isinstance(v, str) and v == "":
            continue
        cleaned_fields[k] = v

    return cleaned_fields


def main():
    print(f"JSON路径 = {JSON_PATH}")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise Exception("JSON 顶层不是 list，请检查文件结构。")

    token = get_tenant_access_token()
    print("tenant_access_token 获取成功")

    success_count = 0
    fail_count = 0

    for idx, item in enumerate(data, start=1):
        try:
            fields = build_fields(item)

            # 调试时可打开，查看实际发给飞书的内容
            print(f"\n第{idx}条 payload:")
            print(json.dumps({"fields": fields}, ensure_ascii=False, indent=2))

            status_code, result = create_record(token, fields)

            if status_code == 200 and result.get("code") == 0:
                print(f"✅ 第{idx}条成功")
                success_count += 1
            else:
                print(f"❌ 第{idx}条失败: {result}")
                fail_count += 1

        except Exception as e:
            print(f"❌ 第{idx}条异常: {e}")
            fail_count += 1

    print(f"\n完成：成功 {success_count} 条，失败 {fail_count} 条")


if __name__ == "__main__":
    main()