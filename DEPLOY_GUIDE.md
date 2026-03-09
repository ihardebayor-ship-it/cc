# Deploy GHL Scraper to EasyPanel

## Step-by-Step Instructions

### Step 1: Push code to GitHub

1. Create a new GitHub repo (e.g., `ghl-scraper`)
2. Upload these 3 files to it:
   - `scraper.py`
   - `Dockerfile`
   - `requirements.txt`

### Step 2: Set up EasyPanel

1. Log into your EasyPanel dashboard
2. Click **"+ Create Project"**
3. Give it a name like `ghl-scraper`

### Step 3: Add the App

1. Inside your project, click **"+ App"**
2. Choose **"App"** (not database or service)
3. Name it `scraper`

### Step 4: Connect to GitHub

1. In the app settings, go to the **"Build"** tab
2. Select **"GitHub"** as the source
3. Connect your GitHub account if you haven't already
4. Pick your `ghl-scraper` repo
5. Branch: `main`

### Step 5: Configure

1. **Build type**: Dockerfile (it will auto-detect your Dockerfile)
2. **Port**: `8000`
3. Go to **"Domains"** tab and add a domain (or use the free EasyPanel subdomain)
4. **Optional**: Under "Volumes", add a volume:
   - Mount path: `/data/results`
   - This keeps your CSV results even if the container restarts

### Step 6: Deploy

1. Click **"Deploy"**
2. Wait for the build to finish (usually 1-2 minutes)
3. Visit your domain — you'll see the scraper dashboard

---

## How to Use

Once it's running, visit your app URL and you'll see a dashboard with buttons:

- **Search Common Crawl** — Searches the free Common Crawl database for GHL sites
- **Check Status** — Shows how many sites found so far
- **Download Results** — Gets your CSV file with all the GHL sites + calendar info
- **Google Dork Queries** — Gives you Google searches to find even more GHL sites

### API Usage

You can also send your own list of URLs to check:

```bash
curl -X POST https://your-app.easypanel.host/api/check \
  -H "Content-Type: application/json" \
  -d '{"urls": ["site1.com", "site2.com", "site3.com"]}'
```

### Check progress:
```
https://your-app.easypanel.host/api/status
```

### Download CSV results:
```
https://your-app.easypanel.host/api/results
```

---

## Tips

- The Common Crawl search is completely free and doesn't hit any websites directly
- When checking URLs directly, the scraper is polite (1 second delay between batches)
- Results are saved as CSV so you can open them in Google Sheets or Excel
- You can send thousands of URLs at once via the `/api/check` endpoint
