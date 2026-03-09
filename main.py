import requests
import json
import time

TARGET = "widgets.leadconnectorhq.com/*"

def get_latest_index():
    """Fetches the most recent live index ID from Common Crawl"""
    try:
        response = requests.get("https://index.commoncrawl.org/collinfo.json")
        if response.status_code == 200:
            indexes = response.json()
            # The first one in the list is usually the newest
            latest = indexes[0]['id']
            print(f"📡 Detected latest live index: {latest}")
            return latest
    except Exception as e:
        print(f"Error fetching index list: {e}")
    return "CC-MAIN-2025-49" # Fallback to a guaranteed old index

def start_hunt():
    index_id = get_latest_index()
    api_url = f"https://index.commoncrawl.org/{index_id}-index?url={TARGET}&output=json&fl=url"
    
    print(f"🚀 Hunting GHL assets in {index_id}...")
    
    try:
        # We use a timeout to prevent the script from hanging forever
        response = requests.get(api_url, stream=True, timeout=30)
        
        if response.status_code == 200:
            count = 0
            with open("/app/data/ghl_discovered.txt", "a") as f:
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        url = data.get('url')
                        f.write(f"{url}\n")
                        count += 1
                        if count % 100 == 0:
                            print(f"Found {count} assets...")
            print(f"✅ Success! Total found: {count}")
        else:
            print(f"❌ Server returned {response.status_code}. The index {index_id} might be offline.")

    except Exception as e:
        print(f"💥 Connection Error: {e}")

if __name__ == "__main__":
    while True:
        start_hunt()
        print("Waiting 24 hours for next crawl check...")
        time.sleep(86400)
