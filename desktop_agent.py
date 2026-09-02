"""
WorkTrack Desktop Monitoring Agent
===================================
Real-time cross-platform client monitoring agent.
Tracks:
  - Active desktop applications (VS Code, Excel, Slack, Figma, etc.)
  - Active browser websites & tab titles across all browsers (Chrome, Edge, Firefox, Brave, Opera, etc.)
  - Full-screen desktop screenshot captures (single & multi-monitor)
  - Prohibited / blocked application detection with instant alert screenshots
  - Automated JWT authentication & background session synchronization with WorkTrack Web App
"""

import os
import re
import sys
import time
import json
import base64
import getpass
import platform
import argparse
import threading
from io import BytesIO
from datetime import datetime

import requests

# ── Desktop capture libraries ──
try:
    from PIL import Image, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ── Windows specific native API (ctypes) ──
IS_WINDOWS = platform.system().lower() == "windows"
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

# ==========================
# CONFIGURATION & CONSTANTS
# ==========================

DEFAULT_BASE_URL = "https://work-track-management-backend-g5cu.onrender.com"
SESSION_FILE = os.path.join(os.path.expanduser("~"), ".worktrack_agent_session.json")

DEFAULT_SCREENSHOT_INTERVAL = 300  # 5 minutes
DEFAULT_QUALITY = 85
BLOCKED_APP_POLL_INTERVAL = 3
SETTINGS_REFRESH_INTERVAL = 180    # 3 minutes

# Known browsers executable names mapping
BROWSER_PROCESSES = {
    "chrome.exe": "Google Chrome",
    "chrome": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "msedge": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "firefox": "Mozilla Firefox",
    "brave.exe": "Brave Browser",
    "brave": "Brave Browser",
    "opera.exe": "Opera",
    "opera": "Opera",
    "vivaldi.exe": "Vivaldi",
    "vivaldi": "Vivaldi",
    "arc.exe": "Arc Browser",
    "arc": "Arc Browser",
    "safari": "Apple Safari",
}

# Known friendly application names mapping
FRIENDLY_APP_NAMES = {
    "code.exe": "Visual Studio Code",
    "code": "Visual Studio Code",
    "devenv.exe": "Visual Studio",
    "devenv": "Visual Studio",
    "slack.exe": "Slack",
    "slack": "Slack",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "discord.exe": "Discord",
    "discord": "Discord",
    "excel.exe": "Microsoft Excel",
    "winword.exe": "Microsoft Word",
    "powerpnt.exe": "Microsoft PowerPoint",
    "notepad.exe": "Notepad",
    "notepad++.exe": "Notepad++",
    "postman.exe": "Postman",
    "figma.exe": "Figma",
    "spotify.exe": "Spotify",
    "zoom.exe": "Zoom",
    "telegram.exe": "Telegram",
    "whatsapp.exe": "WhatsApp",
    "windowsterminal.exe": "Windows Terminal",
    "powershell.exe": "PowerShell",
    "cmd.exe": "Command Prompt",
    "pycharm64.exe": "PyCharm",
    "webstorm64.exe": "WebStorm",
    "dbeaver.exe": "DBeaver",
    "pgadmin4.exe": "pgAdmin",
    "git-kraken.exe": "GitKraken",
    "sourcetree.exe": "SourceTree",
}

# Common TLDs for URL domain heuristic extraction
TLD_REGEX = re.compile(
    r"\b([a-zA-Z0-9][-a-zA-Z0-9]*\.(?:com|org|net|edu|gov|io|app|dev|ai|in|co|uk|de|me|so|tech|xyz|ca|au|fr|info|biz|tv|cc))\b",
    re.IGNORECASE
)


