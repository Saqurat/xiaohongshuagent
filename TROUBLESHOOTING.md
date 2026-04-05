# 问题排查记录

本文档记录项目开发过程中遇到的所有问题及解决方案，供后续参考。

---

## 1. MiniMax 模型 JSON 解析失败（OUTPUT_PARSING_FAILURE）

**问题描述**：MiniMax-M2.5 模型输出包含 `<think>...</think>` 扩展思考标签，导致 JSON 解析失败。

**错误日志**：
```
Failed to parse LLM output as JSON or YAML
```

**原因**：LangChain 的 `PydanticOutputParser` 直接处理包含 `<think>...</think>` 的原始输出，JSON 解析失败。

**解决方案**：
- 新增 `JsonExtractor` 类（`content_service.py`），手动处理 prompt → LLM → parse 链路
- 使用正则移除 `<think>...</think>` 思考块
- 支持 YAML-like 格式 fallback 解析（模型可能输出 `title: xxx` 而非 `"title": "xxx"`）
- 使用 `chr()` 常量定义思考标签，避免源文件编码问题

**关键代码**：
```python
_THINK_START = chr(0x3C) + "think" + chr(0x3E)   # <think>
_THINK_END = chr(0x3C) + "/think" + chr(0x3E)      #</think>
```

---

## 2. topic_service.py 思考标签正则失效

**问题描述**：文件中写入的思考标签变成乱码字符，正则匹配完全失效。

**原因**：文件编码问题，特殊字符在保存时损坏。

**解决方案**：重写整个 `topic_service.py`，使用 `chr()` 构造思考标签常量。

---

## 3. 图片生成 API 不兼容

**问题描述**：MiniMax 不支持 image-01 模型，切换到阿里百炼 `qwen-image-2.0-pro`。

**错误日志**：
```
404 page not found
```

**原因**：阿里百炼 API 与 OpenAI 接口不兼容，无法通过 `base_url` 转接。

**解决方案**：
- 新增独立的 `image_service.py`，使用 httpx 直调阿里百炼 API
- 请求格式不同：
  ```python
  payload = {
      "model": settings.image_model,
      "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
      "parameters": {"size": "1024*1024", "n": image_count, "watermark": False}
  }
  ```
- 响应格式也不同：`output.choices[].message.content[].image`
- 新增 `IMAGE_API_KEY` / `IMAGE_BASE_URL` / `IMAGE_SIZE` 配置项

---

## 4. 阿里百炼 API 429 请求过多

**错误日志**：
```
Client error '429 Too Many Requests'
```

**解决方案**：增加指数退避重试逻辑（10s → 30s → 60s），最大重试 3 次。

---

## 5. Playwright Windows 事件循环不兼容

**错误日志**：
```
NotImplementedError: Event loop policy is not reproducible yet on Windows
```

**原因**：`WindowsProactorEventLoopPolicy` 与 Playwright 不兼容。

**解决方案**（`run.py`）：
```python
if sys.platform.startswith("win"):
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

---

## 6. MCP TaskGroup 异常未捕获

**错误日志**：
```
unhandled errors in a TaskGroup (1 sub-exception)
```

**原因**：`ExceptionGroup`（anyio 库）不在标准 `Exception` 继承体系中，`except Exception` 捕获不到。

**解决方案**：
```python
except ExceptionGroup as e:
    for exc in e.exceptions:
        raise exc
```

---

## 7. 飞书字段名称不匹配

**错误日志**：飞书返回字段名与代码中硬编码的字段名不一致。

**解决方案**：新增 `_get_table_fields()` API，动态获取表字段名和类型映射，不再依赖硬编码字段名。

---

## 8. 飞书日期字段类型错误

**错误日志**：
```
DateFieldConvFail
```

**原因**：飞书日期字段需要 Unix 时间戳（整数），而非字符串。

**解决方案**：
```python
if matched_field_info.get("type") == 5 and isinstance(value, str):
    try:
        value = int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())
    except ValueError:
        # 回退：仅日期格式（爬虫数据只有日期无时间）
        value = int(datetime.strptime(value, "%Y-%m-%d").timestamp())
```

---

## 9. 飞书 URL 字段类型错误

**错误日志**：
```
URLFieldConvFail: 'Link' must be an object
```

**原因**：飞书 URL 字段（`ui_type=Url`，`type=15`）需要 `{link, text}` 对象格式，而非普通字符串。

**解决方案**：
```python
elif ftype == 15 and isinstance(value, str):
    value = {"link": value, "text": value}
```

> 注意：早期文档标注 type=17，实际测试确认 type=15 为正确值。

---

## 10. 飞书数字字段类型错误

**问题描述**：用户将表字段从文本改为数字类型后，写入时仍传字符串导致失败。

**解决方案**：通知用户保持字段类型与数据格式一致，或在写入前做类型转换。

---

## 11. 爬虫采集数量为 0

**问题描述**：搜索关键词后返回 0 条候选卡片。

**原因分析**：
- 搜索 URL 被小红书重定向添加 `type=51`（视频分类），导致几乎全为视频卡片
- 视频卡片过滤逻辑（`_is_video_card`）过滤掉了几乎所有卡片
- 滚动次数不足（5 轮），图片懒加载导致部分卡片 href 超时

**解决方案**：
- 增加滚动次数至 8 轮：`await self._scroll_page(page, rounds=8)`
- 降低 href 获取超时至 5 秒，避免阻塞：`get_attribute("href", timeout=5000)`
- 减小目标数量（`target_count`）或使用多个不同关键词分散视频集中问题

---

## 12. Windows 控制台 Unicode 编码错误

**错误日志**：
```
UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'
```

**原因**：Windows GBK 控制台无法输出 `✓` 等 Unicode 字符。

**解决方案**：将所有 UI 输出中的特殊符号替换为 ASCII 字符（如 `OK`）。

---

## 13. 爬虫卡片 href 超时导致采集中断

**问题描述**：部分卡片因图片懒加载未完成，`get_attribute("href")` 超时 30 秒，for 循环串行等待严重影响效率。

**解决方案**：将 href 获取超时从默认 30s 降至 5s，超时则跳过该卡片，保证采集效率。

---

## 配置变更汇总

| 配置项 | 原值 | 新值 | 说明 |
|--------|------|------|------|
| `OPENAI_MODEL` | `gpt-4o-mini` | `MiniMax-M2.5` | 文本模型切换 |
| `IMAGE_MODEL` | `gpt-image-1` | `qwen-image-2.0-pro` | 图片模型切换 |
| 启动方式 | `uvicorn app.main:app...` | `python run.py` | 统一入口 |
| 事件循环 | `WindowsProactorEventLoopPolicy` | `WindowsSelectorEventLoopPolicy` | Windows 兼容性 |

---

## 环境要求

- Python 3.10+
- Windows 11（爬虫使用 Playwright，需 Chromium）
- MiniMax API Key（文本生成）
- 阿里百炼 API Key（图片生成）
- 飞书自建应用（多维表格读写权限）
- 小红书 MCP 服务（发布功能，可选）
