import ast
import json
import re
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.models.schemas import (
    ContentGenerateRequest,
    ContentGenerateResponse,
)


# Literal strings for thinking tags (MiniMax extended thinking uses <think>…</think>)
_THINK_START = "<think>"
_THINK_END = "</think>"


class JsonExtractor(PydanticOutputParser):
    """Wraps PydanticOutputParser to handle LLM output that may contain
    non-JSON text such as extended-thinking tags (MiniMax emits <think>…</think>)
    around the actual structured response, or may output YAML-like format
    instead of strict JSON.

    Steps:
    1. Strip <think>…</think> thinking blocks.
    2. Strip leading/trailing whitespace.
    3. Try parsing as JSON first.
    4. Fall back to parsing YAML-like format (key: value without quotes).
    """

    def parse(self, response: str) -> ContentGenerateResponse:
        # LangChain returns AIMessage; extract .content if available
        if hasattr(response, "content"):
            text = response.content
        elif isinstance(response, str):
            text = response
        else:
            text = str(response)



        # Step 1 – remove thinking tags (DOTALL makes . match newlines)
        text = re.sub(
            _THINK_START + r".*?" + _THINK_END,
            "",
            text,
            flags=re.DOTALL,
        )

        # Step 2 – strip whitespace and markdown code-fence markers
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            # Strip generic code fence
            text = re.sub(r"^```[a-z]*\n?", "", text)
        text = text.strip()

        # Step 3 – try JSON
        try:
            parsed = json.loads(text)
            # If model outputs a list, wrap as contents
            if isinstance(parsed, list):
                return ContentGenerateResponse(contents=parsed)
            # If model outputs ContentItem fields directly (no "contents" wrapper),
            # wrap them appropriately
            if "contents" in parsed:
                return ContentGenerateResponse(**parsed)
            elif "title" in parsed or "content" in parsed or "body" in parsed:
                return ContentGenerateResponse(contents=[parsed])
            else:
                raise ValueError(f"JSON parsed but unknown structure: {list(parsed.keys())}")
        except json.JSONDecodeError:
            # Try stripping trailing ``` if present
            text2 = re.sub(r"```+$", "", text).strip()
            try:
                parsed = json.loads(text2)
                if isinstance(parsed, list):
                    return ContentGenerateResponse(contents=parsed)
                if "contents" in parsed:
                    return ContentGenerateResponse(**parsed)
                elif "title" in parsed or "content" in parsed or "body" in parsed:
                    return ContentGenerateResponse(contents=[parsed])
            except json.JSONDecodeError:
                pass

        # Step 4 – parse YAML-like "key: value" format
        try:
            return self._parse_yaml_like(text)
        except Exception as e:
            raise ValueError(
                f"Failed to parse LLM output as JSON or YAML: {e}\n"
                f"Text preview (500 chars): {text[:500]}"
            )

    def _parse_yaml_like(self, text: str) -> ContentGenerateResponse:
        """Parse YAML-like output produced by some models (title: ..., not "title":)."""
        from app.models.schemas import ContentItem

        lines = text.split("\n")
        item: dict[str, object] = {}
        current_multiline_key: str | None = None
        multililine_buffer: list[str] = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                if current_multiline_key:
                    multililine_buffer.append("")
                continue

            m = re.match(r"^(\w+):\s*(.*)$", line_stripped)
            if m:
                key, val = m.group(1), m.group(2)

                # Flush previous multililine field (skip for hashtags - uses dash-collected list)
                if current_multiline_key is not None:
                    if current_multiline_key != "hashtags":
                        item[current_multiline_key] = "\n".join(multiline_buffer).strip()
                    current_multiline_key = None
                    multililine_buffer = []

                # Decode HTML entities that may appear in model output
                val = (
                    val.replace("&gt;", ">")
                    .replace("&lt;", "<")
                    .replace("&amp;", "&")
                    .replace("&#39;", "'")
                    .replace("&quot;", '"')
                )

                if key == "hashtags":
                    # Format: ["#a", "#b"] or #a #b #c or #a, #b, #c or:
                    #   - item1
                    #   - item2
                    val_stripped = val.strip()
                    if val_stripped.startswith("["):
                        val = ast.literal_eval(val_stripped)
                    else:
                        # Collect inline values: split on commas, Chinese commas, spaces,
                        # OR on '#'-boundary to handle "#tag1#tag2#tag3" as separate tags
                        parts = re.split(r"[,，\s]+|(?<=[^\s#])#", val_stripped)
                        items = [t.strip() for t in parts if t.strip()]
                        # Ensure each tag starts with #
                        items = [t if t.startswith("#") else "#" + t for t in items]
                        item[key] = items
                    # hashtags multililine: collect subsequent - lines
                    current_multiline_key = key
                    multililine_buffer = []
                elif key == "body" or key == "content":
                    # Body may span multiple lines
                    current_multiline_key = key
                    multililine_buffer = [val] if val else []
                else:
                    item[key] = val
            else:
                # Continuation of multililine field (indented or unindented)
                # or unmatched line in JSON-like text (skip)
                if current_multiline_key is not None:
                    stripped = line_stripped
                    if current_multiline_key == "hashtags" and stripped.startswith("-"):
                        # YAML list continuation
                        stripped = stripped[1:].strip()
                        existing = list(item.get("hashtags", []))
                        existing.append(stripped)
                        item["hashtags"] = existing
                    else:
                        multililine_buffer.append(stripped)

        # Flush any remaining multililine field
        if current_multiline_key is not None:
            item[current_multiline_key] = "\n".join(multiline_buffer).strip()

        # Map alternate field names
        if "content" in item and "body" not in item:
            item["body"] = item.pop("content")

        # Wrap parsed item in contents list
        if not item.get("title") and not item.get("body") and not item.get("content"):
            raise ValueError(f"YAML parse returned empty item: {item}")
        parsed = {"contents": [item]}
        return ContentGenerateResponse(**parsed)


def load_prompt_template() -> str:
    prompt_path = Path("app/prompts/content_generation_prompt.txt")
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


def generate_contents(request: ContentGenerateRequest) -> ContentGenerateResponse:
    template = load_prompt_template()

    parser = JsonExtractor(pydantic_object=ContentGenerateResponse)

    prompt = ChatPromptTemplate.from_template(template)
    llm = build_llm()

    # Manual chain: invoke prompt, then LLM, then parse manually
    prompt_output = prompt.invoke(
        {
            "count": request.count,
            "topic": request.topic,
            "reason": request.reason,
            "audience": request.audience,
            "tone": request.tone,
            "format_instructions": parser.get_format_instructions(),
        }
    )
    llm_output = llm.invoke(prompt_output)

    result = parser.parse(llm_output)

    return result