import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
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


def collect_site_emails(urls: List[SelectedUrlItem]):
    emails = []
    for url_item in urls:
        url = url_item.url
        try:
            fetched = _fetch_page(url)
            if fetched is None:
                continue
            _, soup = fetched

        except requests.RequestException:
            continue

        soup_for_email_extraction = BeautifulSoup(str(soup), "html.parser")
        emails.extend(_extract_email_from_page(soup_for_email_extraction, url))
    emails = _merge_emails(emails)
    return emails