import base64
import copy
import json
import os
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
        "capture_gif":         "ctrl+shift+g",
        "capture_color_picker": "ctrl+alt+c",
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
    # 2026-09-20 Windows-integration pass — Startup group in Settings.
    # Note: "launch at Windows startup" itself is intentionally NOT stored here —
    # the HKCU\...\Run registry key is the single source of truth (see
    # editor_window.SettingsDialog._is_startup/_set_startup), so the checkbox
    # always reflects reality even if the user removed it via Windows' own
    # Startup Apps settings instead of through SnapCap.
    "skip_splash_on_autostart": True,  # when launched via the Run-key/startup-folder entry (--autostart flag), skip the ~1-2s splash screen for a quieter boot
    "show_startup_notification": True, # the "Running in the system tray" tray balloon shown on every non-first launch — can be silenced for autostart
    # 2026-09-21 self-update pass — opt-in, default OFF: when True, a detected
    # GitHub release is downloaded and installed silently in the background
    # instead of just showing the "update available" tray notification (see
    # update_checker.perform_self_update / start_background_autoupdate).
    "auto_update": False,
    # 2026-09-22 desktop widget pass — a small always-on-top floating panel
    # with the "captured this month" stat + one-click "Capture now" / "Open
    # Library". Default ON (opt-out, not opt-in) since it's a passive,
    # non-intrusive panel and the whole point is being visible without an
    # extra step; "widget_pos" is None until the user drags it once, at
    # which point WidgetWindow persists {"x": int, "y": int} here so it
    # reopens in the same spot across restarts.
    "show_desktop_widget": False,  # opt-in - off by default, enable from Settings
    "widget_pos": None,
    # 2026-09-26 "GIF recording" pass (competitor research: ShareX ships a
    # region GIF recorder as a core feature; Greenshot has none). Frames are
    # captured at gif_fps for at most gif_max_duration_sec, then encoded with
    # Pillow — see gif_recorder.py. Kept short/region-only by design: a full
    # video pipeline (audio, long recordings, MP4/H.264) is a much bigger
    # lift than fits this pass — see CHANGELOG for that scoping call.
    "gif_fps":               8,
    "gif_max_duration_sec":  15,
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


def _type_ok(default, value) -> bool:
    """Does a loaded value have the same shape as its default? bool is
    checked before int because bool is an int subclass in Python (a
    hand-edited `"capture_delay_sec": true` must not pass as a number)."""
    if default is None:
        return True  # e.g. widget_pos: None until first drag, then a dict
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, dict):
        return isinstance(value, dict)
    if isinstance(default, list):
        return isinstance(value, list)
    return True


def _merge(defaults: dict, data: dict) -> dict:
    """Defaults first, user values win — recursively for nested dicts
    (hotkeys, upload_targets). The previous flat `{**DEFAULT_CONFIG, **data}`
    replaced a nested dict wholesale, so a config.json written before a new
    nested default existed (e.g. the capture_text_ocr hotkey) never gained
    it: no hotkey got registered, and Settings → Hotkeys (which lists
    whatever keys are present) had no row to set it from. A value whose
    type doesn't match its default (hand-edited / half-written file) falls
    back to the default instead of crashing the code that reads it.
    Keys not in defaults are kept as-is (forward compatibility)."""
    out = copy.deepcopy(defaults)
    for key, value in data.items():
        if key in defaults:
            default = defaults[key]
            if not _type_ok(default, value):
                continue
            if isinstance(default, dict) and default:
                out[key] = _merge(default, value)
            else:
                out[key] = copy.deepcopy(value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load() -> dict:
    """Always returns a fresh, fully-populated dict — a deep copy, never
    sharing nested objects with DEFAULT_CONFIG (the old shallow
    `dict(DEFAULT_CONFIG)` fallback let Settings' in-place writes to
    conf["hotkeys"][...] / conf["upload_targets"][...] mutate the module
    defaults themselves for the rest of the process)."""
    _make_dirs()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged = _merge(DEFAULT_CONFIG, data)
                _transform_secrets(merged, _decrypt)
                _make_save_dir(merged)
                return merged
        except Exception:
            pass
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    _make_save_dir(cfg)
    return cfg


def save(cfg: dict):
    """Writes cfg to disk with secrets DPAPI-encrypted. Operates on a deep
    copy so the caller's in-memory cfg (which the rest of the app reads
    plaintext values from for actual API calls) is never mutated.

    Atomic: written to a sibling temp file, flushed to disk, then swapped
    in with os.replace(). A crash / power loss mid-write used to be able to
    leave a truncated config.json, which load() then treats as corrupt and
    silently replaces with defaults — losing every setting, including the
    saved API key."""
    _make_dirs()
    on_disk = _transform_secrets(copy.deepcopy(cfg), _encrypt)
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(on_disk, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_FILE)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
