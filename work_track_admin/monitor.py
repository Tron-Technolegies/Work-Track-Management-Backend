"""
WorkTrack Desktop Monitoring Agent
===================================
Runs on the employee's machine and:
  - Captures a full-resolution desktop screenshot every 5 minutes (configurable)
  - Polls running processes every 3 seconds for blocked/unwanted applications
  - Takes an IMMEDIATE screenshot when a blocked app is detected
  - Fetches monitoring config from the server so admins can change settings live

Usage:
    # Recommended -- auto-login with credentials:
    set WORKTRACK_EMAIL=your_email@example.com
    set WORKTRACK_PASSWORD=your_password
    set WORKTRACK_BASE_URL=http://localhost:8000    (optional)
    python work_track_admin/monitor.py

    # Alternative -- supply a pre-existing JWT access token:
    set WORKTRACK_TOKEN=<JWT access token>
    python work_track_admin/monitor.py

    # CLI flags (override env vars):
    python work_track_admin/monitor.py --email x@x.com --password secret --interval 10
    python work_track_admin/monitor.py --token <JWT> --interval 10
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

# -----------------------------------------------------------------
# Force UTF-8 output on Windows so emoji/Unicode never crashes the process
# -----------------------------------------------------------------
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    else:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# -----------------------------------------------------------------
# Optional platform-specific libs
# -----------------------------------------------------------------
try:
    from PIL import Image, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[WARN] Pillow not found. Install it: pip install Pillow")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[WARN] psutil not found. Install it: pip install psutil")


# ==========================
# CONFIG
# ==========================

DJANGO_BASE_URL = os.getenv("WORKTRACK_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

# Credential-based auto-login (recommended)
WORKTRACK_EMAIL    = os.getenv("WORKTRACK_EMAIL", "").strip()
WORKTRACK_PASSWORD = os.getenv("WORKTRACK_PASSWORD", "")

# Fallback: accept a pre-set access token
_raw_token = os.getenv("WORKTRACK_TOKEN", "").strip().strip('"').strip("'")
if _raw_token.lower().startswith("bearer "):
    _raw_token = _raw_token[7:].strip()
_INITIAL_TOKEN = _raw_token

# Optional interval override for testing
TEST_INTERVAL_OVERRIDE = None
if os.getenv("WORKTRACK_INTERVAL"):
    try:
        TEST_INTERVAL_OVERRIDE = int(os.getenv("WORKTRACK_INTERVAL"))
    except ValueError:
        pass

# -----------------------------------------------------------------
# Parse CLI flags (override env vars)
# -----------------------------------------------------------------
if "--email" in sys.argv:
    try:
        WORKTRACK_EMAIL = sys.argv[sys.argv.index("--email") + 1].strip()
    except IndexError:
        pass

if "--password" in sys.argv:
    try:
        WORKTRACK_PASSWORD = sys.argv[sys.argv.index("--password") + 1]
    except IndexError:
        pass

if "--token" in sys.argv:
    try:
        t = sys.argv[sys.argv.index("--token") + 1].strip().strip('"').strip("'")
        if t.lower().startswith("bearer "):
            t = t[7:].strip()
        _INITIAL_TOKEN = t
    except IndexError:
        pass

if "--interval" in sys.argv:
    try:
        TEST_INTERVAL_OVERRIDE = int(sys.argv[sys.argv.index("--interval") + 1])
    except (IndexError, ValueError):
        pass

if "--url" in sys.argv:
    try:
        DJANGO_BASE_URL = sys.argv[sys.argv.index("--url") + 1].rstrip("/")
    except IndexError:
        pass

# Endpoints
LOGIN_URL           = f"{DJANGO_BASE_URL}/admin_app/login/"
TOKEN_REFRESH_URL   = f"{DJANGO_BASE_URL}/user_app/token/refresh/"
UPLOAD_URL          = f"{DJANGO_BASE_URL}/user_app/upload-screenshot/"
CURRENT_SESSION_URL = f"{DJANGO_BASE_URL}/user_app/current-session/"
BLOCKED_APPS_URL    = f"{DJANGO_BASE_URL}/user_app/blocked-apps/"
START_APP_URL       = f"{DJANGO_BASE_URL}/user_app/start-application/"
END_APP_URL         = f"{DJANGO_BASE_URL}/user_app/end-application/"
START_WEBSITE_URL   = f"{DJANGO_BASE_URL}/user_app/start-website/"
END_WEBSITE_URL     = f"{DJANGO_BASE_URL}/user_app/end-website/"

# Defaults (overridden by server settings)
DEFAULT_SCREENSHOT_INTERVAL = 300   # 5 minutes
DEFAULT_QUALITY             = 90    # JPEG quality %
BLOCKED_APP_POLL_INTERVAL   = 3     # Check for blocked apps every 3 seconds
SETTINGS_REFRESH_INTERVAL   = 300   # Re-fetch settings every 5 minutes

try:
    USERNAME = os.getlogin()
except Exception:
    USERNAME = os.getenv("USERNAME", "unknown")


# ==========================
# TOKEN STATE  (mutable, thread-safe)
# ==========================

_token_lock    = threading.Lock()
_access_token  = _INITIAL_TOKEN   # updated after login / refresh
_refresh_token = ""               # populated from login response


def _get_access_token() -> str:
    with _token_lock:
        return _access_token


def _set_tokens(access: str, refresh: str = ""):
    global _access_token, _refresh_token
    with _token_lock:
        _access_token = access
        if refresh:
            _refresh_token = refresh


def _is_token_configured() -> bool:
    with _token_lock:
        return bool(_access_token) and _access_token not in ("", "PASTE_USER_JWT_ACCESS_TOKEN_HERE")


# ==========================
# CREDENTIAL-BASED LOGIN
# ==========================

def login_with_credentials() -> bool:
    """
    POST /admin_app/login/ with WORKTRACK_EMAIL + WORKTRACK_PASSWORD.
    Stores the returned access + refresh tokens.
    Returns True on success.
    """
    if not WORKTRACK_EMAIL or not WORKTRACK_PASSWORD:
        return False

    try:
        r = requests.post(
            LOGIN_URL,
            json={"email": WORKTRACK_EMAIL, "password": WORKTRACK_PASSWORD},
            timeout=10,
        )
        if r.status_code == 200:
            data    = r.json()
            access  = data.get("access", "")
            refresh = data.get("refresh", "")
            if access:
                _set_tokens(access, refresh)
                print(f"[AUTH] Logged in successfully as {WORKTRACK_EMAIL}")
                return True
            else:
                print(f"[AUTH] Login response missing 'access' key. Got: {list(data.keys())}")
        else:
            print(f"[AUTH] Login failed: HTTP {r.status_code} - {r.text[:300]}")
    except Exception as e:
        print(f"[AUTH] Login error: {e}")
    return False


# ==========================
# SILENT TOKEN REFRESH
# ==========================

def refresh_access_token() -> bool:
    """
    POST /user_app/token/refresh/ with the stored refresh token.
    Updates _access_token in-place.
    Returns True on success.
    """
    with _token_lock:
        rt = _refresh_token
    if not rt:
        return False
    try:
        r = requests.post(TOKEN_REFRESH_URL, json={"refresh": rt}, timeout=10)
        if r.status_code == 200:
            data        = r.json()
            new_access  = data.get("access", "")
            new_refresh = data.get("refresh", rt)   # rotate when ROTATE_REFRESH_TOKENS=True
            if new_access:
                _set_tokens(new_access, new_refresh)
                print("[AUTH] Access token refreshed silently.")
                return True
        else:
            print(f"[WARN] Token refresh failed: HTTP {r.status_code}")
    except Exception as e:
        print(f"[WARN] Token refresh error: {e}")
    return False


def _handle_401() -> bool:
    """
    Called when any API call returns 401.
    Tries silent refresh first, then full re-login.
    Returns True if we successfully recovered a valid token.
    """
    print("[AUTH] Token expired or rejected - trying silent refresh...")
    if refresh_access_token():
        return True
    print("[AUTH] Refresh failed - re-logging in with credentials...")
    if login_with_credentials():
        return True
    print("[AUTH] Authentication failed. Check WORKTRACK_EMAIL / WORKTRACK_PASSWORD.")
    return False


# ==========================
# SHARED STATE  (thread-safe via lock)
# ==========================

_lock = threading.Lock()
_config = {
    "screenshot_interval":      DEFAULT_SCREENSHOT_INTERVAL,
    "capture_quality":          DEFAULT_QUALITY,
    "screenshot_enabled":       True,
    "screenshot_on_blocked_app": True,
    "blocked_applications":     [],   # list of lowercase app names
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
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type":  "application/json",
    }


# ==========================
# SERVER SETTINGS FETCH
# ==========================

def fetch_settings():
    """Pull monitoring settings + blocked apps from server. Updates _config in-place."""
    if not _is_token_configured():
        return

    try:
        r = requests.get(BLOCKED_APPS_URL, headers=_headers(), timeout=8)

        # On 401: refresh/re-login and retry once
        if r.status_code == 401:
            if _handle_401():
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
                f"[SETTINGS] interval={_config['screenshot_interval']}s | "
                f"quality={_config['capture_quality']}% | "
                f"blocked apps={_config['blocked_applications']}"
            )
        else:
            print(f"[WARN] Settings fetch failed: HTTP {r.status_code}")
    except Exception as e:
        print(f"[WARN] Settings fetch error: {e}")


# ==========================
# SCREENSHOT CAPTURE
# ==========================

def _attach_desktop():
    """Ensure current thread has access to the interactive desktop on Windows."""
    if platform.system() == "Windows":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwinsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
            if hwinsta:
                user32.SetProcessWindowStation(hwinsta)
                hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
                if hdesk:
                    user32.SetThreadDesktop(hdesk)
        except Exception:
            pass


def get_active_foreground_window() -> dict:
    """
    Return the active foreground window title and process name using
    Windows GetForegroundWindow and GetWindowThreadProcessId.
    Always calls _attach_desktop() first to ensure access.
    """
    _attach_desktop()
    info = {"title": "Unknown", "process_name": "Unknown", "pid": 0}
    if platform.system() != "Windows":
        return info

    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return info

        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            info["title"] = buff.value

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        info["pid"] = pid.value

        if PSUTIL_AVAILABLE and pid.value:
            try:
                proc = psutil.Process(pid.value)
                info["process_name"] = proc.name()
            except Exception:
                pass
    except Exception:
        pass

    return info


def _capture_screen(quality: int) -> bytes | None:
    """
    Capture the full physical desktop screen across ALL monitors as JPEG bytes.
    Strictly uses ImageGrab(all_screens=True).
    Does NOT fall back to single-monitor grab to prevent partial captures.
    Returns compressed JPEG bytes, or None if capture fails.
    """
    _attach_desktop()

    if not PIL_AVAILABLE:
        print("[ERROR] Pillow is not available for all_screens desktop capture.")
        return None

    print("[SCREENSHOT] Capture started (all_screens=True)")
    if platform.system() == "Windows":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            monitors = user32.GetSystemMetrics(80)  # SM_CMONITORS
            vw = user32.GetSystemMetrics(78)        # SM_CXVIRTUALSCREEN
            vh = user32.GetSystemMetrics(79)        # SM_CYVIRTUALSCREEN
            print(f"[SCREENSHOT] Monitors detected: {monitors} | Virtual desktop: {vw}x{vh}")
        except Exception:
            pass

    img = None
    # Retry up to 2 times on transient error
    for attempt in range(1, 3):
        try:
            img = ImageGrab.grab(all_screens=True)
            if img is not None:
                break
        except Exception as e:
            print(f"[WARN] ImageGrab(all_screens=True) attempt {attempt} failed: {e}")
            time.sleep(0.5)

    if img is None:
        print("[ERROR] Screen capture failed: could not grab full desktop across all screens.")
        return None

    print(f"[SCREENSHOT] Captured resolution: {img.width}x{img.height} (Mode: {img.mode})")

    # Convert to RGB (drop alpha channel if any)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, subsampling=0)
    jpeg_bytes = buf.getvalue()
    size_kb = len(jpeg_bytes) / 1024
    print(f"[SCREENSHOT] JPEG compressed size: {size_kb:.1f} KB")
    print("[SCREENSHOT] Capture successful")
    return jpeg_bytes


def send_screenshot(reason: str) -> bool:
    """
    Capture and upload a screenshot.
    Returns True if successfully captured AND uploaded AND backend returned HTTP 201.
    Returns False otherwise.
    """
    if not _is_token_configured():
        print("[WARN] JWT token not configured.")
        return False

    with _lock:
        quality = _config["capture_quality"]

    try:
        image_bytes = _capture_screen(quality)
        if image_bytes is None:
            return False

        encoded = base64.b64encode(image_bytes).decode("utf-8")
        payload = {"image": encoded, "reason": reason}

        print(f"[SCREENSHOT] Uploading ({reason})...")
        r = requests.post(UPLOAD_URL, json=payload, headers=_headers(), timeout=30)

        # On 401: refresh/re-login and retry the upload once
        if r.status_code == 401:
            if _handle_401():
                r = requests.post(UPLOAD_URL, json=payload, headers=_headers(), timeout=30)

        ts = datetime.now().strftime("%H:%M:%S")

        if r.status_code == 201:
            resp_json = r.json()
            data = resp_json.get("data", {})
            screenshot_id = data.get("id", "N/A")
            cloudinary_url = data.get("image", "N/A")
            size_kb = len(image_bytes) / 1024
            print(f"[SCREENSHOT] HTTP 201")
            print(f"[SCREENSHOT] Screenshot ID: {screenshot_id}")
            print(f"[SCREENSHOT] Cloudinary URL: {cloudinary_url}")
            print(f"[SCREENSHOT] [{ts}] Upload successful ({reason}) - {size_kb:.0f} KB")
            return True
        elif r.status_code == 401:
            print("[SCREENSHOT] Upload failed")
            print("[SCREENSHOT] HTTP: 401")
            print("[AUTH] JWT token expired or invalid - could not re-authenticate.")
            return False
        elif r.status_code == 403:
            print("[SCREENSHOT] Upload failed")
            print("[SCREENSHOT] HTTP: 403")
            print("[AUTH] No permission to upload screenshots.")
            return False
        elif r.status_code == 400:
            print("[SCREENSHOT] Upload failed")
            print("[SCREENSHOT] HTTP: 400")
            print(f"[SCREENSHOT] Response: {r.text[:300]}")
            return False
        else:
            print("[SCREENSHOT] Upload failed")
            print(f"[SCREENSHOT] HTTP: {r.status_code}")
            print(f"[SCREENSHOT] Response: {r.text[:300]}")
            return False

    except requests.exceptions.Timeout:
        print("[SCREENSHOT] Upload timed out.")
        return False
    except requests.exceptions.RequestException as e:
        print(f"[SCREENSHOT] Network error: {e}")
        return False
    except Exception as e:
        print(f"[SCREENSHOT] Screenshot error: {e}")
        return False


# ==========================
# ACTIVE APPLICATION & WEBSITE TRACKING
# ==========================

import re

BROWSER_PROCESSES = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "brave.exe": "Brave Browser",
    "opera.exe": "Opera",
    "vivaldi.exe": "Vivaldi",
    "iexplore.exe": "Internet Explorer",
}

DOMAIN_REGEX = re.compile(
    r'\b([a-zA-Z0-9][-a-zA-Z0-9]*\.(?:com|org|net|edu|gov|io|co|in|ai|app|dev|me|info|tv|local))\b',
    re.IGNORECASE
)

_tracking_lock = threading.Lock()
_active_app_state = {"process_name": "", "window_title": ""}
_active_web_state = {"browser_name": "", "website": "", "page_title": ""}


def parse_browser_and_website(proc_name: str, window_title: str) -> tuple:
    """
    If the active process is a web browser, return (browser_name, website_domain, clean_page_title).
    Otherwise return (None, None, window_title).
    """
    p_lower = proc_name.lower().strip()
    if p_lower not in BROWSER_PROCESSES:
        return (None, None, window_title)

    browser_name = BROWSER_PROCESSES[p_lower]

    clean_title = window_title
    for suffix in [
        f" - {browser_name}",
        " - Google Chrome",
        " - Personal - Microsoft Edge",
        " - Personal - Microsoft​ Edge",
        " - Microsoft​ Edge",
        " - Microsoft Edge",
        " — Mozilla Firefox",
        " - Mozilla Firefox",
        " - Brave",
        " - Opera",
    ]:
        if clean_title.endswith(suffix):
            clean_title = clean_title[:-len(suffix)].strip()
            break

    t_lower = clean_title.lower()
    domain = None

    if "youtube" in t_lower:
        domain = "youtube.com"
    elif "google search" in t_lower or t_lower == "google":
        domain = "google.com"
    elif "whatsapp" in t_lower:
        domain = "whatsapp.com"
    elif "github" in t_lower:
        domain = "github.com"
    elif "facebook" in t_lower:
        domain = "facebook.com"
    elif "instagram" in t_lower:
        domain = "instagram.com"
    elif "linkedin" in t_lower:
        domain = "linkedin.com"
    elif "twitter" in t_lower or t_lower.endswith(" / x") or " - x" in t_lower:
        domain = "x.com"
    elif "reddit" in t_lower:
        domain = "reddit.com"
    elif "netflix" in t_lower:
        domain = "netflix.com"
    elif "gmail" in t_lower:
        domain = "mail.google.com"
    elif "slack" in t_lower:
        domain = "slack.com"
    elif "work track" in t_lower or "worktrack" in t_lower:
        domain = "worktrackmanagemnet.netlify.app"
    else:
        match = DOMAIN_REGEX.search(clean_title)
        if match:
            domain = match.group(1).lower()

    if not domain and clean_title and clean_title.lower() != "new tab":
        domain = "web-browsing"

    return (browser_name, domain, clean_title)


def send_active_application(process_name: str, window_title: str):
    """Notify backend of active foreground desktop application."""
    global _active_app_state
    if not _is_token_configured() or not process_name or process_name == "Unknown":
        return

    with _tracking_lock:
        if (
            _active_app_state["process_name"] == process_name
            and _active_app_state["window_title"] == window_title
        ):
            return

    try:
        payload = {"application_name": process_name, "window_title": window_title}
        r = requests.post(START_APP_URL, json=payload, headers=_headers(), timeout=5)
        if r.status_code == 401 and _handle_401():
            r = requests.post(START_APP_URL, json=payload, headers=_headers(), timeout=5)

        if r.status_code in (200, 201):
            with _tracking_lock:
                _active_app_state["process_name"] = process_name
                _active_app_state["window_title"] = window_title
            print(f"[APP] Active Application: {process_name} | Window: '{window_title[:50]}'")
    except Exception as e:
        print(f"[APP] Application tracking error: {e}")


def send_active_website(browser_name: str, website: str, page_title: str):
    """Notify backend of active website / domain viewed in browser."""
    global _active_web_state
    if not _is_token_configured() or not website:
        return

    with _tracking_lock:
        if (
            _active_web_state["browser_name"] == browser_name
            and _active_web_state["website"] == website
            and _active_web_state["page_title"] == page_title
        ):
            return

    try:
        payload = {
            "browser_name": browser_name,
            "website": website,
            "page_title": page_title
        }
        r = requests.post(START_WEBSITE_URL, json=payload, headers=_headers(), timeout=5)
        if r.status_code == 401 and _handle_401():
            r = requests.post(START_WEBSITE_URL, json=payload, headers=_headers(), timeout=5)

        if r.status_code in (200, 201):
            with _tracking_lock:
                _active_web_state["browser_name"] = browser_name
                _active_web_state["website"] = website
                _active_web_state["page_title"] = page_title
            print(f"[WEB] Active Website: {website} ({browser_name}) | Page: '{page_title[:45]}'")
    except Exception as e:
        print(f"[WEB] Website tracking error: {e}")


def close_active_website():
    """Close active website tracking when leaving browser."""
    global _active_web_state
    with _tracking_lock:
        if not _active_web_state["website"]:
            return
        _active_web_state = {"browser_name": "", "website": "", "page_title": ""}
    try:
        requests.post(END_WEBSITE_URL, headers=_headers(), timeout=5)
    except Exception:
        pass


def close_all_tracking_sessions():
    """Close both application and website tracking sessions on clock out."""
    global _active_app_state, _active_web_state
    with _tracking_lock:
        had_web = bool(_active_web_state["website"])
        had_app = bool(_active_app_state["process_name"])
        _active_web_state = {"browser_name": "", "website": "", "page_title": ""}
        _active_app_state = {"process_name": "", "window_title": ""}

    if had_web:
        try:
            requests.post(END_WEBSITE_URL, headers=_headers(), timeout=5)
        except Exception:
            pass

    if had_app:
        try:
            requests.post(END_APP_URL, headers=_headers(), timeout=5)
        except Exception:
            pass


# ==========================
# SESSION CHECK
# ==========================

def is_clocked_in() -> bool:
    if not _is_token_configured():
        return False
    try:
        r = requests.get(CURRENT_SESSION_URL, headers=_headers(), timeout=5)
        if r.status_code == 401:
            if _handle_401():
                r = requests.get(CURRENT_SESSION_URL, headers=_headers(), timeout=5)
        if r.status_code == 200:
            return r.json().get("clocked_in", False)
    except Exception as e:
        print(f"[ERROR] Session check error: {e}")
    return False


# ==========================
# RUNNING PROCESS DETECTOR
# ==========================

def get_running_process_names() -> set:
    """Return a set of lowercase process names currently running."""
    if not PSUTIL_AVAILABLE:
        return set()
    names = set()
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info["name"]
                if name:
                    clean = name.lower().removesuffix(".exe")
                    names.add(clean)
                    names.add(name.lower())
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
    print("[INFO] Blocked app watcher started")

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
                matched = (
                    blocked_lower in running
                    or blocked_lower + ".exe" in running
                    or blocked_lower.removesuffix(".exe") in running
                )

                if matched:
                    last_shot = _blocked_app_cooldowns.get(blocked_lower, 0)
                    if now - last_shot >= BLOCKED_APP_COOLDOWN_SEC:
                        print(f"[BLOCKED] App detected: '{blocked}' - capturing immediate screenshot!")
                        _blocked_app_cooldowns[blocked_lower] = now
                        send_screenshot("blocked_app")
                    else:
                        remaining = int(BLOCKED_APP_COOLDOWN_SEC - (now - last_shot))
                        print(f"[BLOCKED] '{blocked}' cooldown: {remaining}s remaining")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[WARN] Watcher error: {e}")


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
            print(f"[WARN] Settings refresh error: {e}")


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

    # Step 1: Authenticate
    if WORKTRACK_EMAIL and WORKTRACK_PASSWORD:
        if not login_with_credentials():
            print("[ERROR] Could not login. Check your email and password.")
            print(f"  Email used: {WORKTRACK_EMAIL}")
            print(f"  Login URL : {LOGIN_URL}")
            sys.exit(1)
    elif _is_token_configured():
        print(f"[AUTH] Using pre-set JWT token (WORKTRACK_TOKEN)")
    else:
        print()
        print("[ERROR] No authentication provided!")
        print("  Set WORKTRACK_EMAIL and WORKTRACK_PASSWORD env vars for auto-login, OR")
        print("  set WORKTRACK_TOKEN to a valid JWT access token.")
        print()
        print("  Example:")
        print("    set WORKTRACK_EMAIL=you@example.com")
        print("    set WORKTRACK_PASSWORD=yourpassword")
        print("    python work_track_admin\\monitor.py")
        sys.exit(1)

    if not PIL_AVAILABLE:
        print("[ERROR] Pillow is required for screenshot capture.")
        print("  Install with: pip install Pillow")
        sys.exit(1)

    if not PSUTIL_AVAILABLE:
        print("[WARN] psutil not found - blocked app detection disabled.")
        print("  Install with: pip install psutil")

    if TEST_INTERVAL_OVERRIDE is not None:
        print(f"[INFO] Test mode: screenshot interval overridden to {TEST_INTERVAL_OVERRIDE}s")

    # Initial settings fetch
    fetch_settings()

    # Start background threads
    watcher_thread = threading.Thread(target=blocked_app_watcher, daemon=True)
    watcher_thread.start()

    refresher_thread = threading.Thread(target=settings_refresher, daemon=True)
    refresher_thread.start()

    previous_state       = None
    last_screenshot_time = 0.0   # epoch time of last successful screenshot

    print("\n[OK] Agent running. Press Ctrl+C to stop.\n")

    while True:
        try:
            current_state = is_clocked_in()

            # State-change banner
            if current_state != previous_state:
                if current_state:
                    print("[INFO] Employee clocked IN - full-desktop monitoring active")
                    print("       Screenshots, active applications, and websites are tracked.")
                    print("       Monitoring continues across all Windows applications and screens.\n")
                    # Immediate physical screenshot upon Clock In
                    print("[SCREENSHOT] Triggering immediate desktop capture on Clock In...")
                    if send_screenshot("clock-in"):
                        last_screenshot_time = time.time()
                    else:
                        last_screenshot_time = 0.0  # retry on next loop
                else:
                    print("[INFO] Employee clocked OUT - desktop monitoring stopped (checking every 5 s)\n")
                    close_all_tracking_sessions()
                previous_state = current_state

            # When clocked IN
            if current_state:
                # 1. Track active foreground application & website in real-time
                fg = get_active_foreground_window()
                proc = fg.get("process_name", "")
                title = fg.get("title", "")

                if proc and proc != "Unknown":
                    send_active_application(proc, title)

                    browser, domain, clean_title = parse_browser_and_website(proc, title)
                    if browser and domain:
                        send_active_website(browser, domain, clean_title)
                    else:
                        close_active_website()

                # 2. Check screenshot capture schedule
                with _lock:
                    enabled  = _config["screenshot_enabled"]
                    interval = _config["screenshot_interval"]

                if TEST_INTERVAL_OVERRIDE is not None:
                    interval = TEST_INTERVAL_OVERRIDE

                now = time.time()
                due_for_screenshot = (now - last_screenshot_time) >= interval

                if enabled and due_for_screenshot:
                    if send_screenshot("periodic"):
                        last_screenshot_time = time.time()
                    else:
                        print("[SCREENSHOT] Upload failed - will retry on next cycle")

                elif not enabled:
                    print("[INFO] Screenshot capture is disabled in settings.")

            # Responsive polling interval (3 seconds for accurate app/website tracking)
            time.sleep(3)

        except KeyboardInterrupt:
            print("\n[STOP] Agent stopped by user.")
            close_all_tracking_sessions()
            break
        except Exception as e:
            print(f"[WARN] Main loop error: {e}")
            time.sleep(3)


# ==========================
# ENTRY POINT
# ==========================

if __name__ == "__main__":
    screenshot_loop()

