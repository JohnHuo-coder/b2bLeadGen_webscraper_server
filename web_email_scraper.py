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



EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _decode_cfemail(encoded: str) -> Optional[str]:
    if not encoded or len(encoded) < 4 or len(encoded) % 2 != 0:
        return None
    try:
        key = int(encoded[:2], 16)
        decoded = "".join(
            chr(int(encoded[i : i + 2], 16) ^ key) for i in range(2, len(encoded), 2)
        )
    except ValueError:
        return None
    return decoded if EMAIL_PATTERN.fullmatch(decoded) else None


def _context_around(text: str, start: int, end: int, radius: int = 300) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def _append_email(results: list, email: str, url: str, context: str) -> None:
    results.append({"email": email, "url": url, "context": context})


def _extract_email(text, url) -> list:
    results = []
    for match in EMAIL_PATTERN.finditer(text):
        _append_email(
            results,
            match.group(),
            url,
            _context_around(text, match.start(), match.end()),
        )
    return results


def _extract_obfuscated_emails(soup: BeautifulSoup, url: str) -> list:
    results = []
    for tag in soup.select("[data-cfemail]"):
        email = _decode_cfemail(tag.get("data-cfemail", ""))
        if not email:
            continue
        parent = tag.find_parent(["li", "p", "div", "td", "span"])
        context = parent.get_text(separator="\n", strip=True) if parent else tag.get_text(strip=True)
        _append_email(results, email, url, context)
    return results


def _extract_mailto_emails(soup: BeautifulSoup, url: str) -> list:
    results = []
    for tag in soup.select('a[href^="mailto:"]'):
        href = tag.get("href", "")
        email = href.split("mailto:", 1)[1].split("?", 1)[0].strip()
        if not EMAIL_PATTERN.fullmatch(email):
            continue
        parent = tag.find_parent(["li", "p", "div", "td", "span"])
        context = parent.get_text(separator="\n", strip=True) if parent else tag.get_text(strip=True)
        _append_email(results, email, url, context)
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
    results = []
    results.extend(_extract_obfuscated_emails(soup, url))
    results.extend(_extract_mailto_emails(soup, url))

    for tag in soup.select("script, style, noscript"):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    results.extend(_extract_email(text, url))
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