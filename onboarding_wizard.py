"""
Onboarding wizard — shown on first run only.
Multi-page QDialog: language → welcome → hotkeys → AI setup → save location → finish.
Supports English and Hebrew (RTL) with a live language switch.
"""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QStackedWidget, QWidget, QFrame,
    QCheckBox, QApplication, QButtonGroup, QRadioButton,
)
from PyQt6.QtGui import QFont, QColor, QPainter, QPixmap, QLinearGradient
from PyQt6.QtCore import Qt

import a11y
import config as cfg
from i18n import t, is_rtl, current_language, detect_system_language

# ── Style constants ────────────────────────────────────────────────────────────
# Brand palette (default). STANDARDS.md §20.2 — when a Windows Contrast Theme
# is active, _refresh_palette() below reassigns these module-level names to
# the user's own system colors instead, the same way editor_window.apply_theme()
# already does for the editor/library. Every helper in this file (_btn, _h,
# _p, _sep, _hotkey_row) and every page class reads these names at build
# time, so refreshing them before building the dialog/pages is enough —
# no other code needs to change.
_BRAND_BG      = "#0f0e17"
_BRAND_CARD    = "#16213e"
_BRAND_ACCENT  = "#00d9a3"
_BRAND_ACCENT2 = "#3b82f6"
_BRAND_TEXT    = "#eaeaea"
_BRAND_MUTED   = "#8892a4"
_BRAND_BORDER  = "#1f3a6b"
_BRAND_BTN_PRIMARY_TEXT = "#1a1a2e"

_BG      = _BRAND_BG
_CARD    = _BRAND_CARD
_ACCENT  = _BRAND_ACCENT
_ACCENT2 = _BRAND_ACCENT2
_TEXT    = _BRAND_TEXT
_MUTED   = _BRAND_MUTED
_BORDER  = _BRAND_BORDER
_BTN_PRIMARY_TEXT = _BRAND_BTN_PRIMARY_TEXT


def _refresh_palette():
    """Call before building the dialog or any page. Swaps the module-level
    color constants to the user's system colors while a Windows Contrast
    Theme is active, or restores the brand palette otherwise."""
    global _BG, _CARD, _ACCENT, _ACCENT2, _TEXT, _MUTED, _BORDER, _BTN_PRIMARY_TEXT
    if a11y.is_high_contrast():
        c = a11y.system_colors()
        _BG, _CARD = c["window"], c["window"]
        _ACCENT, _ACCENT2 = c["highlight"], c["highlight"]
        _TEXT, _MUTED = c["window_text"], c["window_text"]
        _BORDER = c["window_text"]
        _BTN_PRIMARY_TEXT = c["highlight_text"]
    else:
        _BG, _CARD = _BRAND_BG, _BRAND_CARD
        _ACCENT, _ACCENT2 = _BRAND_ACCENT, _BRAND_ACCENT2
        _TEXT, _MUTED = _BRAND_TEXT, _BRAND_MUTED
        _BORDER = _BRAND_BORDER
        _BTN_PRIMARY_TEXT = _BRAND_BTN_PRIMARY_TEXT


def _base_ss() -> str:
    return f"""
    QDialog, QWidget {{ background: {_BG}; color: {_TEXT}; font-family: 'Segoe UI'; }}
    QLabel {{ color: {_TEXT}; }}
    QLineEdit {{
        background: {_CARD}; color: {_TEXT}; border: 1px solid {_BORDER};
        border-radius: 6px; padding: 8px 12px; font-size: 13px;
    }}
    QLineEdit:focus {{ border-color: {_ACCENT}; border-width: 2px; }}
    QCheckBox, QRadioButton {{ color: {_TEXT}; font-size: 13px; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px;
                             border: 2px solid {_BORDER}; background: {_CARD}; }}
    QCheckBox::indicator:checked {{ background: {_ACCENT}; border-color: {_ACCENT}; }}
    QCheckBox:focus, QRadioButton:focus {{ outline: none; }}
    QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border-color: {_ACCENT2}; }}
    QRadioButton::indicator {{ width: 18px; height: 18px; border-radius: 9px;
                                border: 2px solid {_BORDER}; background: {_CARD}; }}
    QRadioButton::indicator:checked {{ background: {_ACCENT}; border-color: {_ACCENT}; }}
    QPushButton:focus {{ outline: none; border: 2px solid {_ACCENT2}; }}
"""

