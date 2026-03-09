import cdx_toolkit
import time
import os
import re

# We target the booking/calendar sub-folders specifically
CALENDAR_TARGETS = [
    "widgets.leadconnectorhq.com/booking/*",
    "link.msgsndr.com/widget/booking/*"
]

def hunt_calendars():
    cdx = cdx_toolkit.CDXFetcher(source='cc')
    
    for target in CALENDAR_TARGETS:
        print(f"📅 Searching for Calendar Widgets: {target}")
        
        try:
            for obj in cdx.iter(target):
                url = obj.get('url')
                
                # Calendar URLs almost always end in a 20-character alphanumeric ID
                # Example: .../booking/DuRajeaVgEXQKFG3mFKA
                match = re.search(r'/booking/([a-zA-Z0-9]{20})', url)
                
                if match:
                    calendar_id = match.group(1)
                    
                    with open("/app/data/ghl_calendars.txt", "a") as f:
                        f.write(f"{calendar_id} | {url}\n")
                    
                    print(f"✅ Found Calendar: {calendar_id}")
        
        except Exception as e:
            print(f"⚠️ Error on {target}: {e}")

if __name__ == "__main__":
    os.makedirs("/app/data", exist_ok=True)
    while True:
        hunt_calendars()
        print("Cycle finished. Sleeping...")
        time.sleep(3600)
