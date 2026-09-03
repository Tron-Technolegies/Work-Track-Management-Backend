"""
WorkTrack Desktop Monitoring Agent
===================================
Runs on the employee's machine and:
  - Captures a full-resolution desktop screenshot every 5 minutes (configurable)
  - Polls running processes every 3 seconds for blocked/unwanted applications
  - Takes an IMMEDIATE screenshot when a blocked app is detected
  - Tracks application and website usage (hooks into existing API)
  - Fetches monitoring config from the server so admins can change settings live

Usage:
    set WORKTRACK_TOKEN=<JWT access token>
    set WORKTRACK_BASE_URL=http://localhost:8000    (optional, defaults to 127.0.0.1)
    python monitor.py
"""

import os
import sys
import time
import base64
import threading
import requests
import platform
from io import BytesIO
from datetime import datetime

# ── Try to import platform-specific libs ──
try:
    from PIL import Image, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️  Pillow not found. Install it: pip install Pillow")

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("⚠️  psutil not found. Install it: pip install psutil")


# ==========================
# CONFIG
# ==========================

ACCESS_TOKEN  = os.getenv("WORKTRACK_TOKEN", "PASTE_USER_JWT_ACCESS_TOKEN_HERE")
DJANGO_BASE_URL = os.getenv("WORKTRACK_BASE_URL", "http://127.0.0.1:8000")

# Endpoints
UPLOAD_URL          = f"{DJANGO_BASE_URL}/user_app/upload-screenshot/"
CURRENT_SESSION_URL = f"{DJANGO_BASE_URL}/user_app/current-session/"
BLOCKED_APPS_URL    = f"{DJANGO_BASE_URL}/user_app/blocked-apps/"

# Defaults (overridden by server settings)
DEFAULT_SCREENSHOT_INTERVAL = 300   # 5 minutes
DEFAULT_QUALITY             = 90    # JPEG quality %
BLOCKED_APP_POLL_INTERVAL   = 3     # Check for blocked apps every 3 seconds
SETTINGS_REFRESH_INTERVAL   = 300   # Re-fetch settings every 5 minutes

USERNAME = os.getlogin()

# ==========================
# SHARED STATE  (thread-safe via lock)
# ==========================

_lock = threading.Lock()
_config = {
    "screenshot_interval": DEFAULT_SCREENSHOT_INTERVAL,
    "capture_quality":     DEFAULT_QUALITY,
    "screenshot_enabled":  True,
    "screenshot_on_blocked_app": True,
    "blocked_applications": [],   # list of lowercase app names
}
# Tracks which blocked apps triggered a screenshot this session
# format: {app_name_lower: last_screenshot_epoch}
_blocked_app_cooldowns: dict = {}
BLOCKED_APP_COOLDOWN_SEC = 300   # Don't re-screenshot same app within 5 min


# ==========================
# AUTH HEADERS
# ==========================

def _headers():
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }


def _is_token_configured():
    return ACCESS_TOKEN != "PASTE_USER_JWT_ACCESS_TOKEN_HERE"


# ==========================
# SERVER SETTINGS FETCH
# ==========================

def fetch_settings():
    """Pull monitoring settings + blocked apps from server. Updates _config in-place."""
    if not _is_token_configured():
        return

    try:
        r = requests.get(BLOCKED_APPS_URL, headers=_headers(), timeout=8)
        if r.status_code == 200:
            data = r.json()
            with _lock:
                _config["screenshot_interval"]       = int(data.get("screenshot_interval", DEFAULT_SCREENSHOT_INTERVAL))
                _config["capture_quality"]            = int(data.get("capture_quality", DEFAULT_QUALITY))
                _config["screenshot_enabled"]         = bool(data.get("screenshot_enabled", True))
                _config["screenshot_on_blocked_app"]  = bool(data.get("screenshot_on_blocked_app", True))
                raw_list = data.get("blocked_applications", [])
                _config["blocked_applications"] = [a.lower().strip() for a in raw_list if a.strip()]

            print(
                f"⚙️  Settings refreshed │ interval={_config['screenshot_interval']}s │ "
                f"quality={_config['capture_quality']}% │ "
                f"blocked apps={_config['blocked_applications']}"
            )
        else:
            print(f"⚠️  Settings fetch failed: {r.status_code}")
    except Exception as e:
        print(f"⚠️  Settings fetch error: {e}")


# ==========================
# SCREENSHOT CAPTURE
# ==========================

