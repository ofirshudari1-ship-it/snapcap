"""
Build a self-extracting installer EXE for SnapCap.
Uses Python + PyInstaller to create a proper Windows installer
without depending on Inno Setup / NSIS being pre-installed.

The installer:
  1. Shows a modern PyQt6 wizard with license, install-path, shortcut options
  2. Extracts the bundled SnapCap.exe to the chosen directory
  3. Creates Start Menu / Desktop shortcuts
  4. Writes an uninstall registry entry
  5. Optionally runs SnapCap on finish
"""
import os
import sys
import shutil
import subprocess
import zipfile
import base64
import struct
import winreg
import tempfile
from pathlib import Path

# This script lives in build\ (dev tooling, kept out of the project root per
# the project's folder-hygiene standard) — run everything relative to the
# project root, one level up, where main.py/assets/etc. actually live.
os.chdir(Path(__file__).resolve().parent.parent)

sys.path.insert(0, str(Path(".").resolve()))
from config import APP_VERSION as APP_VER  # single source of truth for the version string

# We will create the installer as a Python script that bundles the EXE,
# then compile THAT script with PyInstaller.

INSTALLER_SCRIPT = r'''
import sys, os, shutil, winreg, subprocess, zipfile, io, base64, struct, threading, locale, time
from pathlib import Path

APP_NAME   = "SnapCap"
APP_VER    = "__APP_VERSION__"
PUBLISHER  = "SnapCap"
EXE_NAME   = "SnapCap.exe"
REG_KEY    = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\SnapCap"


# ── Shared install primitives (used by both the GUI wizard below and the
# --silent unattended path) ─────────────────────────────────────────────────
def _find_app_payload_dir() -> "Path | None":
    """Locates the bundled SnapCap/ app folder next to this installer exe
    (or in its onefile temp extraction dir). Same search order as
    InstallWorker._find_app_dir used previously — kept as a free function so
    the silent path doesn't need a QThread instance to call it."""
    here = Path(sys.executable).parent
    candidates = [
        here / "SnapCap",
        here.parent / "SnapCap",
        Path(sys._MEIPASS) / "SnapCap" if hasattr(sys, "_MEIPASS") else None,
    ]
    for c in candidates:
        if c and (c / "SnapCap.exe").exists():
            return c
    return None


def _read_existing_install_dir() -> "Path | None":
    """Reads InstallLocation from the registry entry a previous install
    wrote (see _write_registry_entry) — lets --silent update in place
    instead of guessing a default path, and lets it tell an update apart
    from a first-time silent install (no existing entry -> fresh install).

    Checks HKLM first — where the entry is written per STANDARDS.md §7.1,
    matching the per-machine Program Files install — then falls back to
    HKCU so an in-place update over an install made by an older SnapCap
    build (which wrote the entry to HKCU) still finds its install dir."""
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, REG_KEY, 0, winreg.KEY_READ)
            try:
                val, _ = winreg.QueryValueEx(key, "InstallLocation")
            finally:
                winreg.CloseKey(key)
            if val and Path(val).parent.exists():
                return Path(val)
        except Exception:
            pass
    return None


def _create_shortcut(target: Path, link: Path, arguments: str = "", log=lambda m: None):
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(str(link))
        sc.Targetpath = str(target)
        sc.WorkingDirectory = str(target.parent)
        sc.IconLocation = str(target)
        if arguments:
            sc.Arguments = arguments
        sc.save()
    except Exception as e:
        log(f"  Shortcut warning: {e}")


def _write_registry_entry(install_dir: Path, log=lambda m: None):
    """Writes the uninstall entry to HKLM — SnapCap installs per-machine
    under %PROGRAMFILES% and the installer requests admin elevation via
    --uac-admin (see build below), so HKLM is the correct hive per
    STANDARDS.md §7.1's table for this tool (unlike a per-user tool such
    as Playnest, which intentionally uses HKCU). Was HKCU here, a
    mismatch with what §7.1 documents and with the rest of the install
    (Program Files, admin elevation) — fixed 2026-09-23. Any stale HKCU
    entry from an older SnapCap build is cleaned up by main.py's
    --uninstall handler, which checks both hives."""
    try:
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY)
        winreg.SetValueEx(key, "DisplayName",      0, winreg.REG_SZ, "SnapCap")
        winreg.SetValueEx(key, "DisplayVersion",   0, winreg.REG_SZ, APP_VER)
        winreg.SetValueEx(key, "Publisher",        0, winreg.REG_SZ, "SnapCap")
        winreg.SetValueEx(key, "InstallLocation",  0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "UninstallString",  0, winreg.REG_SZ, str(install_dir / "SnapCap.exe") + " --uninstall")
        winreg.SetValueEx(key, "DisplayIcon",      0, winreg.REG_SZ, str(install_dir / "SnapCap.exe"))
        winreg.SetValueEx(key, "NoModify",         0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
    except Exception as e:
        log(f"  Registry warning: {e}")


def _is_app_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SnapCap.exe"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "SnapCap.exe" in out.stdout
    except Exception:
        return False


def _wait_for_app_exit(timeout_sec: float = 15.0) -> bool:
    """Best-effort wait for a running SnapCap.exe to exit before an update
    overwrites its files — the self-update caller (update_checker.py)
    already quits the app before launching this installer, but this covers
    the race where the process hasn't fully torn down yet, and any other
    case (manual double-click of an old downloaded installer) where it's
    still running. Returns True once it's gone (or was never running),
    False if it's still running after the timeout — the caller proceeds
    anyway rather than hanging forever unattended."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not _is_app_running():
            return True
        time.sleep(0.5)
    return not _is_app_running()


def run_silent_install(argv) -> int:
    """
    Unattended install, launched as `SnapCap_Setup.exe --silent [--relaunch]`
    — used by update_checker.py's self-update flow (subprocess.Popen, not
    waited on) and available for any other scripted/silent deployment.
    Zero dialogs, zero user interaction:
      - Installs to the existing install location (read from the registry
        entry a prior install wrote) when this is an update, or the default
        Program Files path for a first-time silent install.
      - User settings/library live under %USERPROFILE%\\.snapcap, entirely
        outside the install directory, so they're untouched either way —
        nothing here needs to special-case "preserve user data".
      - Desktop/Start Menu shortcuts are only (re)created on a first-time
        install; an update doesn't re-litigate the user's shortcut choices.
      - Writes the same uninstall registry entry the GUI wizard writes.
      - `--relaunch` starts SnapCap.exe again once the copy is done.
    Returns a real process exit code (0 = success) instead of calling
    QApplication.exec()/sys.exit() with a GUI — nothing here ever imports
    PyQt6, so this path works even on a machine where Qt fails to init
    (e.g. no display session during some remote/scripted install).
    """
    log_lines = []
    def _log(msg):
        log_lines.append(msg)

    def _finish(code: int) -> int:
        try:
            log_path = Path(os.environ.get("TEMP", str(Path.home()))) / "SnapCap_silent_install.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\\n--- silent install {time.strftime('%Y-%m-%d %H:%M:%S')} (exit {code}) ---\\n")
                f.write("\\n".join(log_lines) + "\\n")
        except Exception:
            pass
        return code

    try:
        if not _wait_for_app_exit():
            _log("WARN: SnapCap.exe still appeared to be running after waiting — proceeding anyway")

        existing_dir = _read_existing_install_dir()
        is_update = existing_dir is not None
        dest = existing_dir or (
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "SnapCap"
        )

        src = _find_app_payload_dir()
        if not src:
            _log("ERROR: bundled app payload (SnapCap/) not found next to the installer")
            return _finish(3)

        _log(f"Installing to {dest} (update={is_update})")
        try:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest, dirs_exist_ok=True)
        except OSError as e:
            # Disk full, permission denied (not elevated / UAC declined),
            # target file locked by a still-running process, etc.
            _log(f"ERROR: copy failed: {e}")
            return _finish(2)
        _log(f"Copied {sum(1 for _ in src.rglob('*'))} files")

        if not is_update:
            try:
                _create_shortcut(
                    dest / "SnapCap.exe",
                    Path(os.environ["USERPROFILE"]) / "Desktop" / "SnapCap.lnk",
                    log=_log,
                )
                sm_dir = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" /
                          "Start Menu" / "Programs" / "SnapCap")
                sm_dir.mkdir(parents=True, exist_ok=True)
                _create_shortcut(dest / "SnapCap.exe", sm_dir / "SnapCap.lnk", log=_log)
                _log("Shortcuts created (first-time install)")
            except Exception as e:
                _log(f"Shortcut step warning: {e}")
        else:
            _log("Update install — leaving existing shortcuts as-is")

        _write_registry_entry(dest, log=_log)
        _log("Registry entry written")

        if "--relaunch" in argv:
            try:
                subprocess.Popen(
                    [str(dest / "SnapCap.exe")],
                    creationflags=subprocess.DETACHED_PROCESS,
                )
                _log("Relaunched SnapCap.exe")
            except Exception as e:
                _log(f"Relaunch failed (non-fatal): {e}")

        _log("Silent install complete")
        return _finish(0)
    except Exception as e:
        _log(f"FATAL: {e}")
        return _finish(1)


if "--silent" in sys.argv:
    # Handled before importing PyQt6 at all — see run_silent_install's
    # docstring for why that matters for unattended/scripted use.
    sys.exit(run_silent_install(sys.argv))


from PyQt6.QtWidgets import (
    QApplication, QDialog, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QProgressBar,
    QTextEdit, QFileDialog, QMessageBox, QRadioButton, QButtonGroup, QWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QColor, QPainter, QFont, QIcon, QLinearGradient, QPalette

DARK  = "#0f0e17"
PANEL = "#16213e"
RED   = "#00d9a3"
BLUE  = "#3b82f6"
FG    = "#eaeaea"
MUTED = "#8892a4"
BORDER= "#1f3a6b"

# ── Bilingual strings (EN / HE) ─────────────────────────────────────────────
TR = {
    "en": {
        "choose_lang": "Choose your language",
        "lang_en": "🇬🇧  English",
        "lang_he": "🇮🇱  עברית (Hebrew)",
        "welcome_title": "Welcome to SnapCap Setup",
        "welcome_body": f"This wizard will install <b>SnapCap v{APP_VER}</b> on your computer.",
        "features_title": "Features:",
        "license_title": "License Agreement",
        "license_agree": "I accept the terms of the license agreement",
        "dir_title": "Choose Install Location",
        "dir_label": "Install SnapCap to:",
        "browse": "Browse…",
        "cb_desktop": "Create Desktop shortcut",
        "cb_startmenu": "Create Start Menu shortcut",
        "cb_startup": "Launch SnapCap when Windows starts",
        "installing_title": "Installing SnapCap…",
        "preparing": "Preparing…",
        "finish_title": "Installation Complete!",
        "finish_body": "<b>SnapCap has been installed successfully!</b><br><br>It runs in your system tray. Look for the teal <b>S</b> icon.",
        "cb_launch": "Launch SnapCap now",
        "btn_finish": "Finish  ✓",
        "btn_next": "Next  →",
        "btn_back": "←  Back",
        "btn_cancel": "Cancel",
        "btn_retry": "Retry",
        "app_running_msg": "SnapCap is currently running.\n\nPlease close it before continuing the installation.",
        "wizard_title": "SnapCap — Setup Wizard",
    },
    "he": {
        "choose_lang": "בחר שפה",
        "lang_en": "🇬🇧  English (אנגלית)",
        "lang_he": "🇮🇱  עברית",
        "welcome_title": "ברוכים הבאים להתקנת SnapCap",
        "welcome_body": f"אשף זה יתקין את <b>SnapCap גרסה {APP_VER}</b> על המחשב שלך.",
        "features_title": "תכונות:",
        "license_title": "הסכם רישיון",
        "license_agree": "אני מקבל את תנאי הסכם הרישיון",
        "dir_title": "בחר מיקום התקנה",
        "dir_label": "התקן את SnapCap אל:",
        "browse": "עיון…",
        "cb_desktop": "צור קיצור דרך בשולחן העבודה",
        "cb_startmenu": "צור קיצור דרך בתפריט התחל",
        "cb_startup": "הפעל את SnapCap בהפעלת Windows",
        "installing_title": "מתקין את SnapCap…",
        "preparing": "מכין...",
        "finish_title": "ההתקנה הושלמה!",
        "finish_body": "<b>SnapCap הותקן בהצלחה!</b><br><br>הוא פועל במגש המערכת. חפש את הסמל הטורקיז <b>S</b>.",
        "cb_launch": "הפעל את SnapCap עכשיו",
        "btn_finish": "סיום  ✓",
        "btn_next": "הבא  →",
        "btn_back": "←  הקודם",
        "btn_cancel": "ביטול",
        "btn_retry": "נסה שוב",
        "app_running_msg": "SnapCap פועל כרגע.\n\nיש לסגור אותו לפני שממשיכים בהתקנה.",
        "wizard_title": "SnapCap — אשף התקנה",
    },
}

def detect_lang():
    # Default is English for every tool (2026-09-14 decision) — the language
    # picker page still lets the user switch to Hebrew immediately, this just
    # controls which option is pre-selected when that page first appears.
    return "en"

LANG = {"code": detect_lang()}
def tr(key): return TR.get(LANG["code"], TR["en"]).get(key, key)

STYLE = f"""
QDialog, QWidget {{ background:{DARK}; color:{FG}; font-family:'Segoe UI'; font-size:13px; }}
QLabel {{ color:{FG}; }}
QPushButton {{
    background:#1f3a6b; border:none; border-radius:8px;
    padding:8px 20px; color:{FG};
}}
QPushButton:hover {{ background:{BLUE}; }}
QPushButton:disabled {{ background:#22223a; color:#5a5a72; }}
QPushButton#finish {{ background:{RED}; color:#1a1a2e; font-weight:bold; }}
QPushButton#finish:disabled {{ background:#22223a; color:#5a5a72; }}
QLineEdit {{
    background:{PANEL}; border:1px solid {BORDER}; border-radius:8px;
    padding:7px 11px; color:{FG};
}}
QLineEdit:focus {{ border-color: {RED}; }}
QCheckBox, QRadioButton {{ color:{FG}; spacing:10px; }}
QCheckBox::indicator {{ width:18px; height:18px; border:2px solid {BORDER}; border-radius:6px; background:{PANEL}; }}
QCheckBox::indicator:hover {{ border-color:{RED}; }}
QCheckBox::indicator:checked {{ background:{RED}; border-color:{RED}; }}
QRadioButton::indicator {{ width:18px; height:18px; border:2px solid {BORDER}; border-radius:9px; background:{PANEL}; }}
QRadioButton::indicator:hover {{ border-color:{RED}; }}
QRadioButton::indicator:checked {{ background:{RED}; border-color:{RED}; }}
QProgressBar {{
    background:{PANEL}; border:none; border-radius:7px; height:14px; text-align: center;
}}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {RED}, stop:1 {BLUE}); border-radius:7px; }}
QTextEdit {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:8px; color:#aaa; font-size:11px; }}
"""

# ── Banner ────────────────────────────────────────────────────────────────────
def make_banner(w=550, h=96) -> QPixmap:
    px = QPixmap(w, h)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor("#0f3460"))
    grad.setColorAt(1, QColor("#16213e"))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(px.rect(), grad)
    # Gradient S badge
    badge = QLinearGradient(20, 15, 80, 75)
    badge.setColorAt(0, QColor(RED))
    badge.setColorAt(1, QColor(BLUE))
    p.setBrush(badge)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(20, 16, 62, 62)
    p.setPen(QColor("white"))
    p.setFont(QFont("Arial", 32, QFont.Weight.Bold))
    p.drawText(20, 16, 62, 62, Qt.AlignmentFlag.AlignCenter, "S")
    # Title
    p.setFont(QFont("Segoe UI", 27, QFont.Weight.Bold))
    p.setPen(QColor("white"))
    p.drawText(98, 18, 400, 42, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "SnapCap")
    p.setFont(QFont("Segoe UI", 11))
    p.setPen(QColor(MUTED))
    p.drawText(100, 58, 420, 25, Qt.AlignmentFlag.AlignLeft, "The screenshot tool the market was missing")
    p.setFont(QFont("Segoe UI", 9))
    p.setPen(QColor(RED))
    p.drawText(w - 90, 12, 80, 20, Qt.AlignmentFlag.AlignRight, f"v{APP_VER}")
    p.end()
    return px

def make_icon(size=64) -> QIcon:
    """The window/title-bar icon. `--icon` at PyInstaller build time only sets
    the .exe FILE icon (what Explorer/taskbar shows for the file) — it does
    NOT set a QWidget's own titlebar icon at runtime; without an explicit
    setWindowIcon() call, Qt falls back to a generic default, which is the
    "no icon" the title bar was showing. Drawn the same way as the banner's
    badge instead of loading assets/icon.ico from disk, so it can't fail on
    a resource path that doesn't resolve inside the frozen installer exe."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor(RED))
    grad.setColorAt(1, QColor(BLUE))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setPen(QColor("white"))
    p.setFont(QFont("Arial", int(size * 0.45), QFont.Weight.Bold))
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    p.end()
    return QIcon(px)

# ── Pages (plain QWidget, no QWizard) ──────────────────────────────────────────
# NOTE: an earlier version of this installer used QWizard with registerField()
# mandatory fields + isComplete() overrides. That combination has repeatedly
# caused the Next button to appear stuck/unresponsive (a known QWizard
# footgun). We use the same QStackedWidget + manual button-state pattern as
# the main app's onboarding_wizard.py, which has never shown this bug.
class BasePage(QWidget):
    completeChanged = pyqtSignal()
    def refresh_texts(self):
        """Called whenever the page is shown or the language changes."""
        pass
    def is_complete(self) -> bool:
        return True
    def on_enter(self):
        """Called every time this page becomes the visible page."""
        pass

class LanguageToggle(QWidget):
    """A compact inline language switch — NOT a dedicated first page. A whole
    page asking to pick a language before the user has even seen what's
    being installed felt like a bad first impression (bare page, no
    branding) and was flagged as such — this now lives as a small control
    on the install-location page instead, where it's still available early
    but doesn't front-load the whole wizard with it."""
    def __init__(self, on_change):
        super().__init__()
        self._on_change_cb = on_change
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._group = QButtonGroup(self)
        self._en = QRadioButton()
        self._he = QRadioButton()
        for r in (self._en, self._he):
            r.setStyleSheet(f"""
                QRadioButton {{ font-size:12px; padding:6px 12px; background:{PANEL};
                                border:1px solid {BORDER}; border-radius:14px; }}
                QRadioButton:hover {{ border-color:{RED}; }}
                QRadioButton::indicator {{ width:12px; height:12px; }}
            """)
            self._group.addButton(r)
            row.addWidget(r)
        row.addStretch()
        (self._he if LANG["code"] == "he" else self._en).setChecked(True)
        self._group.buttonClicked.connect(self._on_change)
        self.refresh_texts()

    def refresh_texts(self):
        self._en.setText(tr("lang_en"))
        self._he.setText(tr("lang_he"))

    def _on_change(self):
        LANG["code"] = "he" if self._he.isChecked() else "en"
        self._on_change_cb()

class WelcomePage(BasePage):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        l.setSpacing(12)
        banner = QLabel(); banner.setPixmap(make_banner()); l.addWidget(banner)
        l.addSpacing(8)
        self._features = QLabel()
        self._features.setWordWrap(True)
        self._features.setStyleSheet(f"color:{FG}; font-size:13px; line-height:1.6;")
        l.addWidget(self._features)
        l.addStretch()
        self.refresh_texts()

    def refresh_texts(self):
        self._features.setText(
            f"<b>{tr('welcome_title')}</b><br><br>"
            f"{tr('welcome_body')}<br><br>"
            f"<b>{tr('features_title')}</b><br>"
            "&#x2714; Region, window, fullscreen &amp; scrolling screenshot<br>"
            "&#x2714; Full annotation suite: arrows, steps, callouts, blur<br>"
            "&#x2714; AI-powered PII auto-redaction (emails, phones, cards)<br>"
            "&#x2714; OCR with table extraction (CSV)<br>"
            "&#x2714; Claude AI: summarize, alt-text, bug reports<br>"
            "&#x2714; Searchable screenshot library with OCR index<br>"
            "&#x2714; Imgur, Slack, Teams, webhook, clipboard sharing<br>"
        )

class LicensePage(BasePage):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(
            "MIT License\n\n"
            "Copyright (c) 2026 SnapCap\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining a copy "
            "of this software and associated documentation files (the 'Software'), to deal "
            "in the Software without restriction, including without limitation the rights "
            "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell "
            "copies of the Software, and to permit persons to whom the Software is "
            "furnished to do so, subject to the following conditions:\n\n"
            "The above copyright notice and this permission notice shall be included in all "
            "copies or substantial portions of the Software.\n\n"
            "THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR "
            "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, "
            "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT."
        )
        l.addWidget(te)
        self._agree = QCheckBox()
        self._agree.stateChanged.connect(self.completeChanged)
        l.addWidget(self._agree)
        self.refresh_texts()
    def refresh_texts(self):
        self._agree.setText(tr("license_agree"))
    def is_complete(self):
        return self._agree.isChecked()

class DirPage(BasePage):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)

        self._lang_toggle = LanguageToggle(self._on_language_changed)
        l.addWidget(self._lang_toggle)
        l.addSpacing(10)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{BORDER};")
        l.addWidget(sep)
        l.addSpacing(14)

        # Default to Program Files, matching where other Windows apps install.
        # The installer EXE requests admin elevation (UAC) via --uac-admin at
        # build time, so writing here works out of the box.
        default = str(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "SnapCap")
        self._label = QLabel()
        l.addWidget(self._label)
        row = QHBoxLayout()
        self._path = QLineEdit(default)
        self._path.textChanged.connect(self.completeChanged)
        row.addWidget(self._path)
        self._browse_btn = QPushButton()
        self._browse_btn.clicked.connect(self._browse)
        row.addWidget(self._browse_btn)
        l.addLayout(row)
        self._desktop = QCheckBox(); self._desktop.setChecked(True)
        self._startmenu = QCheckBox(); self._startmenu.setChecked(True)
        self._startup = QCheckBox(); self._startup.setChecked(False)
        l.addWidget(self._desktop)
        l.addWidget(self._startmenu)
        l.addWidget(self._startup)
        l.addStretch()
        self.refresh_texts()
    def refresh_texts(self):
        self._lang_toggle.refresh_texts()
        self._label.setText(tr("dir_label"))
        self._browse_btn.setText(tr("browse"))
        self._desktop.setText(tr("cb_desktop"))
        self._startmenu.setText(tr("cb_startmenu"))
        self._startup.setText(tr("cb_startup"))
    def _on_language_changed(self):
        self.completeChanged.emit()  # wizard's handler calls _retranslate_all() on any signal
    def is_complete(self):
        return bool(self._path.text().strip())
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("browse"), self._path.text())
        if d: self._path.setText(d + "\\SnapCap")
    def values(self):
        return {
            "install_dir": self._path.text().strip(),
            "desktop": self._desktop.isChecked(),
            "startmenu": self._startmenu.isChecked(),
            "startup": self._startup.isChecked(),
        }

class InstallPage(BasePage):
    def __init__(self, get_dir_values):
        super().__init__()
        self._get_dir_values = get_dir_values
        self._done = False
        self._started = False
        l = QVBoxLayout(self)
        self._status = QLabel()
        l.addWidget(self._status)
        self._bar = QProgressBar(); self._bar.setRange(0, 100); self._bar.setValue(0)
        l.addWidget(self._bar)
        self._log = QTextEdit(); self._log.setReadOnly(True); self._log.setFixedHeight(160)
        l.addWidget(self._log)
        l.addStretch()
        self.refresh_texts()
    def refresh_texts(self):
        if not self._done:
            self._status.setText(tr("preparing"))
    def on_enter(self):
        if not self._started:
            self._started = True
            QTimer.singleShot(200, self._start_install)
    def _log_line(self, msg):
        self._log.append(msg)
    def _is_app_running(self) -> bool:
        return _is_app_running()
    def _ensure_app_not_running(self) -> bool:
        """Blocks (with a retry prompt) until SnapCap isn't running, or the
        user cancels. Prevents overwriting a locked EXE mid-install/update."""
        while self._is_app_running():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("wizard_title"))
            box.setText(tr("app_running_msg"))
            retry_btn = box.addButton(tr("btn_retry"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("btn_cancel"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not retry_btn:
                return False
        return True
    def _start_install(self):
        if not self._ensure_app_not_running():
            self._status.setText(tr("btn_cancel"))
            QApplication.instance().quit()
            return
        vals = self._get_dir_values()
        self._worker = InstallWorker(vals["install_dir"], vals["desktop"], vals["startmenu"], vals["startup"])
        self._worker.progress.connect(self._bar.setValue)
        self._worker.status.connect(self._status.setText)
        self._worker.log.connect(self._log_line)
        self._worker.finished.connect(self._on_done)
        self._worker.start()
    def _on_done(self):
        self._done = True
        self._bar.setValue(100)
        self._status.setText("✓")
        self.completeChanged.emit()
    def is_complete(self):
        return self._done

class FinishPage(BasePage):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        self._lbl = QLabel()
        self._lbl.setWordWrap(True)
        l.addWidget(self._lbl)
        self._launch = QCheckBox()
        self._launch.setChecked(True)
        l.addWidget(self._launch)
        l.addStretch()
        self._copyright = QLabel(f"© 2026 {PUBLISHER}. All rights reserved.")
        self._copyright.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self._copyright.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(self._copyright)
        self.refresh_texts()
    def refresh_texts(self):
        self._lbl.setText(
            f"{tr('finish_body')}<br><br>"
            "Ctrl+Shift+S — Capture region<br>"
            "Ctrl+Shift+F — Capture fullscreen<br>"
            "Ctrl+Shift+W — Capture window<br>"
            "Ctrl+Shift+L — Scrolling capture<br>"
        )
        self._launch.setText(tr("cb_launch"))
    def launch_checked(self):
        return self._launch.isChecked()

# ── Install Worker ─────────────────────────────────────────────────────────────
class InstallWorker(QThread):
    progress = pyqtSignal(int)
    status   = pyqtSignal(str)
    log      = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, install_dir, desktop, startmenu, startup):
        super().__init__()
        self.install_dir = install_dir
        self.desktop = desktop
        self.startmenu = startmenu
        self.startup = startup

    def run(self):
        try:
            dest = Path(self.install_dir)
            self.status.emit("Creating directory…")
            self.log.emit(f"→ {dest}")
            dest.mkdir(parents=True, exist_ok=True)
            self.progress.emit(10)

            # Copy the whole onedir app folder (SnapCap.exe + _internal/
            # dependencies) — bundled next to the installer or in its temp
            # extraction dir. copytree with dirs_exist_ok=True so an update
            # over an existing install overwrites in place instead of
            # failing because the destination already exists.
            self.status.emit("Copying SnapCap files…")
            src = _find_app_payload_dir()
            if src and src.exists():
                shutil.copytree(src, dest, dirs_exist_ok=True)
                self.log.emit(f"✓ Copied {src.name}/ ({sum(1 for _ in src.rglob('*'))} files)")
            else:
                self.log.emit("⚠ App folder not found — installer may be incomplete")
            self.progress.emit(40)

            # Shortcuts
            if self.desktop:
                self.status.emit("Creating Desktop shortcut…")
                self._create_shortcut(
                    dest / "SnapCap.exe",
                    Path(os.environ["USERPROFILE"]) / "Desktop" / "SnapCap.lnk",
                )
                self.log.emit("✓ Desktop shortcut")
            self.progress.emit(55)

            if self.startmenu:
                self.status.emit("Creating Start Menu shortcut…")
                sm_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "SnapCap"
                sm_dir.mkdir(parents=True, exist_ok=True)
                self._create_shortcut(dest / "SnapCap.exe", sm_dir / "SnapCap.lnk")
                self.log.emit("✓ Start Menu shortcut")
            self.progress.emit(70)

            if self.startup:
                self.status.emit("Adding to startup…")
                startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                # --autostart: lets main.py recognize a boot-time launch and
                # skip the splash screen / startup balloon by default, same as
                # the HKCU Run-key path SnapCap writes when toggled from Settings.
                self._create_shortcut(dest / "SnapCap.exe", startup_dir / "SnapCap.lnk", arguments="--autostart")
                self.log.emit("✓ Added to startup")
            self.progress.emit(80)

            # Registry entry for Add/Remove Programs
            self.status.emit("Writing registry entry…")
            self._write_registry(dest)
            self.log.emit("✓ Registry entry written")
            self.progress.emit(95)

            self.status.emit("Done!")
            self.log.emit("✓ Installation complete")
            self.progress.emit(100)
            self.finished.emit()

        except Exception as e:
            self.log.emit(f"ERROR: {e}")
            self.status.emit(f"Error: {e}")
            self.finished.emit()

    def _create_shortcut(self, target: Path, link: Path, arguments: str = ""):
        _create_shortcut(target, link, arguments, log=self.log.emit)

    def _write_registry(self, install_dir: Path):
        _write_registry_entry(install_dir, log=self.log.emit)

# ── Wizard (QStackedWidget-based — see BasePage note above) ───────────────────
class SetupWizard(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("wizard_title"))
        self.setWindowIcon(make_icon())
        self.setMinimumSize(640, 560)

        self._dir_page = DirPage()
        self._pages = [
            WelcomePage(),
            LicensePage(),
            self._dir_page,
            InstallPage(self._dir_page.values),
            FinishPage(),
        ]
        self._index = 0
        self._accepted = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        for p in self._pages:
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(28, 24, 28, 12)
            wl.addWidget(p)
            self._stack.addWidget(wrap)
            p.completeChanged.connect(self._on_page_changed_signal)
        root.addWidget(self._stack, 1)

        nav = QWidget()
        # Forced LTR regardless of page language: Next always on the right,
        # Back always on the left. Letting this mirror under RTL (as QWizard
        # used to do automatically) silently swaps their positions, which
        # reads to a user as "the Next button is broken".
        nav.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        nav.setStyleSheet(f"background:{PANEL}; border-top:1px solid {BORDER};")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(20, 14, 20, 14)
        self._cancel_btn = QPushButton()
        self._cancel_btn.clicked.connect(self.reject)
        self._back_btn = QPushButton()
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn = QPushButton()
        self._next_btn.setObjectName("finish")
        # The app-level `QPushButton#finish` ID-selector rule in STYLE does
        # not reliably apply to this specific button on Windows (confirmed by
        # rendering it: the button kept the plain QPushButton look instead of
        # the intended teal fill, leaving its #1a1a2e text nearly invisible -
        # this is what users were reporting as unreadable installer buttons).
        # Setting the same rule directly on the widget bypasses whatever is
        # blocking the selector match and is guaranteed to apply.
        self._next_btn.setStyleSheet(f"""
            QPushButton {{ background:{RED}; color:#1a1a2e; font-weight:bold;
                           border:none; border-radius:8px; padding:8px 20px; }}
            QPushButton:hover {{ background:#00f0b5; }}
            QPushButton:disabled {{ background:#22223a; color:#5a5a72; }}
        """)
        self._next_btn.clicked.connect(self._go_next)
        nl.addWidget(self._cancel_btn)
        nl.addStretch()
        nl.addWidget(self._back_btn)
        nl.addWidget(self._next_btn)
        root.addWidget(nav)

        self._retranslate_all()
        self._goto(0)

    def _on_page_changed_signal(self):
        # A page's own state changed — checkbox, text, install finished, or
        # the language toggle on the install-location page. Retranslating is
        # cheap and idempotent, so just always do it rather than special-case
        # which page can trigger a language change.
        self._retranslate_all()
        self._update_nav()

    def _retranslate_all(self):
        self.setWindowTitle(tr("wizard_title"))
        # RTL applies to page content (paragraph/checkbox alignment) so
        # Hebrew reads naturally; the nav bar stays forced LTR (see above).
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if LANG["code"] == "he" else Qt.LayoutDirection.LeftToRight
        )
        for p in self._pages:
            p.refresh_texts()
        self._cancel_btn.setText(tr("btn_cancel"))
        self._update_nav()

    def _goto(self, index: int):
        self._index = index
        self._stack.setCurrentIndex(index)
        self._pages[index].on_enter()
        self._update_nav()

    def _update_nav(self):
        is_last = self._index == len(self._pages) - 1
        is_install_page = isinstance(self._pages[self._index], InstallPage)
        self._back_btn.setVisible(0 < self._index < len(self._pages) - 2)
        self._cancel_btn.setVisible(not is_last)
        self._next_btn.setText(tr("btn_finish") if is_last else tr("btn_next"))
        self._next_btn.setEnabled(self._pages[self._index].is_complete())
        if is_install_page:
            self._back_btn.setVisible(False)

    def _go_back(self):
        if self._index > 0:
            self._goto(self._index - 1)

    def _go_next(self):
        if self._index == len(self._pages) - 1:
            self._accepted = True
            self.accept()
            return
        self._goto(self._index + 1)

    def launch_requested(self) -> bool:
        return self._accepted and self._pages[-1].launch_checked()

    def install_dir(self) -> str:
        return self._dir_page.values()["install_dir"]


def main():
    app = QApplication(sys.argv)
    # Force Fusion style: Qt6's native Windows 11 style ignores custom
    # QPushButton background/border QSS for several button states (a known
    # Qt-on-Windows-11 limitation), which made the Next/Finish button render
    # as near-invisible native chrome instead of the intended solid teal
    # fill. Fusion fully respects the stylesheet everywhere.
    app.setStyle("Fusion")
    # Fusion + a stylesheet still isn't enough on Windows 11: when the OS is
    # in dark mode, Qt6 seeds QPalette from the system theme and some builds
    # keep using that palette's (light-mode, near-black) ButtonText/WindowText
    # for QPushButton regardless of the QSS `color` property - this is what
    # made "Next"/"Finish" render as unreadable dark text on a dark/teal fill.
    # Setting an explicit dark QPalette (including the Disabled group) closes
    # that gap for every widget, not just the ones the stylesheet covers.
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(DARK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(FG))
    palette.setColor(QPalette.ColorRole.Base, QColor(PANEL))
    palette.setColor(QPalette.ColorRole.Text, QColor(FG))
    palette.setColor(QPalette.ColorRole.Button, QColor(BORDER))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(FG))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("white"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(RED))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1a1a2e"))
    disabled_fg = QColor("#5a5a72")
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled_fg)
    app.setPalette(palette)
    app.setApplicationName("SnapCap Setup")
    app.setWindowIcon(make_icon())  # covers QMessageBox popups too, not just the main dialog
    app.setStyleSheet(STYLE)

    wiz = SetupWizard()
    wiz.exec()

    if wiz.launch_requested():
        exe = Path(wiz.install_dir()) / "SnapCap.exe"
        if exe.exists():
            import subprocess
            subprocess.Popen([str(exe)], creationflags=subprocess.DETACHED_PROCESS)

    sys.exit(0)

if __name__ == "__main__":
    main()
'''.replace("__APP_VERSION__", APP_VER)
# ^ substituted here (not baked in above as a literal) so the embedded
# installer's version string can never drift from version.json/APP_VERSION —
# exactly the "version updated in one place but not another" bug the project
# standard calls out (STANDARDS.md, "sync גרסה מלא").

