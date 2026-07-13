from typing import Dict, List

import re
import simplemma
from schemas import keyWordItem, urlItem

FIELD_WEIGHTS: Dict[str, int] = {
    "path": 3,
    "title": 2,
    "h1": 2,
    "anchor": 1,
}


def path_to_segments(path: str) -> list[str]:
    path = (path or "/").strip("/").lower()
    path = re.sub(r"[-_:&|]+", " ", path)
    if not path:
        return []
    return [
        p for part in path.split("/")
        if (p := re.sub(r"\s+", " ", part).strip())
    ]


def normalize_phrase(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text, flags=re.UNICODE)
    if not text:
        return ""
    text = lemmatize_phrase(text)
    return text


def lemmatize_phrase(text: str) -> str:
    return " ".join(
        simplemma.lemmatize(w, lang="en")
        for w in text.split()
    )


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(phrase)}\b", re.UNICODE)


def _prepare_keywords(keywords: List[keyWordItem]) -> List[dict]:
    prepared: List[dict] = []
    for kw in keywords:
        if not (kw.aliases or kw.topic):
            continue
        seen: set[str] = set()
        patterns: List[re.Pattern[str]] = []
        for x in [*kw.aliases, kw.topic]:
            phrase = normalize_phrase(x)
            if phrase and phrase not in seen:
                seen.add(phrase)
                patterns.append(_phrase_pattern(phrase))
        if patterns:
            prepared.append({
                "topic": kw.topic,
                "priority": kw.priority,
                "patterns": patterns,
                "supports_requirements": kw.supports_requirements or []
            })
    return prepared


def build_candidate_fields(item: urlItem) -> Dict[str, List[str] | str]:
    path_segments = [
        s for s in (lemmatize_phrase(seg) for seg in path_to_segments(item.path))
        if s
    ]
    anchor_texts = [
        t for t in (normalize_phrase(a) for a in item.anchor_texts)
        if t
    ]
    return {
        "path": path_segments,
        "title": normalize_phrase(item.title) if item.title else "",
        "h1": normalize_phrase(item.h1) if item.h1 else "",
        "anchor": anchor_texts,
    }


def _pattern_matches_field(
    pattern: re.Pattern[str],
    field: str,
    value: List[str] | str,
) -> bool:
    if field == "path" or field == "anchor":
        return any(pattern.search(text) for text in value)
    return bool(value and pattern.search(value))


def _find_matched_topics(
    fields: Dict[str, List[str] | str],
    prepared_kws: List[dict],
) -> List[dict]:
    matched: List[dict] = []
    for kw in prepared_kws:
        matched_in: List[str] = []
        for field, weight in FIELD_WEIGHTS.items():
            value = fields[field]
            if any(
                _pattern_matches_field(p, field, value)
                for p in kw["patterns"]
            ):
                matched_in.append(field)
        if matched_in:
            matched.append({
                "topic": kw["topic"],
                "priority": kw["priority"],
                "matched_in": matched_in,
                "supports_requirements": kw["supports_requirements"]
            })
    return matched


def _priority_weight(priority: int, max_priority: int) -> int:
    """Convert configured priority to score weight (lower priority = higher weight)."""
    return max_priority - priority + 1


def _collect_all_requirements(keywords: List[keyWordItem]) -> List[int]:
    seen: set[int] = set()
    requirements: List[int] = []
    for kw in keywords:
        for req in kw.supports_requirements or []:
            if req not in seen:
                seen.add(req)
                requirements.append(req)
    return requirements


def _compute_requirement_scores(
    matched_topics: List[dict],
    max_priority: int,
    all_requirements: List[int],
) -> tuple[Dict[int, int], int]:
    scores = {req: 0 for req in all_requirements}
    if not matched_topics:
        return scores, 0

    for entry in matched_topics:
        best_weight = max(
            FIELD_WEIGHTS[field] for field in entry["matched_in"]
        )
        topic_score = _priority_weight(entry["priority"], max_priority) * best_weight
        for req in entry["supports_requirements"]:
            if req in scores:
                scores[req] += topic_score

    return scores, sum(scores.values())


def filter_urls(items: List[urlItem], keywords: List[keyWordItem]) -> List[dict]:
    prepared_kws = _prepare_keywords(keywords)
    max_priority = max(kw.priority for kw in keywords) if keywords else 1
    all_requirements = _collect_all_requirements(keywords)

    results: List[dict] = []
    for item in items:
        fields = build_candidate_fields(item)
        matched_topics = _find_matched_topics(fields, prepared_kws)
        if not matched_topics:
            continue
        requirement_scores, score = _compute_requirement_scores(
            matched_topics, max_priority, all_requirements
        )
        results.append({
            **item.model_dump(),
            "matched_topics": matched_topics,
            "requirement_scores": requirement_scores,
            "score": score,
        })

    results.sort(key=lambda r: (r["depth"], -r["score"], r["url"]))
    return results
