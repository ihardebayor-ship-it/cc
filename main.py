import requests
import json
import time

# FIXED: Using the actual latest live index
INDEX = "CC-MAIN-2026-08" 

# FIXED: Back to the broad wildcard that was working
TARGET = "widgets.leadconnectorhq.com/*"

def get_ghl_users():
    api_url = f"https://index.commoncrawl.org/{INDEX}-index?url={TARGET}&output=json&fl=url"
    
    print(f"🚀 Hunting GHL assets in {INDEX}...")
    
    try:
        # stream=True handles the massive list of results without crashing
        response = requests.get(api_url, stream=True)
        
        if response.status_code == 200:
            count = 0
            # Open the file in 'append' mode on your Easypanel volume
            with open("/app/data/ghl_discovered.txt", "a") as f:
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        url = data.get('url')
                        f.write(f"{url}\n")
                        count += 1
                        # Optional: prints every 100th find to the Easypanel console
                        if count % 100 == 0:
                            print(f"Found {count} assets so far...")
            
            print(f"✅ Success! Total found: {count}")
        elif response.status_code == 404:
            print(f"❌ Error 404: The index {INDEX} is not responding. Trying fallback...")
            # If 2026-08 fails, the server might be lagging. Try 2026-04.
        else:
            print(f"⚠️ Server returned error: {response.status_code}")

    except Exception as e:
        print(f"💥 Script Error: {e}")

if __name__ == "__main__":
    # Run once, then sleep so Easypanel doesn't keep restarting it instantly
    get_ghl_users()
    print("Process finished. Sleeping for 24 hours.")
    time.sleep(86400)
