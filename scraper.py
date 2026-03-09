"""
GoHighLevel Website Scraper v2
Finds websites built with GoHighLevel that have calendar widgets.

3 Working Methods:
1. Common Crawl CDX - searches for GHL infrastructure URLs
2. Direct URL checker - checks your own URL list fast
3. DNS/Certificate search - finds GHL domains via crt.sh
"""

import asyncio
import csv
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

app = FastAPI(title="GHL Calendar Scraper v2")

# --- CONFIG ---
OUTPUT_DIR = "/data/results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# GHL fingerprints
GHL_SIGNATURES = [
    "msgsndr.com",
    "leadconnectorhq.com",
    "gohighlevel.com",
    "highlevel.com",
]

CALENDAR_SIGNATURES = [
    "calendars.leadconnectorhq.com",
    "calendar.leadconnectorhq.com",
    "msgsndr.com/widget/booking",
    "widget/booking",
    "calendar-widget",
    "booking-widget",
    "msgsndr.com/calendars",
    "calendar/",
    "schedule-appointment",
    "book-appointment",
]

# State
scraper_status = {
    "running": False,
    "method": "",
    "total_checked": 0,
    "ghl_found": 0,
    "calendar_found": 0,
    "errors": 0,
    "started_at": None,
    "last_update": None,
    "message": "Idle",
}

all_results = []


def reset_status(method: str):
    global scraper_status, all_results
    scraper_status = {
        "running": True,
        "method": method,
        "total_checked": 0,
        "ghl_found": 0,
        "calendar_found": 0,
        "errors": 0,
        "started_at": datetime.now().isoformat(),
        "last_update": datetime.now().isoformat(),
        "message": f"Starting {method}...",
    }
    all_results = []


# ========================================
# METHOD 1: Common Crawl CDX (URL search)
# ========================================
async def search_commoncrawl_cdx() -> list[str]:
    """
    Search Common Crawl CDX for pages hosted on GHL infrastructure.
    These are actual GHL-hosted sites.
    """
    global scraper_status
    urls_found = []

    # GHL hosts customer sites on these domains
    search_patterns = [
        "*.msgsndr.com",
        "*.leadconnectorhq.com",
        "*.gohighlevel.com",
    ]

    # Try multiple recent Common Crawl indexes
    indexes = [
        "CC-MAIN-2025-05",
        "CC-MAIN-2024-51",
        "CC-MAIN-2024-46",
        "CC-MAIN-2024-42",
        "CC-MAIN-2024-38",
    ]

    async with httpx.AsyncClient(timeout=60) as client:
        for index in indexes:
            for pattern in search_patterns:
                try:
                    scraper_status["message"] = f"Searching {index} for {pattern}..."
                    scraper_status["last_update"] = datetime.now().isoformat()

                    url = f"https://index.commoncrawl.org/{index}-index"
                    params = {
                        "url": pattern,
                        "output": "json",
                        "limit": 5000,
                    }

                    resp = await client.get(url, params=params)

                    if resp.status_code == 200 and resp.text.strip():
                        for line in resp.text.strip().split("\n"):
                            if line.strip():
                                try:
                                    record = json.loads(line)
                                    page_url = record.get("url", "")
                                    if page_url:
                                        urls_found.append(page_url)
                                except json.JSONDecodeError:
                                    continue

                    print(f"  {index} / {pattern}: found {len(urls_found)} total so far")

                except httpx.TimeoutException:
                    print(f"  Timeout: {index} / {pattern}")
                    scraper_status["errors"] += 1
                except Exception as e:
                    print(f"  Error: {index} / {pattern}: {e}")
                    scraper_status["errors"] += 1

                await asyncio.sleep(0.5)

    # Deduplicate
    seen = set()
    unique = []
    for u in urls_found:
        domain = urlparse(u).netloc
        if domain and domain not in seen:
            seen.add(domain)
            unique.append(u)

    return unique