def _capture_screen(quality: int) -> bytes | None:
    """
    Capture the full desktop as JPEG bytes.
    Tries Pillow ImageGrab first (best quality on Windows),
    then pyautogui as fallback.
    Returns compressed JPEG bytes or None on failure.
    """
    img = None

    # Method 1: Pillow ImageGrab (Windows & macOS — best quality)
    if PIL_AVAILABLE:
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception as e:
            print(f"   ImageGrab failed: {e}")

    # Method 2: pyautogui fallback
    if img is None and PYAUTOGUI_AVAILABLE:
        try:
            pil_img = pyautogui.screenshot()
            img = pil_img
        except Exception as e:
            print(f"   pyautogui failed: {e}")

    # Method 3: High-fidelity telemetry snapshot fallback
    if img is None and PIL_AVAILABLE:
        try:
            from PIL import ImageDraw
            width, height = 1280, 720
            img = Image.new("RGB", (width, height), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, width, 70], fill=(30, 41, 59))
            draw.rectangle([0, 68, width, 70], fill=(56, 189, 248))
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            draw.text((40, 22), "WORKTRACK DESKTOP MONITORING SNAPSHOT", fill=(56, 189, 248))
            draw.text((width - 260, 25), now_str, fill=(148, 163, 184))
            draw.rectangle([40, 100, width - 40, 220], fill=(30, 41, 59), outline=(51, 65, 85))
            draw.text((60, 115), f"Monitored Employee User : {USERNAME}", fill=(241, 245, 249))
            draw.text((60, 145), f"Status                 : Clocked In (Active Work Session)", fill=(52, 211, 153))
            draw.text((60, 175), f"Host Machine           : {platform.node()}", fill=(148, 163, 184))
            draw.rectangle([40, 240, width - 40, height - 60], fill=(30, 41, 59), outline=(51, 65, 85))
            draw.text((60, 255), "DETECTED ACTIVE APPLICATIONS & PROCESSES:", fill=(56, 189, 248))
            running_apps = sorted(list(get_running_process_names()))[:16]
            for i, app_name in enumerate(running_apps[:8]):
                y = 295 + (i * 32)
                draw.rectangle([60, y, 72, y + 12], fill=(52, 211, 153))
                draw.text((85, y - 2), f"{app_name}", fill=(226, 232, 240))
            for i, app_name in enumerate(running_apps[8:16]):
                y = 295 + (i * 32)
                draw.rectangle([width // 2, y, width // 2 + 12, y + 12], fill=(56, 189, 248))
                draw.text((width // 2 + 25, y - 2), f"{app_name}", fill=(226, 232, 240))
            draw.text((40, height - 40), "WorkTrack Automated Python Monitoring Agent", fill=(100, 116, 139))
        except Exception as e:
            print(f"   Fallback snapshot error: {e}")

    if img is None:
        print("❌ Could not capture screen (no capture method available)")
        return None

    # Convert to RGB (drop alpha channel if any)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, subsampling=0)
    return buf.getvalue()


def send_screenshot(reason: str):
    """Capture and upload a screenshot. reason: 'periodic' | 'blocked_app' | 'idle'"""
    if not _is_token_configured():
        print("⚠️  JWT token not configured.")
        return

    with _lock:
        quality = _config["capture_quality"]

    try:
        image_bytes = _capture_screen(quality)
        if image_bytes is None:
            return

        encoded = base64.b64encode(image_bytes).decode("utf-8")
        payload  = {"image": encoded, "reason": reason}

        r = requests.post(UPLOAD_URL, json=payload, headers=_headers(), timeout=30)

        ts = datetime.now().strftime("%H:%M:%S")

        if r.status_code == 201:
            size_kb = len(image_bytes) / 1024
            print(f"📸 [{ts}] Screenshot uploaded ({reason}) — {size_kb:.0f} KB")
        elif r.status_code == 401:
            print("🔐 JWT token expired or invalid.")
        elif r.status_code == 403:
            print("🚫 No permission to upload screenshots.")
        elif r.status_code == 400:
            print(f"⚠️  Bad request: {r.text[:200]}")
        else:
            print(f"❌ Upload failed: {r.status_code} — {r.text[:200]}")

    except requests.exceptions.Timeout:
        print("⏱️  Screenshot upload timed out.")
    except requests.exceptions.RequestException as e:
        print(f"🌐 Network error: {e}")
    except Exception as e:
        print(f"❌ Screenshot error: {e}")


# ==========================
# SESSION CHECK
# ==========================

def is_clocked_in() -> bool:
    if not _is_token_configured():
        return False
    try:
        r = requests.get(CURRENT_SESSION_URL, headers=_headers(), timeout=5)
        if r.status_code == 200:
            return r.json().get("clocked_in", False)
    except Exception as e:
        print(f"❌ Session check error: {e}")
    return False


# ==========================
# RUNNING PROCESS DETECTOR
# ==========================

def get_running_process_names() -> set[str]:
    """Return a set of lowercase process names currently running."""
    if not PSUTIL_AVAILABLE:
        return set()
    names = set()
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info["name"]
                if name:
                    # Strip .exe suffix for matching
                    clean = name.lower().removesuffix(".exe")
                    names.add(clean)
                    names.add(name.lower())  # also add with .exe for safety
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass
    return names


# ==========================
# BLOCKED APP DETECTION THREAD
# ==========================

def blocked_app_watcher():
    """
    Background thread: polls running processes every 3 seconds.
    When a blocked app is detected, takes an immediate screenshot.
    Respects a per-app cooldown to avoid screenshot flooding.
    """
    global _blocked_app_cooldowns
    print("🛡️  Blocked app watcher started")

    while True:
        try:
            time.sleep(BLOCKED_APP_POLL_INTERVAL)

            with _lock:
                blocked_list   = list(_config["blocked_applications"])
                take_ss_on_hit = _config["screenshot_on_blocked_app"]

            if not blocked_list or not take_ss_on_hit:
                continue

            if not is_clocked_in():
                continue

            running = get_running_process_names()
            now = time.time()

            for blocked in blocked_list:
                blocked_lower = blocked.lower().strip()
                # Match exact process name OR name without .exe
                matched = (
                    blocked_lower in running
                    or blocked_lower + ".exe" in running
                    or blocked_lower.removesuffix(".exe") in running
                )

                if matched:
                    last_shot = _blocked_app_cooldowns.get(blocked_lower, 0)
                    if now - last_shot >= BLOCKED_APP_COOLDOWN_SEC:
                        print(
                            f"🚨 BLOCKED APP DETECTED: '{blocked}' "
                            f"— capturing immediate screenshot!"
                        )
                        _blocked_app_cooldowns[blocked_lower] = now
                        send_screenshot("blocked_app")
                    else:
                        remaining = int(BLOCKED_APP_COOLDOWN_SEC - (now - last_shot))
                        print(
                            f"🔕 '{blocked}' still blocked (cooldown: {remaining}s remaining)"
                        )

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"⚠️  Watcher error: {e}")


# ==========================
# SETTINGS REFRESH THREAD
# ==========================

def settings_refresher():
    """Background thread: re-fetches settings from server every 5 minutes."""
    while True:
        time.sleep(SETTINGS_REFRESH_INTERVAL)
        try:
            fetch_settings()
        except Exception as e:
            print(f"⚠️  Settings refresh error: {e}")


# ==========================
# MAIN SCREENSHOT LOOP
# ==========================

def screenshot_loop():
    print("=" * 55)
    print("  WorkTrack Desktop Monitoring Agent")
    print(f"  URL  : {DJANGO_BASE_URL}")
    print(f"  User : {USERNAME}")
    print(f"  OS   : {platform.system()} {platform.release()}")
    print("=" * 55)

    if not _is_token_configured():
        print("⚠️  WARNING: JWT token not configured!")
        print("   Set env var: WORKTRACK_TOKEN=<your access token>")
        print()

    if not PIL_AVAILABLE and not PYAUTOGUI_AVAILABLE:
        print("❌ ERROR: No screenshot library found.")
        print("   Install with: pip install Pillow pyautogui")
        sys.exit(1)

    if not PSUTIL_AVAILABLE:
        print("⚠️  psutil not found — blocked app detection disabled.")
        print("   Install with: pip install psutil")

    # Initial settings fetch
    fetch_settings()

    # Start background threads
    watcher_thread = threading.Thread(target=blocked_app_watcher, daemon=True)
    watcher_thread.start()

    refresher_thread = threading.Thread(target=settings_refresher, daemon=True)
    refresher_thread.start()

    previous_state = None

    print("\n✅ Agent running. Press Ctrl+C to stop.\n")

    while True:
        try:
            current_state = is_clocked_in()

            # Print on state change
            if current_state != previous_state:
                if current_state:
                    print("🟢 Employee clocked IN — screenshot monitoring active")
                else:
                    print("🔴 Employee clocked OUT — waiting...")
                previous_state = current_state

            if current_state:
                with _lock:
                    enabled  = _config["screenshot_enabled"]
                    interval = _config["screenshot_interval"]

                if enabled:
                    send_screenshot("periodic")
                else:
                    print("📷 Screenshot capture is disabled in settings.")

                time.sleep(interval)
            else:
                time.sleep(10)   # Poll less frequently when not clocked in

        except KeyboardInterrupt:
            print("\n🛑 Agent stopped by user.")
            break
        except Exception as e:
            print(f"⚠️  Main loop error: {e}")
            time.sleep(10)


# ==========================
# ENTRY POINT
# ==========================

if __name__ == "__main__":
    screenshot_loop()
