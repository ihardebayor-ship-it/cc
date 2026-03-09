"""
GoHighLevel Website Scraper
Finds websites built with GoHighLevel that have calendar widgets.
Uses Common Crawl index + direct async checking.
"""

import asyncio
import csv
import json
import os
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse

app = FastAPI(title="GHL Calendar Scraper")

# --- CONFIG ---
OUTPUT_DIR = "/data/results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# GHL fingerprints to look for in page source
GHL_SIGNATURES = [
    "msgsndr.com",
    "leadconnectorhq.com",
    "app.gohighlevel.com",
    "highlevel.com",
]

# Calendar-specific signatures
CALENDAR_SIGNATURES = [
    "calendars.leadconnectorhq.com",
    "calendar.leadconnectorhq.com",
    "msgsndr.com/widget/booking",
    "widget/booking",
    "calendar-widget",
    "booking-widget",
    "msgsndr.com/calendars",
]

# Scraper state
scraper_status = {
    "running": False,
    "total_checked": 0,
    "ghl_found": 0,
    "calendar_found": 0,
    "errors": 0,
    "started_at": None,
    "last_update": None,
}


# =====================
# COMMON CRAWL SEARCH
# =====================
async def search_common_crawl(keyword: str, max_pages: int = 5) -> list[str]:
    """
    Search Common Crawl index for pages containing GHL signatures.
    This is FREE and doesn't require scraping any website.
    """
    urls_found = []
    # Use the latest Common Crawl index
    index = "CC-MAIN-2025-08"  # Update to latest available

    async with httpx.AsyncClient(timeout=30) as client:
        for sig in GHL_SIGNATURES:
            try:
                search_url = f"https://index.commoncrawl.org/{index}-index"
                params = {
                    "url": f"*.{keyword}*" if keyword else "*",
                    "output": "json",
                    "limit": 1000,
                    "filter": f"=content:{sig}",
                }
                # Common Crawl CDX API search
                resp = await client.get(search_url, params=params)
                if resp.status_code == 200:
                    for line in resp.text.strip().split("\n"):
                        if line:
                            try:
                                record = json.loads(line)
                                urls_found.append(record.get("url", ""))
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                print(f"Common Crawl error for {sig}: {e}")

    # Deduplicate by domain
    seen_domains = set()
    unique_urls = []
    for url in urls_found:
        domain = urlparse(url).netloc
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            unique_urls.append(url)

    return unique_urls


# =====================
# DIRECT SITE CHECKER
# =====================
async def check_site(client: httpx.AsyncClient, url: str) -> dict | None:
    """
    Check a single website for GHL + calendar signatures.
    Returns site info if it matches, None if not.
    """
    try:
        if not url.startswith("http"):
            url = f"https://{url}"

        resp = await client.get(url, follow_redirects=True, timeout=15)
        html = resp.text.lower()

        # Check for GHL
        is_ghl = any(sig in html for sig in GHL_SIGNATURES)
        if not is_ghl:
            return None

        # Check for calendar widget
        has_calendar = any(sig in html for sig in CALENDAR_SIGNATURES)

        domain = urlparse(str(resp.url)).netloc

        return {
            "url": str(resp.url),
            "domain": domain,
            "is_ghl": True,
            "has_calendar": has_calendar,
            "status_code": resp.status_code,
            "checked_at": datetime.now().isoformat(),
        }

    except Exception:
        return None


async def check_sites_batch(urls: list[str], batch_size: int = 50) -> list[dict]:
    """
    Check many sites at once using async. Fast!
    """
    global scraper_status
    results = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"
        },
        follow_redirects=True,
        timeout=15,
    ) as client:

        for i in range(0, len(urls), batch_size):
            batch = urls[i : i + batch_size]
            tasks = [check_site(client, url) for url in batch]
            batch_results = await asyncio.gather(*tasks)

            for result in batch_results:
                scraper_status["total_checked"] += 1
                if result:
                    if result["is_ghl"]:
                        scraper_status["ghl_found"] += 1
                    if result["has_calendar"]:
                        scraper_status["calendar_found"] += 1
                    results.append(result)
                else:
                    scraper_status["errors"] += 1

            scraper_status["last_update"] = datetime.now().isoformat()
            # Small delay to be polite
            await asyncio.sleep(1)

    return results


def save_results(results: list[dict], filename: str = "ghl_sites.csv"):
    """Save results to CSV file."""
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", newline="") as f:
        if results:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
    return filepath


