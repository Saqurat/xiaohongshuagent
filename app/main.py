import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.routes_health import router as health_router
from app.api.routes_analysis import router as analysis_router
from app.api.routes_topics import router as topics_router
from app.api.routes_content import router as content_router
from app.api.routes_agent import router as agent_router
from app.api.routes_local_site_crawler import router as local_crawl_router
from app.api.routes_publish import router as publish_router
from app.api.routes_feishu import router as feishu_router
from app.api.routes_xhs_service import router as xhs_service_router

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    description="AI-powered content mining and generation system for social media."
)

app.include_router(health_router)
app.include_router(analysis_router)
app.include_router(topics_router)
app.include_router(content_router)
app.include_router(agent_router)
app.include_router(local_crawl_router)
app.include_router(publish_router)
app.include_router(feishu_router)
app.include_router(xhs_service_router)

Path("data/output/images").mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory="data/output/images"), name="images")
app.mount("/static", StaticFiles(directory="static"), name="static")

from fastapi.responses import RedirectResponse

@app.get("/", tags=["Root"])
def root():
    return RedirectResponse(url="/static/index.html")