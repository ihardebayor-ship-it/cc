import requests
import json
import time

# The target GHL widget domain
TARGET = "widgets.leadconnectorhq.com/*"
# Change this to the latest available index (e.g., CC-MAIN-2026-05)
INDEX = "CC-MAIN-2026-05" 

def get_ghl_users():
    # We ask the API for the URL and the 'filename' 
    # The filename tells us which crawl archive it's in
    api_url = f"https://index.commoncrawl.org/{INDEX}-index?url={TARGET}&output=json&fl=url,timestamp"
    
    print(f"Searching for GHL users via {TARGET}...")
    
    try:
        response = requests.get(api_url, stream=True)
        if response.status_code != 200:
            print(f"Error: API returned {response.status_code}")
            return

        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                asset_url = data.get('url')
                
                # Logic: If the URL contains a Location ID, it's a GHL user
                # Example: widgets.leadconnectorhq.com/chat-widget/loader.js?v=123
                if "loader.js" in asset_url or "chat-widget" in asset_url:
                    with open("/app/data/ghl_widgets_found.txt", "a") as f:
                        f.write(f"{asset_url}\n")
                    print(f"Found Asset: {asset_url}")

    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    get_ghl_users()
    print("Search complete. Check /app/data/ghl_widgets_found.txt")
