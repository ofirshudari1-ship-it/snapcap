"""
Share Manager — handles all sharing destinations:
  - Clipboard (image or file path)
  - Save to disk (PNG/JPEG/WEBP)
  - Imgur upload (public link)
  - Custom URL / webhook
  - Slack, Teams, WhatsApp, email, Explorer, Paint
"""
import io
import os
import base64
import datetime
import subprocess
import shlex
from pathlib import Path
from typing import Optional

import pyperclip
from PIL import Image

import config as cfg


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


# ── Save ──────────────────────────────────────────────────────────────────────

def save_image(img: Image.Image, filename: Optional[str] = None, fmt: Optional[str] = None) -> str:
    """Save image to configured save directory. Returns the saved file path."""
    conf = cfg.load()
    save_dir = Path(conf["save_dir"])
    save_dir.mkdir(parents=True, exist_ok=True)

    fmt = (fmt or conf.get("image_format", "png")).lower()
    if not filename:
        filename = f"SnapCap_{_timestamp()}.{fmt}"
    else:
        # Defense in depth: strip any directory component so a crafted or
        # absolute filename (e.g. AI-generated title, "..\\..\\x") can never
        # escape save_dir via Path's "absolute RHS replaces LHS" behavior.
        filename = Path(filename).name
        if "." not in Path(filename).suffix:
            filename = f"{filename}.{fmt}"

    path = save_dir / filename

    if fmt in ("jpg", "jpeg"):
        img.convert("RGB").save(path, "JPEG", quality=conf.get("jpeg_quality", 90), optimize=True)
    elif fmt == "webp":
        img.save(path, "WEBP", quality=90)
    else:
        img.save(path, "PNG", optimize=True)

    return str(path)


# ── Clipboard ─────────────────────────────────────────────────────────────────

def copy_to_clipboard(img: Image.Image):
    """Copy image to Windows clipboard (as DIB bitmap)."""
    opened = False
    try:
        import win32clipboard
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "BMP")
        bmp_data = buf.getvalue()[14:]  # strip BMP file header, keep DIB header

        win32clipboard.OpenClipboard()
        opened = True
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
    except Exception:
        # Fallback: save temp PNG and put its path on clipboard.
        # NamedTemporaryFile(delete=False) avoids the create/open race of mktemp().
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img.save(tmp)
        pyperclip.copy(tmp)
        return
    finally:
        if opened:
            try:
                import win32clipboard
                win32clipboard.CloseClipboard()
            except Exception:
                pass


def copy_path_to_clipboard(path: str):
    pyperclip.copy(path)


# ── Imgur ─────────────────────────────────────────────────────────────────────

def upload_imgur(img: Image.Image, client_id: str) -> Optional[str]:
    """Upload to Imgur. Returns the direct image URL or None on failure."""
    import requests
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    try:
        resp = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": f"Client-ID {client_id}"},
            data={"image": b64, "type": "base64"},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["data"]["link"]
    except Exception:
        pass
    return None


# ── Custom webhook ─────────────────────────────────────────────────────────────

def upload_custom(img: Image.Image, url: str, method: str = "POST") -> Optional[str]:
    """POST/PUT image to a custom webhook URL. Returns response text."""
    import requests
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    fn = getattr(requests, method.lower(), requests.post)
    try:
        resp = fn(url, files={"file": ("screenshot.png", buf, "image/png")}, timeout=30)
        return resp.text
    except Exception as e:
        return str(e)


# ── App integrations ──────────────────────────────────────────────────────────

def open_in_explorer(path: str):
    """Open file location in Windows Explorer — safe, no shell injection."""
    subprocess.Popen(["explorer", "/select,", path])


def open_in_paint(path: str):
    """Open image in MS Paint."""
    subprocess.Popen(["mspaint", path])


def open_in_mail(path: str, subject: str = "Screenshot"):
    """Open default mail client (mailto: link; attachment must be added manually by user)."""
    import urllib.parse
    safe_subject = urllib.parse.quote(subject)
    os.startfile(f"mailto:?subject={safe_subject}&body=See%20attached%20screenshot")


def share_to_slack(img: Image.Image, webhook_url: str, message: str = "") -> bool:
    """Post screenshot to a Slack Incoming Webhook."""
    import requests, json
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    try:
        resp = requests.post(
            webhook_url,
            data={"payload": json.dumps({"text": message})},
            files={"file": ("screenshot.png", buf, "image/png")},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception:
        return False


def share_to_teams(img: Image.Image, webhook_url: str, message: str = "") -> bool:
    """Post screenshot to a Microsoft Teams Incoming Webhook."""
    import requests
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "text": message or "New screenshot from SnapCap",
        "sections": [{"images": [{"image": f"data:image/png;base64,{b64}"}]}],
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=30)
        return resp.status_code in (200, 202)
    except Exception:
        return False


def send_to_whatsapp_web(img_path: str):
    """Open WhatsApp Web — user attaches image manually."""
    import webbrowser
    webbrowser.open("https://web.whatsapp.com")


# ── Pipeline ──────────────────────────────────────────────────────────────────

def share_pipeline(img: Image.Image, destinations: list, ai_title: Optional[str] = None) -> dict:
    """
    Run a sharing pipeline.
    destinations: list of strings — 'save', 'clipboard', 'imgur', 'explorer', 'mail', 'paint',
                  'slack', 'teams'
    Returns dict of {destination: result_string}.
    """
    conf = cfg.load()
    results = {}
    saved_path = None

    needs_file = any(d in destinations for d in ("save", "explorer", "mail", "paint"))
    if needs_file or conf.get("auto_save"):
        saved_path = save_image(img, filename=ai_title or None)
        results["save"] = saved_path

    for dest in destinations:
        if dest == "clipboard":
            copy_to_clipboard(img)
            results["clipboard"] = "Copied to clipboard"
        elif dest == "path_clipboard" and saved_path:
            copy_path_to_clipboard(saved_path)
            results["path_clipboard"] = saved_path
        elif dest == "imgur":
            cid = conf.get("upload_targets", {}).get("imgur", {}).get("client_id", "")
            if cid:
                url = upload_imgur(img, cid)
                results["imgur"] = url or "Upload failed"
        elif dest == "explorer" and saved_path:
            open_in_explorer(saved_path)
            results["explorer"] = saved_path
        elif dest == "mail" and saved_path:
            open_in_mail(saved_path)
            results["mail"] = saved_path
        elif dest == "paint" and saved_path:
            open_in_paint(saved_path)
            results["paint"] = saved_path
        elif dest == "slack":
            wh = conf.get("slack_webhook", "")
            if wh:
                ok = share_to_slack(img, wh)
                results["slack"] = "Sent" if ok else "Failed"
        elif dest == "teams":
            wh = conf.get("teams_webhook", "")
            if wh:
                ok = share_to_teams(img, wh)
                results["teams"] = "Sent" if ok else "Failed"

    return results
