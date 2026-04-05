from fastapi import APIRouter, HTTPException

from app.models.schemas import TopicGenerateRequest, TopicGenerateResponse
from app.services.topic_service import generate_topics

router = APIRouter(prefix="/topics", tags=["Topics"])


@router.post("/generate", response_model=TopicGenerateResponse)
def generate_topic_endpoint(request: TopicGenerateRequest):
    try:
        return generate_topics(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))