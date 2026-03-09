import cdx_toolkit
import time
import os

# The 'footprint' - GHL assets are served from this domain
GHL_FOOTPRINT = "*.msgsndr.com/*" 

def start_extraction():
    # 'cc' source points to Common Crawl
    cdx = cdx_toolkit.CDXFetcher(source='cc')
    
    # We use a wildcard to find any site calling GHL assets
    # This can return millions of rows, so we process in chunks
    print(f"Hunting for GHL sites using footprint: {GHL_FOOTPRINT}")
    
    # Limit is set to 1000 for safety; remove limit for full grab
    for obj in cdx.iter(GHL_FOOTPRINT, limit=1000):
        url = obj.get('url')
        timestamp = obj.get('timestamp')
        
        # Log the found URL to a file in Easypanel's persistent storage
        with open("/app/data/ghl_sites.txt", "a") as f:
            f.write(f"{timestamp} | {url}\n")
            
        print(f"Found GHL Activity: {url}")

if __name__ == "__main__":
    while True:
        try:
            start_extraction()
            # Common Crawl API is rate-limited; don't get banned!
            time.sleep(60) 
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(300)
