"""
Splash screen — shown briefly on app startup.

Implements STANDARDS.md §19 (the binding cross-project splash-screen
template, originated in HOMEY AI, PyQt6-equivalent here):
  1. Gradient background in SnapCap's own brand colors, not a generic panel.
  2. The real logo asset (assets/logo-mark.svg) as the large, dominant,
     centered element — not a small icon or text-only placeholder.
  3. Frameless + translucent top-level window, background painted as a
     rounded rect via QPainterPath — not a square system-bordered window.
  4. A subtle continuous spinner (QPropertyAnimation rotating an arc) —
     not a fake determinate progress bar (we have no real load percentage
     to report).
  5. Minimum 800ms display enforced in code by measuring real elapsed time
     from show() to "ready", plus an 8s safety timeout so the splash can
     never get stuck on screen.
  6. No flicker: SnapCap has no traditional main window shown at startup
     (it's a tray-resident app) — see the note on `show_splash_then` below
     for how that maps onto §19's "hidden main window" requirement.
"""
import sys
import time
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QApplication
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QLinearGradient, QPainterPath, QPen, QBrush,
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPointF, pyqtProperty

import a11y
import config as cfg

# Enforced minimum time the splash stays visible, measured from show() to
# the moment startup work finishes (see show_splash_then) — not just a
# fixed sleep, so a slower first-run (onboarding setup, config load, etc.)
# never *shortens* the floor, it only ever waits out the remaining gap.
_MIN_MS = 800
# Safety timeout: if startup work stalls, the splash is forced to close
# anyway rather than being able to hang on screen forever.
_SAFETY_MS = 8000


