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
"""
from typing import Callable, Optional

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPainterPath, QPen
from PyQt6.QtCore import Qt, QPoint, QPointF, QTimer

import config as cfg
from i18n import t, is_rtl, current_language
from library_window import count_captured_this_month

# Periodic stat refresh while the widget is visible (a capture triggered via
# the global hotkey, not the widget's own button, wouldn't otherwise update
# the count until the widget is reopened). _post_capture() in main.py also
# calls refresh_stat() directly right after a capture completes — this timer
# is just the belt-and-suspenders fallback for anything that path misses.
_REFRESH_MS = 15000


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

        self._drag_offset: Optional[QPoint] = None

        self._build_ui()
        self._restore_position()
        self.refresh_stat()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_stat)
        self._refresh_timer.start(_REFRESH_MS)

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(0)
        self._stat_label = QLabel()
        self._stat_label.setStyleSheet(
            "color: #eaeaea; font-size: 12px; font-weight: 600; "
            "font-family: 'Segoe UI'; background: transparent;"
        )
        top_row.addWidget(self._stat_label)
        top_row.addStretch()

        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip(t("cb_show_desktop_widget", self._lang))
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #8892a4; border: none;
                font-size: 15px; font-weight: bold; border-radius: 10px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.12); color: #eaeaea; }
        """)
        close_btn.clicked.connect(self._on_close_clicked)
        top_row.addWidget(close_btn)
        outer.addLayout(top_row)

        outer.addStretch()

        capture_btn = QPushButton(t("widget_capture_now", self._lang))
        capture_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        capture_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #00d9a3, stop:1 #3b82f6);
                color: #0d1524; font-weight: bold; font-size: 12px;
                font-family: 'Segoe UI'; border: none; border-radius: 9px;
                padding: 8px 10px;
            }
            QPushButton:hover { background: #00d9a3; }
        """)
        capture_btn.clicked.connect(self._capture_now)
        outer.addWidget(capture_btn)

        library_btn = QPushButton(t("widget_open_library", self._lang))
        library_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        library_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); color: #eaeaea;
                font-size: 12px; font-family: 'Segoe UI'; border: none;
                border-radius: 9px; padding: 7px 10px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.16); }
        """)
        library_btn.clicked.connect(self._open_library)
        outer.addWidget(library_btn)

    def paintEvent(self, event):
        # Same painting approach as splash_screen.SplashScreen: frameless +
        # translucent window, rounded-rect background painted directly via
        # QPainterPath, brand gradient top-left -> bottom-right (135°, per
        # assets/BRAND.md). QPointF is used explicitly for the gradient's
        # start/stop points — QLinearGradient(QPoint, QPoint) was found to
        # crash this PyQt6/Qt6 build (see splash_screen._Spinner.paintEvent);
        # the QPointF overload avoids that same crash.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), self.RADIUS, self.RADIUS)

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

    # ── Actions ──────────────────────────────────────────────────────────────
    def _capture_now(self):
        self._on_capture()

    def _open_library(self):
        self._on_open_library()

    def _on_close_clicked(self):
        """Hides the widget AND persists the opt-out. Just hiding it without
        saving anything would make it silently reappear on next launch with
        no obvious way the user turned it off — Settings → Desktop Widget
        stays the single source of truth, and its checkbox correctly reads
        unchecked the next time Settings is opened."""
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

    def _restore_position(self):
        conf = cfg.load()
        pos = conf.get("widget_pos")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            try:
                self.move(int(pos["x"]), int(pos["y"]))
                return
            except (TypeError, ValueError):
                pass
        # First run (no saved position yet): bottom-right corner of the
        # primary screen's available geometry, clear of the taskbar — an
        # unobtrusive default spot that doesn't cover anything important.
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.WIDTH - 24, geo.bottom() - self.HEIGHT - 24)

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)