def create_installer_script():
    script_path = Path("build/installer_app.py")
    script_path.write_text(INSTALLER_SCRIPT, encoding="utf-8")
    print(f"OK Installer script written: {script_path}")
    return script_path


def build_installer_exe(script_path: Path):
    print("Building installer EXE with PyInstaller...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "SnapCap_Setup",
        "--onefile",
        "--windowed",
        # Absolute paths below: PyInstaller resolves relative --icon/--add-data
        # sources against --specpath (build/), not the CWD, so a relative
        # "build/dist/..." here would double up to "build/build/dist/...".
        "--icon", str(Path("assets/icon.ico").resolve()),
        # Source is a directory (the whole --onedir output folder) — PyInstaller
        # copies its entire tree into the bundle under dest "SnapCap/", which
        # _find_app_dir() above looks for at runtime.
        "--add-data", f'{Path("build/dist/SnapCap").resolve()};SnapCap',
        "--hidden-import", "PyQt6.QtCore",
        "--hidden-import", "PyQt6.QtGui",
        "--hidden-import", "PyQt6.QtWidgets",
        "--hidden-import", "win32com.client",
        "--hidden-import", "winreg",
        "--uac-admin",   # embeds a manifest so Windows prompts for elevation —
                         # required to write to C:\Program Files by default
        "--distpath", "build/dist",
        "--workpath", "build/pyinstaller-work",
        "--specpath", "build",
        "--noconfirm",
        str(script_path),
    ]
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode == 0


