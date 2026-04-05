# XHS Content Agent — 小红书 AI 内容助手

基于 FastAPI + LangChain 构建的小红书内容挖掘与自动生成系统。支持从爬取竞品数据、分析爆款规律、AI 生成文案与配图，到一键发布的完整闭环。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| 数据采集 | 通过 Playwright 爬取小红书搜索结果，支持按关键词过滤，自动跳过视频与广告 |
| 数据分析 | 提取高频关键词、热门标签、标题规律与用户洞察，输出结构化分析报告 |
| 话题生成 | 基于分析结果，调用 LLM 生成高质量选题建议（含标题与理由） |
| 内容生成 | 针对每个选题生成完整文案：正文、标题、话题标签、互动引导语、内容类型 |
| 图片生成 | 调用阿里百炼 `qwen-image-2.0-pro` 生成符合小红书风格的配图 |
| 内容发布 | 支持 MCP 协议或 REST API 两种模式发布至小红书 |
| 飞书同步 | 将爬取数据与 AI 生成内容同步至飞书多维表格，便于团队协作与审核 |
| MCP Server | 将主流水线封装为 MCP 工具，可在 Claude Desktop / Cursor 等 AI 工具中直接调用 |
| Web UI | 内置静态前端，提供爬取、生成、发布的图形化操作界面 |

---

## 技术栈

- **后端框架**：FastAPI + Uvicorn
- **LLM 调用**：LangChain + MiniMax-M2.5（OpenAI 兼容接口）
- **图片生成**：阿里百炼 `qwen-image-2.0-pro`
- **爬虫**：Playwright（Chromium）
- **MCP 协议**：`mcp` SDK（FastMCP）
- **飞书 API**：飞书多维表格 Open API
- **中文处理**：jieba 分词
- **数据验证**：Pydantic v2

---

## 项目结构

```
xhs_content_agent/
├── app/
│   ├── api/               # FastAPI 路由层
│   │   ├── routes_agent.py            # 主流水线
│   │   ├── routes_analysis.py          # 数据分析
│   │   ├── routes_content.py           # 文案生成
│   │   ├── routes_feishu.py            # 飞书同步
│   │   ├── routes_local_site_crawler.py # 爬虫
│   │   ├── routes_publish.py           # 发布
│   │   ├── routes_topics.py            # 话题生成
│   │   └── routes_xhs_service.py       # 小红书服务
│   ├── core/
│   │   └── config.py      # 配置管理（从 .env 读取）
│   ├── models/
│   │   └── schemas.py     # Pydantic 数据模型
│   ├── prompts/
│   │   ├── content_generation_prompt.txt
│   │   └── topic_generation_prompt.txt
│   └── services/
│       ├── agent_service.py            # 主流水线编排
│       ├── analysis_service.py          # 笔记数据分析
│       ├── topic_service.py            # 话题生成
│       ├── content_service.py          # 文案生成
│       ├── image_service.py            # 图片生成（阿里百炼）
│       ├── publish_service.py          # 小红书发布
│       ├── feishu_service.py           # 飞书同步
│       ├── local_site_crawler_service.py # 小红书爬虫（Playwright）
│       └── mcp_client_service.py       # MCP 客户端
├── static/                # Web 前端页面（静态文件）
├── data/
│   ├── raw/               # 爬取数据 / Cookies / 状态文件
│   └── output/images/     # 生成的图片输出目录
├── xiaohongshumcp/        # 小红书 MCP 可执行文件
├── mcp_server.py          # MCP Server 入口
├── run.py                 # 服务启动入口
└── .env                   # 环境变量配置（勿提交）
```

---

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
.venv\Scripts\activate        # Windows PowerShell
# 或
.\.venv\Scripts\Activate.ps1 # Windows PowerShell（受限执行策略时）

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

> 注意：`.venv` 已包含在 `.gitignore` 中，无需提交。首次运行 `playwright install chromium` 可能需要几分钟下载 Chromium。

### 2. 配置环境变量

在项目根目录创建 `.env` 文件（参考 `.env.example` 填写）：

