import cdx_toolkit
import time

# These footprints find sites loading GHL's core tools
FINGERPRINTS = ["*.msgsndr.com/*", "*.leadconnectorhq.com/*"]

def crawl():
    # 'cc' tells the toolkit to use Common Crawl
    cdx = cdx_toolkit.CDXFetcher(source='cc')
    
    for pattern in FINGERPRINTS:
        print(f"Searching for {pattern}...")
        # We limit to 1000 for the first run to test
        for obj in cdx.iter(pattern, limit=1000):
            url = obj.get('url')
            # Save to the persistent volume path in Easypanel
            with open("/app/data/ghl_discovered.txt", "a") as f:
                f.write(f"{url}\n")
            print(f"Found: {url}")

if __name__ == "__main__":
    while True:
        try:
            crawl()
            print("Batch complete. Sleeping for 1 hour...")
            time.sleep(3600) 
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)
