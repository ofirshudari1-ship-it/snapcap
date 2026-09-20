import base64
import copy
import json
import sys
from pathlib import Path

try:
    import win32crypt  # part of pywin32, already a hard dependency (see requirements.txt)
    _DPAPI_AVAILABLE = True
except Exception:
    _DPAPI_AVAILABLE = False

# Fields that hold credentials and must never sit in config.json as plaintext.
# Nested ones are (parent_key, child_key) pairs under upload_targets.
_SENSITIVE_TOP_LEVEL = ["anthropic_api_key", "slack_webhook", "teams_webhook"]
_SENSITIVE_UPLOAD_TARGET_FIELDS = {
    "imgur": ["client_id"],
    "s3": ["key_id", "key_secret"],
}
_ENC_PREFIX = "dpapi:"


def _load_version_info() -> dict:
    """version.json is the project's single source of truth for the version
    string (per project standard) — it's what gets bumped in one place and
    read everywhere else (window titles, About, installer filename), instead
    of drifting out of sync across files."""
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "version.json")
    candidates.append(Path(__file__).resolve().parent / "version.json")
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {"version": "1.1.1", "name": "SnapCap", "publisher": "SnapCap"}


_version_info = _load_version_info()
APP_NAME    = _version_info.get("name", "SnapCap")
APP_VERSION = _version_info.get("version", "1.1.1")

CONFIG_DIR  = Path.home() / ".snapcap"
CONFIG_FILE = CONFIG_DIR / "config.json"
LIBRARY_DIR = CONFIG_DIR / "library"
TEMP_DIR    = CONFIG_DIR / "temp"

DEFAULT_CONFIG = {
    "hotkeys": {
        "capture_region":    "ctrl+shift+s",
        "capture_fullscreen":"ctrl+shift+f",
        "capture_window":    "ctrl+shift+w",
        "capture_scroll":    "ctrl+shift+l",
        "open_library":      "ctrl+shift+o",
        "capture_text_ocr":  "ctrl+shift+t",
    },
    "save_dir":        str(Path.home() / "Pictures" / "SnapCap"),
    "auto_copy":       True,
    "auto_save":       True,
    "image_format":    "png",
    "jpeg_quality":    90,
    "show_toolbar":    True,
    "theme":           "system",
    "ai_enabled":      False,
    "anthropic_api_key": "",
    "upload_destination": "clipboard",
    "upload_targets": {
        "imgur":      {"enabled": False, "client_id": ""},
        "s3":         {"enabled": False, "bucket": "", "key_id": "", "key_secret": ""},
        "custom_url": {"enabled": False, "url": "", "method": "POST"},
    },
    "auto_redact":        False,
    "redact_types":       ["email", "phone", "credit_card", "api_key"],
    "watermark_enabled":   False,
    "watermark_text":      "",
    "smart_window_naming": True,
    "library_search_ocr":  True,
    "slack_webhook":       "",
    "teams_webhook":       "",
    "first_run":           True,
    "last_version_check":  "",
    "check_updates":       True,
    "language":            "en",  # default is English for every tool (2026-09-14 decision) — was "auto" (system-locale detection, which silently switched to Hebrew on he-IL Windows)
    "redact_style":        "blur",
    # 2026-09-20 "wow" upgrade pass — real, opt-out-able capture behavior:
    "capture_delay_sec":     0,     # 0/3/5/10 — countdown shown before the actual pixel-grab, so a user can open a menu/tooltip first
    "capture_sound":         True, # short shutter sound on every successful capture (winsound, no bundled asset)
    "skip_editor_on_capture": False,  # when True: capture still auto-copies/saves/redacts/watermarks, but the annotation editor doesn't pop open every time
}


def _encrypt(plaintext: str) -> str:
    """DPAPI-encrypt a secret for storage, tied to the current Windows user
    account (CryptProtectData with no explicit key — matches the pattern
    already used in the AutoProcessTwin/OptiGuard C# products via
    ProtectedData/DataProtectionScope). Falls back to plaintext if pywin32
    is unavailable or empty/already-encrypted input is passed through."""
    if not plaintext or plaintext.startswith(_ENC_PREFIX):
        return plaintext
    if not _DPAPI_AVAILABLE:
        return plaintext
    try:
        blob = win32crypt.CryptProtectData(plaintext.encode("utf-8"), None, None, None, None, 0)
        return _ENC_PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception:
        return plaintext


def _decrypt(value: str) -> str:
    """Reverse of _encrypt(). Returns the value unchanged if it isn't an
    encrypted blob (plaintext from an older config, or DPAPI unavailable)."""
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    if not _DPAPI_AVAILABLE:
        return value
    try:
        blob = base64.b64decode(value[len(_ENC_PREFIX):])
        return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-8")
    except Exception:
        return value


def _transform_secrets(cfg: dict, fn) -> dict:
    """Apply fn (either _encrypt or _decrypt) to every sensitive field in cfg,
    in place. Missing/malformed nested structures are skipped, not errors."""
    for key in _SENSITIVE_TOP_LEVEL:
        if key in cfg and isinstance(cfg[key], str):
            cfg[key] = fn(cfg[key])
    targets = cfg.get("upload_targets")
    if isinstance(targets, dict):
        for target_name, fields in _SENSITIVE_UPLOAD_TARGET_FIELDS.items():
            target = targets.get(target_name)
            if isinstance(target, dict):
                for field in fields:
                    if field in target and isinstance(target[field], str):
                        target[field] = fn(target[field])
    return cfg


def _make_dirs():
    """Create config/library/temp dirs — never calls load(), no recursion."""
    for d in [CONFIG_DIR, LIBRARY_DIR, TEMP_DIR]:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def _make_save_dir(cfg: dict):
    """Create the user's save directory from a loaded config dict."""
    try:
        Path(cfg.get("save_dir", DEFAULT_CONFIG["save_dir"])).mkdir(
            parents=True, exist_ok=True
        )
    except Exception:
        pass


# Public alias kept for any code that called ensure_dirs()
def ensure_dirs():
    _make_dirs()


def load() -> dict:
    _make_dirs()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge: defaults first, then user values (user wins)
            merged = {**DEFAULT_CONFIG, **data}
            _transform_secrets(merged, _decrypt)
            _make_save_dir(merged)
            return merged
        except Exception:
            pass
    cfg = dict(DEFAULT_CONFIG)
    _make_save_dir(cfg)
    return cfg


def save(cfg: dict):
    """Writes cfg to disk with secrets DPAPI-encrypted. Operates on a deep
    copy so the caller's in-memory cfg (which the rest of the app reads
    plaintext values from for actual API calls) is never mutated."""
    _make_dirs()
    on_disk = _transform_secrets(copy.deepcopy(cfg), _encrypt)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(on_disk, f, indent=2, ensure_ascii=False)
