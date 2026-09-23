"""
Desktop Widget — a small, always-on-top floating panel that shows the real
"captured this month" stat plus one-click "Capture now" / "Open Library"
quick actions, so the two most-used flows never require opening the full
app or remembering a hotkey.

Visual pattern is deliberately reused from splash_screen.py (STANDARDS.md
§19): frameless + translucent top-level window, background painted as a
rounded rect via QPainterPath, SnapCap's own brand gradient
(#00d9a3 -> #3b82f6, 135°, per assets/BRAND.md). The drag-to-move
interaction reuses the pattern already proven in editor_window.PinWindow
(mousePressEvent / mouseMoveEvent, no window-manager chrome of its own).

1.10.0 hardening pass:
  - Never appears in a screenshot: the window is excluded from screen
    capture (a11y.exclude_from_capture / WDA_EXCLUDEFROMCAPTURE). Before
    this, the always-on-top panel was baked into every fullscreen capture
    and into any region capture that overlapped it — including captures
    started from its own "Capture now" button.
  - Windows High Contrast (STANDARDS.md §20.2): brand gradient and fixed
    colors are replaced by the user's system colors while a Contrast Theme
    is on; re-checked at runtime, not just at startup.
  - A saved position that is no longer on any connected screen (monitor
    unplugged, resolution changed) is discarded instead of reopening the
    panel off-screen where it can't be dragged back (§12.3).
  - Accessible names without the decorative emoji, visible focus ring.
"""
from typing import Callable, Optional

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPainterPath, QPen, QGuiApplication
from PyQt6.QtCore import Qt, QPoint, QPointF, QTimer, QEvent, QRect

import a11y
import config as cfg
from i18n import t, is_rtl, current_language
from library_window import count_captured_this_month

# Periodic stat refresh while the widget is visible (a capture triggered via
# the global hotkey, not the widget's own button, wouldn't otherwise update
# the count until the widget is reopened). _post_capture() in main.py also
# calls refresh_stat() directly right after a capture is saved — this timer
# is just the belt-and-suspenders fallback for anything that path misses
# (e.g. a manual Save from the editor). The same tick re-checks High
# Contrast, so toggling a Contrast Theme while SnapCap runs is picked up.
_REFRESH_MS = 15000

# Minimum part of the widget (px) that must overlap a connected screen for a
# saved position to be trusted on restore — enough to grab and drag it back.
_MIN_VISIBLE_PX = 40


