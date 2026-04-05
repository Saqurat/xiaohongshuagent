import traceback

from fastapi import APIRouter, HTTPException

from app.models.schemas import SearchCrawlRequest, SearchCrawlResponse
from app.services.local_site_crawler_service import crawl_local_site_notes

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