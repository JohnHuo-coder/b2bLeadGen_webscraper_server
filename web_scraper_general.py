import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag, Comment, Doctype, ProcessingInstruction, Declaration
from schemas import SelectedUrlItem


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 15

NON_HTML_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".pdf", ".zip", ".css", ".js", ".json", ".xml",
    ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".eot",
)



def normalize_keep_newlines(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines)


def _is_likely_html_url(url: str) -> bool:
    path = urlparse(url.lower()).path
    return not any(path.endswith(ext) for ext in NON_HTML_EXTENSIONS)


def _is_non_html_content_type(content_type: str) -> bool:
    ct = content_type.split(";")[0].strip().lower()
    if ct in ("text/html", "application/xhtml+xml"):
        return False
    if ct.startswith(("image/", "video/", "audio/", "font/")):
        return True
    if ct in (
        "application/pdf",
        "application/zip",
        "text/css",
        "text/javascript",
        "application/javascript",
        "application/json",
        "application/xml",
    ):
        return True
    return False


def _looks_like_binary(data: bytes) -> bool:
    if len(data) < 4:
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:4] == b"\x89PNG":
        return True
    if data[:4] in (b"GIF8", b"GIF9"):
        return True
    if data[:4] == b"%PDF":
        return True
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def _fetch_page(url: str) -> Optional[Tuple[str, BeautifulSoup]]:
    if not _is_likely_html_url(url):
        return None

    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if content_type and _is_non_html_content_type(content_type):
        return None

    raw = response.content
    if _looks_like_binary(raw):
        return None

    text = raw.decode(response.encoding or "utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    return text, soup


def render_table(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        values = [c.get_text(" ", strip=True) for c in cells if c.get_text(" ", strip=True)]

        if not values:
            continue

        if len(values) >= 2:
            rows.append(f"{values[0]}: {' | '.join(values[1:])}")
        else:
            rows.append(values[0])

    return "\n".join(rows)


def render_list(lst: Tag) -> str:
    items = []
    for li in lst.find_all("li", recursive = False):
        txt = render_inline(li)
        if txt:
            items.append(f"- {txt}")
    return "\n".join(items)



BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "h4"}
INLINE_TAGS = {"a", "span", "strong", "b", "em", "i", "u", "small", "code"}
LIST_TAGS = {"ul", "ol"}

def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def render_inline(node: Tag, cur: str = "inline") -> str:
    """Render one block's internal text; inline tags do not force new lines."""
    parts: List[Tuple[str, str]] = []
    for child in node.children:
        if isinstance(child, (Comment, Doctype, ProcessingInstruction, Declaration)):
            continue
        elif isinstance(child, NavigableString):
            text = norm_ws(str(child))
            if text:
                parts.append((text, "inline"))
        elif isinstance(child, Tag):
            name = child.name.lower()
            if name in {"br"}:
                parts.append(("\n", "break"))
            elif name == "table":
                text = render_table(child)
                if text.strip():
                    parts.append((text, "block"))
            elif name in LIST_TAGS:
                text = render_list(child)
                if text:
                    parts.append((text, "block"))
            elif name in INLINE_TAGS:
                text = render_inline(child, "inline")
                if text:
                    parts.append((text, "inline"))
            elif name in BLOCK_TAGS:
                text = render_inline(child, "block")
                if text:
                    parts.append((text, "block"))
            else:
                text = render_inline(child, "inline")
                if text:
                    parts.append((text, "inline"))

    out_parts: List[str] = []
    prev_kind = "block" if cur == "block" else None

    for text, kind in parts:
        if kind == "break":
            if out_parts and not out_parts[-1].endswith("\n"):
                out_parts.append("\n")
            prev_kind = "break"
            continue

        if not out_parts:
            out_parts.append(text)
        else:
            if prev_kind == "block" or kind == "block":
                sep = "\n"
            else:
                sep = " "
            if out_parts[-1].endswith("\n"):
                sep = ""
            out_parts.append(sep + text)
        prev_kind = kind

    joined = "".join(out_parts)
    joined = re.sub(r"[ \t]+\n", "\n", joined)
    joined = re.sub(r"\n[ \t]+", "\n", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    joined = re.sub(r" {2,}", " ", joined)
    return joined.strip()

def smart_render_blocks(root: Tag) -> List[str]:
    chunks: List[str] = []

    for el in root.find_all(BLOCK_TAGS | LIST_TAGS | {"table"}, recursive=False):
        name = el.name.lower()

        if name in LIST_TAGS:
            items = []
            for li in el.find_all("li", recursive=False):
                txt = render_inline(li)
                if txt:
                    items.append(f"- {txt}")
            if items:
                chunks.append("\n".join(items))

        elif name == "table":
            txt = render_table(el)
            if txt:
                chunks.append(txt)

        elif name in BLOCK_TAGS:
            txt = render_inline(el)
            if txt:
                chunks.append(txt)

    return [re.sub(r"\n{3,}", "\n\n", c).strip() for c in chunks if c.strip()]


def smart_render(root: Tag) -> str:
    return "\n\n".join(smart_render_blocks(root))

def _clean_content(soup):
    for tag in soup.select(
        "script, style, noscript, svg, iframe, "
        "header, nav, footer, aside, "
        "[role='navigation'], [role='contentinfo']"
    ):
        tag.decompose()

    # remove booking availability form and sales link sections
    for tag in soup.select("form[name='availabilitysearchform']"):
        tag.decompose()
    for tag in soup.select("section[id*='sale' i]"):
        tag.decompose()

    # remove common reservation widgets and chat launchers
    protected_tags = {"html", "body", "main", "article"}
    for tag in soup.select(
        "[id*='booking' i], [class*='booking' i], "
        "[id*='reservation' i], [class*='reservation' i], "
        "[id*='availability' i], [class*='availability' i], "
        "[id*='chat' i], [class*='chat' i], "
        "[id*='contact' i], [class*='contact' i], "
        "[id*='enquiry' i], [class*='enquiry' i], [name*='enquiry' i], "
        "[id*='search' i], [class*='search' i], [name*='search' i]"
    ):
        if tag.name in protected_tags:
            continue
        tag.decompose()
    
    # remove language menu and currency menu
    for tag in soup.select(
        "li[class*='language' i], ul[class*='language' i], "
        "li[class*='currencies' i], ul[class*='currencies' i], "
        "li[class*='currency' i], ul[class*='currency' i]"
    ):
        tag.decompose()
    
    # delete common cookie/banner popup（based on class/id keyword）
    noisy_keywords = (
        "cookie",
        "consent",
        "banner",
        "popup",
        "modal",
        "subscribe",
        "newsletter",
        "floating",
        "drawer",
    )
    # tags that are allowed to be removed by keyword rule
    removable_tags = {"div", "section", "aside", "form", "dialog"}
    # never remove these structural roots (also used above for widget selectors)

    to_remove = []
    for tag in soup.find_all(True):
        if tag.name in protected_tags or tag.name not in removable_tags:
            continue

        joined = " ".join(tag.get("class", [])) + " " + (tag.get("id") or "")
        low = joined.lower()
        text_len = len(tag.get_text(" ", strip=True))
        role = (tag.get("role") or "").lower()

        # keyword hit => likely popup/widget noise
        if any(k in low for k in noisy_keywords) or role in {"dialog", "alertdialog"}:
            to_remove.append(tag)

    for tag in to_remove:
        tag.decompose()

    root = (
        soup.select_one("main, [role='main'], #content, .content, .entry-content")
        or soup.body
        or soup
    )
    return smart_render_blocks(root)


def collect_site_content(urls: List[SelectedUrlItem], max_chars: int):
    results = []
    for url_item in urls:
        result = {}
        url = url_item.url
        try:
            fetched = _fetch_page(url)
            if fetched is None:
                continue
            _, soup = fetched

        except requests.RequestException:
            continue
        
        soup_for_text = BeautifulSoup(str(soup), "html.parser")
        blocks = _clean_content(soup_for_text)

        if blocks:
            text = _truncate_blocks(blocks, max_chars)
            result = {
                **url_item.model_dump(),
                "content": text
            }
            results.append(result)
    return results


_TRUNCATED_SUFFIX = "\n...[TRUNCATED]"


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text

    suffix_len = len(_TRUNCATED_SUFFIX)
    if max_chars <= suffix_len:
        return text[:max_chars]

    budget = max_chars - suffix_len
    cut = text[:budget]

    sentence_ends = list(re.finditer(r'[.!?。！？]["\']?(?:\s+|$)', cut))
    if sentence_ends:
        cut = cut[:sentence_ends[-1].end()].rstrip()
    else:
        last_space = cut.rfind(" ")
        if last_space > budget // 2:
            cut = cut[:last_space].rstrip()
        else:
            cut = cut.rstrip()

    return cut + _TRUNCATED_SUFFIX


def _truncate_blocks(blocks: List[str], max_chars: int) -> str:
    if max_chars <= 0:
        return ""

    kept: List[str] = []
    used = 0
    truncated = False
    separator = "\n\n"
    non_empty = [b.strip() for b in blocks if b and b.strip()]

    for block in non_empty:
        sep_len = len(separator) if kept else 0
        remaining = max_chars - used - sep_len

        if remaining <= 0:
            truncated = True
            break

        if len(block) <= remaining:
            kept.append(block)
            used += sep_len + len(block)
            continue

        piece = _truncate_at_sentence(block, remaining)
        if piece:
            kept.append(piece)
        truncated = True
        break

    if len(kept) < len(non_empty):
        truncated = True

    result = separator.join(kept).strip()
    if truncated and result and not result.endswith(_TRUNCATED_SUFFIX):
        result += _TRUNCATED_SUFFIX
    return result

def scrape_website(
    website_urls: List[SelectedUrlItem],
    max_chars: int
) -> List[Dict]:

    results = collect_site_content(website_urls, max_chars)
    return results