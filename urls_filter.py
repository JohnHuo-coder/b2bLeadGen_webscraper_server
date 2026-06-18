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

def matches_any_alias(candidates: set[str], alias: str) -> bool:
    if not alias:
        return False
    return any(alias in c for c in candidates if c)

def build_candidates(item: urlItem) -> set[str]:
    parts = [lemmatize_phrase(s) for s in path_to_segments(item.path)]
    parts += [normalize_phrase(t) for t in item.anchor_texts]
    if item.title:
        parts.append(normalize_phrase(item.title))
    if item.h1:
        parts.append(normalize_phrase(item.h1))
    return {p for p in parts if p}

def filter_urls(items: List[urlItem], keywords: List[keyWordItem]) -> List[dict]:
    prepared_kws = [
        {
            "aliases": [
                a
                for a in (normalize_phrase(x) for x in [*kw.aliases, kw.topic])
                if a
            ],
        }
        for kw in keywords
        if kw.aliases or kw.topic
    ]

    results: List[dict] = []
    for item in items:
        candidates = build_candidates(item)
        if any(
            matches_any_alias(candidates, alias)
            for kw in prepared_kws
            for alias in kw["aliases"]
        ):
            results.append(item.model_dump())
    return results

                