def _btn(text: str, primary=True) -> QPushButton:
    b = QPushButton(text)
    hc = a11y.is_high_contrast()
    if primary:
        # Brand-mode hover/pressed shades stay as originally designed;
        # under High Contrast the accent (already the user's own
        # "highlight" system color) is used for hover instead, so nothing
        # here paints a color the user didn't choose.
        hover = _ACCENT2 if hc else "#00b386"
        pressed_rule = "" if hc else "QPushButton:pressed { background: #009973; }"
        b.setStyleSheet(f"""
            QPushButton {{ background: {_ACCENT}; color: {_BTN_PRIMARY_TEXT}; border: none;
                           border-radius: 8px; padding: 10px 28px; font-size: 14px;
                           font-weight: bold; }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:focus {{ border: 2px solid {_TEXT}; }}
            {pressed_rule}
        """)
    else:
        b.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {_MUTED}; border: 1px solid {_BORDER};
                           border-radius: 8px; padding: 10px 22px; font-size: 13px; }}
            QPushButton:hover {{ color: {_TEXT}; border-color: {_TEXT}; }}
            QPushButton:focus {{ border: 2px solid {_ACCENT2}; }}
        """)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _h(text: str, size: int = 22, bold=True) -> QLabel:
    lbl = QLabel(text)
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    lbl.setFont(f)
    lbl.setStyleSheet(f"color: {_TEXT};")
    return lbl


def _p(text: str, size: int = 13, muted=False) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", size))
    lbl.setStyleSheet(f"color: {_MUTED if muted else _TEXT};")
    lbl.setWordWrap(True)
    return lbl


def _sep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"background: {_BORDER}; border: none; max-height: 1px;")
    return sep


def _hotkey_row(action: str, keys: str) -> QWidget:
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 4, 0, 4)
    lbl_a = QLabel(action)
    lbl_a.setStyleSheet(f"color: {_TEXT}; font-size: 13px;")
    lbl_k = QLabel(keys)
    lbl_k.setStyleSheet(f"""
        color: {_ACCENT}; font-family: 'Consolas', monospace; font-size: 12px;
        background: {_CARD}; border: 1px solid {_BORDER}; border-radius: 4px;
        padding: 2px 8px;
    """)
    row.addWidget(lbl_a)
    row.addStretch()
    row.addWidget(lbl_k)
    return w


# ── Pages ──────────────────────────────────────────────────────────────────────

class _LanguagePage(QWidget):
    """Page 0 — pick English or Hebrew. Emits nothing; wizard reads .selected()."""
    def __init__(self, initial_lang: str):
        super().__init__()
        v = QVBoxLayout(self)
        v.setSpacing(18)
        v.setContentsMargins(40, 60, 40, 20)

        icon = QLabel("🌐")
        icon.setFont(QFont("Segoe UI", 44))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(icon)

        title = _h(t("choose_language", "en"), 24)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(title)

        sub = _p(t("choose_language_sub", "en"), 13, muted=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(sub)
        v.addSpacing(20)

        self._group = QButtonGroup(self)
        self._en_radio = QRadioButton("🇬🇧   " + t("lang_english", "en"))
        self._he_radio = QRadioButton("🇮🇱   " + t("lang_hebrew", "he"))
        for radio in (self._en_radio, self._he_radio):
            radio.setStyleSheet(f"""
                QRadioButton {{ font-size: 15px; padding: 14px 20px; background: {_CARD};
                                border: 1px solid {_BORDER}; border-radius: 10px; }}
                QRadioButton:hover {{ border-color: {_ACCENT}; }}
            """)
            self._group.addButton(radio)
            v.addWidget(radio)
            v.addSpacing(10)

        if initial_lang == "he":
            self._he_radio.setChecked(True)
        else:
            self._en_radio.setChecked(True)

        v.addStretch()

    def selected(self) -> str:
        return "he" if self._he_radio.isChecked() else "en"


class _WelcomePage(QWidget):
    def __init__(self, lang: str):
        super().__init__()
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(40, 24, 40, 16)

        icon_lbl = QLabel()
        pxm = QPixmap(56, 56)
        pxm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pxm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, 56, 56)
        grad.setColorAt(0, QColor("#00d9a3"))
        grad.setColorAt(1, QColor("#3b82f6"))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, 56, 56)
        p.setPen(QColor("white"))
        p.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        p.drawText(pxm.rect(), Qt.AlignmentFlag.AlignCenter, "S")
        p.end()
        icon_lbl.setPixmap(pxm)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(icon_lbl)

        title = _h(t("welcome_title", lang), 22)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        v.addWidget(title)

        # A fixed, generous minimum height (rather than relying on sizeHint,
        # which can under-measure multi-line Hebrew/BiDi text) keeps this
        # label from visually colliding with the feature rows below it.
        sub = _p(t("welcome_sub", lang), 12, muted=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setMinimumHeight(84)
        v.addWidget(sub)

        features = [
            ("🎯", t("feat_capture", lang)),
            ("✏️", t("feat_annotate", lang)),
            ("🔒", t("feat_redact", lang)),
            ("🤖", t("feat_ai", lang)),
            ("📚", t("feat_library", lang)),
        ]
        for icon, text in features:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 2, 12, 2)
            icon_lbl2 = QLabel(icon)
            icon_lbl2.setFixedWidth(24)
            rl.addWidget(icon_lbl2)
            feat_lbl = _p(text, 11)
            feat_lbl.setWordWrap(True)
            rl.addWidget(feat_lbl, 1)
            v.addWidget(row)

        v.addStretch()


class _HotkeysPage(QWidget):
    def __init__(self, conf: dict, lang: str):
        super().__init__()
        v = QVBoxLayout(self)
        v.setSpacing(14)
        v.setContentsMargins(40, 40, 40, 20)

        v.addWidget(_h(t("hotkeys_title", lang), 22))
        v.addWidget(_p(t("hotkeys_sub", lang), muted=True))
        v.addSpacing(8)
        v.addWidget(_sep())
        v.addSpacing(8)

        hk = conf.get("hotkeys", {})
        rows = [
            (t("hk_region", lang),     hk.get("capture_region",    "Ctrl+Shift+S")),
            (t("hk_fullscreen", lang), hk.get("capture_fullscreen", "Ctrl+Shift+F")),
            (t("hk_window", lang),     hk.get("capture_window",     "Ctrl+Shift+W")),
            (t("hk_scroll", lang),     hk.get("capture_scroll",     "Ctrl+Shift+L")),
            (t("hk_library", lang),    hk.get("open_library",       "Ctrl+Shift+O")),
            (t("hk_text_ocr", lang),   hk.get("capture_text_ocr",   "Ctrl+Shift+T")),
        ]
        for action, keys in rows:
            v.addWidget(_hotkey_row(action, keys.upper()))

        v.addWidget(_sep())
        v.addSpacing(6)
        v.addWidget(_p(t("hotkeys_note", lang), muted=True))
        v.addStretch()

        tip = QWidget()
        tip.setStyleSheet(f"background: {_CARD}; border-radius: 8px;")
        tl = QHBoxLayout(tip)
        tl.setContentsMargins(16, 12, 16, 12)
        tl.addWidget(QLabel("💡"))
        tl.addWidget(_p(t("hotkeys_tip", lang), 12))
        tl.addStretch()
        v.addWidget(tip)
        v.addStretch()


class _AISetupPage(QWidget):
    def __init__(self, conf: dict, lang: str):
        super().__init__()
        self._conf = conf
        v = QVBoxLayout(self)
        v.setSpacing(14)
        v.setContentsMargins(40, 40, 40, 20)

        v.addWidget(_h(t("ai_title", lang), 22))
        v.addWidget(_p(t("ai_sub", lang), muted=True))
        v.addSpacing(8)

        key_lbl = QLabel(t("ai_key_label", lang))
        key_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        v.addWidget(key_lbl)

        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText(t("ai_key_placeholder", lang))
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setText(conf.get("anthropic_api_key", ""))
        v.addWidget(self._key_edit)

        show_cb = QCheckBox(t("show_key", lang))
        show_cb.toggled.connect(
            lambda c: self._key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password
            )
        )
        v.addWidget(show_cb)
        v.addSpacing(4)

        self._auto_redact_cb = QCheckBox(t("ai_auto_redact", lang))
        self._auto_redact_cb.setChecked(conf.get("auto_redact", False))
        v.addWidget(self._auto_redact_cb)

        v.addSpacing(16)
        info = QWidget()
        info.setStyleSheet(f"background: {_CARD}; border-radius: 8px; border: 1px solid {_BORDER};")
        il = QVBoxLayout(info)
        il.setContentsMargins(16, 12, 16, 12)
        il.addWidget(_p(t("ai_key_where", lang), 12))
        link = QLabel('<a href="https://console.anthropic.com" style="color:#00d9a3;">console.anthropic.com → API Keys</a>')
        link.setOpenExternalLinks(True)
        il.addWidget(link)
        il.addWidget(_p(t("ai_key_skip_note", lang), 11, muted=True))
        v.addWidget(info)
        v.addStretch()

    def values(self) -> dict:
        return {
            "anthropic_api_key": self._key_edit.text().strip(),
            "ai_enabled": bool(self._key_edit.text().strip()),
            "auto_redact": self._auto_redact_cb.isChecked(),
        }


class _SaveDirPage(QWidget):
    def __init__(self, conf: dict, lang: str):
        super().__init__()
        self._conf = conf
        self._lang = lang
        v = QVBoxLayout(self)
        v.setSpacing(14)
        v.setContentsMargins(40, 40, 40, 20)

        v.addWidget(_h(t("save_title", lang), 22))
        v.addWidget(_p(t("save_sub", lang), muted=True))
        v.addSpacing(8)

        row = QHBoxLayout()
        self._dir_edit = QLineEdit(conf.get("save_dir", str(Path.home() / "Pictures" / "SnapCap")))
        browse = _btn(t("browse", lang), primary=False)
        browse.clicked.connect(self._browse)
        row.addWidget(self._dir_edit)
        row.addWidget(browse)
        v.addLayout(row)
        v.addSpacing(8)

        self._auto_copy_cb = QCheckBox(t("save_auto_copy", lang))
        self._auto_copy_cb.setChecked(conf.get("auto_copy", True))
        self._auto_save_cb = QCheckBox(t("save_auto_save", lang))
        self._auto_save_cb.setChecked(conf.get("auto_save", True))
        v.addWidget(self._auto_copy_cb)
        v.addWidget(self._auto_save_cb)
        v.addSpacing(16)

        startup_cb = QCheckBox(t("save_startup", lang))
        startup_cb.setChecked(self._is_startup())
        startup_cb.toggled.connect(self._toggle_startup)
        v.addWidget(startup_cb)
        v.addStretch()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, t("browse", self._lang))
        if d:
            self._dir_edit.setText(d)

    def _is_startup(self) -> bool:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                 winreg.KEY_READ)
            winreg.QueryValueEx(key, "SnapCap")
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    def _toggle_startup(self, enable: bool):
        try:
            import winreg, sys
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                 winreg.KEY_SET_VALUE)
            if enable:
                exe = sys.executable
                winreg.SetValueEx(key, "SnapCap", 0, winreg.REG_SZ, f'"{exe}" --autostart')
            else:
                try:
                    winreg.DeleteValue(key, "SnapCap")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def values(self) -> dict:
        return {
            "save_dir":   self._dir_edit.text().strip() or str(Path.home() / "Pictures" / "SnapCap"),
            "auto_copy":  self._auto_copy_cb.isChecked(),
            "auto_save":  self._auto_save_cb.isChecked(),
        }


class _FinishPage(QWidget):
    def __init__(self, conf: dict, lang: str):
        super().__init__()
        v = QVBoxLayout(self)
        v.setSpacing(18)
        v.setContentsMargins(40, 60, 40, 40)

        icon = QLabel("🎉")
        icon.setFont(QFont("Segoe UI", 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(icon)

        title = _h(t("finish_title", lang), 26)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(title)

        hotkey = conf.get("hotkeys", {}).get("capture_region", "Ctrl+Shift+S").upper()
        msg = _p(t("finish_sub", lang, hotkey=hotkey), 14, muted=False)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(msg)
        v.addStretch()

        tip = QWidget()
        tip.setStyleSheet(f"background: {_CARD}; border-radius: 10px; border: 1px solid {_BORDER};")
        tl = QHBoxLayout(tip)
        tl.setContentsMargins(20, 14, 20, 14)
        tl.addWidget(QLabel("⚙️"))
        tl.addWidget(_p(t("finish_tip", lang), 12))
        tl.addStretch()
        v.addWidget(tip)
        v.addStretch()

        copyright_lbl = _p(f"© 2026 {cfg.APP_NAME}", 10, muted=True)
        copyright_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(copyright_lbl)


# ── Main wizard ────────────────────────────────────────────────────────────────

class OnboardingWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._conf = cfg.load()
        self._lang = current_language()
        self.setWindowTitle(t("onboarding_window_title", self._lang))
        self.setFixedSize(640, 620)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        # STANDARDS.md §20.2 — was the only first-run/main window that didn't
        # honor Windows High Contrast (main.py/widget_window.py/splash_screen.py/
        # editor_window.py already did). _refresh_palette() must run before
        # setStyleSheet()/_build() since every color below is read from the
        # module-level constants it sets.
        _refresh_palette()
        self.setStyleSheet(_base_ss())
        self._apply_direction()
        self._build()
        self._center()

    def _initial_language_pick(self) -> str:
        """Which radio is pre-checked on the wizard's language page (page 0).

        2026-09-25 finding: build/build_installer.py's standalone SetupWizard
        has its own language toggle, but it only translates the installer's
        own UI — it never writes config.json or any file the running app
        reads, so an install-time language choice never reaches here. The
        app's saved default (config.py DEFAULT_CONFIG["language"]) is
        deliberately always "en" regardless of Windows locale (2026-09-14
        decision, to avoid silently flipping a user to Hebrew) — that
        decision is left untouched.
        This only changes which radio starts checked on this one page, for a
        genuine first run with no saved language yet: a smarter starting
        point for a Hebrew-locale user, not a silent switch — Next/Skip still
        requires an explicit click either way."""
        if self._conf.get("first_run", True):
            return detect_system_language()
        return self._lang

    def _apply_direction(self):
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl(self._lang) else Qt.LayoutDirection.LeftToRight
        )

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Progress dots + skip ─────────────────────────────────────────────
        dot_row = QWidget()
        dot_row.setStyleSheet(f"background: {_CARD}; border-bottom: 1px solid {_BORDER};")
        dl = QHBoxLayout(dot_row)
        dl.setContentsMargins(20, 12, 20, 12)
        dl.setSpacing(8)
        self._dots: list[QLabel] = []
        for i in range(6):
            d = QLabel("●")
            d.setFont(QFont("Arial", 10))
            d.setStyleSheet(f"color: {_MUTED};")
            self._dots.append(d)
            dl.addWidget(d)
        dl.addStretch()
        self._skip_btn = QPushButton(t("skip_setup", self._lang))
        # Setting a stylesheet directly on a widget stops Qt from cascading
        # the dialog-level "QPushButton:focus" rule (_base_ss()) down to it
        # for states this local sheet doesn't also declare — so without its
        # own explicit :focus rule, Tab-ing to Skip showed no focus ring at
        # all. Back/Next (_btn()) had the same latent gap; fixed there too.
        self._skip_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {_MUTED}; border: 1px solid transparent;
                           font-size: 12px; border-radius: 4px; padding: 2px 6px; }}
            QPushButton:hover {{ color: {_TEXT}; }}
            QPushButton:focus {{ border: 2px solid {_ACCENT2}; outline: none; }}
        """)
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.clicked.connect(self._skip)
        dl.addWidget(self._skip_btn)
        root.addWidget(dot_row)

        # ── Pages ─────────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._page_lang     = _LanguagePage(self._initial_language_pick())
        self._page_welcome  = _WelcomePage(self._lang)
        self._page_hotkeys  = _HotkeysPage(self._conf, self._lang)
        self._page_ai       = _AISetupPage(self._conf, self._lang)
        self._page_save     = _SaveDirPage(self._conf, self._lang)
        self._page_finish   = _FinishPage(self._conf, self._lang)
        for p in [self._page_lang, self._page_welcome, self._page_hotkeys,
                  self._page_ai, self._page_save, self._page_finish]:
            self._stack.addWidget(p)
        root.addWidget(self._stack, 1)

        # ── Nav buttons ───────────────────────────────────────────────────────
        # Kept forced left-to-right regardless of the page language: Next
        # always sits on the right and Back on the left, matching how the
        # buttons read in both languages — letting this mirror under RTL
        # silently swaps their positions, which reads as "Next is broken".
        nav = QWidget()
        nav.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        nav.setStyleSheet(f"background: {_CARD}; border-top: 1px solid {_BORDER};")
        self._nav_layout = QHBoxLayout(nav)
        self._nav_layout.setContentsMargins(24, 14, 24, 14)
        self._back_btn = _btn(t("back", self._lang), primary=False)
        self._next_btn = _btn(t("next", self._lang))
        self._back_btn.clicked.connect(self._prev)
        self._next_btn.clicked.connect(self._next)
        self._nav_layout.addWidget(self._back_btn)
        self._nav_layout.addStretch()
        self._nav_layout.addWidget(self._next_btn)
        root.addWidget(nav)

        self._page = 0
        self._refresh_nav()

    def _refresh_nav(self):
        self._stack.setCurrentIndex(self._page)
        self._back_btn.setVisible(self._page > 0)
        is_last = self._page == self._stack.count() - 1
        self._next_btn.setText(t("finish", self._lang) if is_last else t("next", self._lang))
        # Progress dots previously signalled "current step" by color alone
        # (accent vs muted) — invisible to colorblind users and not backed
        # by any other cue. A bigger filled dot for the current step vs.
        # smaller outline dots for the rest gives a shape/size cue too.
        for i, d in enumerate(self._dots):
            if i == self._page:
                d.setText("●")
                d.setFont(QFont("Arial", 13))
                d.setStyleSheet(f"color: {_ACCENT}; font-weight: bold;")
            elif i < self._page:
                d.setText("●")
                d.setFont(QFont("Arial", 10))
                d.setStyleSheet(f"color: {_MUTED};")
            else:
                d.setText("○")
                d.setFont(QFont("Arial", 10))
                d.setStyleSheet(f"color: {_MUTED};")

    def _rebuild_after_language_change(self):
        """Re-instantiate all pages after language switch, keep current step."""
        current = self._page
        conf = cfg.load()
        self._apply_direction()
        while self._stack.count():
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._page_lang     = _LanguagePage(self._lang)
        self._page_welcome  = _WelcomePage(self._lang)
        self._page_hotkeys  = _HotkeysPage(conf, self._lang)
        self._page_ai       = _AISetupPage(conf, self._lang)
        self._page_save     = _SaveDirPage(conf, self._lang)
        self._page_finish   = _FinishPage(conf, self._lang)
        for p in [self._page_lang, self._page_welcome, self._page_hotkeys,
                  self._page_ai, self._page_save, self._page_finish]:
            self._stack.addWidget(p)
        self._back_btn.setText(t("back", self._lang))
        self._skip_btn.setText(t("skip_setup", self._lang))
        self.setWindowTitle(t("onboarding_window_title", self._lang))
        self._page = current
        self._refresh_nav()

    def _prev(self):
        if self._page > 0:
            self._page -= 1
            self._refresh_nav()

    def _next(self):
        if self._page == 0:
            new_lang = self._page_lang.selected()
            if new_lang != self._lang:
                self._lang = new_lang
                conf = cfg.load()
                conf["language"] = new_lang
                cfg.save(conf)
                self._rebuild_after_language_change()
            self._page += 1
            self._refresh_nav()
            return
        if self._page == self._stack.count() - 1:
            self._save_and_close()
        else:
            self._page += 1
            self._refresh_nav()

    def _skip(self):
        new_lang = self._page_lang.selected()
        conf = cfg.load()
        conf["language"] = new_lang
        cfg.save(conf)
        self._save_and_close()

    def _save_and_close(self):
        """Merge wizard values into config and mark first_run done."""
        conf = cfg.load()
        if hasattr(self._page_ai, "values"):
            conf.update(self._page_ai.values())
        if hasattr(self._page_save, "values"):
            conf.update(self._page_save.values())
        conf["first_run"] = False
        cfg.save(conf)
        self.accept()
