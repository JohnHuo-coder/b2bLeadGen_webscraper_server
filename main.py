import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path
from web_scraper_hotel import scrape_hotel_website_summary
from url_collector import get_urls
from urls_filter import filter_urls
from web_scraper_general import scrape_website
from schemas import QueryBody, UrlFilterBody, ScrapeWebsiteInput, ScrapeEmailsInput
from web_email_scraper import collect_site_emails

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
async def run_collect_url_query(body: QueryBody):
    try:
        results = await get_urls(body.webUrl, body.maxPage)
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
async def run_filter_url_query(body: UrlFilterBody):
    try:
        results = await asyncio.to_thread(
            filter_urls, body.urlItems, body.keyWordItems
        )
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
async def run_scrape_website_general(body: ScrapeWebsiteInput):
    try:
        results = await scrape_website(body.items, body.max_chars)
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


@app.post("/api/scrape_email")
async def run_scrape_website_emails(body: ScrapeEmailsInput):
    try:
        emails = await collect_site_emails(body.items)
        return {
            "status": "ok",
            "results": emails
        }
    except Exception as e:
        return {
            "status": "failed",
            "error": f"Internal Server Error: {e}",
            "results": {}
        }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
