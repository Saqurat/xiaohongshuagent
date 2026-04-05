import json
from pathlib import Path
from typing import List

from app.models.schemas import (
    NoteItem,
    AgentRunRequest,
    AgentRunResponse,
    AgentGeneratedTopicWithContents,
    TopicGenerateRequest,
    ContentGenerateRequest,
)
from app.services.analysis_service import analyze_notes
from app.services.topic_service import generate_topics
from app.services.content_service import generate_contents


def load_sample_notes() -> List[NoteItem]:
    file_path = Path("data/raw/sample_notes.json")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [NoteItem(**item) for item in data]


async def run_agent_pipeline(request: AgentRunRequest) -> AgentRunResponse:
    """
    Note source priority:
    1. request.items  — injected directly (e.g. from test_crawl_result.json)
    2. data/raw/sample_notes.json  — fallback sample data
    """
    notes: List[NoteItem] = request.items if request.items else load_sample_notes()

    # Step 1: analyze
    analysis_result = analyze_notes(notes)

    # Step 2: generate topics
    topic_result = generate_topics(TopicGenerateRequest(
        summary=analysis_result.summary,
        top_keywords=analysis_result.top_keywords,
        top_tags=analysis_result.top_tags,
        title_patterns=analysis_result.title_patterns,
        insight_points=analysis_result.insight_points,
        audience=request.audience,
        count=request.topic_count,
    ))

    # Step 3: generate contents per topic
    results = []
    for topic in topic_result.topics:
        content_result = generate_contents(ContentGenerateRequest(
            topic=topic.title,
            reason=topic.reason,
            audience=request.audience,
            tone=request.tone,
            count=request.content_count_per_topic,
        ))
        results.append(AgentGeneratedTopicWithContents(
            topic=topic,
            contents=content_result.contents,
        ))

    return AgentRunResponse(
        analysis_summary=analysis_result.summary,
        top_keywords=analysis_result.top_keywords,
        top_tags=analysis_result.top_tags,
        title_patterns=analysis_result.title_patterns,
        insight_points=analysis_result.insight_points,
        results=results,
    )
