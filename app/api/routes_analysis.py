import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.models.schemas import AnalyzeRequest, AnalyzeResponse, NoteItem
from app.services.analysis_service import analyze_notes

router = APIRouter(prefix="/analysis", tags=["Analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    if not request.items:
        raise HTTPException(status_code=400, detail="items cannot be empty")

    return analyze_notes(request.items)


@router.get("/sample-analyze", response_model=AnalyzeResponse)
def analyze_sample_data():
    file_path = Path("data/raw/sample_notes.json")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="sample_notes.json not found")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    notes = [NoteItem(**item) for item in data]
    return analyze_notes(notes)