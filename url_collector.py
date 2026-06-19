from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15
DEFAULT_MAX_PAGES = 50
DEFAULT_FETCH_WORKERS = 5
NON_HTML_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".pdf", ".zip", ".css", ".js", ".json", ".xml",
    ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".eot",
)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.split("#")[0])
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return parsed._replace(path=path, fragment="", params="").geturl()


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


def _fetch_page(url: str) -> Optional[BeautifulSoup]:
    if not _is_likely_html_url(url):
        return None

    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if content_type and _is_non_html_content_type(content_type):
        return None

    raw = response.content
    if _looks_like_binary(raw):
        return None

    text = raw.decode(response.encoding or "utf-8", errors="replace")
    return BeautifulSoup(text, "html.parser")


def _append_anchor_texts(target: List[str], texts: List[str]) -> None:
    for text in texts:
        if text and text not in target:
            target.append(text)


def _extract_internal_links(
    base_url: str,
    page_url: str,
    soup: BeautifulSoup,
) -> Dict[str, List[str]]:
    link_map: Dict[str, List[str]] = {}

    for a_tag in soup.find_all("a", href=True):
        link_name = a_tag.get_text(" ", strip=True)
        href = a_tag["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        absolute = urljoin(page_url, href)
        if not _is_same_domain(base_url, absolute):
            continue

        link = _normalize_url(absolute)
        if not _is_likely_html_url(link):
            continue

        if link not in link_map:
            link_map[link] = []
        if link_name and link_name not in link_map[link]:
            link_map[link].append(link_name)

    return link_map


def _new_page_entry(
    url: str,
    *,
    anchor_texts: List[str],
    depth: int,
) -> Dict[str, object]:
    return {
        "url": url,
        "path": urlparse(url).path or "/",
        "anchor_texts": anchor_texts[:],
        "depth": depth,
        "title": "",
        "h1": "",
        "_fetched": False,
    }


def _merge_anchor_texts(existing: Dict[str, object], anchor_texts: List[str]) -> None:
    _append_anchor_texts(existing["anchor_texts"], anchor_texts)


def _drop_page(pages: Dict[str, Dict[str, object]], url: str) -> None:
    pages.pop(url, None)


def _fetch_and_extract(
    base_url: str,
    url: str,
) -> Tuple[str, Optional[BeautifulSoup], Optional[Dict[str, List[str]]]]:
    try:
        soup = _fetch_page(url)
        if soup is None:
            return url, None, None
        link_map = _extract_internal_links(base_url, url, soup)
        return url, soup, link_map
    except requests.RequestException:
        return url, None, None


def _apply_fetch_result(
    pages: Dict[str, Dict[str, object]],
    url: str,
    depth: int,
    soup: BeautifulSoup,
    link_map: Dict[str, List[str]],
    next_frontier: List[Tuple[str, int]],
    next_urls: Set[str],
) -> None:
    entry = pages[url]
    if soup.title and soup.title.string:
        entry["title"] = soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        entry["h1"] = h1.get_text(" ", strip=True)

    for link, anchor_texts in link_map.items():
        if link not in pages:
            pages[link] = _new_page_entry(
                link,
                anchor_texts=anchor_texts,
                depth=depth + 1,
            )
            if not pages[link]["_fetched"] and link not in next_urls:
                next_urls.add(link)
                next_frontier.append((link, depth + 1))
        else:
            _merge_anchor_texts(pages[link], anchor_texts)
            if not pages[link]["_fetched"] and link not in next_urls:
                next_urls.add(link)
                next_frontier.append((link, int(pages[link]["depth"])))


def get_urls(
    base_url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    fetch_workers: int = DEFAULT_FETCH_WORKERS,
) -> List[Dict[str, object]]:
    if not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"
    base_url = _normalize_url(base_url)

    pages: Dict[str, Dict[str, object]] = {
        base_url: _new_page_entry(
            base_url,
            anchor_texts=["home", "about"],
            depth=0,
        )
    }
    frontier: List[Tuple[str, int]] = [(base_url, 0)]
    fetched_count = 0
    workers = max(1, fetch_workers)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        while frontier and fetched_count < max_pages:
            batch: List[Tuple[str, int]] = []
            for url, depth in frontier:
                if fetched_count + len(batch) >= max_pages:
                    break
                if url not in pages:
                    continue
                entry = pages[url]
                if entry["_fetched"]:
                    continue
                entry["_fetched"] = True
                batch.append((url, depth))

            if not batch:
                break

            futures = {
                executor.submit(_fetch_and_extract, base_url, url): (url, depth)
                for url, depth in batch
            }

            next_frontier: List[Tuple[str, int]] = []
            next_urls: Set[str] = set()

            for future in as_completed(futures):
                url, depth = futures[future]
                _, soup, link_map = future.result()
                if soup is None or link_map is None:
                    _drop_page(pages, url)
                    continue

                fetched_count += 1
                _apply_fetch_result(
                    pages, url, depth, soup, link_map, next_frontier, next_urls
                )

            frontier = next_frontier

    results = list(pages.values())
    for item in results:
        item.pop("_fetched", None)
    results.sort(key=lambda item: (item["depth"], item["url"]))
    return results