class WorkTrackAgent:
    def __init__(self, base_url: str = None):
        self.base_url = (base_url or os.getenv("WORKTRACK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.access_token = os.getenv("WORKTRACK_TOKEN", "")
        self.refresh_token = ""
        self.user_info = {}
        self.lock = threading.Lock()

        # Monitoring settings (synced from server)
        self.config = {
            "screenshot_interval": DEFAULT_SCREENSHOT_INTERVAL,
            "capture_quality": DEFAULT_QUALITY,
            "screenshot_enabled": True,
            "screenshot_on_blocked_app": True,
            "blocked_applications": [],
        }

        # State tracking
        self.current_app_name = ""
        self.current_window_title = ""
        self.current_website = ""
        self.current_page_title = ""
        self.last_app_ping = 0
        self.last_website_ping = 0
        self.last_screenshot_time = 0
        self.blocked_app_cooldowns = {}
        self.is_running = True

    # ==========================
    # AUTHENTICATION
    # ==========================

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def load_session(self) -> bool:
        """Load cached tokens from local session file."""
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token", "")
                    self.refresh_token = data.get("refresh_token", "")
                    self.user_info = data.get("user", {})
                    base = data.get("base_url")
                    if base:
                        self.base_url = base
                    if self.access_token:
                        return True
            except Exception as e:
                print(f"⚠️  Could not read session cache: {e}")
        return False

    def save_session(self):
        """Save tokens and user info to local session file."""
        try:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "user": self.user_info,
                    "base_url": self.base_url,
                    "saved_at": datetime.now().isoformat(),
                }, f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save session cache: {e}")

    def refresh_access_token(self) -> bool:
        """Silently refresh expired access token using refresh token."""
        if not self.refresh_token:
            return False
        try:
            url = f"{self.base_url}/api/token/refresh/"
            r = requests.post(url, json={"refresh": self.refresh_token}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                self.access_token = data.get("access")
                if data.get("refresh"):
                    self.refresh_token = data.get("refresh")
                self.save_session()
                print("🔄 JWT access token refreshed successfully.")
                return True
        except Exception as e:
            print(f"⚠️  Token refresh failed: {e}")
        return False

    def login(self, email: str = None, password: str = None) -> bool:
        """Authenticate with WorkTrack credentials."""
        if not email or not password:
            print("\n" + "=" * 50)
            print("  🔐 WorkTrack Desktop Agent — Employee Login")
            print("=" * 50)
            email = input("Email: ").strip()
            password = getpass.getpass("Password: ").strip()

        if not email or not password:
            print("❌ Email and password are required.")
            return False

        try:
            url = f"{self.base_url}/admin_app/login/"
            r = requests.post(url, json={"email": email, "password": password}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                self.user_info = data.get("user", {})
                self.access_token = data.get("access") or data.get("token") or ""
                self.refresh_token = data.get("refresh") or ""

                if not self.access_token:
                    # Request direct SimpleJWT pair
                    tok_res = requests.post(f"{self.base_url}/api/token/", json={"username": email, "password": password}, timeout=10)
                    if tok_res.status_code == 200:
                        td = tok_res.json()
                        self.access_token = td.get("access", "")
                        self.refresh_token = td.get("refresh", "")

                if self.access_token:
                    self.save_session()
                    name = self.user_info.get("first_name", email)
                    print(f"✅ Logged in successfully as {name}!")
                    return True
                else:
                    print("⚠️  Login succeeded but access token was not found in response.")
            else:
                print(f"❌ Login failed ({r.status_code}): {r.text[:200]}")
        except Exception as e:
            print(f"❌ Login error: {e}")

        return False

    def authenticate_or_prompt(self) -> bool:
        """Authenticate using cached session, env token, or prompt."""
        if self.access_token:
            if self.verify_token():
                return True
            if self.refresh_access_token():
                return True

        if self.load_session():
            if self.verify_token():
                return True
            if self.refresh_access_token():
                return True

        return self.login()

    def verify_token(self) -> bool:
        """Check if current access token is valid."""
        try:
            url = f"{self.base_url}/user_app/current-session/"
            r = requests.get(url, headers=self._headers(), timeout=6)
            return r.status_code == 200
        except Exception:
            return False

    # ==========================
    # SERVER SETTINGS & SYNC
    # ==========================

    def fetch_settings(self):
        """Fetch company monitoring settings and blocked applications."""
        try:
            url = f"{self.base_url}/user_app/blocked-apps/"
            r = requests.get(url, headers=self._headers(), timeout=8)
            if r.status_code == 200:
                data = r.json()
                with self.lock:
                    self.config["screenshot_interval"] = int(data.get("screenshot_interval", DEFAULT_SCREENSHOT_INTERVAL))
                    self.config["capture_quality"] = int(data.get("capture_quality", DEFAULT_QUALITY))
                    self.config["screenshot_enabled"] = bool(data.get("screenshot_enabled", True))
                    self.config["screenshot_on_blocked_app"] = bool(data.get("screenshot_on_blocked_app", True))
                    raw_apps = data.get("blocked_applications", [])
                    self.config["blocked_applications"] = [a.lower().strip() for a in raw_apps if a.strip()]
            elif r.status_code == 401:
                self.refresh_access_token()
        except Exception as e:
            print(f"⚠️  Settings fetch error: {e}")

    def get_session_status(self) -> tuple[bool, bool]:
        """Return (is_clocked_in, is_on_break)."""
        try:
            url = f"{self.base_url}/user_app/current-session/"
            r = requests.get(url, headers=self._headers(), timeout=6)
            if r.status_code == 200:
                data = r.json()
                return bool(data.get("clocked_in", False)), bool(data.get("is_on_break", False))
            elif r.status_code == 401:
                if self.refresh_access_token():
                    return self.get_session_status()
        except Exception as e:
            print(f"⚠️  Session check error: {e}")
        return False, False

    # ==========================
    # DESKTOP ACTIVE WINDOW & PROCESS TRACKING
    # ==========================

    def get_active_window_info(self) -> tuple[str, str, str, str]:
        """
        Identify active foreground window and process.
        Returns: (app_name, window_title, browser_name_or_empty, detected_website_or_empty)
        """
        app_name = "Desktop"
        window_title = ""
        browser_name = ""
        website = ""

        if IS_WINDOWS:
            try:
                hwnd = user32.GetForegroundWindow()
                if hwnd:
                    # 1. Get window title
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        window_title = buf.value.strip()

                    # 2. Get process executable name
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value and PSUTIL_AVAILABLE:
                        try:
                            proc = psutil.Process(pid.value)
                            raw_exe = proc.name().lower()
                            app_name = FRIENDLY_APP_NAMES.get(raw_exe, proc.name().removesuffix(".exe").title())

                            # Check if it's a browser
                            if raw_exe in BROWSER_PROCESSES:
                                browser_name = BROWSER_PROCESSES[raw_exe]
                                app_name = browser_name
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
            except Exception:
                pass
        else:
            # macOS / Linux fallback with psutil
            if PSUTIL_AVAILABLE:
                try:
                    for proc in psutil.process_iter(["name", "cpu_percent"]):
                        try:
                            name = proc.info["name"]
                            if name and name.lower() not in ["system", "idle", "launchd"]:
                                app_name = name
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

        # 3. If active app is a browser, extract website domain and page title from window title
        if browser_name and window_title:
            website, page_title = self._parse_browser_title(browser_name, window_title)
        else:
            page_title = window_title

        return app_name, window_title, browser_name, website

    def _parse_browser_title(self, browser_name: str, raw_title: str) -> tuple[str, str]:
        """Extract clean website hostname and page title from browser window title."""
        cleaned = raw_title
        suffixes = [
            f" - {browser_name}",
            " - Google Chrome",
            " - Microsoft Edge",
            " - Mozilla Firefox",
            " - Brave",
            " - Opera",
            " - Vivaldi",
            " — Mozilla Firefox",
        ]
        for s in suffixes:
            if cleaned.endswith(s):
                cleaned = cleaned[:-len(s)].strip()

        # Heuristic 1: Extract domain using TLD regex
        tld_match = TLD_REGEX.search(cleaned)
        if tld_match:
            domain = tld_match.group(1).lower()
            return domain, cleaned

        # Heuristic 2: Known brand keywords in title
        title_lower = cleaned.lower()
        known_sites = {
            "github": "github.com",
            "youtube": "youtube.com",
            "google search": "google.com",
            "google": "google.com",
            "gmail": "mail.google.com",
            "stackoverflow": "stackoverflow.com",
            "stack overflow": "stackoverflow.com",
            "linkedin": "linkedin.com",
            "reddit": "reddit.com",
            "twitter": "x.com",
            "notion": "notion.so",
            "figma": "figma.com",
            "slack": "slack.com",
            "trello": "trello.com",
            "jira": "atlassian.net",
            "work track": "worktrackmanagemnet.netlify.app",
            "worktrack": "worktrackmanagemnet.netlify.app",
            "chatgpt": "chatgpt.com",
            "claude": "claude.ai",
            "netflix": "netflix.com",
            "amazon": "amazon.com",
            "facebook": "facebook.com",
            "instagram": "instagram.com",
            "whatsapp": "web.whatsapp.com",
        }
        for keyword, domain in known_sites.items():
            if keyword in title_lower:
                return domain, cleaned

        # Heuristic 3: Check for separator like " | " or " - " (e.g., "Title - SiteName")
        if " - " in cleaned:
            parts = cleaned.rsplit(" - ", 1)
            site_candidate = parts[-1].strip().lower().replace(" ", "") + ".com"
            return site_candidate, cleaned
        if " | " in cleaned:
            parts = cleaned.rsplit(" | ", 1)
            site_candidate = parts[-1].strip().lower().replace(" ", "") + ".com"
            return site_candidate, cleaned

        return "web-browsing", cleaned

    def log_application_activity(self, app_name: str, window_title: str):
        """Send active application usage to backend API."""
        if not app_name:
            return
        now = time.time()
        # Log if app changed OR every 60s as heartbeat
        if app_name == self.current_app_name and (now - self.last_app_ping) < 60:
            return

        try:
            url = f"{self.base_url}/user_app/start-application/"
            payload = {
                "application_name": app_name,
                "window_title": window_title or app_name,
            }
            r = requests.post(url, json=payload, headers=self._headers(), timeout=6)
            if r.status_code in [200, 201]:
                self.current_app_name = app_name
                self.current_window_title = window_title
                self.last_app_ping = now
            elif r.status_code == 401:
                self.refresh_access_token()
        except Exception:
            pass

    def log_website_activity(self, browser_name: str, website: str, page_title: str):
        """Send active website usage to backend API."""
        if not website:
            return
        now = time.time()
        # Log if website changed OR every 60s as heartbeat
        if website == self.current_website and (now - self.last_website_ping) < 60:
            return

        try:
            url = f"{self.base_url}/user_app/start-website/"
            payload = {
                "browser_name": browser_name or "Web Browser",
                "website": website,
                "page_title": page_title or website,
            }
            r = requests.post(url, json=payload, headers=self._headers(), timeout=6)
            if r.status_code in [200, 201]:
                self.current_website = website
                self.current_page_title = page_title
                self.last_website_ping = now
            elif r.status_code == 401:
                self.refresh_access_token()
        except Exception:
            pass

    # ==========================
    # DESKTOP SCREENSHOT CAPTURE & UPLOAD
    # ==========================

    def _grab_windows_gdi(self) -> Image.Image | None:
        """High-performance Windows GDI multi-monitor capture."""
        if not (IS_WINDOWS and PIL_AVAILABLE):
            return None
        try:
            user32.SetProcessDPIAware()
            # Virtual screen metrics (captures multi-monitor bounds)
            x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
            y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
            w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
            h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
            if w <= 0 or h <= 0:
                x, y = 0, 0
                w = user32.GetSystemMetrics(0)
                h = user32.GetSystemMetrics(1)

            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
            gdi32.SelectObject(hdc_mem, hbm)

            # 0x00CC0020 is standard SRCCOPY (reliable across all Windows environments)
            gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, 0x00CC0020)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', wintypes.DWORD),
                    ('biWidth', wintypes.LONG),
                    ('biHeight', wintypes.LONG),
                    ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD),
                    ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD),
                    ('biXPelsPerMeter', wintypes.LONG),
                    ('biYPelsPerMeter', wintypes.LONG),
                    ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h  # top-down bitmap
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0

            buffer = ctypes.create_string_buffer(w * h * 4)
            lines = gdi32.GetDIBits(hdc_mem, hbm, 0, h, buffer, ctypes.byref(bmi), 0)

            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)

            if lines > 0:
                img = Image.frombuffer('RGBA', (w, h), buffer, 'raw', 'BGRA', 0, 1)
                return img.convert('RGB')
        except Exception:
            pass
        return None

    def capture_screen_bytes(self, quality: int) -> bytes | None:
        """Capture entire desktop screen as JPEG bytes."""
        img = None

        # 1. Native Windows GDI capture (fastest & most reliable on Windows)
        if IS_WINDOWS:
            img = self._grab_windows_gdi()

        # 2. Pillow ImageGrab fallback
        if img is None and PIL_AVAILABLE:
            try:
                img = ImageGrab.grab(all_screens=True)
            except Exception:
                try:
                    img = ImageGrab.grab()
                except Exception:
                    pass

        # 3. MSS multi-screen capture fallback
        if img is None and MSS_AVAILABLE:
            try:
                with mss.mss() as sct:
                    monitor = sct.monitors[0]
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except Exception:
                pass

        # 4. PyAutoGUI fallback
        if img is None and PYAUTOGUI_AVAILABLE:
            try:
                img = pyautogui.screenshot()
            except Exception:
                pass

        if img is None:
            return None

        # Convert to RGB if RGBA/P
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Compress to JPEG
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    def send_screenshot(self, reason: str = "periodic") -> bool:
        """Capture full-screen desktop and upload to WorkTrack Cloudinary backend."""
        with self.lock:
            quality = self.config["capture_quality"]
            enabled = self.config["screenshot_enabled"]

        if not enabled and reason == "periodic":
            return False

        try:
            image_bytes = self.capture_screen_bytes(quality)
            if not image_bytes:
                print("❌ Screenshot capture failed (no display grab available).")
                return False

            encoded = base64.b64encode(image_bytes).decode("utf-8")
            payload = {
                "image": f"data:image/jpeg;base64,{encoded}",
                "captured_at": datetime.now().isoformat(),
                "reason": reason,
            }

            url = f"{self.base_url}/user_app/upload-screenshot/"
            r = requests.post(url, json=payload, headers=self._headers(), timeout=30)
            now_str = datetime.now().strftime("%H:%M:%S")

            if r.status_code in [200, 201]:
                size_kb = len(image_bytes) / 1024
                print(f"📸 [{now_str}] Desktop Screenshot captured & uploaded ({reason}) — {size_kb:.0f} KB")
                self.last_screenshot_time = time.time()
                return True
            elif r.status_code == 401:
                if self.refresh_access_token():
                    return self.send_screenshot(reason)
            else:
                print(f"⚠️  Screenshot upload response ({r.status_code}): {r.text[:150]}")
        except Exception as e:
            print(f"⚠️  Screenshot upload error: {e}")

        return False

    # ==========================
    # BLOCKED APPLICATION WATCHER
    # ==========================

    def get_running_process_names(self) -> set[str]:
        """Return set of clean running process names."""
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

    def blocked_app_watcher_loop(self):
        """Background thread checking for prohibited applications."""
        while self.is_running:
            try:
                time.sleep(BLOCKED_APP_POLL_INTERVAL)

                with self.lock:
                    blocked_list = list(self.config["blocked_applications"])
                    take_ss = self.config["screenshot_on_blocked_app"]

                if not blocked_list or not take_ss:
                    continue

                running = self.get_running_process_names()
                now = time.time()

                for blocked in blocked_list:
                    blocked_lower = blocked.lower().strip()
                    matched = (
                        blocked_lower in running
                        or f"{blocked_lower}.exe" in running
                        or blocked_lower.removesuffix(".exe") in running
                    )

                    if matched:
                        last_alert = self.blocked_app_cooldowns.get(blocked_lower, 0)
                        if (now - last_alert) >= 300:  # 5 min cooldown per app
                            print(f"\n🚨 PROHIBITED APP DETECTED: '{blocked}' — capturing immediate alert screenshot!")
                            self.blocked_app_cooldowns[blocked_lower] = now
                            self.send_screenshot("blocked_app")
            except Exception:
                pass

    def settings_refresher_loop(self):
        """Background thread refreshing monitoring settings every 3 minutes."""
        while self.is_running:
            time.sleep(SETTINGS_REFRESH_INTERVAL)
            try:
                self.fetch_settings()
            except Exception:
                pass

    # ==========================
    # MAIN AGENT LOOP
    # ==========================

    def run(self):
        print("=" * 60)
        print("  🚀 WorkTrack Desktop Monitoring Agent")
        print(f"  🌐 Backend : {self.base_url}")
        print(f"  💻 Host    : {platform.node()} ({platform.system()} {platform.release()})")
        print("=" * 60)

        if not self.authenticate_or_prompt():
            print("❌ Authentication failed. Exiting.")
            return

        # Fetch initial server config
        self.fetch_settings()

        # Start background threads
        threading.Thread(target=self.blocked_app_watcher_loop, daemon=True).start()
        threading.Thread(target=self.settings_refresher_loop, daemon=True).start()

        print("\n✅ Desktop Agent is ACTIVE.")
        print("   Tracking active windows, applications, browser websites, and screenshots.")
        print("   Press Ctrl+C to pause or stop.\n")

        last_state = None

        while self.is_running:
            try:
                clocked_in, on_break = self.get_session_status()
                current_state = (clocked_in, on_break)

                # State change notification
                if current_state != last_state:
                    if clocked_in and not on_break:
                        print("🟢 Employee CLOCKED IN — Live tracking & screenshots active")
                    elif clocked_in and on_break:
                        print("⏸️  Employee ON BREAK — Tracking paused")
                    else:
                        print("⚪ Employee CLOCKED OUT — Waiting for clock in from Web App...")
                    last_state = current_state

                # If actively working
                if clocked_in and not on_break:
                    # 1. Track active application & browser website
                    app_name, window_title, browser_name, website = self.get_active_window_info()

                    if app_name:
                        self.log_application_activity(app_name, window_title)

                    if browser_name and website:
                        self.log_website_activity(browser_name, website, window_title)

                    # 2. Check periodic screenshot timer
                    with self.lock:
                        interval = self.config["screenshot_interval"]
                        enabled = self.config["screenshot_enabled"]

                    now = time.time()
                    if enabled and (now - self.last_screenshot_time) >= interval:
                        self.send_screenshot("periodic")

                    time.sleep(2)  # Fast 2s sampling for active window switches
                else:
                    time.sleep(5)  # Relaxed polling when clocked out or on break

            except KeyboardInterrupt:
                print("\n🛑 Agent stopped by user.")
                self.is_running = False
                break
            except Exception as e:
                print(f"⚠️  Agent loop error: {e}")
                time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="WorkTrack Desktop Monitoring Agent")
    parser.add_argument("--url", help="Backend URL (default: Render production URL)", default=None)
    parser.add_argument("--email", help="Employee login email", default=None)
    parser.add_argument("--password", help="Employee login password", default=None)
    parser.add_argument("--token", help="Direct JWT Access Token", default=None)
    args = parser.parse_args()

    agent = WorkTrackAgent(base_url=args.url)
    if args.token:
        agent.access_token = args.token

    if args.email and args.password:
        agent.login(args.email, args.password)

    agent.run()


if __name__ == "__main__":
    main()
