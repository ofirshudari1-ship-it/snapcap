"""
SnapCap — GitHub-based update checker + self-update.

check_for_update() runs in a background thread, a few seconds after app
startup, and never blocks the UI. Hits the GitHub Releases API for this
project's repo, compares the latest published tag against the running
config.APP_VERSION, and — if a newer version is available — hands the
caller a small dict with the new version, the release page URL, and (if
present) the installer asset's download URL/size.

Two ways the caller can use that:
  1. Notify-only (existing, default): show a tray balloon linking to the
     release page; the user downloads/runs the installer by hand.
  2. Self-update (default ON, Settings -> "Automatically download and
     install updates", or the "Update Now" button): the installer .exe is
     downloaded to a temp file and verified (byte count vs. the GitHub API's
     asset size, "MZ" PE magic, and the sha256 digest GitHub publishes for
     the asset when present), then launched with `--silent --relaunch`
     (non-blocking) so it installs once this process exits and relaunches
     SnapCap. The installer is per-machine (Program Files) and so needs one
     Windows UAC prompt - launch_silent_install() surfaces it via
     ShellExecute; the app can never install fully invisibly.

Fails silently on any network/parsing/disk error: no internet, GitHub down,
rate limited, repo renamed, disk full, antivirus blocked the exe, whatever —
the caller always gets a clean status dict back and can fall back to the
manual-download notification. Nothing in this module raises out to the
caller.
"""
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

log = logging.getLogger("snapcap.update")

GITHUB_REPO = "ofirshudari1-ship-it/snapcap"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
USER_AGENT = "SnapCap-UpdateChecker/1.0"
# Only installer URLs attached to THIS repo's releases are ever downloaded
# and executed. GitHub's API is trusted over HTTPS, but pinning the prefix
# means a malformed/unexpected API payload (or a future bug that feeds this
# module some other URL) can't turn the self-updater into "download and run
# an arbitrary exe". urllib follows GitHub's redirect to its CDN on its own.
ALLOWED_ASSET_PREFIX = f"https://github.com/{GITHUB_REPO}/releases/download/"
_TEMP_INSTALLER_PREFIX = "SnapCap-Setup-"


def _parse_version(v: str):
    """'v1.4.2' / '1.4.2' -> (1, 4, 2). Non-numeric junk is treated as 0."""
    v = (v or "").strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    parts = []
    for piece in v.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    # Pad to 3 components so "1.9" and "1.9.0" compare equal — plain tuple
    # comparison would otherwise call (1, 9, 0) newer than (1, 9).
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    try:
        return _parse_version(latest) > _parse_version(current)
    except Exception:
        return False


def _find_installer_asset(data: dict) -> Optional[dict]:
    """Picks the SnapCap-Setup-*.exe asset off a GitHub release's asset
    list. Returns {"url": browser_download_url, "size": int, "name": str}
    or None if the release has no matching asset attached (e.g. a
    source-only tag, or the build/publish step hasn't attached one yet)."""
    for asset in data.get("assets", []) or []:
        name = asset.get("name") or ""
        if name.lower().startswith("snapcap-setup") and name.lower().endswith(".exe"):
            digest = str(asset.get("digest") or "").strip().lower()
            sha256 = digest[len("sha256:"):] if digest.startswith("sha256:") else ""
            if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
                sha256 = ""
            return {
                "url": asset.get("browser_download_url"),
                "size": asset.get("size"),
                "name": name,
                "sha256": sha256,
            }
    return None