# ========================================
# METHOD 2: Certificate Transparency Search
# ========================================
async def search_certificates() -> list[str]:
    """
    Search crt.sh (Certificate Transparency logs) for domains
    that have SSL certs issued by/for GHL infrastructure.
    This finds custom domains pointed at GHL.
    """
    global scraper_status
    domains_found = []

    search_terms = [
        "%.msgsndr.com",
        "%.leadconnectorhq.com",
    ]

    async with httpx.AsyncClient(timeout=120) as client:
        for term in search_terms:
            try:
                scraper_status["message"] = f"Searching certificates for {term}..."
                scraper_status["last_update"] = datetime.now().isoformat()

                resp = await client.get(
                    "https://crt.sh/",
                    params={"q": term, "output": "json"},
                    timeout=120,
                )

                if resp.status_code == 200:
                    try:
                        certs = resp.json()
                        for cert in certs:
                            name = cert.get("common_name", "")
                            if name and "*" not in name:
                                domains_found.append(name)
                            # Also check SAN names
                            name_value = cert.get("name_value", "")
                            if name_value:
                                for n in name_value.split("\n"):
                                    n = n.strip()
                                    if n and "*" not in n:
                                        domains_found.append(n)
                    except Exception:
                        pass

                print(f"  crt.sh {term}: found {len(domains_found)} domains so far")

            except Exception as e:
                print(f"  crt.sh error for {term}: {e}")
                scraper_status["errors"] += 1

            await asyncio.sleep(2)

    # Deduplicate
    unique = list(set(domains_found))
    # Filter out the GHL infrastructure domains themselves
    filtered = [
        d for d in unique
        if not any(d.endswith(sig) for sig in GHL_SIGNATURES)
        and "." in d
    ]

    return filtered


# ========================================
# METHOD 3: Direct URL Checker (async fast)
# ========================================
async def check_site(client: httpx.AsyncClient, url: str) -> dict | None:
    """Check a single site for GHL + calendar."""
    try:
        if not url.startswith("http"):
            url = f"https://{url}"

        resp = await client.get(url, follow_redirects=True, timeout=15)
        html = resp.text.lower()

        is_ghl = any(sig in html for sig in GHL_SIGNATURES)
        if not is_ghl:
            return None

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
    """Check many sites fast using async batches."""
    global scraper_status, all_results
    results = []

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"},
        follow_redirects=True,
        timeout=15,
    ) as client:
        for i in range(0, len(urls), batch_size):
            batch = urls[i: i + batch_size]
            scraper_status["message"] = f"Checking batch {i // batch_size + 1} ({i}/{len(urls)} URLs)..."
            scraper_status["last_update"] = datetime.now().isoformat()

            tasks = [check_site(client, url) for url in batch]
            batch_results = await asyncio.gather(*tasks)

            for result in batch_results:
                scraper_status["total_checked"] += 1
                if result:
                    scraper_status["ghl_found"] += 1
                    if result["has_calendar"]:
                        scraper_status["calendar_found"] += 1
                    results.append(result)
                    all_results.append(result)

            await asyncio.sleep(1)

    return results


def save_results(results: list[dict], filename: str = "ghl_sites.csv"):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not results:
        with open(filepath, "w") as f:
            f.write("url,domain,is_ghl,has_calendar,status_code,checked_at\n")
        return filepath

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    return filepath


