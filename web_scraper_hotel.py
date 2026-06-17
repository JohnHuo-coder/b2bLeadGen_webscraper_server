import re
from collections import Counter, deque
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag, Comment, Doctype, ProcessingInstruction, Declaration
from collections import defaultdict

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

MAX_PAGES = 20
REQUEST_TIMEOUT = 15

NON_HTML_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".pdf", ".zip", ".css", ".js", ".json", ".xml",
    ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".eot",
)

ABOUT_KEYWORDS = (
    "about", 
    "overview", 
    "story", 
    "experience"
)

ROOM_KEYWORDS = (
    "accommodation", 
    "room", 
    "stay", 
    "suite", 
    "guestroom", 
    "offer", 
    "package"
)

AMENITY_KEYWORDS = (
    "facility", 
    "facilities", 
    "amenities", 
    "amenity", 
    "services",
    "dining"
)



def normalize_keep_newlines(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines)


def _is_same_domain(base_url: str, candidate_url: str) -> bool:
    return urlparse(base_url).netloc == urlparse(candidate_url).netloc


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


def _extract_internal_links(base_url: str, soup: BeautifulSoup) -> Set[str]:
    links: Set[str] = set()
    link_to_name = {}
    for a_tag in soup.find_all("a", href=True):
        link_name = a_tag.get_text(" ", strip = True)
        href = a_tag["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(base_url, href)
        if not _is_same_domain(base_url, absolute):
            continue
        link = absolute.split("#")[0]
        if not _is_likely_html_url(link):
            continue
        links.add(link)
        link_to_name[link] = link_name
    return links, link_to_name


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


def _pick_next_links(links: Set[str]) -> List[str]:
    scored = []
    for link in links:
        lower_link = link.lower()
        score = 0
        if any(keyword in lower_link for keyword in ABOUT_KEYWORDS):
            score += 6
        if any(keyword in lower_link for keyword in ROOM_KEYWORDS):
            score += 4
        if any(keyword in lower_link for keyword in AMENITY_KEYWORDS):
            score += 2
        scored.append((score, link))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [link for _, link in scored]

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

def smart_render(root: Tag) -> str:
    chunks = []

    for el in root.find_all(BLOCK_TAGS | LIST_TAGS | {"table"}, recursive=False):
        name = el.name.lower()

        if name in LIST_TAGS:
            items = []
            for li in el.find_all("li", recursive = False):
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
    
    out = "\n\n".join(chunks)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out

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
    for tag in soup.select(
        "[id*='booking' i], [class*='booking' i], "
        "[id*='reservation' i], [class*='reservation' i], "
        "[id*='availability' i], [class*='availability' i], "
        "[id*='chat' i], [class*='chat' i], "
        "[id*='contact' i], [class*='contact' i], "
        "[id*='enquiry' i], [class*='enquiry' i], [name*='enquiry' i], "
        "[id*='search' i], [class*='search' i], [name*='search' i]"
    ):
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
    # never remove these structural roots
    protected_tags = {"html", "body", "main", "article"}

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
    text = render_inline(root)
    return text

def _get_footer_contact(soup):
    footer = soup.select_one("footer")
    if not footer: 
        return ""
    return footer.get_text(separator="\n", strip=True)

def _extract_email(text, url) -> list:
    email_pattern = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
    results = []
    for match in re.finditer(email_pattern, text):
        email = match.group()
        start = max(0, match.start()-300)
        end = min(len(text), match.end() + 300)
        context = text[start:end]
        results.append(
            {
                "email": email,
                "url": url,
                "context": context
            }
        )
    return results

def _merge_emails(emails):
    merged = {}
    for item in emails:
        email = item["email"].lower()

        if email not in merged:
            merged[email] = {
                "email": email,
                "urls": [],
                "contexts": []
            }

        merged[email]["urls"].append(item["url"])
        merged[email]["contexts"].append(item["context"])
    return merged

def _extract_email_from_page(soup, url):
    for tag in soup.select("script, style, noscript"):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    results = _extract_email(text, url)
    return results

def collect_site_content(base_url: str, max_pages: int = MAX_PAGES):
    queue = deque([base_url])
    link_queue = deque(["home"])
    visited: Set[str] = set()
    visited.add(base_url)
    succeeded = set()
    pages: Dict[str, str] = {}
    emails: list = []

    key_words = ["about", "overview", "story", "experience", 
                 "accommodation", "room", "stay", "suite", "guestroom", "offer", "package",
                 "facility", "facilities", "amenities", "amenity", "services","dining"]

    classified_results = defaultdict(list)
    seen_by_key = defaultdict(set)

    while queue and len(succeeded) < max_pages:
        current = queue.popleft()
        link_name = link_queue.popleft()
        try:
            fetched = _fetch_page(current)
            if fetched is None:
                continue
            _, soup = fetched
            succeeded.add(current)
        except requests.RequestException:
            continue
        
        soup_for_text = BeautifulSoup(str(soup), "html.parser")
        text = _clean_content(soup_for_text) 

        soup_for_email_extraction = BeautifulSoup(str(soup), "html.parser")
        emails.extend(_extract_email_from_page(soup_for_email_extraction, current))

        if text:
            if link_name == "home" and text not in seen_by_key["about"]:
                seen_by_key["about"].add(text)
                classified_results["about"].append(text)
            for key in key_words:
                if (key in current or key in link_name.lower()) and text not in seen_by_key[key]:
                    seen_by_key[key].add(text)
                    classified_results[key].append(text)
            # page is no longer useful, could be deleted
            pages[current] = text[:40000]
            
        links, link_to_name = _extract_internal_links(base_url, soup)
        ranked =  _pick_next_links(links)
        for link in ranked:
            if link not in visited and len(queue) < max_pages * 2:
                visited.add(link)
                queue.append(link)
                link_name = link_to_name[link]
                link_queue.append(link_name)
    emails = _merge_emails(emails)
    return pages, classified_results, emails


def _truncate_chars(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[TRUNCATED]"

def scrape_hotel_website_summary(
    website_url: str,
    max_pages: int = MAX_PAGES,
) -> Dict[str, object]:
    """
    Generic hotel website summarizer.
    Returns:
    - recent_events: recent event snippets if found
    - hotel_style: economy / luxury / mixed classification
    - target_customer_segments: inferred audience segments
    - high_level_summary: concise plain-language summary
    """
    if not website_url.startswith(("http://", "https://")):
        website_url = f"https://{website_url}"

    pages, classified_results, emails = collect_site_content(website_url, max_pages=max_pages)
    facility_amenity = [
        key.upper() + "\n" + "\n".join(classified_results.get(key, [])) + "\n"
        for key in ["facility", "facilities", "amenities", "amenity", "dining"]
        if classified_results.get(key)
    ]
    room_price = [
        key.upper() + "\n" + "\n".join(classified_results.get(key, [])) + "\n"
        for key in ["accommodation", "room", "stay", "suite", "guestroom", "offer", "package"]
        if classified_results.get(key)
    ]
    about = [
        key.upper() + "\n" + "\n".join(classified_results.get(key, [])) + "\n"
        for key in ["about", "overview", "story", "experience"]
        if classified_results.get(key)
    ]

    facility_amenity = _truncate_chars("\n\n".join(facility_amenity), 3200)
    room_price = _truncate_chars("\n\n".join(room_price), 3200)
    about = _truncate_chars("\n\n".join(about), 3200)

    if not pages:
        return {
            "website_url": website_url,
            "status": "failed",
            "error": "Could not fetch website pages.",
            "about": "",
            "facility_amenity": "",
            "room_price": "",
            "emails": {}

        }

    return {
        "website_url": website_url,
        "status": "ok",
        "pages_scanned": len(pages),
        "about": about,
        "facility_amenity": facility_amenity,
        "room_price": room_price,
        "emails": emails
    }