def main():
    print("=" * 55)
    print("  SnapCap — Building Installer")
    print("=" * 55)

    app_dir = Path("build/dist/SnapCap")
    if not (app_dir / "SnapCap.exe").exists():
        print("ERROR: build/dist/SnapCap/SnapCap.exe not found. Run build_exe.bat first.")
        sys.exit(1)

    script = create_installer_script()
    ok = build_installer_exe(script)

    built_installer = Path("build/dist/SnapCap_Setup.exe")
    if ok and built_installer.exists():
        size = built_installer.stat().st_size / 1024 / 1024
        # Move the single final deliverable to the project root (per the
        # project's standard: the installer the user downloads lives at
        # the root, not buried in a build/dist/ scratch folder), versioned.
        final_path = Path(f"SnapCap-Setup-{APP_VER}.exe")
        # Remove any older versioned installer already sitting in root first,
        # so we never end up with two side by side.
        for old in Path(".").glob("SnapCap-Setup-*.exe"):
            old.unlink()
        shutil.move(str(built_installer), str(final_path))
        script.unlink(missing_ok=True)
        try:
            shutil.rmtree(app_dir, ignore_errors=True)
        except Exception:
            pass
        print(f"\nSUCCESS! Single installer file: {final_path} ({size:.1f} MB)")
    else:
        print("\nBUILD FAILED. Check output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
