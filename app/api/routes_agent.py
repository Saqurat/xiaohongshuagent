from fastapi import APIRouter, HTTPException

from app.models.schemas import AgentRunRequest, AgentRunResponse
from app.services.agent_service import run_agent_pipeline

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.post("/run", response_model=AgentRunResponse)
async def run_agent_endpoint(request: AgentRunRequest):
    try:
        return await run_agent_pipeline(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))