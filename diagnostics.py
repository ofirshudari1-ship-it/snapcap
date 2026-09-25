"""
Export Diagnostics — bundles everything support needs to troubleshoot a
user's SnapCap install into a single .zip, with secrets stripped out before
anything touches disk.

Contents:
  - snapcap.log        (the rotating operational log, if it exists yet —
                         logger.py only creates it once setup_logging() has
                         actually run)
  - version.json        (exact contents of the app's version.json, so
                         support always knows precisely which build this is,
                         not just the "vX.Y.Z" the user typed in an email)
  - config.json          the persisted config, with every credential-shaped
                         field redacted (see _redact_config below) rather
                         than omitted — support can still see *that* a field
                         was configured (e.g. "AI enabled: yes, key set")
                         without ever seeing the secret itself.
  - system-info.txt      OS version, Python version, PyQt6 version, SnapCap
                         version, install path.

Kept as its own module (not inlined in main.py/editor_window.py) so both
call sites — Settings → Advanced and the About dialog — share one
implementation, and so it's independently unit-testable without spinning up
a QApplication.
"""
from __future__ import annotations

import copy
import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import config as cfg
from logger import LOG_FILE

_REDACTED = "***REDACTED***"

# Mirrors config.py's own sensitive-field lists (config._SENSITIVE_TOP_LEVEL /
# _SENSITIVE_UPLOAD_TARGET_FIELDS) rather than importing them directly, so a
# private/underscore-prefixed name in config.py isn't relied on across module
# boundaries. custom_url.url is redacted too, even though config.py doesn't
# encrypt it at rest — an arbitrary POST endpoint can carry an API token or
# signed-upload secret in its query string, and there's no legitimate reason
# a diagnostics bundle needs the real URL.
_SENSITIVE_TOP_LEVEL = ["anthropic_api_key", "slack_webhook", "teams_webhook"]
_SENSITIVE_UPLOAD_TARGET_FIELDS = {
    "imgur": ["client_id"],
    "s3": ["key_id", "key_secret"],
    "custom_url": ["url"],
}


def default_zip_name(version: str | None = None) -> str:
    version = version or cfg.APP_VERSION
    date_str = datetime.now().strftime("%Y-%m-%d")
    return f"SnapCap-Diagnostics-{version}-{date_str}.zip"


def _redact_config(conf: dict) -> dict:
    """Returns a deep copy of conf with every credential-shaped field
    replaced by a fixed marker (not deleted — a missing key would be
    ambiguous with "this SnapCap build predates the field")."""
    out = copy.deepcopy(conf)
    for key in _SENSITIVE_TOP_LEVEL:
        if key in out and out[key]:
            out[key] = _REDACTED
    targets = out.get("upload_targets")
    if isinstance(targets, dict):
        for target_name, fields in _SENSITIVE_UPLOAD_TARGET_FIELDS.items():
            target = targets.get(target_name)
            if isinstance(target, dict):
                for field in fields:
                    if field in target and target[field]:
                        target[field] = _REDACTED
    return out


def _system_info_text(install_path: Path) -> str:
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        pyqt_version = f"PyQt6 {PYQT_VERSION_STR} (Qt {QT_VERSION_STR})"
    except Exception:
        pyqt_version = "PyQt6 (version unavailable)"

    lines = [
        f"SnapCap version:  {cfg.APP_VERSION}",
        f"OS:               {platform.platform()}",
        f"Python:           {sys.version.split()[0]}",
        pyqt_version,
        f"Install path:     {install_path}",
        f"Generated:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return "\n".join(lines) + "\n"


def _install_path() -> Path:
    if hasattr(sys, "_MEIPASS"):
        # Frozen (PyInstaller --onedir) build: the running exe's own folder
        # is the actual install directory, not the temp _MEIPASS unpack dir.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _version_json_bytes() -> bytes:
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "version.json")
    candidates.append(Path(__file__).resolve().parent / "version.json")
    for path in candidates:
        try:
            return path.read_bytes()
        except Exception:
            continue
    # Fall back to whatever config.py already parsed, so the bundle always
    # has *something* even if the on-disk file can't be found.
    return json.dumps(
        {"version": cfg.APP_VERSION, "name": cfg.APP_NAME, "publisher": cfg.APP_NAME},
        indent=2,
    ).encode("utf-8")


def build_diagnostics_zip(dest_path: str | Path) -> Path:
    """Writes the diagnostics bundle to dest_path and returns it as a Path.
    Never touches the real config file — reads through config.load() (which
    already decrypts secrets into memory) purely to redact and re-serialize,
    nothing is written back."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    install_path = _install_path()

    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if LOG_FILE.exists():
            zf.write(LOG_FILE, arcname="snapcap.log")

        zf.writestr("version.json", _version_json_bytes())

        redacted_conf = _redact_config(cfg.load())
        zf.writestr(
            "config.json",
            json.dumps(redacted_conf, indent=2, ensure_ascii=False),
        )

        zf.writestr("system-info.txt", _system_info_text(install_path))

    return dest_path
