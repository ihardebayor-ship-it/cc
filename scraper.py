"""
GoHighLevel Website Scraper v3
Finds websites built with GoHighLevel that have calendar widgets.

Working Methods:
1. Certificate Transparency (crt.sh) - finds domains with GHL SSL certs
2. Common Crawl CDX - single URL lookups (not bulk wildcard)
3. Direct URL checker - checks your own URL list fast
4. cdx_toolkit - for bulk Common Crawl searching
"""

import asyncio
import csv
import json
import os
import re
import subprocess
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

app = FastAPI(title="GHL Calendar Scraper v3")

# --- CONFIG ---
OUTPUT_DIR = "/data/results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
    "book-a-call",
    "schedule-a-call",
]

# State
scraper_status = {
    "running": False,
    "method": "",
    "total_checked": 0,
    "ghl_found": 0,
    "calendar_found": 0,
    "errors": 0,
    "domains_discovered": 0,
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
        "domains_discovered": 0,
        "started_at": datetime.now().isoformat(),
        "last_update": datetime.now().isoformat(),
        "message": f"Starting {method}...",
    }
    all_results = []


def update_msg(msg: str):
    scraper_status["message"] = msg
    scraper_status["last_update"] = datetime.now().isoformat()
    print(f"  [{scraper_status['method']}] {msg}")


# ========================================
# METHOD 1: Certificate Transparency (crt.sh)
# This is the MOST RELIABLE free method.
# It finds domains that have SSL certs linked to GHL.
# ========================================
async def search_certificates() -> list[str]:
    """
    Search crt.sh for domains with SSL certs tied to GHL infrastructure.
    crt.sh is a free Certificate Transparency log search engine.
    """
    domains_found = set()

    # Search for certs that reference GHL domains
    search_terms = [
        "%.msgsndr.com",
        "%.leadconnectorhq.com",
    ]

    async with httpx.AsyncClient(timeout=180) as client:
        for term in search_terms:
            try:
                update_msg(f"Searching crt.sh for {term} ...")

                resp = await client.get(
                    "https://crt.sh/",
                    params={"q": term, "output": "json"},
                    timeout=180,
                )

                if resp.status_code == 200:
                    try:
                        certs = resp.json()
                        for cert in certs:
                            # Get the common name
                            cn = cert.get("common_name", "").strip()
                            if cn and "*" not in cn and "." in cn:
                                domains_found.add(cn.lower())

                            # Get Subject Alternative Names (SAN)
                            san = cert.get("name_value", "")
                            if san:
                                for name in san.split("\n"):
                                    name = name.strip().lower()
                                    if name and "*" not in name and "." in name:
                                        domains_found.add(name)

                        update_msg(f"crt.sh '{term}': {len(domains_found)} domains so far")
                    except json.JSONDecodeError:
                        update_msg(f"crt.sh returned non-JSON for {term}")

                elif resp.status_code == 429:
                    update_msg(f"crt.sh rate limited. Waiting 30s...")
                    await asyncio.sleep(30)
                else:
                    update_msg(f"crt.sh returned status {resp.status_code} for {term}")

            except httpx.TimeoutException:
                update_msg(f"crt.sh timeout for {term} (this is normal, it's a slow API)")
            except Exception as e:
                update_msg(f"crt.sh error for {term}: {e}")
                scraper_status["errors"] += 1

            await asyncio.sleep(3)

    # Remove GHL's own infrastructure domains (we want customer sites)
    filtered = set()
    ghl_infra = ["msgsndr.com", "leadconnectorhq.com", "gohighlevel.com", "highlevel.com"]
    for d in domains_found:
        is_infra = any(d == infra or d.endswith(f".{infra}") for infra in ghl_infra)
        if not is_infra:
            filtered.add(d)

    scraper_status["domains_discovered"] = len(filtered)
    return list(filtered)


