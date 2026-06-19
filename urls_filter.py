from typing import List

import re
import simplemma
from pydantic import BaseModel


class urlItem(BaseModel):
    url: str
    path: str
    anchor_texts: List[str]
    depth: int
    title: str
    h1: str

class keyWordItem(BaseModel):
    topic: str
    aliases: List[str]
    priority: int
    reason: str


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


def _prepare_alias_patterns(keywords: List[keyWordItem]) -> List[re.Pattern[str]]:
    seen: set[str] = set()
    patterns: List[re.Pattern[str]] = []
    for kw in keywords:
        if not (kw.aliases or kw.topic):
            continue
        for x in [*kw.aliases, kw.topic]:
            phrase = normalize_phrase(x)
            if phrase and phrase not in seen:
                seen.add(phrase)
                patterns.append(_phrase_pattern(phrase))
    return patterns


def _matches_any(candidates: set[str], patterns: List[re.Pattern[str]]) -> bool:
    return any(p.search(c) for p in patterns for c in candidates if c)

def build_candidates(item: urlItem) -> set[str]:
    parts = [lemmatize_phrase(s) for s in path_to_segments(item.path)]
    parts += [normalize_phrase(t) for t in item.anchor_texts]
    if item.title:
        parts.append(normalize_phrase(item.title))
    if item.h1:
        parts.append(normalize_phrase(item.h1))
    return {p for p in parts if p}

def filter_urls(items: List[urlItem], keywords: List[keyWordItem]) -> List[dict]:
    patterns = _prepare_alias_patterns(keywords)

    results: List[dict] = []
    for item in items:
        candidates = build_candidates(item)
        if _matches_any(candidates, patterns):
            results.append(item.model_dump())
    return results
