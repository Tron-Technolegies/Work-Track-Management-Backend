import os
import time
import base64
import requests
import pyautogui
from io import BytesIO
from datetime import datetime

# ==========================
# CONFIG
# ==========================

# Access via environment variables:
# set WORKTRACK_TOKEN=your_token
# set WORKTRACK_BASE_URL=http://localhost:8000
ACCESS_TOKEN = os.getenv("WORKTRACK_TOKEN", "PASTE_USER_JWT_ACCESS_TOKEN_HERE")
DJANGO_BASE_URL = os.getenv("WORKTRACK_BASE_URL", "http://127.0.0.1:8000")

SCREENSHOT_INTERVAL_SEC = 60
UPLOAD_URL = f"{DJANGO_BASE_URL}/user_app/upload-screenshot/"
CURRENT_SESSION_URL = f"{DJANGO_BASE_URL}/user_app/current-session/"

USERNAME = os.getlogin()

# ==========================
# SCREENSHOT UPLOAD
# ==========================

def send_screenshot_to_server(reason):
    if ACCESS_TOKEN == "PASTE_USER_JWT_ACCESS_TOKEN_HERE":
        print("⚠️  Warning: JWT token not configured. Set WORKTRACK_TOKEN environment variable.")
        return

    try:
        screenshot = pyautogui.screenshot()
        buffer = BytesIO()
        screenshot.save(buffer, format="PNG")

        encoded_image = base64.b64encode(buffer.getvalue()).decode()

        payload = {
            "image": encoded_image,
            "reason": reason,
        }

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}"
        }

        res = requests.post(UPLOAD_URL, json=payload, headers=headers, timeout=10)
        if res.status_code == 201:
            print(f"📸 Screenshot uploaded at {datetime.now().strftime('%H:%M:%S')}")
        else:
            print(f"❌ Upload failed: {res.status_code} - {res.text}")

    except Exception as e:
        print("❌ Screenshot failed:", e)


def is_clocked_in():
    
    if ACCESS_TOKEN == "PASTE_USER_JWT_ACCESS_TOKEN_HERE":
        return False

    try:

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}"
        }

        response = requests.get(
            CURRENT_SESSION_URL,
            headers=headers,
            timeout=5
        )

        if response.status_code == 200:

            data = response.json()

            return data.get("clocked_in", False)

        return False

    except Exception as e:

        print("❌ Current Session Error:", e)

        return False

# ==========================
# MAIN LOOP
# ==========================

def screenshot_loop():
    
    print(f"🟢 Screenshot agent started (URL: {DJANGO_BASE_URL})")
    print(f"👤 Monitoring user: {USERNAME}")

    previous_state = None

    while True:

        try:

            current_state = is_clocked_in()

            # Print only when the status changes
            if current_state != previous_state:

                if current_state:
                    print("🟢 User Clocked In")
                else:
                    print("🔴 User Clocked Out")

                previous_state = current_state

            if current_state:

                send_screenshot_to_server("periodic")

                time.sleep(SCREENSHOT_INTERVAL_SEC)

            else:
                time.sleep(5)

        except KeyboardInterrupt:

            print("\n🛑 Agent stopped")
            break

        except Exception as e:

            print(f"⚠️ Loop error: {e}")
            time.sleep(5)
# ==========================
# ENTRY POINT
# ==========================

if __name__ == "__main__":
    screenshot_loop()

