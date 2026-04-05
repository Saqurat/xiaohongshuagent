from collections import Counter
from typing import List
import re

import jieba

from app.models.schemas import (
    NoteItem,
    ScoredNoteItem,
    AnalyzeResponse,
    TitleFeatureStats,
)


STOPWORDS = {
    "的", "了", "和", "是", "我", "也", "很", "都", "就", "又", "太",
    "在", "真的", "一个", "这", "几款", "适合", "怎么", "到底", "一下",
    "以及", "我们", "你们", "他们", "自己", "可以", "不会", "就是"
}

RECOMMENDATION_WORDS = [
    "推荐", "合集", "测评", "避雷", "平替", "必备", "清单", "教程", "分享"
]


def calculate_viral_score(note: NoteItem) -> float:
    """
    Calculate a simple viral score based on engagement.
    """
    return note.likes * 0.4 + note.favorites * 0.4 + note.comments * 0.2


def extract_title_keywords(notes: List[NoteItem], top_k: int = 10) -> List[str]:
    """
    Extract keywords from Chinese titles using jieba.
    """
    all_words = []

    for note in notes:
        words = jieba.lcut(note.title)
        for word in words:
            cleaned = word.strip()
            if (
                cleaned
                and cleaned not in STOPWORDS
                and len(cleaned) >= 2
                and not re.fullmatch(r"[\W_]+", cleaned)
            ):
                all_words.append(cleaned)

    counter = Counter(all_words)
    return [word for word, _ in counter.most_common(top_k)]


def extract_top_tags(notes: List[NoteItem], top_k: int = 10) -> List[str]:
    """
    Extract top tags from all notes.
    """
    all_tags = []
    for note in notes:
        all_tags.extend(note.tags)

    counter = Counter(all_tags)
    return [tag for tag, _ in counter.most_common(top_k)]


def analyze_title_features(notes: List[NoteItem]) -> TitleFeatureStats:
    """
    Analyze title-level statistical features.
    """
    total_titles = len(notes)
    if total_titles == 0:
        return TitleFeatureStats(
            average_title_length=0,
            titles_with_numbers=0,
            titles_with_recommendation_words=0,
            titles_with_question_marks=0,
        )

    total_length = 0
    titles_with_numbers = 0
    titles_with_recommendation_words = 0
    titles_with_question_marks = 0

    for note in notes:
        title = note.title
        total_length += len(title)

        if re.search(r"\d", title):
            titles_with_numbers += 1

        if any(word in title for word in RECOMMENDATION_WORDS):
            titles_with_recommendation_words += 1

        if "?" in title or "？" in title:
            titles_with_question_marks += 1

    return TitleFeatureStats(
        average_title_length=round(total_length / total_titles, 2),
        titles_with_numbers=titles_with_numbers,
        titles_with_recommendation_words=titles_with_recommendation_words,
        titles_with_question_marks=titles_with_question_marks,
    )


def extract_title_patterns(notes: List[NoteItem], top_k: int = 10) -> List[str]:
    """
    Extract frequent pattern words appearing in titles.
    """
    pattern_counter = Counter()

    for note in notes:
        title = note.title
        for word in RECOMMENDATION_WORDS:
            if word in title:
                pattern_counter[word] += 1

    return [word for word, _ in pattern_counter.most_common(top_k)]


def generate_insight_points(
    notes: List[NoteItem],
    top_keywords: List[str],
    top_tags: List[str],
    title_stats: TitleFeatureStats,
    title_patterns: List[str],
) -> List[str]:
    """
    Generate rule-based insight points for business interpretation.
    """
    insights = []

    if top_tags:
        insights.append(f"高频标签集中在：{', '.join(top_tags[:3])}，说明这些话题更容易吸引用户关注。")

    if top_keywords:
        insights.append(f"高频标题关键词包括：{', '.join(top_keywords[:5])}，可以作为后续选题生成的重要参考。")

    if title_patterns:
        insights.append(f"标题中常见模式词有：{', '.join(title_patterns[:5])}，说明“推荐/测评/避雷/合集”类表达更受欢迎。")

    if title_stats.titles_with_numbers > 0:
        insights.append("部分高表现标题包含数字，说明清单型、步骤型、数量型表达具有一定吸引力。")

    if title_stats.titles_with_question_marks > 0:
        insights.append("部分标题使用问句形式，说明提问式标题有助于激发读者点击兴趣。")

    avg_score = sum(calculate_viral_score(note) for note in notes) / len(notes) if notes else 0
    insights.append(f"当前样本平均爆款分数为 {avg_score:.2f}，可作为后续内容优化的参考基线。")

    return insights


def analyze_notes(notes: List[NoteItem], top_n: int = 3) -> AnalyzeResponse:
    """
    Analyze notes and return a richer content-insight report.
    """
    scored_notes = [
        ScoredNoteItem(**note.model_dump(), viral_score=calculate_viral_score(note))
        for note in notes
    ]

    scored_notes.sort(key=lambda x: x.viral_score, reverse=True)

    top_notes = scored_notes[:top_n]
    top_keywords = extract_title_keywords(notes)
    top_tags = extract_top_tags(notes)
    title_stats = analyze_title_features(notes)
    title_patterns = extract_title_patterns(notes)
    insight_points = generate_insight_points(
        notes=notes,
        top_keywords=top_keywords,
        top_tags=top_tags,
        title_stats=title_stats,
        title_patterns=title_patterns,
    )

    summary = (
        f"共分析 {len(notes)} 条内容。高表现内容主要集中在 "
        f"{'、'.join(top_tags[:3]) if top_tags else '若干热门话题'}，"
        f"标题中常见“{'、'.join(title_patterns[:3]) if title_patterns else '推荐/测评类'}”表达，"
        f"整体上更偏向实用建议、经验分享和问题解决型内容。"
    )

    return AnalyzeResponse(
        total_count=len(notes),
        top_notes=top_notes,
        top_keywords=top_keywords,
        top_tags=top_tags,
        title_feature_stats=title_stats,
        title_patterns=title_patterns,
        insight_points=insight_points,
        summary=summary,
    )