def _safe_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def check_for_update(current_version: str, timeout: float = 5.0) -> Optional[dict]:
    """
    Single synchronous check against the GitHub releases API.
    Returns {"version": "1.4.2", "url": "https://github.com/.../releases/tag/v1.4.2",
    "asset_url": "...", "asset_size": 123, "asset_name": "SnapCap-Setup-1.4.2.exe"}
    if a newer release is published (asset_* keys only present if the
    release actually has an installer attached), otherwise None. Never
    raises.
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
            info = {"version": tag.lstrip("vV"), "url": html_url}
            asset = _find_installer_asset(data)
            if asset and asset.get("url"):
                info["asset_url"] = asset["url"]
                info["asset_size"] = asset["size"]
                info["asset_name"] = asset["name"]
                if asset.get("sha256"):
                    info["asset_sha256"] = asset["sha256"]
            log.info("Update check: v%s available (current v%s, asset=%s)",
                     info["version"], current_version, bool(asset and asset.get("url")))
            return info
        log.info("Update check: up to date (current v%s, latest tag %r)", current_version, tag)
    except Exception as e:
        log.warning("Update check failed: %s", e)
    return None


def download_installer(asset_url: str, expected_size: Optional[int] = None,
                        on_progress=None, timeout: float = 30.0,
                        expected_sha256: Optional[str] = None) -> Optional[Path]:
    """
    Downloads the installer .exe from a GitHub release asset URL to a
    fresh temp file, streaming in chunks so a large download doesn't have
    to sit fully in memory. Verifies the number of bytes actually written
    against `expected_size` (the GitHub API's reported asset size — a
    simple, dependency-free stand-in for a full checksum: it catches a
    truncated/interrupted download, which is the failure mode that
    actually matters for "did this complete cleanly").

    on_progress(bytes_downloaded, total_bytes), if given, is called after
    every chunk — wire it to a Qt signal's .emit() for a UI progress bar.
    Any exception it raises is swallowed so a UI hiccup can't abort the
    download.

    Returns the local Path on success. Returns None (after deleting any
    partial file) on any failure: network error, size mismatch, disk full,
    permission denied, etc. Never raises.
    """
    tmp_path = None
    try:
        if not is_trusted_asset_url(asset_url):
            return None
        fd, tmp_name = tempfile.mkstemp(prefix=_TEMP_INSTALLER_PREFIX, suffix=".exe")
        os.close(fd)
        tmp_path = Path(tmp_name)

        req = urllib.request.Request(
            asset_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"},
        )
        downloaded = 0
        hasher = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = expected_size or _safe_int(resp.headers.get("Content-Length"))
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        try:
                            on_progress(downloaded, total)
                        except Exception:
                            pass

        if downloaded <= 0:
            tmp_path.unlink(missing_ok=True)
            return None
        if expected_size and downloaded != expected_size:
            log.warning("Update download size mismatch: expected %s, got %s", expected_size, downloaded)
            tmp_path.unlink(missing_ok=True)
            return None
        if expected_sha256 and hasher.hexdigest() != expected_sha256.lower():
            log.warning("Update download sha256 mismatch - discarded")
            tmp_path.unlink(missing_ok=True)
            return None
        # A Windows executable always starts with the "MZ" DOS header. An
        # HTML error page / captive-portal login page served with a 200
        # would otherwise pass the size check whenever GitHub didn't report
        # a size, and then get "launched" as an installer.
        with open(tmp_path, "rb") as f:
            if f.read(2) != b"MZ":
                log.warning("Update download is not a PE executable - discarded")
                tmp_path.unlink(missing_ok=True)
                return None
        log.info("Update downloaded and verified: %s (%d bytes)", tmp_path, downloaded)
        return tmp_path
    except Exception as e:
        log.warning("Update download failed: %s", e)
        try:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def is_trusted_asset_url(url) -> bool:
    return isinstance(url, str) and url.startswith(ALLOWED_ASSET_PREFIX)


def cleanup_stale_downloads(max_age_sec: float = 3600.0) -> int:
    """Deletes installer copies a previous self-update left in %TEMP%.
    download_installer() has to leave the file in place (the detached
    silent installer is running FROM it when this process exits), so every
    auto-update used to strand a ~140 MB SnapCap-Setup-*.exe in the temp
    folder forever. Called once at startup; only removes files older than
    max_age_sec so an installer that may still be finishing is never
    touched, and silently skips anything locked/undeletable. Returns the
    number of files removed. Never raises."""
    removed = 0
    try:
        now = time.time()
        for p in Path(tempfile.gettempdir()).glob(f"{_TEMP_INSTALLER_PREFIX}*.exe"):
            try:
                if now - p.stat().st_mtime > max_age_sec:
                    p.unlink()
                    removed += 1
            except Exception:
                continue
    except Exception:
        pass
    return removed


def launch_silent_install(installer_path, relaunch: bool = True) -> bool:
    """
    Launches the downloaded installer with the silent/unattended switch
    (see build/build_installer.py's `--silent` handling), non-blocking —
    this process is about to quit itself right after calling this, so it
    must never wait on the child (Popen, not run()/call()). `--relaunch`
    tells the installer to start SnapCap.exe again once the silent install
    finishes.

    Returns True once the process has been launched (Popen didn't raise).
    This does NOT confirm the install itself succeeds — that already runs
    detached, after this process is gone, so there's nothing left here to
    observe. Returns False if launching failed outright: path doesn't
    exist, permission denied, antivirus blocked it, etc. Never raises.
    """
    try:
        installer_path = Path(installer_path)
        if not installer_path.exists():
            return False
        args = [str(installer_path), "--silent"]
        if relaunch:
            args.append("--relaunch")
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
        try:
            subprocess.Popen(args, creationflags=creationflags)
            return True
        except OSError as e:
            # The installer embeds a requireAdministrator manifest
            # (--uac-admin): CreateProcess from a non-elevated app fails
            # with ERROR_ELEVATION_REQUIRED (740). That was the reason the
            # silent update never ran. ShellExecute shows the one UAC
            # prompt instead; declining it returns <= 32.
            if getattr(e, "winerror", None) != 740 or os.name != "nt":
                raise
            return _shell_execute_elevated(str(installer_path), " ".join(args[1:]))
    except Exception as e:
        log.warning("Launching the silent installer failed: %s", e)
        return False


def _shell_execute_elevated(exe: str, params: str) -> bool:
    """Starts `exe` through the shell so Windows shows its UAC prompt.
    True once the prompt was accepted and the process started."""
    try:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(None, "open", exe, params, None, 0)
        if rc > 32:
            log.info("Silent installer started via ShellExecute (UAC accepted)")
            return True
        log.warning("Silent installer not started (UAC declined or blocked, code %s)", rc)
    except Exception as e:
        log.warning("ShellExecute failed: %s", e)
    return False


_STAGED: dict = {}


def download_update(current_version: str, on_progress=None, timeout: float = 30.0) -> dict:
    """check -> download -> verify, WITHOUT launching anything. Returns
        {"status": "no_update"}
        {"status": "ready", "installer_path": "...", "version": "1.7.0", "info": {...}}
        {"status": "failed", "reason": "no_asset" | "download_failed", "info": {...}}
    The caller decides when it is safe to install (see main.py: only with no
    editor open, or on exit). Re-uses an installer already staged for the
    same version instead of downloading 140 MB again every 6 hours. Never
    raises."""
    try:
        info = check_for_update(current_version, timeout=5.0)
    except Exception:
        info = None
    if not info:
        return {"status": "no_update"}

    asset_url = info.get("asset_url")
    if not asset_url:
        return {"status": "failed", "reason": "no_asset", "info": info}

    try:
        staged = _STAGED.get(info["version"])
        if staged and Path(staged).exists() and Path(staged).stat().st_size == (info.get("asset_size") or -1):
            return {"status": "ready", "installer_path": str(staged), "version": info["version"], "info": info}
    except Exception:
        pass

    installer_path = download_installer(
        asset_url, expected_size=info.get("asset_size"),
        on_progress=on_progress, timeout=timeout,
        expected_sha256=info.get("asset_sha256"),
    )
    if not installer_path:
        return {"status": "failed", "reason": "download_failed", "info": info}
    _STAGED[info["version"]] = str(installer_path)
    return {"status": "ready", "installer_path": str(installer_path), "version": info["version"], "info": info}


def perform_self_update(current_version: str, on_progress=None, timeout: float = 30.0) -> dict:
    """
    Full self-update pipeline: check -> download -> verify -> launch the
    silent installer. Returns a small status dict describing what
    happened, so the caller (Settings' "Update Now") can decide
    whether to quit the running app (status == "launched") or fall back to
    the existing manual-download notification (anything else):

        {"status": "no_update"}
        {"status": "launched", "installer_path": "C:\\...\\SnapCap-Setup-xxxx.exe", "version": "1.7.0"}
        {"status": "failed", "reason": "no_asset" | "download_failed" | "launch_failed",
         "info": {...} | None}

    "info" (when present) is exactly what check_for_update() returned, so
    the caller can still show "version X is available, open the release
    page" as a fallback even though the automatic path failed. Never
    raises.
    """
    res = download_update(current_version, on_progress=on_progress, timeout=timeout)
    if res["status"] != "ready":
        return res
    if not launch_silent_install(res["installer_path"]):
        return {"status": "failed", "reason": "launch_failed", "info": res["info"]}
    return {"status": "launched", "installer_path": res["installer_path"], "version": res["version"]}


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


def start_background_prepare(current_version: str, on_ready, on_fallback, delay: float = 5.0):
    """
    Background half of the default-ON auto-update: after `delay` seconds,
    check GitHub and (if a newer release exists) download + verify the
    installer, WITHOUT installing it.

    - status == "ready": on_ready(version, installer_path) - the caller
      installs at a safe moment (no editor open) or when the app exits.
    - status == "failed" with release info (no asset / download failed):
      on_fallback(version, url) - the ordinary manual-download balloon.
    - no update / check failed: nothing is called.

    Both callbacks run on the worker thread (use Qt signals' .emit). Any
    exception anywhere is logged and swallowed; never blocks the caller.
    """
    def _run():
        try:
            time.sleep(delay)
        except Exception:
            pass
        try:
            result = download_update(current_version)
            status = result.get("status")
            if status == "ready":
                on_ready(result["version"], result["installer_path"])
            elif status == "failed" and result.get("info"):
                info = result["info"]
                log.warning("Auto-update could not prepare v%s (%s)", info.get("version"), result.get("reason"))
                on_fallback(info["version"], info["url"])
        except Exception as e:
            log.warning("Background auto-update crashed: %s", e)

    th = threading.Thread(target=_run, daemon=True, name="SnapCapAutoUpdate")
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
