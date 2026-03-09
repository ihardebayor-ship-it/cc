import cdx_toolkit
import time
import os

# The specific LeadConnector widget footprint
TARGET = "widgets.leadconnectorhq.com/*"

def hunt_leadconnector():
    # 'cc' source automatically finds the latest monthly indexes
    cdx = cdx_toolkit.CDXFetcher(source='cc')
    
    print(f"🎯 Target Acquired: {TARGET}")
    print("Searching for websites with GHL widgets...")

    try:
        # We iterate through the index. 'limit' is optional, remove for full grab.
        for obj in cdx.iter(TARGET):
            asset_url = obj.get('url')
            timestamp = obj.get('timestamp')
            
            # The 'url' in the CDX result is the widget itself. 
            # In some cases, the metadata includes the 'referrer' (the host site).
            # We save the full asset URL because it contains the Location ID.
            with open("/app/data/leadconnector_hits.txt", "a") as f:
                f.write(f"{timestamp} | {asset_url}\n")
            
            print(f"Found Widget Instance: {asset_url}")

    except Exception as e:
        print(f"⚠️ API Error: {e}")

if __name__ == "__main__":
    # Ensure Easypanel storage is ready
    os.makedirs("/app/data", exist_ok=True)

    while True:
        hunt_leadconnector()
        print("✅ Cycle complete. Sleeping to avoid rate limits...")
        time.sleep(3600)