# ========================================
# API ENDPOINTS
# ========================================
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <html>
    <head>
        <title>GHL Scraper v2</title>
        <style>
            * { box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #0f172a; color: #e2e8f0; }
            h1 { color: #38bdf8; margin-bottom: 5px; }
            h1 span { font-size: 14px; color: #64748b; }
            .btn { background: #2563eb; color: white; padding: 12px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; margin: 5px; text-decoration: none; display: inline-block; transition: background 0.2s; }
            .btn:hover { background: #1d4ed8; }
            .btn.green { background: #059669; }
            .btn.green:hover { background: #047857; }
            .btn.orange { background: #d97706; }
            .btn.orange:hover { background: #b45309; }
            .card { background: #1e293b; padding: 20px; border-radius: 12px; margin: 15px 0; border: 1px solid #334155; }
            code { background: #334155; padding: 2px 8px; border-radius: 4px; font-size: 13px; }
            .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 15px 0; }
            .stat { background: #0f172a; padding: 15px; border-radius: 8px; text-align: center; }
            .stat .num { font-size: 28px; font-weight: bold; color: #38bdf8; }
            .stat .label { font-size: 12px; color: #94a3b8; margin-top: 5px; }
            .status-msg { color: #fbbf24; font-style: italic; margin-top: 10px; }
            textarea { width: 100%; height: 120px; background: #0f172a; color: #e2e8f0; border: 1px solid #475569; border-radius: 8px; padding: 10px; font-family: monospace; font-size: 13px; resize: vertical; }
            .running { animation: pulse 1.5s infinite; }
            @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
        </style>
    </head>
    <body>
        <h1>🔍 GHL Calendar Scraper <span>v2</span></h1>

        <div class="card">
            <h3>⚡ Auto-Discovery (no URLs needed)</h3>
            <p>These search free public databases to find GHL sites automatically.</p>
            <a class="btn green" href="/api/search/commoncrawl" id="ccBtn">Search Common Crawl</a>
            <a class="btn green" href="/api/search/certificates" id="certBtn">Search SSL Certificates</a>
            <a class="btn green" href="/api/search/all" id="allBtn">Run All Methods</a>
        </div>

        <div class="card">
            <h3>📋 Check Your Own URLs</h3>
            <p>Paste URLs (one per line) and check them all at once:</p>
            <textarea id="urlInput" placeholder="site1.com&#10;site2.com&#10;site3.com"></textarea>
            <br><button class="btn orange" onclick="checkUrls()">Check These URLs</button>
        </div>

        <div class="card">
            <h3>📊 Live Status</h3>
            <div class="stats">
                <div class="stat"><div class="num" id="checked">0</div><div class="label">Checked</div></div>
                <div class="stat"><div class="num" id="ghl">0</div><div class="label">GHL Sites</div></div>
                <div class="stat"><div class="num" id="calendar">0</div><div class="label">With Calendar</div></div>
                <div class="stat"><div class="num" id="errors">0</div><div class="label">Errors</div></div>
            </div>
            <div>Method: <span id="method">—</span> | Running: <span id="running">No</span></div>
            <div class="status-msg" id="message">Idle</div>
        </div>

        <div class="card">
            <h3>📥 Results</h3>
            <a class="btn" href="/api/results">Download CSV</a>
            <a class="btn" href="/api/results/json">View as JSON</a>
            <a class="btn" href="/api/dorks">Google Dork Queries</a>
        </div>

        <div class="card">
            <h3>🔗 API Reference</h3>
            <p><code>GET /api/search/commoncrawl</code> — Search Common Crawl CDX index</p>
            <p><code>GET /api/search/certificates</code> — Search SSL certificate logs</p>
            <p><code>GET /api/search/all</code> — Run all discovery methods</p>
            <p><code>POST /api/check</code> — Check your own URLs <code>{"urls": [...]}</code></p>
            <p><code>GET /api/status</code> — Current progress</p>
            <p><code>GET /api/results</code> — Download CSV</p>
            <p><code>GET /api/results/json</code> — Results as JSON</p>
        </div>

        <script>
            async function updateStatus() {
                try {
                    const resp = await fetch('/api/status');
                    const d = await resp.json();
                    document.getElementById('checked').textContent = d.total_checked;
                    document.getElementById('ghl').textContent = d.ghl_found;
                    document.getElementById('calendar').textContent = d.calendar_found;
                    document.getElementById('errors').textContent = d.errors;
                    document.getElementById('method').textContent = d.method || '—';
                    document.getElementById('running').textContent = d.running ? '✅ Yes' : 'No';
                    document.getElementById('running').className = d.running ? 'running' : '';
                    document.getElementById('message').textContent = d.message || 'Idle';
                } catch(e) {}
            }

            async function checkUrls() {
                const text = document.getElementById('urlInput').value.trim();
                if (!text) { alert('Paste some URLs first!'); return; }
                const urls = text.split('\\n').map(u => u.trim()).filter(u => u);
                const resp = await fetch('/api/check', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({urls: urls})
                });
                const data = await resp.json();
                alert(data.message);
            }

            updateStatus();
            setInterval(updateStatus, 3000);
        </script>
    </body>
    </html>
    """


@app.get("/api/search/commoncrawl")
async def search_cc(background_tasks: BackgroundTasks):
    if scraper_status["running"]:
        return {"message": "Already running. Check /api/status"}

    async def run():
        global scraper_status
        reset_status("Common Crawl CDX")
        try:
            urls = await search_commoncrawl_cdx()
            scraper_status["message"] = f"Found {len(urls)} GHL URLs. Now checking for calendars..."
            print(f"Common Crawl found {len(urls)} unique domains")

            if urls:
                results = await check_sites_batch(urls)
                save_results(results)
                scraper_status["message"] = f"Done! Found {len(results)} GHL sites, {sum(1 for r in results if r['has_calendar'])} with calendars."
            else:
                scraper_status["message"] = "No URLs found from Common Crawl. Try the Certificate search instead."

            scraper_status["running"] = False
        except Exception as e:
            scraper_status["running"] = False
            scraper_status["message"] = f"Error: {e}"
            print(f"Error: {e}")

    background_tasks.add_task(run)
    return {"message": "Common Crawl search started! Watch the dashboard for progress."}


@app.get("/api/search/certificates")
async def search_certs(background_tasks: BackgroundTasks):
    if scraper_status["running"]:
        return {"message": "Already running. Check /api/status"}

    async def run():
        global scraper_status
        reset_status("Certificate Transparency")
        try:
            domains = await search_certificates()
            scraper_status["message"] = f"Found {len(domains)} domains from certs. Checking for GHL + calendars..."
            print(f"Certificate search found {len(domains)} domains")

            if domains:
                results = await check_sites_batch(domains)
                save_results(results)
                scraper_status["message"] = f"Done! Found {len(results)} GHL sites, {sum(1 for r in results if r['has_calendar'])} with calendars."
            else:
                scraper_status["message"] = "No domains found from certificate search."

            scraper_status["running"] = False
        except Exception as e:
            scraper_status["running"] = False
            scraper_status["message"] = f"Error: {e}"

    background_tasks.add_task(run)
    return {"message": "Certificate search started! Watch the dashboard for progress."}


@app.get("/api/search/all")
async def search_all(background_tasks: BackgroundTasks):
    if scraper_status["running"]:
        return {"message": "Already running. Check /api/status"}

    async def run():
        global scraper_status
        reset_status("All Methods")
        all_domains = set()

        try:
            # Method 1: Common Crawl
            scraper_status["message"] = "Step 1/2: Searching Common Crawl..."
            cc_urls = await search_commoncrawl_cdx()
            all_domains.update(cc_urls)
            print(f"After Common Crawl: {len(all_domains)} unique domains")

            # Method 2: Certificates
            scraper_status["message"] = "Step 2/2: Searching SSL certificates..."
            cert_domains = await search_certificates()
            all_domains.update(cert_domains)
            print(f"After Certificates: {len(all_domains)} unique domains")

            # Check all domains
            all_list = list(all_domains)
            scraper_status["message"] = f"Found {len(all_list)} total domains. Checking for GHL + calendars..."

            if all_list:
                results = await check_sites_batch(all_list)
                save_results(results)
                cal_count = sum(1 for r in results if r["has_calendar"])
                scraper_status["message"] = f"Done! {len(results)} GHL sites, {cal_count} with calendars."
            else:
                scraper_status["message"] = "No domains found. Try pasting your own URLs."

            scraper_status["running"] = False
        except Exception as e:
            scraper_status["running"] = False
            scraper_status["message"] = f"Error: {e}"

    background_tasks.add_task(run)
    return {"message": "Running all search methods! This may take a few minutes."}


@app.post("/api/check")
async def check_urls(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    urls = body.get("urls", [])
    if not urls:
        return {"error": "Send JSON with 'urls' array"}

    async def run():
        global scraper_status
        reset_status("Direct URL Check")
        scraper_status["message"] = f"Checking {len(urls)} URLs..."
        results = await check_sites_batch(urls)
        save_results(results)
        cal_count = sum(1 for r in results if r["has_calendar"])
        scraper_status["message"] = f"Done! {len(results)} GHL sites, {cal_count} with calendars."
        scraper_status["running"] = False

    background_tasks.add_task(run)
    return {"message": f"Checking {len(urls)} URLs. Watch the dashboard!"}


@app.get("/api/status")
async def get_status():
    return scraper_status


@app.get("/api/results")
async def get_results():
    filepath = os.path.join(OUTPUT_DIR, "ghl_sites.csv")
    if os.path.exists(filepath) and os.path.getsize(filepath) > 50:
        return FileResponse(filepath, filename="ghl_sites.csv", media_type="text/csv")
    return {"message": "No results yet. Run a search first."}


@app.get("/api/results/json")
async def get_results_json():
    global all_results
    if all_results:
        return {"count": len(all_results), "results": all_results}
    return {"count": 0, "results": [], "message": "No results yet."}


@app.get("/api/dorks")
async def get_dorks():
    return {
        "instructions": "Copy these into Google search to find GHL websites. Then paste the domains into the URL checker above.",
        "queries": [
            '"powered by leadconnector"',
            '"msgsndr.com" calendar',
            '"leadconnectorhq.com" booking',
            '"calendars.leadconnectorhq.com"',
            '"widget/booking" "msgsndr"',
            '"app.msgsndr.com" schedule',
            'inurl:"msgsndr.com"',
            '"book a call" "leadconnectorhq"',
            '"schedule appointment" "msgsndr"',
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
