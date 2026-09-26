"""
Color Picker — a full-screen loupe for sampling a pixel's color anywhere
on screen (ShareX ships this as a dedicated tool separate from its
annotation editor; SnapCap's editor had no equivalent). Move the mouse to
preview a magnified swatch + live HEX/RGB readout, click to grab it (the
value is copied to the clipboard by the caller), Escape cancels.

Reuses the same full-desktop-grab + logical/physical DPI-scaling approach
already proven in region_selector.RegionSelector — see the comments there
for why the devicePixelRatio math matters on scaled displays.
"""
from typing import Optional

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QPoint, QSize, QEventLoop, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap, QFont

from region_selector import grab_all_screens_pil, pil_to_qpixmap
from i18n import t, current_language


class ColorPickerOverlay(QWidget):
    """Full-screen transparent overlay: paints the frozen desktop grab,
    tracks the mouse, and shows a zoomed loupe + HEX/RGB swatch near the
    cursor. Emits `color_picked` on left-click, `cancelled` on Escape."""

    color_picked = pyqtSignal(str)
    cancelled = pyqtSignal()

    LOUPE_SIZE = 120
    ZOOM = 8

    def __init__(self, background: QPixmap):
        super().__init__()
        self._bg = background
        self._img = background.toImage()
        self._scale = background.devicePixelRatio() or 1.0
        self._pos = QPoint(0, 0)
        self._hex = "#000000"
        self._rgb = (0, 0, 0)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.BypassWindowManagerHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        screen = QApplication.primaryScreen()
        screen_geo = screen.virtualGeometry() if screen else self.rect()
        self.setGeometry(screen_geo)
        self._origin = screen_geo.topLeft()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()

    def mouseMoveEvent(self, e):
        self._pos = e.position().toPoint()
        self._sample(self._pos)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._sample(e.position().toPoint())
            picked = self._hex
            self.close()
            self.color_picked.emit(picked)

    def _sample(self, pos: QPoint):
        s = self._scale
        x = round(pos.x() * s)
        y = round(pos.y() * s)
        if 0 <= x < self._img.width() and 0 <= y < self._img.height():
            c = self._img.pixelColor(x, y)
            self._rgb = (c.red(), c.green(), c.blue())
            self._hex = f"#{c.red():02x}{c.green():02x}{c.blue():02x}"

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg)

        pos = self._pos
        s = self._scale
        loupe = self.LOUPE_SIZE
        crop_size = max(1, loupe // self.ZOOM)
        cx = round(pos.x() * s) - crop_size // 2
        cy = round(pos.y() * s) - crop_size // 2
        crop = self._bg.copy(cx, cy, crop_size, crop_size)
        scaled = crop.scaled(
            QSize(loupe, loupe),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

        lx = pos.x() + 24
        ly = pos.y() - loupe - 24
        if ly < 0:
            ly = pos.y() + 24
        if lx + loupe + 100 > self.width():
            lx = pos.x() - loupe - 24 - 100

        p.drawPixmap(lx, ly, scaled)
        p.setPen(QPen(QColor("#00d9a3"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(lx, ly, loupe, loupe)

        # Crosshair marking the exact sampled pixel at loupe center.
        p.setPen(QPen(QColor(255, 255, 255, 200), 1))
        p.drawLine(lx + loupe // 2, ly, lx + loupe // 2, ly + loupe)
        p.drawLine(lx, ly + loupe // 2, lx + loupe, ly + loupe // 2)

        # Color swatch + HEX/RGB readout to the right of the loupe.
        swatch_x = lx + loupe + 8
        p.fillRect(swatch_x, ly, 26, loupe, QColor(self._hex))
        p.setPen(QPen(QColor("#00d9a3"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(swatch_x, ly, 26, loupe)

        p.setPen(QColor("white"))
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        r, g, b = self._rgb
        p.fillRect(swatch_x + 32, ly, 130, loupe, QColor(0, 0, 0, 170))
        p.drawText(swatch_x + 38, ly + loupe // 2 - 6, self._hex.upper())
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(swatch_x + 38, ly + loupe // 2 + 14, f"RGB {r}, {g}, {b}")

        # Hint text, top-left.
        p.setFont(QFont("Segoe UI", 12))
        hint = t("color_picker_hint", current_language())
        p.fillRect(20, 20, 10 + 9 * len(hint), 30, QColor(0, 0, 0, 160))
        p.setPen(QColor("white"))
        p.drawText(24, 40, hint)
        p.end()


def pick_color() -> Optional[str]:
    """Shows the color picker overlay and blocks until the user clicks (or
    cancels with Escape). Returns '#rrggbb' or None. Never raises — any
    failure to grab the background falls back gracefully, matching
    region_selector.select_region()'s pattern."""
    screen = QApplication.primaryScreen()
    scale = screen.devicePixelRatio() if screen else 1.0
    try:
        pil_bg = grab_all_screens_pil()
        bg_pxm = pil_to_qpixmap(pil_bg)
        bg_pxm.setDevicePixelRatio(scale)
    except Exception:
        from PyQt6.QtCore import QRect
        geo = screen.virtualGeometry() if screen else QRect(0, 0, 1920, 1080)
        bg_pxm = QPixmap(round(geo.width() * scale), round(geo.height() * scale))
        bg_pxm.setDevicePixelRatio(scale)
        bg_pxm.fill(QColor(20, 20, 30))

    result: list = [None]
    overlay = ColorPickerOverlay(bg_pxm)

    def on_picked(hex_color):
        result[0] = hex_color

    overlay.color_picked.connect(on_picked)
    overlay.showFullScreen()

    local_loop = QEventLoop()
    overlay.destroyed.connect(local_loop.quit)
    overlay.color_picked.connect(local_loop.quit)
    overlay.cancelled.connect(local_loop.quit)
    local_loop.exec()

    return result[0]