# ========================================
# METHOD 2: Common Crawl CDX (single URL lookups)
# Rate-limited, so we do small careful queries.
# ========================================
async def search_commoncrawl_cdx(seed_domains: list[str] = None) -> list[str]:
    """
    Use Common Crawl CDX to verify/expand a list of domains.
    Does single-domain lookups (not bulk wildcard) to avoid rate limits.
    """
    CC_INDEX = "CC-MAIN-2026-08-index"
    urls_found = []

    # If no seeds given, try some known GHL URL patterns
    if not seed_domains:
        seed_domains = [
            "msgsndr.com",
            "leadconnectorhq.com",
        ]

    async with httpx.AsyncClient(timeout=30) as client:
        for domain in seed_domains[:100]:  # Limit to avoid rate limits
            try:
                update_msg(f"CDX lookup: {domain}")

                url = f"https://index.commoncrawl.org/{CC_INDEX}"
                params = {
                    "url": domain,
                    "output": "json",
                    "limit": 10,
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

                # Be very gentle with CDX rate limits
                await asyncio.sleep(2)

            except Exception as e:
                scraper_status["errors"] += 1
                await asyncio.sleep(5)

    return urls_found


# ========================================
# METHOD 3: Direct site checker (async fast)
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
    total = len(urls)

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        follow_redirects=True,
        timeout=15,
    ) as client:
        for i in range(0, total, batch_size):
            batch = urls[i: i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size
            update_msg(f"Checking sites: batch {batch_num}/{total_batches} ({i}/{total})")

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


def append_results(results: list[dict], filename: str = "ghl_sites.csv"):
    """Append new results to existing CSV (doesn't overwrite)."""
    filepath = os.path.join(OUTPUT_DIR, filename)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 50

    with open(filepath, "a", newline="") as f:
        if results:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            if not file_exists:
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
        <title>GHL Scraper v3</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 960px; margin: 0 auto; padding: 20px; background: #0f172a; color: #e2e8f0; }
            h1 { color: #38bdf8; margin-bottom: 5px; }
            h1 span { font-size: 14px; color: #64748b; font-weight: normal; }
            h3 { margin-bottom: 10px; color: #f1f5f9; }
            p { margin-bottom: 10px; color: #94a3b8; line-height: 1.5; }
            .btn { background: #2563eb; color: white; padding: 10px 18px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; margin: 4px; text-decoration: none; display: inline-block; transition: all 0.2s; }
            .btn:hover { background: #1d4ed8; transform: translateY(-1px); }
            .btn.green { background: #059669; }
            .btn.green:hover { background: #047857; }
            .btn.orange { background: #d97706; }
            .btn.orange:hover { background: #b45309; }
            .btn.red { background: #dc2626; font-size: 12px; padding: 6px 12px; }
            .card { background: #1e293b; padding: 20px; border-radius: 12px; margin: 15px 0; border: 1px solid #334155; }
            code { background: #334155; padding: 2px 8px; border-radius: 4px; font-size: 13px; }
            .stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 15px 0; }
            .stat { background: #0f172a; padding: 12px; border-radius: 8px; text-align: center; }
            .stat .num { font-size: 24px; font-weight: bold; color: #38bdf8; }
            .stat .label { font-size: 11px; color: #94a3b8; margin-top: 4px; }
            .status-msg { color: #fbbf24; font-style: italic; margin-top: 10px; font-size: 14px; min-height: 20px; }
            textarea { width: 100%; height: 120px; background: #0f172a; color: #e2e8f0; border: 1px solid #475569; border-radius: 8px; padding: 10px; font-family: monospace; font-size: 13px; resize: vertical; margin-bottom: 10px; }
            .running { animation: pulse 1.5s infinite; }
            @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
            .badge { display: inline-block; background: #059669; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-left: 5px; }
            .badge.best { background: #f59e0b; }
        </style>
    </head>
    <body>
        <h1>🔍 GHL Calendar Scraper <span>v3</span></h1>

        <div class="card">
            <h3>⚡ Auto-Discovery</h3>

            <p><strong>SSL Certificate Search</strong> <span class="badge best">BEST METHOD</span><br>
            Searches public SSL certificate logs for domains using GHL. Finds thousands of real customer sites.</p>
            <a class="btn green" href="/api/search/certificates">🔒 Search SSL Certificates</a>

            <br><br>
            <p><strong>Full Pipeline</strong><br>
            Runs certificate search, then checks every found domain for GHL + calendar widgets.</p>
            <a class="btn green" href="/api/search/full">🚀 Run Full Pipeline</a>
        </div>

        <div class="card">
            <h3>📋 Check Your Own URLs</h3>
            <p>Paste URLs (one per line) and check them all at once:</p>
            <textarea id="urlInput" placeholder="example.com&#10;another-site.com&#10;business-site.com"></textarea>
            <button class="btn orange" onclick="checkUrls()">⚡ Check These URLs</button>
        </div>

        <div class="card">
            <h3>📊 Live Status</h3>
            <div class="stats">
                <div class="stat"><div class="num" id="discovered">0</div><div class="label">Discovered</div></div>
                <div class="stat"><div class="num" id="checked">0</div><div class="label">Checked</div></div>
                <div class="stat"><div class="num" id="ghl">0</div><div class="label">GHL Sites</div></div>
                <div class="stat"><div class="num" id="calendar">0</div><div class="label">With Calendar</div></div>
                <div class="stat"><div class="num" id="errors">0</div><div class="label">Errors</div></div>
            </div>
            <div style="font-size:13px;">Method: <strong id="method">—</strong> | Running: <strong id="running">No</strong></div>
            <div class="status-msg" id="message">Idle</div>
        </div>

        <div class="card">
            <h3>📥 Results</h3>
            <a class="btn" href="/api/results">📄 Download CSV</a>
            <a class="btn" href="/api/results/json">{ } View JSON</a>
            <a class="btn" href="/api/dorks">🔍 Google Dork Queries</a>
            <a class="btn red" href="/api/clear">🗑 Clear Results</a>
        </div>

        <div class="card">
            <h3>🔗 API</h3>
            <p><code>GET /api/search/certificates</code> — Find GHL domains via SSL certs</p>
            <p><code>GET /api/search/full</code> — Full pipeline: discover + check all</p>
            <p><code>POST /api/check</code> — Check your own URLs <code>{"urls":[...]}</code></p>
            <p><code>GET /api/status</code> — Progress</p>
            <p><code>GET /api/results</code> — CSV download</p>
            <p><code>GET /api/results/json</code> — JSON results</p>
        </div>

        <script>
            async function updateStatus() {
                try {
                    const r = await fetch('/api/status');
                    const d = await r.json();
                    document.getElementById('discovered').textContent = d.domains_discovered || 0;
                    document.getElementById('checked').textContent = d.total_checked;
                    document.getElementById('ghl').textContent = d.ghl_found;
                    document.getElementById('calendar').textContent = d.calendar_found;
                    document.getElementById('errors').textContent = d.errors;
                    document.getElementById('method').textContent = d.method || '—';
                    const runEl = document.getElementById('running');
                    runEl.textContent = d.running ? '✅ Yes' : 'No';
                    runEl.className = d.running ? 'running' : '';
                    document.getElementById('message').textContent = d.message || 'Idle';
                } catch(e) {}
            }

            async function checkUrls() {
                const text = document.getElementById('urlInput').value.trim();
                if (!text) { alert('Paste some URLs first!'); return; }
                const urls = text.split('\\n').map(u => u.trim()).filter(u => u);
                const r = await fetch('/api/check', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({urls})
                });
                const d = await r.json();
                alert(d.message);
            }

            updateStatus();
            setInterval(updateStatus, 2000);
        </script>
    </body>
    </html>
    """


# --- Search: Certificates only ---
@app.get("/api/search/certificates")
async def search_certs_endpoint(background_tasks: BackgroundTasks):
    if scraper_status["running"]:
        return {"message": "Already running. Check /api/status"}

    async def run():
        reset_status("Certificate Transparency")
        try:
            domains = await search_certificates()
            update_msg(f"Found {len(domains)} customer domains from SSL certs.")
            # Save just the domain list
            filepath = os.path.join(OUTPUT_DIR, "discovered_domains.txt")
            with open(filepath, "w") as f:
                f.write("\n".join(sorted(domains)))
            update_msg(f"Done! {len(domains)} domains saved. Use 'Full Pipeline' to check them for calendars.")
            scraper_status["running"] = False
        except Exception as e:
            update_msg(f"Error: {e}")
            scraper_status["running"] = False

    background_tasks.add_task(run)
    return {"message": "Certificate search started! This searches public SSL logs — may take 1-3 minutes."}


# --- Search: Full pipeline (discover + check) ---
@app.get("/api/search/full")
async def search_full(background_tasks: BackgroundTasks):
    if scraper_status["running"]:
        return {"message": "Already running. Check /api/status"}

    async def run():
        reset_status("Full Pipeline")
        try:
            # Step 1: Discover domains
            update_msg("Step 1: Searching SSL certificates for GHL domains...")
            domains = await search_certificates()
            update_msg(f"Step 1 done: {len(domains)} domains found.")

            if not domains:
                update_msg("No domains found. crt.sh may be slow — try again in a few minutes.")
                scraper_status["running"] = False
                return

            # Step 2: Check each domain for GHL + calendars
            update_msg(f"Step 2: Checking {len(domains)} domains for GHL + calendar widgets...")
            results = await check_sites_batch(domains)

            # Save
            save_results(results)
            cal = sum(1 for r in results if r.get("has_calendar"))
            update_msg(f"✅ Done! {len(results)} confirmed GHL sites, {cal} with calendar widgets.")
            scraper_status["running"] = False

        except Exception as e:
            update_msg(f"Error: {e}")
            scraper_status["running"] = False

    background_tasks.add_task(run)
    return {"message": "Full pipeline started! Step 1: discover domains, Step 2: check for calendars."}


# --- Check custom URLs ---
@app.post("/api/check")
async def check_urls_endpoint(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    urls = body.get("urls", [])
    if not urls:
        return {"error": "Send JSON with 'urls' array"}

    async def run():
        reset_status("Direct URL Check")
        update_msg(f"Checking {len(urls)} URLs...")
        results = await check_sites_batch(urls)
        append_results(results)
        cal = sum(1 for r in results if r.get("has_calendar"))
        update_msg(f"✅ Done! {len(results)} GHL sites, {cal} with calendars.")
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
    # Also check for discovered domains
    domain_file = os.path.join(OUTPUT_DIR, "discovered_domains.txt")
    if os.path.exists(domain_file):
        return FileResponse(domain_file, filename="discovered_domains.txt", media_type="text/plain")
    return {"message": "No results yet. Run a search first."}


@app.get("/api/results/json")
async def get_results_json():
    if all_results:
        return {
            "count": len(all_results),
            "ghl_count": sum(1 for r in all_results if r.get("is_ghl")),
            "calendar_count": sum(1 for r in all_results if r.get("has_calendar")),
            "results": all_results,
        }
    return {"count": 0, "results": [], "message": "No results yet."}


@app.get("/api/clear")
async def clear_results():
    global all_results
    all_results = []
    for f in ["ghl_sites.csv", "discovered_domains.txt"]:
        fp = os.path.join(OUTPUT_DIR, f)
        if os.path.exists(fp):
            os.remove(fp)
    return {"message": "Results cleared."}


@app.get("/api/dorks")
async def get_dorks():
    return {
        "instructions": "Copy these into Google. Then paste the domains you find into the URL checker.",
        "queries": [
            '"powered by leadconnector"',
            '"msgsndr.com" calendar',
            '"leadconnectorhq.com" booking',
            '"calendars.leadconnectorhq.com"',
            '"widget/booking" "msgsndr"',
            '"book a call" "leadconnectorhq"',
            '"schedule appointment" "msgsndr"',
            'inurl:"msgsndr.com"',
            '"app.msgsndr.com"',
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
