"""
Region selector overlay — translucent fullscreen window
for rubber-band region selection with zoom magnifier.
"""
import sys
from PyQt6.QtWidgets import QApplication, QWidget, QLabel
from PyQt6.QtCore import Qt, QRect, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPixmap, QFont, QCursor, QScreen,
)
from PIL import Image
import mss


def grab_all_screens_pil() -> Image.Image:
    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[0])
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def pil_to_qpixmap(img: Image.Image):
    from PyQt6.QtGui import QImage, QPixmap
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimage = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


class RegionSelector(QWidget):
    """
    Full-screen overlay for selecting a capture region.
    Emits `region_selected(x, y, w, h)` on release.
    Emits `cancelled()` on Escape.
    """
    region_selected = pyqtSignal(int, int, int, int)
    cancelled = pyqtSignal()

    def __init__(self, background: QPixmap):
        super().__init__()
        self._bg = background
        # The background pixmap holds raw physical-pixel screen data; its
        # devicePixelRatio (set by the caller) tells Qt how many physical
        # pixels correspond to one logical pixel here. Without it, Qt paints
        # the pixmap 1:1 in physical pixels — on any scaled display (125%,
        # 150%, …) that overflows the logical-pixel overlay and LOOKS like
        # the screen was zoomed in. We use it below to convert mouse
        # positions (always logical) back to physical pixels for cropping
        # and for the final mss capture coordinates.
        self._scale = background.devicePixelRatio() or 1.0
        self._start: QPoint | None = None
        self._end: QPoint | None = None
        self._selecting = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.BypassWindowManagerHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        # Cover all screens. virtualGeometry() can start at a non-zero /
        # negative origin on multi-monitor setups (e.g. a monitor placed to
        # the left of the primary) — remember that offset so we can convert
        # the widget-local selection rect back to global screen coordinates.
        screen = QApplication.primaryScreen()
        screen_geo = screen.virtualGeometry() if screen else self.rect()
        self.setGeometry(screen_geo)
        self._origin = screen_geo.topLeft()

        # Magnifier label
        self._mag = QLabel(self)
        self._mag.setFixedSize(160, 120)
        self._mag.setStyleSheet("border: 2px solid #00d9a3; border-radius: 4px;")
        self._mag.hide()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = e.position().toPoint()
            self._end = self._start
            self._selecting = True

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        self._end = pos
        if self._selecting:
            self._update_magnifier(pos)
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            self._mag.hide()
            rect = self._selection_rect()
            if rect.width() > 4 and rect.height() > 4:
                # Convert widget-local LOGICAL coordinates to global PHYSICAL
                # screen coordinates: add the (logical) virtual-desktop origin
                # for multi-monitor setups, then scale up to physical pixels
                # since mss.grab() (and the actual screen resolution) works
                # in physical pixels, not the DPI-scaled logical ones Qt uses.
                s = self._scale
                self.region_selected.emit(
                    round((rect.x() + self._origin.x()) * s),
                    round((rect.y() + self._origin.y()) * s),
                    round(rect.width() * s),
                    round(rect.height() * s),
                )
            self.close()

    def _selection_rect(self) -> QRect:
        if not self._start or not self._end:
            return QRect()
        return QRect(
            min(self._start.x(), self._end.x()),
            min(self._start.y(), self._end.y()),
            abs(self._end.x() - self._start.x()),
            abs(self._end.y() - self._start.y()),
        )

    def _update_magnifier(self, pos: QPoint):
        # Zoom 3x around cursor. QPixmap.copy() always operates in the
        # pixmap's raw/physical pixel space regardless of devicePixelRatio,
        # so the logical cursor position and crop size must be scaled up to
        # match — otherwise the magnifier reads from the wrong spot (and, on
        # a scaled display, from a shifted/wrong-sized region).
        s = self._scale
        crop_size = round(40 * s)
        x = max(0, round(pos.x() * s) - crop_size // 2)
        y = max(0, round(pos.y() * s) - crop_size // 2)
        crop = self._bg.copy(x, y, crop_size, crop_size)
        scaled = crop.scaled(QSize(160, 120), Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.FastTransformation)
        self._mag.setPixmap(scaled)
        # Position magnifier away from cursor
        mx = pos.x() + 20
        my = pos.y() - 140
        if my < 0:
            my = pos.y() + 20
        if mx + 160 > self.width():
            mx = pos.x() - 180
        self._mag.move(mx, my)
        self._mag.show()

    def paintEvent(self, e):
        p = QPainter(self)

        # Draw dim background
        p.drawPixmap(0, 0, self._bg)
        p.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if not self._start:
            # Draw instructions
            p.setPen(QColor("white"))
            p.setFont(QFont("Segoe UI", 18))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Drag to select region  •  ESC to cancel")
            p.end()
            return

        rect = self._selection_rect()
        if rect.isValid():
            # Clear selection area (show full brightness). The 3-rect
            # drawPixmap(target, pixmap, source) overload takes `source` in
            # the pixmap's raw physical-pixel space — `target` stays in this
            # widget's logical space, so only `source` needs scaling here.
            s = self._scale
            src_rect = QRect(
                round(rect.x() * s), round(rect.y() * s),
                round(rect.width() * s), round(rect.height() * s),
            )
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.drawPixmap(rect, self._bg, src_rect)

            # Border
            p.setPen(QPen(QColor("#00d9a3"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)

            # Size label
            p.setPen(QColor("white"))
            p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            size_txt = f"{rect.width()} × {rect.height()}"
            lx = rect.x() + 4
            ly = rect.y() - 22 if rect.y() > 30 else rect.y() + 4
            p.fillRect(lx - 4, ly - 16, len(size_txt) * 8 + 8, 22, QColor(0, 0, 0, 160))
            p.drawText(lx, ly, size_txt)

            # Crosshairs
            p.setPen(QPen(QColor(255, 255, 255, 60), 1, Qt.PenStyle.DashLine))
            if self._end:
                p.drawLine(0, self._end.y(), self.width(), self._end.y())
                p.drawLine(self._end.x(), 0, self._end.x(), self.height())

        p.end()


def select_region() -> tuple[int, int, int, int] | None:
    """
    Show region selector and block until user selects or cancels.
    Returns (x, y, w, h) or None.
    Never raises: any failure to grab the background falls back to a plain
    dark overlay so the tool stays usable instead of crashing.
    """
    screen = QApplication.primaryScreen()
    scale = screen.devicePixelRatio() if screen else 1.0
    try:
        pil_bg = grab_all_screens_pil()
        bg_pxm = pil_to_qpixmap(pil_bg)
        # Tell Qt this pixmap's raw (physical) pixels represent
        # physical_size/scale logical pixels — without this, Qt paints it
        # 1:1 in physical pixels, which overflows/looks zoomed-in on any
        # display scaled above 100%.
        bg_pxm.setDevicePixelRatio(scale)
    except Exception:
        geo = screen.virtualGeometry() if screen else QRect(0, 0, 1920, 1080)
        bg_pxm = QPixmap(round(geo.width() * scale), round(geo.height() * scale))
        bg_pxm.setDevicePixelRatio(scale)
        bg_pxm.fill(QColor(20, 20, 30))

    result: list = [None]

    app = QApplication.instance()
    selector = RegionSelector(bg_pxm)

    def on_selected(x, y, w, h):
        result[0] = (x, y, w, h)

    selector.region_selected.connect(on_selected)
    selector.showFullScreen()

    # Run a local event loop until window closes
    loop = selector
    from PyQt6.QtCore import QEventLoop
    local_loop = QEventLoop()
    selector.destroyed.connect(local_loop.quit)
    selector.region_selected.connect(local_loop.quit)
    selector.cancelled.connect(local_loop.quit)
    local_loop.exec()

    return result[0]
