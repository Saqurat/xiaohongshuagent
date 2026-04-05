import json
import re
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.models.schemas import (
    TopicGenerateRequest,
    TopicGenerateResponse,
    TopicItem,
)

# Literal thinking tags as hex bytes to avoid source file encoding corruption
_THINK_START = chr(0x3C) + "think" + chr(0x3E)   # <think>
_THINK_END = chr(0x3C) + "/think" + chr(0x3E)      # </think>


def load_prompt_template() -> str:
    prompt_path = Path("app/prompts/topic_generation_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def build_llm() -> ChatOpenAI:
    llm_kwargs = {
        "model": settings.openai_model,
        "temperature": settings.openai_temperature,
        "api_key": settings.openai_api_key,
    }
    if settings.openai_base_url:
        llm_kwargs["base_url"] = settings.openai_base_url
    return ChatOpenAI(**llm_kwargs)


def _extract_json(text: str) -> str:
    """Strip thinking tags, then find and return the first JSON object or array."""
    # Step 1: remove <think>…</think> thinking blocks
    text = re.sub(
        _THINK_START + r".*?" + _THINK_END,
        "",
        text,
        flags=re.DOTALL,
    )
    text = text.strip()

    # Step 2: strip markdown code fences (```json ... ``` or ``` ...)
    if text.startswith("```"):
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
    text = text.rstrip("`").strip()

    # Step 3: find first { or [ and match to its closing bracket
    for start_pat, end_pat in [("{", "}"), ("[", "]")]:
        start = text.find(start_pat)
        if start == -1:
            continue
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == start_pat:
                depth += 1
            elif ch == end_pat:
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return text.strip()


def generate_topics(request: TopicGenerateRequest) -> TopicGenerateResponse:
    template = load_prompt_template()
    prompt = ChatPromptTemplate.from_template(template)
    llm = build_llm()

    # Manual invocation to have full control over parsing
    prompt_output = prompt.invoke(
        {
            "count": request.count,
            "audience": request.audience,
            "summary": request.summary,
            "top_keywords": ", ".join(request.top_keywords),
            "top_tags": ", ".join(request.top_tags),
            "title_patterns": ", ".join(request.title_patterns),
            "insight_points": ", ".join(request.insight_points),
        }
    )
    llm_output = llm.invoke(prompt_output)
    result_text = llm_output.content if hasattr(llm_output, "content") else str(llm_output)

    with open("_topic_raw.txt", "w", encoding="utf-8") as f:
        f.write(f"len={len(result_text)}\n")
        f.write(result_text[:300])

    try:
        json_text = _extract_json(result_text)
        with open("_topic_json.txt", "w", encoding="utf-8") as f:
            f.write(f"json_text len={len(json_text)}\n")
            f.write(json_text[:300])
        parsed = json.loads(json_text)
        topics_data = parsed.get("topics", [])
        topics = [TopicItem(**item) for item in topics_data]
        return TopicGenerateResponse(topics=topics)
    except Exception as e:
        raise ValueError(f"Failed to parse LLM output as JSON: {e}\nRaw output:\n{result_text[:500]}")