# =====================
# GOOGLE DORKING SEEDS
# =====================
def get_google_dork_queries() -> list[str]:
    """
    Returns Google search queries you can use to find GHL sites.
    Copy these into Google to find seed URLs.
    """
    return [
        '"powered by leadconnector"',
        '"msgsndr.com" calendar',
        '"leadconnectorhq.com" booking',
        'site:*.com "msgsndr.com"',
        'inurl:widget/booking "leadconnectorhq"',
        '"app.msgsndr.com" schedule',
        '"calendars.leadconnectorhq.com"',
    ]


# =====================
# API ENDPOINTS
# =====================
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <html>
    <head>
        <title>GHL Scraper</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; background: #0f172a; color: #e2e8f0; }
            h1 { color: #38bdf8; }
            .btn { background: #2563eb; color: white; padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; margin: 5px; text-decoration: none; display: inline-block; }
            .btn:hover { background: #1d4ed8; }
            .card { background: #1e293b; padding: 20px; border-radius: 12px; margin: 15px 0; }
            code { background: #334155; padding: 2px 6px; border-radius: 4px; }
            a { color: #38bdf8; }
            #status { white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <h1>🔍 GHL Calendar Scraper</h1>
        <div class="card">
            <h3>Quick Start</h3>
            <p>Find websites built with GoHighLevel that have calendar/booking widgets.</p>
            <a class="btn" href="/api/search/commoncrawl">Search Common Crawl</a>
            <a class="btn" href="/api/status">Check Status</a>
            <a class="btn" href="/api/results">Download Results</a>
            <a class="btn" href="/api/dorks">Google Dork Queries</a>
        </div>
        <div class="card">
            <h3>API Endpoints</h3>
            <p><code>GET /api/search/commoncrawl</code> — Search Common Crawl for GHL sites</p>
            <p><code>POST /api/check</code> — Check a list of URLs (send JSON body with "urls" array)</p>
            <p><code>GET /api/status</code> — See current scraper progress</p>
            <p><code>GET /api/results</code> — Download results as CSV</p>
            <p><code>GET /api/dorks</code> — Get Google dork queries to find seed URLs</p>
        </div>
        <div class="card">
            <h3>Status</h3>
            <div id="status">Loading...</div>
        </div>
        <script>
            async function updateStatus() {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                document.getElementById('status').textContent = JSON.stringify(data, null, 2);
            }
            updateStatus();
            setInterval(updateStatus, 5000);
        </script>
    </body>
    </html>
    """


@app.get("/api/search/commoncrawl")
async def search_cc(background_tasks: BackgroundTasks):
    """Start a Common Crawl search in the background."""
    global scraper_status

    if scraper_status["running"]:
        return {"message": "Scraper is already running. Check /api/status"}

    async def run_search():
        global scraper_status
        scraper_status = {
            "running": True,
            "total_checked": 0,
            "ghl_found": 0,
            "calendar_found": 0,
            "errors": 0,
            "started_at": datetime.now().isoformat(),
            "last_update": datetime.now().isoformat(),
        }

        try:
            # Search Common Crawl
            urls = await search_common_crawl("")
            print(f"Found {len(urls)} URLs from Common Crawl")

            # Check each URL for calendar widgets
            results = await check_sites_batch(urls)

            # Save results
            save_results(results)
            scraper_status["running"] = False

        except Exception as e:
            scraper_status["running"] = False
            print(f"Search error: {e}")

    background_tasks.add_task(run_search)
    return {"message": "Common Crawl search started! Check /api/status for progress."}


@app.post("/api/check")
async def check_urls(body: dict, background_tasks: BackgroundTasks):
    """
    Check a list of URLs for GHL + calendar.
    Send JSON: {"urls": ["site1.com", "site2.com", ...]}
    """
    urls = body.get("urls", [])
    if not urls:
        return {"error": "Send a JSON body with 'urls' array"}

    async def run_check():
        global scraper_status
        scraper_status = {
            "running": True,
            "total_checked": 0,
            "ghl_found": 0,
            "calendar_found": 0,
            "errors": 0,
            "started_at": datetime.now().isoformat(),
            "last_update": None,
        }

        results = await check_sites_batch(urls)
        save_results(results)
        scraper_status["running"] = False

    background_tasks.add_task(run_check)
    return {"message": f"Checking {len(urls)} URLs. Check /api/status for progress."}


@app.get("/api/status")
async def get_status():
    return scraper_status


@app.get("/api/results")
async def get_results():
    filepath = os.path.join(OUTPUT_DIR, "ghl_sites.csv")
    if os.path.exists(filepath):
        return FileResponse(filepath, filename="ghl_sites.csv", media_type="text/csv")
    return {"message": "No results yet. Run a search first."}


@app.get("/api/dorks")
async def get_dorks():
    return {"queries": get_google_dork_queries()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
