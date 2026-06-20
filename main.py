import base64
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import sys
from pathlib import Path
from web_scraper_hotel import scrape_hotel_website_summary
from url_collector import get_urls
from urls_filter import filter_urls
from web_scraper_general import scrape_website
from schemas import QueryBody, UrlFilterBody, ScrapeWebsiteInput

ROOT = Path(__file__).resolve().parent

app = FastAPI(title="web_sraper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/scrape/hotel")
def run_query(body: QueryBody):
    try:
        result = scrape_hotel_website_summary(body.webUrl, body.maxPage)
        return result
    except Exception as e:
        return {
            "website_url": body.webUrl,
            "status": "failed",
            "error": f"Internal Server Error: {e}",
            "about": "",
            "about": "",
            "facility_amenity": "",
            "room_price": "",
            "emails": {}
        }

@app.post("/api/collect_urls")
def run_collect_url_query(body: QueryBody):
    try:
        results = get_urls(body.webUrl, body.maxPage)
        return {
            "website_url": body.webUrl,
            "status": "ok",
            "results": results
        }
    except Exception as e:
        return {
            "website_url": body.webUrl,
            "status": "failed",
            "error": f"Internal Server Error: {e}",
            "results": []
        }


@app.post("/api/filter_urls")
def run_filter_url_query(body: UrlFilterBody):
    try:
        results = filter_urls(body.urlItems, body.keyWordItems)
        return {
            "status": "ok",
            "results": results
        }
    except Exception as e:
        return {
            "status": "failed",
            "error": f"Internal Server Error: {e}",
            "results": []
        }

  
@app.post("/api/scrape_general")
def run_scrape_website_general(body: ScrapeWebsiteInput):
    try:
        results = scrape_website(body.items, body.max_chars)
        return {
            "status": "ok",
            "results": results
        }
    except Exception as e:
        return {
            "status": "failed",
            "error": f"Internal Server Error: {e}",
            "results": []
        }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}