class WidgetWindow(QWidget):
    """`on_capture` / `on_open_library` are the *exact* callables SnapCapApp's
    tray menu and global hotkeys already use (bridge.trigger_region.emit /
    bridge.trigger_library.emit) — the widget never reimplements capture or
    library-opening logic, it only fires the same signal the hotkey does."""

    WIDTH = 250
    HEIGHT = 140
    RADIUS = 16

    def __init__(self, on_capture: Callable[[], None], on_open_library: Callable[[], None]):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._on_capture = on_capture
        self._on_open_library = on_open_library
        self._lang = current_language()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # A Tool-flagged frameless window already doesn't grab taskbar focus,
        # but WA_ShowWithoutActivating also stops show()/move() from
        # stealing keyboard focus away from whatever app the user is in —
        # required by spec ("no focus-stealing").
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl(self._lang) else Qt.LayoutDirection.LeftToRight
        )
        self.setToolTip(t("widget_tooltip", self._lang))
        self.setAccessibleName(t("app_name", self._lang))

        self._drag_offset: Optional[QPoint] = None
        # Set in showEvent once the native window exists — True when
        # WDA_EXCLUDEFROMCAPTURE took effect. main.py hides the widget around
        # a capture only when this stays False (Windows older than 10 2004).
        self.excluded_from_capture = False
        self._high_contrast = a11y.is_high_contrast()

        self._build_ui()
        self._apply_styles()
        self._restore_position()
        self.refresh_stat()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh_tick)
        self._refresh_timer.start(_REFRESH_MS)

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(0)
        self._stat_label = QLabel()
        top_row.addWidget(self._stat_label)
        top_row.addStretch()

        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Was t("cb_show_desktop_widget") — i.e. the close control's tooltip
        # read "Show desktop widget", the opposite of what it does. "×" alone
        # is also announced by screen readers as "multiplication sign".
        self._close_btn.setToolTip(t("close", self._lang))
        self._close_btn.setAccessibleName(t("close", self._lang))
        self._close_btn.clicked.connect(self._on_close_clicked)
        top_row.addWidget(self._close_btn)
        outer.addLayout(top_row)

        outer.addStretch()

        self._capture_btn = QPushButton(t("widget_capture_now", self._lang))
        self._capture_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._capture_btn.setAccessibleName(a11y.plain_label(self._capture_btn.text()))
        self._capture_btn.clicked.connect(self._capture_now)
        outer.addWidget(self._capture_btn)

        self._library_btn = QPushButton(t("widget_open_library", self._lang))
        self._library_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._library_btn.setAccessibleName(a11y.plain_label(self._library_btn.text()))
        self._library_btn.clicked.connect(self._open_library)
        outer.addWidget(self._library_btn)

        # Tab order = visual reading order: close (top corner) -> primary
        # action -> secondary action.
        QWidget.setTabOrder(self._close_btn, self._capture_btn)
        QWidget.setTabOrder(self._capture_btn, self._library_btn)

    def _apply_styles(self):
        """Brand styling normally; the user's own system colors when a
        Windows Contrast Theme is active (STANDARDS.md §20.2 — never paint
        brand colors over a palette the user chose on purpose). Every
        button gets an explicit :focus ring either way (§18.2)."""
        if self._high_contrast:
            c = a11y.system_colors()
            self._stat_label.setStyleSheet(
                f"color: {c['window_text']}; font-size: 12px; font-weight: 600; "
                "font-family: 'Segoe UI'; background: transparent;"
            )
            btn = (
                f"QPushButton {{ background: {c['button']}; color: {c['button_text']}; "
                f"border: 1px solid {c['button_text']}; border-radius: 9px; padding: 7px 10px; "
                "font-size: 12px; font-family: 'Segoe UI'; }}"
                f"QPushButton:hover {{ background: {c['highlight']}; color: {c['highlight_text']}; }}"
                f"QPushButton:focus {{ border: 2px solid {c['highlight']}; }}"
            )
            self._capture_btn.setStyleSheet(btn + "QPushButton { font-weight: bold; }")
            self._library_btn.setStyleSheet(btn)
            self._close_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {c['window_text']}; border: none; "
                "font-size: 15px; font-weight: bold; border-radius: 12px; }}"
                f"QPushButton:hover {{ background: {c['highlight']}; color: {c['highlight_text']}; }}"
                f"QPushButton:focus {{ border: 2px solid {c['highlight']}; }}"
            )
        else:
            self._stat_label.setStyleSheet(
                "color: #eaeaea; font-size: 12px; font-weight: 600; "
                "font-family: 'Segoe UI'; background: transparent;"
            )
            self._close_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #8892a4; border: none;
                    font-size: 15px; font-weight: bold; border-radius: 12px;
                }
                QPushButton:hover { background: rgba(255,255,255,0.12); color: #eaeaea; }
                QPushButton:focus { border: 2px solid #00d9a3; color: #eaeaea; }
            """)
            self._capture_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #00d9a3, stop:1 #3b82f6);
                    color: #0d1524; font-weight: bold; font-size: 12px;
                    font-family: 'Segoe UI'; border: 2px solid transparent;
                    border-radius: 9px; padding: 6px 8px;
                }
                QPushButton:hover { background: #00d9a3; }
                QPushButton:focus { border: 2px solid #eaeaea; }
            """)
            self._library_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255,255,255,0.08); color: #eaeaea;
                    font-size: 12px; font-family: 'Segoe UI';
                    border: 2px solid transparent;
                    border-radius: 9px; padding: 5px 8px;
                }
                QPushButton:hover { background: rgba(255,255,255,0.16); }
                QPushButton:focus { border: 2px solid #00d9a3; }
            """)
        self.update()

    def _recheck_high_contrast(self):
        hc = a11y.is_high_contrast()
        if hc != self._high_contrast:
            self._high_contrast = hc
            self._apply_styles()

    def changeEvent(self, event):
        # Qt turns WM_SYSCOLORCHANGE into a palette change — the fast path
        # for picking up a Contrast Theme toggle; the refresh timer is the
        # fallback. (QEvent.Type.ThemeChange does NOT exist in PyQt6 6.11 —
        # referencing it raised AttributeError on every change event; found
        # by a live launch, now covered by a test.)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange,
                            QEvent.Type.StyleChange):
            self._recheck_high_contrast()
        super().changeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.excluded_from_capture:
            self.excluded_from_capture = a11y.exclude_from_capture(self)

    def paintEvent(self, event):
        # Same painting approach as splash_screen.SplashScreen: frameless +
        # translucent window, rounded-rect background painted directly via
        # QPainterPath, brand gradient top-left -> bottom-right (135°, per
        # assets/BRAND.md). QPointF is used explicitly for the gradient's
        # start/stop points — QLinearGradient(QPoint, QPoint) raises a
        # TypeError on PyQt6 6.11 (no QPoint overload; re-verified
        # 2026-09-23); the QPointF / 4-float overloads are the valid ones.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), self.RADIUS, self.RADIUS)

        if self._high_contrast:
            c = a11y.system_colors()
            painter.fillPath(path, QColor(c["window"]))
            pen = QPen(QColor(c["window_text"]))
            pen.setWidthF(2.0)
        else:
            grad = QLinearGradient(QPointF(0, 0), QPointF(self.width(), self.height()))
            grad.setColorAt(0.0, QColor("#1a1a2e"))
            grad.setColorAt(0.55, QColor("#16213e"))
            grad.setColorAt(1.0, QColor("#123a63"))
            painter.fillPath(path, grad)
            pen = QPen(QColor(0, 217, 163, 80))
            pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()

    # ── Stat ─────────────────────────────────────────────────────────────────
    def refresh_stat(self):
        """Reuses library_window.count_captured_this_month() — the same
        mtime-based computation the Library toolbar stat uses — so the two
        never drift out of sync or compute it twice."""
        conf = cfg.load()
        count = count_captured_this_month(conf.get("save_dir", cfg.DEFAULT_CONFIG["save_dir"]))
        if count > 0:
            self._stat_label.setText(t("lib_stat_month_fmt", self._lang, count=count))
        else:
            self._stat_label.setText(t("widget_stat_zero", self._lang))

    def _on_refresh_tick(self):
        self._recheck_high_contrast()
        if self.isVisible():
            self.refresh_stat()

    # ── Actions ──────────────────────────────────────────────────────────────
    def _capture_now(self):
        self._on_capture()

    def _open_library(self):
        self._on_open_library()

    def _on_close_clicked(self):
        """Hides the widget AND persists the opt-out. Just hiding it without
        saving anything would make it silently reappear on next launch with
        no obvious way the user turned it off — Settings → Desktop Widget
        and the tray menu's "Show desktop widget" item both read this same
        config flag, so either one brings it back."""
        conf = cfg.load()
        conf["show_desktop_widget"] = False
        cfg.save(conf)
        self.hide()

    # ── Drag-to-move + position persistence ────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e):
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()

    def _save_position(self):
        conf = cfg.load()
        conf["widget_pos"] = {"x": self.x(), "y": self.y()}
        cfg.save(conf)

    @staticmethod
    def _is_on_some_screen(x: int, y: int, w: int, h: int) -> bool:
        """True if at least a _MIN_VISIBLE_PX x _MIN_VISIBLE_PX part of the
        rect (x, y, w, h) lies on a currently connected screen."""
        rect = QRect(x, y, w, h)
        for screen in QGuiApplication.screens():
            inter = rect.intersected(screen.availableGeometry())
            if inter.width() >= _MIN_VISIBLE_PX and inter.height() >= _MIN_VISIBLE_PX:
                return True
        return False

    def _restore_position(self):
        conf = cfg.load()
        pos = conf.get("widget_pos")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            try:
                x, y = int(pos["x"]), int(pos["y"])
                # STANDARDS.md §12.3: a position saved on a monitor that's
                # since been unplugged (or before a resolution change) would
                # otherwise reopen this frameless, taskbar-less panel
                # entirely off-screen with no way to drag it back.
                if self._is_on_some_screen(x, y, self.WIDTH, self.HEIGHT):
                    self.move(x, y)
                    return
            except (TypeError, ValueError):
                pass
        # First run (no saved position yet) or stale position: bottom-right
        # corner of the primary screen's available geometry, clear of the
        # taskbar — an unobtrusive default spot that doesn't cover anything
        # important.
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.WIDTH - 24, geo.bottom() - self.HEIGHT - 24)

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)
