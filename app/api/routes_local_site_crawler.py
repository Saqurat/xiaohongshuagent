import traceback

from fastapi import APIRouter, HTTPException

from app.models.schemas import SearchCrawlRequest, SearchCrawlResponse
from app.services.local_site_crawler_service import crawl_local_site_notes, check_crawler_login_status

router = APIRouter(prefix="/local-crawl", tags=["Local Crawl"])


@router.post("/search", response_model=SearchCrawlResponse)
async def search_and_crawl_notes(request: SearchCrawlRequest):
    try:
        return await crawl_local_site_notes(request)
    except Exception as e:
        print("\n===== LOCAL CRAWL ERROR =====")
        traceback.print_exc()
        print("=============================\n")
        raise HTTPException(status_code=500, detail=str(e) or "Local crawl failed")


@router.get("/login-status")
async def get_login_status():
    """
    查询爬虫登录状态（不触发采集）。
    可在启动服务前或定时调用，提前发现登录过期问题。
    """
    try:
        result = await check_crawler_login_status()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))