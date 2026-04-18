from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "XHS Content Agent"
    app_version: str = "0.1.0"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.7
    openai_base_url: Optional[str] = None

    # 文生图模型（阿里百炼）
    image_api_key: str = ""
    image_model: str = "qwen-image-2.0-pro"
    image_base_url: str = ""
    image_size: str = "1024*1024"
    image_output_dir: str = "data/output/images"

    # 飞书多维表格
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_app_token: str = ""
    feishu_table_id: str = ""           # 爬虫数据表
    feishu_publish_table_id: str = ""   # AI 生成笔记表

    # 小红书 MCP 服务地址
    xhs_mcp_url: str = "http://localhost:18060"
    # MCP 协议端点（Streamable HTTP）
    xhs_mcp_endpoint: str = "http://localhost:18060/mcp"
    # MCP 二进制路径（用于后端自动启动）
    xhs_mcp_binary: str = ""

    # 自动回复配置
    feishu_reply_table_id: str = ""      # 回复记录表 ID
    comment_max_notes: int = 3           # 每次最多处理笔记数
    comment_check_interval: int = 2      # 定时任务间隔（小时）

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()