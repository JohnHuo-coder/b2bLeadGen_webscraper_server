from pydantic import BaseModel
from typing import Any, List


class QueryBody(BaseModel):
    webUrl: str
    maxPage: int

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
    priority: int  # lower number = higher importance
    reason: str

class UrlFilterBody(BaseModel):
    urlItems: List[urlItem]
    keyWordItems: List[keyWordItem]

class SelectedUrlItem(BaseModel):
    url: str
    covered_requirements: List[int]
    reason: str

class ScrapeWebsiteInput(BaseModel):
    items: List[SelectedUrlItem]
    max_chars: int