```env
# ========== LLM 配置（MiniMax）==========
OPENAI_API_KEY=your_minimax_api_key
OPENAI_MODEL=MiniMax-M2.5
OPENAI_BASE_URL=https://api.minimaxi.com/v1
OPENAI_TEMPERATURE=0.7

# ========== 图片生成配置（阿里百炼）==========
IMAGE_API_KEY=your_ali_bailian_api_key
IMAGE_MODEL=qwen-image-2.0-pro
IMAGE_BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
IMAGE_SIZE=1024*1024

# ========== 飞书多维表格（可选）==========
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_APP_TOKEN=
FEISHU_TABLE_ID=          # 爬虫数据表
FEISHU_PUBLISH_TABLE_ID=  # AI 生成笔记表

# ========== 小红书 MCP 服务（本地）==========
XHS_MCP_URL=http://localhost:18060
XHS_MCP_ENDPOINT=http://localhost:18060/mcp
XHS_MCP_BINARY=path\to\xiaohongshu-mcp-windows-amd64.exe
```

### 3. 启动服务

```bash
python run.py
```

浏览器访问 `http://127.0.0.1:8000` 进入 Web UI。
FastAPI 交互文档（Swagger）：`http://127.0.0.1:8000/docs`

---

## 主要 API

| 路由 | 说明 |
|------|------|
| `POST /local-crawl/search` | 按关键词爬取小红书图文笔记 |
| `POST /analysis/analyze` | 分析笔记列表，提取关键词、标签、标题规律、洞察点 |
| `POST /topics/generate` | 根据分析结果生成话题建议 |
| `POST /content/generate` | 根据选题生成图文文案 |
| `POST /image/generate` | 根据文案生成配图 |
| `POST /publish/prepare` | 组装发布 Payload（REST / MCP 格式） |
| `POST /publish/send` | 发布至小红书 |
| `POST /feishu/sync` | 将生成内容同步至飞书 |
| `POST /feishu/sync-crawled` | 将爬取数据同步至飞书 |
| `POST /agent/run` | 一键运行完整内容生成流水线（采集 → 分析 → 话题 → 文案 → 图片） |
| `GET  /health` | 健康检查 |

---

## MCP Server 使用

将本项目封装为 MCP Server，可在支持 MCP 协议的 AI 工具（Claude Desktop、Cursor 等）中注册使用。

**启动 MCP Server：**

```bash
python mcp_server.py
```

提供以下 MCP 工具：

| 工具 | 说明 |
|------|------|
| `run_content_pipeline` | 完整运行内容生成流水线 |
| `generate_xhs_images` | 根据文案生成配图 |
| `publish_to_xhs` | 生成配图并一键发布至小红书 |
| `check_xhs_login` | 检查小红书登录状态 |

> **注意**：发布功能依赖本地运行的小红书 MCP 服务（默认端口 `18060`），需提前启动并完成扫码登录。

---

## 爬虫说明

### 登录态

首次运行爬虫时，程序会打开浏览器窗口引导登录小红书。登录完成后状态自动保存至 `data/raw/xhs_state.json`，下次启动自动复用，无需重复登录。

### 采集数量为 0 或不足的排查

1. **视频比例过高**：搜索结果中视频笔记占多数，可换用不同关键词（如 `猫咪 日常` 而非 `猫咪`）
2. **日期过滤**：超过 1 年的图文笔记会被自动跳过
3. **网络超时**：卡片图片懒加载超时会导致该卡片被跳过，属正常现象
4. **登录失效**：删除 `data/raw/xhs_state.json` 重新登录

---

## 飞书同步说明

同步支持两种数据源：

- **AI 生成内容**：通过 `/feishu/sync` 接口同步，由 `sync_to_feishu()` 处理
- **爬取数据**：通过 `/feishu/sync-crawled` 接口同步，由 `sync_crawled_notes_to_feishu()` 处理

字段映射自动从飞书多维表格 API 获取，支持：
- **日期字段**（type=5）：自动转换为 Unix 时间戳
- **URL 字段**（type=15）：自动转换为 `{link, text}` 对象格式
- **数字字段**：直接写入

---

## 注意事项

- 爬取功能需要提前完成小红书登录（首次自动引导）
- 发布功能依赖本地运行的小红书 MCP 服务，需完成扫码登录
- 飞书同步为可选功能，未配置时相关接口返回提示信息而不会报错
- `.env` 文件包含敏感凭据，勿提交至版本控制系统

## 效果截图

![效果1](outcome/1.png)
![效果2](outcome/2.png)
![效果3](outcome/3.png)
![效果4](outcome/4.png)