def _resource_root() -> Path:
    """Same frozen/dev resolution pattern as config.py's _load_version_info:
    PyInstaller --onedir extracts --add-data "assets;assets" under
    sys._MEIPASS, dev runs read straight from the project root."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _make_logo(size: int = 120) -> QPixmap:
    """Renders the project's real logo mark (assets/logo-mark.svg — the same
    gradient badge used identically everywhere per assets/BRAND.md: installer
    icon, installed .exe icon, taskbar, tray, onboarding wizard), scaled up
    as the splash's dominant element. Falls back to a hand-painted version
    with the *identical* gradient/letterform only if the SVG asset can't be
    loaded (missing file in a broken build, QtSvg unavailable) — so the
    splash never shows a bare placeholder.
    """
    pxm = QPixmap(size, size)
    pxm.fill(Qt.GlobalColor.transparent)

    svg_path = _resource_root() / "assets" / "logo-mark.svg"
    try:
        from PyQt6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(str(svg_path))
        if renderer.isValid():
            p = QPainter(pxm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(p)
            p.end()
            return pxm
    except Exception:
        pass

    # Fallback — same gradient badge, painted procedurally.
    p = QPainter(pxm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#00d9a3"))
    grad.setColorAt(1, QColor("#3b82f6"))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", int(size * 0.44), QFont.Weight.Bold))
    p.drawText(pxm.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    p.end()
    return pxm


class _Spinner(QWidget):
    """Continuous rotating arc — an honest "loading" indicator, used because
    SnapCap has no real load-progress percentage to report at startup (a
    determinate bar would be faking one). Driven by a QPropertyAnimation
    over a Qt `angle` property so Qt handles the easing/looping, not a
    manually ticked QTimer."""

    def __init__(self, parent=None, diameter: int = 26):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._angle = 0.0

        self._anim = QPropertyAnimation(self, b"angle", self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setDuration(1000)
        self._anim.setLoopCount(-1)  # continuous — not a determinate progress indicator
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.start()

    def stop(self):
        self._anim.stop()

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, value: float):
        self._angle = value
        self.update()

    angle = pyqtProperty(float, fget=_get_angle, fset=_set_angle)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)

        # QPointF explicitly — QLinearGradient(QPoint, QPoint) has been
        # observed to crash the process under this PyQt6/Qt6 build; the
        # QPointF overload is the safe one.
        grad = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.bottomRight()))
        grad.setColorAt(0, QColor("#00d9a3"))
        grad.setColorAt(1, QColor("#3b82f6"))
        pen = QPen(QBrush(grad), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        span_deg = 100  # partial ring, like a native spinner — reads as "spinning", not a clock/full circle
        start_angle = int((90 - self._angle) * 16)  # Qt angles are in 1/16ths of a degree
        span_angle = int(-span_deg * 16)
        p.drawArc(rect, start_angle, span_angle)
        p.end()


class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(380, 260)
        self._radius = 20
        # STANDARDS.md §20.2: under a Windows Contrast Theme the brand
        # gradient and fixed greys give way to the user's system colors.
        self._hc = a11y.is_high_contrast()
        if self._hc:
            c = a11y.system_colors()
            fg, muted = c["window_text"], c["window_text"]
        else:
            fg, muted = "#eaeaea", "#8892a4"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 30, 0, 22)
        layout.setSpacing(8)

        logo = QLabel()
        logo.setPixmap(_make_logo())
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        layout.addSpacing(4)

        name = QLabel("SnapCap")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(f"color: {fg}; font-size: 19px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(name)

        ver = QLabel(f"v{cfg.APP_VERSION}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(f"color: {muted}; font-size: 11px; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(ver)

        layout.addStretch()

        loading_row = QHBoxLayout()
        loading_row.setSpacing(8)
        loading_row.addStretch()

        self._spinner = _Spinner()
        loading_row.addWidget(self._spinner)

        self._status = QLabel("Starting…")
        self._status.setStyleSheet(f"color: {muted}; font-size: 10px; font-family: 'Segoe UI'; background: transparent;")
        loading_row.addWidget(self._status)

        loading_row.addStretch()
        layout.addLayout(loading_row)

        self._center()

    def paintEvent(self, event):
        # Rounded-rect brand-gradient background, painted directly — not a
        # child widget with a CSS border-radius, and not a plain square
        # system-bordered window (the frameless+translucent flags above
        # make this the *only* thing drawing the window's background/edge).
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), self._radius, self._radius)

        # Diagonal (top-left -> bottom-right, matching assets/BRAND.md's
        # documented 135° gradient direction) using SnapCap's own dark-theme
        # brand colors: Surface(background) -> Surface(panel) -> a darkened
        # tone of the brand Secondary/accent blue (#3b82f6). Deliberately
        # NOT the full bright accent gradient (#00d9a3 -> #3b82f6) as a
        # *background fill* — that combination was already found (and fixed
        # elsewhere in the app, see STANDARDS.md's SnapCap status notes) to
        # fail WCAG contrast for white text on the light teal end. The full
        # bright gradient is still used, at readable size, on the logo mark
        # and the spinner.
        if self._hc:
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
            pen = QPen(QColor(0, 217, 163, 70))
            pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()

    def _center(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.x() + (geo.width() - self.width()) // 2,
            geo.y() + (geo.height() - self.height()) // 2,
        )

    def set_status(self, text: str):
        self._status.setText(text)
        QApplication.processEvents()

    def closeEvent(self, event):
        self._spinner.stop()
        super().closeEvent(event)


def show_splash_then(app: QApplication, on_done):
    """
    Show the splash, run `on_done()` (SnapCap's startup — tray icon +
    hotkeys + app-controller construction; there's no separate traditional
    main window to keep hidden here, the tray icon itself is the only thing
    that appears, and it's a small system-tray glyph, not a window that can
    visibly "flicker"), then close the splash once BOTH:
      - `on_done()` has actually finished, and
      - at least _MIN_MS has elapsed since the splash was first shown
        (measured with time.monotonic(), not assumed) —
    whichever is later. An _SAFETY_MS backstop timer guarantees the splash
    closes even if startup work stalls, so it can never be stuck on screen.
    """
    splash = SplashScreen()
    splash.show()
    QApplication.processEvents()
    start = time.monotonic()

    state = {"closed": False}

    def _close_once():
        if state["closed"]:
            return
        state["closed"] = True
        safety_timer.stop()
        splash.close()

    def _run_startup():
        try:
            on_done()
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            remaining_ms = _MIN_MS - elapsed_ms
            if remaining_ms > 0:
                QTimer.singleShot(int(remaining_ms), _close_once)
            else:
                _close_once()

    safety_timer = QTimer(splash)
    safety_timer.setSingleShot(True)
    safety_timer.timeout.connect(_close_once)
    safety_timer.start(_SAFETY_MS)

    # Deferred (not called inline) so the splash actually gets to paint
    # itself — and the spinner its first frame — before startup work runs.
    QTimer.singleShot(0, _run_startup)
