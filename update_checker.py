"""
SnapCap — GitHub-based update checker.

Runs in a background thread, a few seconds after app startup, and never
blocks the UI. Hits the GitHub Releases API for this project's repo,
compares the latest published tag against the running config.APP_VERSION,
and — if a newer version is available — hands the caller a small dict with
the new version and the release page URL so the caller (main.py) can show a
tray notification linking out to it via webbrowser.open().

Fails silently on any network/parsing error: no internet, GitHub down, rate
limited, repo renamed, whatever — the app must behave exactly as if update
checking were disabled.
"""
import json
import threading
import time
import urllib.request
import webbrowser
from typing import Optional

GITHUB_REPO = "ofirshudari1-ship-it/snapcap"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
USER_AGENT = "SnapCap-UpdateChecker/1.0"


def _parse_version(v: str):
    """'v1.4.2' / '1.4.2' -> (1, 4, 2). Non-numeric junk is treated as 0."""
    v = (v or "").strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    parts = []
    for piece in v.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def _is_newer(latest: str, current: str) -> bool:
    try:
        return _parse_version(latest) > _parse_version(current)
    except Exception:
        return False


def check_for_update(current_version: str, timeout: float = 5.0) -> Optional[dict]:
    """
    Single synchronous check against the GitHub releases API.
    Returns {"version": "1.4.2", "url": "https://github.com/.../releases/tag/v1.4.2"}
    if a newer release is published, otherwise None. Never raises.
    """
    try:
        req = urllib.request.Request(
            RELEASES_API_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        tag = data.get("tag_name", "") or ""
        html_url = data.get("html_url") or RELEASES_PAGE_URL
        if tag and _is_newer(tag, current_version):
            return {"version": tag.lstrip("vV"), "url": html_url}
    except Exception:
        pass
    return None


def start_background_check(current_version: str, on_update, delay: float = 5.0):
    """
    Fire-and-forget background check. Waits `delay` seconds after being
    started (so it never competes with app/tray startup), then checks
    GitHub once. If a newer release exists, calls on_update(version, url)
    — version is the bare version string (e.g. "1.4.2"), url is the
    release page to open in the browser. on_update is expected to be
    thread-safe (e.g. a Qt signal's .emit) since it runs on this
    background thread.

    Any exception anywhere in this path (including inside on_update) is
    swallowed — update checking must never be able to crash or disrupt the
    running app.
    """
    def _run():
        try:
            time.sleep(delay)
        except Exception:
            pass
        try:
            info = check_for_update(current_version)
            if info:
                on_update(info["version"], info["url"])
        except Exception:
            pass

    th = threading.Thread(target=_run, daemon=True, name="SnapCapUpdateChecker")
    th.start()
    return th


def open_release_page(url: str = None):
    """Opens the release page (or the generic 'latest' page) in the
    user's default browser. Never raises — a failed webbrowser.open()
    must not surface an error dialog."""
    try:
        webbrowser.open(url or RELEASES_PAGE_URL)
    except Exception:
        pass
