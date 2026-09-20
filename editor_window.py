"""
SnapCap — Main annotation editor window.
Full-featured markup canvas with modern dark UI.
"""
import sys
import re
import math
import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QToolBar, QLabel, QPushButton, QColorDialog, QSlider,
    QFileDialog, QMessageBox, QComboBox, QInputDialog, QSizePolicy,
    QButtonGroup, QToolButton, QFrame, QScrollArea, QStatusBar,
    QMenu, QDialog, QTextEdit, QProgressDialog, QSpinBox,
    QGridLayout, QCheckBox, QLineEdit, QTabWidget, QGroupBox,
)
from PyQt6.QtCore import (
    Qt, QRect, QPoint, QSize, QTimer, QThread, pyqtSignal, QRectF,
    QPointF,
)
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, QFont,
    QAction, QIcon, QCursor, QKeySequence, QPainterPath, QPolygonF,
    QUndoStack, QUndoCommand,
)
from PIL import Image, ImageQt

import config as cfg
import share_manager as sm
import ai_engine as ai
import update_checker
from i18n import t, is_rtl, current_language


# ── Colour palette (theme-aware) ────────────────────────────────────────────────
_THEMES = {
    "dark": {
        "DARK_BG": "#1a1a2e", "PANEL_BG": "#16213e", "ACCENT": "#0f3460",
        "ACCENT2": "#00d9a3", "TEXT_FG": "#eaeaea", "TOOL_BTN": "#1f3a6b",
        "TOOL_HOV": "#3b82f6",
    },
    "light": {
        "DARK_BG": "#f4f5f9", "PANEL_BG": "#ffffff", "ACCENT": "#dfe6f5",
        "ACCENT2": "#00d9a3", "TEXT_FG": "#1c1c2b", "TOOL_BTN": "#e3e7f1",
        "TOOL_HOV": "#c7d2ea",
    },
}

DARK_BG = _THEMES["dark"]["DARK_BG"]
PANEL_BG = _THEMES["dark"]["PANEL_BG"]
ACCENT   = _THEMES["dark"]["ACCENT"]
ACCENT2  = _THEMES["dark"]["ACCENT2"]
TEXT_FG  = _THEMES["dark"]["TEXT_FG"]
TOOL_BTN = _THEMES["dark"]["TOOL_BTN"]
TOOL_HOV = _THEMES["dark"]["TOOL_HOV"]


def detect_windows_theme() -> str:
    """Read the Windows 'app mode' (dark/light) setting from the registry.
    Falls back to 'dark' if unavailable (older Windows, or the key is
    missing/unreadable) — never raises."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "light" if value else "dark"
    except Exception:
        return "dark"


def apply_theme(name: str = "dark"):
    """Swap the module-level color palette. Call before building any stylesheet.
    name="system" resolves to the current Windows dark/light setting."""
    global DARK_BG, PANEL_BG, ACCENT, ACCENT2, TEXT_FG, TOOL_BTN, TOOL_HOV
    if name == "system":
        name = detect_windows_theme()
    palette = _THEMES.get(name, _THEMES["dark"])
    DARK_BG  = palette["DARK_BG"]
    PANEL_BG = palette["PANEL_BG"]
    ACCENT   = palette["ACCENT"]
    ACCENT2  = palette["ACCENT2"]
    TEXT_FG  = palette["TEXT_FG"]
    TOOL_BTN = palette["TOOL_BTN"]
    TOOL_HOV = palette["TOOL_HOV"]


PRESET_COLORS = [
    "#00d9a3", "#ff6b6b", "#feca57", "#48dbfb",
    "#1dd1a1", "#ffffff", "#000000", "#54a0ff",
]

# ── Tool IDs ───────────────────────────────────────────────────────────────────
TOOL_SELECT   = "select"
TOOL_ARROW    = "arrow"
TOOL_LINE     = "line"
TOOL_RECT     = "rect"
TOOL_ELLIPSE  = "ellipse"
TOOL_TEXT     = "text"
TOOL_PEN      = "pen"
TOOL_HIGHLIGHT= "highlight"
TOOL_BLUR     = "blur"
TOOL_PIXELATE = "pixelate"
TOOL_CROP     = "crop"
TOOL_STEP     = "step"     # numbered step circles
TOOL_CALLOUT  = "callout"


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimage = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def qpixmap_to_pil(pxm: QPixmap) -> Image.Image:
    qimg = pxm.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = qimg.width(), qimg.height()
    ptr = qimg.bits()
    ptr.setsize(height * width * 4)
    return Image.frombuffer("RGBA", (width, height), bytes(ptr), "raw", "RGBA", 0, 1)


# ── Canvas ─────────────────────────────────────────────────────────────────────
class Canvas(QWidget):
    status_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_pixmap: Optional[QPixmap] = None   # original image
        self.overlay_pixmap: Optional[QPixmap] = None  # annotations drawn here
        self.display_scale = 1.0
        self.pan_offset = QPoint(0, 0)
        self._pan_start = None

        self.tool = TOOL_ARROW
        self.color = QColor("#00d9a3")
        self.line_width = 3
        self.font_size = 18
        self.opacity = 1.0
        self.fill_shape = False  # Rect/Ellipse: outline-only (default) or solid-filled

        self._drawing = False
        self._start_pt: Optional[QPoint] = None
        self._cur_pt: Optional[QPoint] = None
        self._pen_path: List[QPoint] = []
        self._step_counter = 1
        self._text_items: List[Dict] = []
        self._pending_text_pos: Optional[QPoint] = None

        self.undo_stack: List[QPixmap] = []
        self.redo_stack: List[QPixmap] = []

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(200, 200)

    # ── Image management ───────────────────────────────────────────────────────
    def set_image(self, pil_img: Image.Image):
        self.base_pixmap = pil_to_qpixmap(pil_img)
        self.overlay_pixmap = QPixmap(self.base_pixmap.size())
        self.overlay_pixmap.fill(Qt.GlobalColor.transparent)
        self._step_counter = 1
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._fit_to_window()
        self.update()

    def _fit_to_window(self):
        if not self.base_pixmap:
            return
        sw = self.width() / self.base_pixmap.width()
        sh = self.height() / self.base_pixmap.height()
        self.display_scale = min(sw, sh, 1.0)
        iw = self.base_pixmap.width() * self.display_scale
        ih = self.base_pixmap.height() * self.display_scale
        self.pan_offset = QPoint(
            int((self.width() - iw) / 2),
            int((self.height() - ih) / 2),
        )

    def resizeEvent(self, e):
        self._fit_to_window()
        super().resizeEvent(e)

    # ── Coordinate helpers ─────────────────────────────────────────────────────
    def _to_image(self, pt: QPoint) -> QPoint:
        return QPoint(
            int((pt.x() - self.pan_offset.x()) / self.display_scale),
            int((pt.y() - self.pan_offset.y()) / self.display_scale),
        )

    def _to_screen(self, pt: QPoint) -> QPoint:
        return QPoint(
            int(pt.x() * self.display_scale + self.pan_offset.x()),
            int(pt.y() * self.display_scale + self.pan_offset.y()),
        )

    # ── Undo / Redo ────────────────────────────────────────────────────────────
    def _push_undo(self):
        if self.overlay_pixmap:
            self.undo_stack.append(self.overlay_pixmap.copy())
            self.redo_stack.clear()
            if len(self.undo_stack) > 50:
                self.undo_stack.pop(0)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.overlay_pixmap.copy())
            self.overlay_pixmap = self.undo_stack.pop()
            self.update()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.overlay_pixmap.copy())
            self.overlay_pixmap = self.redo_stack.pop()
            self.update()

    # ── Drawing helpers ────────────────────────────────────────────────────────
    def _painter(self) -> QPainter:
        p = QPainter(self.overlay_pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        return p

    def _pen(self, width=None, color=None, alpha=255) -> QPen:
        c = color or self.color
        c = QColor(c)
        c.setAlpha(alpha)
        pen = QPen(c, width or self.line_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _draw_arrow(self, p: QPainter, start: QPoint, end: QPoint):
        p.setPen(self._pen(self.line_width + 1))
        p.drawLine(start, end)
        # Arrow head
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        hs = max(14, self.line_width * 4)
        for side in (0.4, -0.4):
            ax = end.x() - hs * math.cos(angle - side)
            ay = end.y() - hs * math.sin(angle - side)
            p.drawLine(end, QPoint(int(ax), int(ay)))

    def _draw_step_circle(self, p: QPainter, center: QPoint, number: int):
        r = max(16, self.line_width * 5)
        c = QColor(self.color)
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, r, r)
        p.setPen(QPen(QColor("white")))
        font = QFont("Arial", r - 4, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(QRect(center.x() - r, center.y() - r, r * 2, r * 2),
                   Qt.AlignmentFlag.AlignCenter, str(number))

    def _draw_callout(self, p: QPainter, rect: QRect, text: str):
        c = QColor(self.color)
        c.setAlpha(220)
        p.setBrush(QBrush(c))
        p.setPen(self._pen(2, QColor("white")))
        p.drawRoundedRect(rect, 8, 8)
        p.setPen(QPen(QColor("white")))
        font = QFont("Arial", self.font_size)
        p.setFont(font)
        p.drawText(rect.adjusted(8, 4, -8, -4), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

    # ── Mouse events ───────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if not self.base_pixmap:
            return
        pt = self._to_image(e.position().toPoint())

        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = e.position().toPoint()
            return

        if e.button() == Qt.MouseButton.LeftButton:
            self._push_undo()
            self._drawing = True
            self._start_pt = pt
            self._cur_pt = pt
            self._pen_path = [pt]

            if self.tool == TOOL_TEXT:
                self._pending_text_pos = pt
                self._drawing = False
                self._ask_text(pt)
            elif self.tool == TOOL_STEP:
                p = self._painter()
                self._draw_step_circle(p, pt, self._step_counter)
                p.end()
                self._step_counter += 1
                self._drawing = False
                self.update()

    def mouseMoveEvent(self, e):
        if not self.base_pixmap:
            return
        pt = self._to_image(e.position().toPoint())

        if self._pan_start is not None:
            delta = e.position().toPoint() - self._pan_start
            self.pan_offset += delta
            self._pan_start = e.position().toPoint()
            self.update()
            return

        if self._drawing:
            self._cur_pt = pt
            if self.tool == TOOL_PEN:
                p = self._painter()
                if len(self._pen_path) >= 2:
                    p.setPen(self._pen())
                    p.drawLine(self._pen_path[-1], pt)
                self._pen_path.append(pt)
                p.end()
            self.update()

        # Status bar coordinates
        self.status_changed.emit(f"  x:{pt.x()}  y:{pt.y()}")

    def mouseReleaseEvent(self, e):
        if not self.base_pixmap or not self._drawing:
            return
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = None
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return

        pt = self._to_image(e.position().toPoint())
        self._cur_pt = pt
        self._drawing = False

        start = self._start_pt
        end = pt
        rect = QRect(
            min(start.x(), end.x()), min(start.y(), end.y()),
            abs(end.x() - start.x()), abs(end.y() - start.y()),
        )

        p = self._painter()

        if self.tool == TOOL_ARROW:
            self._draw_arrow(p, start, end)
        elif self.tool == TOOL_LINE:
            p.setPen(self._pen())
            p.drawLine(start, end)
        elif self.tool == TOOL_RECT:
            p.setPen(self._pen())
            p.setBrush(QBrush(self.color) if self.fill_shape else Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
        elif self.tool == TOOL_ELLIPSE:
            p.setPen(self._pen())
            p.setBrush(QBrush(self.color) if self.fill_shape else Qt.BrushStyle.NoBrush)
            p.drawEllipse(rect)
        elif self.tool == TOOL_HIGHLIGHT:
            c = QColor(self.color)
            c.setAlpha(80)
            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(rect)
        elif self.tool in (TOOL_BLUR, TOOL_PIXELATE):
            p.end()
            self._apply_region_effect(rect, self.tool)
            self.update()
            return
        elif self.tool == TOOL_CALLOUT:
            text, ok = QInputDialog.getText(self, "Callout Text", "Enter text:")
            if ok and text:
                self._draw_callout(p, rect, text)

        p.end()
        self.update()

    def _ask_text(self, pos: QPoint):
        text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
        if ok and text:
            p = self._painter()
            p.setPen(QPen(self.color))
            font = QFont("Arial", self.font_size, QFont.Weight.Bold)
            p.setFont(font)
            p.drawText(pos, text)
            p.end()
            self.update()

    def _apply_region_effect(self, rect: QRect, effect: str):
        """Apply blur/pixelate to a region of the base+overlay composite."""
        composite = self._get_composite_pil()
        crop = composite.crop((rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height()))
        if crop.width <= 0 or crop.height <= 0:
            return
        if effect == TOOL_BLUR:
            from PIL import ImageFilter
            crop = crop.filter(ImageFilter.GaussianBlur(radius=12))
        elif effect == TOOL_PIXELATE:
            small = crop.resize((max(1, crop.width // 8), max(1, crop.height // 8)), Image.NEAREST)
            crop = small.resize((crop.width, crop.height), Image.NEAREST)
        crop_pxm = pil_to_qpixmap(crop)
        p = self._painter()
        p.drawPixmap(rect.x(), rect.y(), crop_pxm)
        p.end()

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        self.display_scale = max(0.1, min(5.0, self.display_scale * factor))
        self.update()

    # ── Paint event ────────────────────────────────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#2b2b3b"))

        if not self.base_pixmap:
            p.setPen(QColor(TEXT_FG))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No image loaded")
            return

        iw = int(self.base_pixmap.width() * self.display_scale)
        ih = int(self.base_pixmap.height() * self.display_scale)
        dest = QRect(self.pan_offset.x(), self.pan_offset.y(), iw, ih)

        p.drawPixmap(dest, self.base_pixmap)
        if self.overlay_pixmap:
            p.drawPixmap(dest, self.overlay_pixmap)

        # Live preview
        if self._drawing and self._start_pt and self._cur_pt:
            start = self._to_screen(self._start_pt)
            end = self._to_screen(self._cur_pt)
            rect = QRect(min(start.x(), end.x()), min(start.y(), end.y()),
                         abs(end.x() - start.x()), abs(end.y() - start.y()))
            p.setOpacity(0.7)
            if self.tool == TOOL_ARROW:
                p.setPen(self._pen(self.line_width + 1, self.color))
                self._draw_arrow(p, start, end)
            elif self.tool == TOOL_RECT:
                p.setPen(self._pen(self.line_width, self.color))
                p.setBrush(QBrush(self.color) if self.fill_shape else Qt.BrushStyle.NoBrush)
                p.drawRect(rect)
            elif self.tool == TOOL_ELLIPSE:
                p.setPen(self._pen(self.line_width, self.color))
                p.setBrush(QBrush(self.color) if self.fill_shape else Qt.BrushStyle.NoBrush)
                p.drawEllipse(rect)
            elif self.tool in (TOOL_BLUR, TOOL_PIXELATE, TOOL_HIGHLIGHT, TOOL_CROP):
                c = QColor(ACCENT2)
                c.setAlpha(50)
                p.setBrush(QBrush(c))
                p.setPen(QPen(QColor(ACCENT2), 1, Qt.PenStyle.DashLine))
                p.drawRect(rect)
        p.end()

    # ── Export ─────────────────────────────────────────────────────────────────
    def _get_composite_pil(self) -> Image.Image:
        if not self.base_pixmap:
            return Image.new("RGBA", (100, 100))
        composite = self.base_pixmap.copy()
        if self.overlay_pixmap:
            p = QPainter(composite)
            p.drawPixmap(0, 0, self.overlay_pixmap)
            p.end()
        return qpixmap_to_pil(composite)

    def get_final_image(self) -> Image.Image:
        return self._get_composite_pil().convert("RGB")


# ── AI Worker Thread ──────────────────────────────────────────────────────────
class AIWorker(QThread):
    result_ready = pyqtSignal(str, str)  # (task_name, result_text)
    error = pyqtSignal(str)

    def __init__(self, task: str, img: Image.Image, api_key: str):
        super().__init__()
        self.task = task
        self.img = img
        self.api_key = api_key

    def run(self):
        try:
            fn = {
                "summarize": ai.ai_summarize,
                "alt_text": ai.ai_alt_text,
                "extract": ai.ai_extract_text_structured,
                "steps": ai.ai_generate_steps,
                "title": ai.ai_smart_title,
                "bug_report": ai.ai_bug_report,
            }.get(self.task)
            if fn:
                result = fn(self.img, self.api_key)
                self.result_ready.emit(self.task, result)
            else:
                self.error.emit(f"Unknown task: {self.task}")
        except Exception as e:
            self.error.emit(str(e))


# Strong references to open PinWindow instances — without this, nothing
# outside a local variable would keep them alive, and PyQt could garbage
# collect (and silently close) the underlying C++ widget the moment the
# Python object that created it goes out of scope.
_PINNED_WINDOWS: list = []


# ── Pin to Screen ────────────────────────────────────────────────────────────
class PinWindow(QWidget):
    """A frameless, always-on-top floating copy of the screenshot — lets the
    user keep a capture visible while working in other windows (e.g.
    comparing a design mock against a live page, or keeping reference notes
    in view). This is the single most-requested feature SnapCap was missing
    relative to CleanShot X / Flameshot, both of which popularized "pin to
    screen"; unlike a cloud upload or a saved file it needs zero network
    access and no dependency — a frameless QWidget is all it takes.

    Interaction: drag with the left mouse button to move, scroll the mouse
    wheel to resize, right-click (or double-click) to close. Kept deliberately
    minimal — no toolbar of its own — since its whole purpose is to get out
    of the way visually while staying on top.
    """

    MIN_SCALE = 0.2
    MAX_SCALE = 3.0

    def __init__(self, pil_img: Image.Image):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._pixmap = pil_to_qpixmap(pil_img)
        self._scale = 1.0
        self._drag_offset: Optional[QPoint] = None
        self.setToolTip(t("pin_tooltip", current_language()))
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._apply_size()

    def _apply_size(self):
        w = max(40, int(self._pixmap.width() * self._scale))
        h = max(40, int(self._pixmap.height() * self._scale))
        self.resize(w, h)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), self._pixmap)
        pen = QPen(QColor(ACCENT2))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        self.close()

    def contextMenuEvent(self, e):
        self.close()

    def wheelEvent(self, e):
        # Resize around the cursor position rather than the top-left corner,
        # so zooming feels anchored to what the user is pointing at.
        old_scale = self._scale
        delta = 0.1 if e.angleDelta().y() > 0 else -0.1
        new_scale = min(self.MAX_SCALE, max(self.MIN_SCALE, self._scale + delta))
        if new_scale == old_scale:
            return
        cursor_global = e.globalPosition().toPoint()
        offset = cursor_global - self.pos()
        ratio = new_scale / old_scale
        new_offset = QPoint(int(offset.x() * ratio), int(offset.y() * ratio))
        self._scale = new_scale
        self._apply_size()
        self.move(cursor_global - new_offset)


# ── Main Editor Window ────────────────────────────────────────────────────────
class EditorWindow(QMainWindow):
    def __init__(self, pil_image: Optional[Image.Image] = None):
        super().__init__()
        self.pil_image = pil_image
        self._conf = cfg.load()
        self._ai_worker: Optional[AIWorker] = None
        apply_theme(self._conf.get("theme", "system"))

        self.setWindowTitle("SnapCap — Editor")
        self.setMinimumSize(720, 480)
        self._apply_style()
        self._size_to_image(pil_image)

        self._build_ui()
        self._build_menubar()
        self._build_shortcuts()

        if pil_image:
            self.canvas.set_image(pil_image)

    def _size_to_image(self, pil_image: Optional[Image.Image]):
        """Size the window to fit the captured image at 1:1, instead of
        always opening at a fixed 1280x800 — a small screenshot now gets a
        small, tidy window instead of swimming in a mostly-empty canvas."""
        TOOL_PANEL_W, OPTIONS_PANEL_W = 80, 250
        CHROME_W = TOOL_PANEL_W + OPTIONS_PANEL_W + 24  # side panels + a little canvas margin
        CHROME_H = 120  # menu bar + status bar + margins

        if not pil_image:
            self.resize(1280, 800)
            return

        screen = QApplication.primaryScreen()
        scale = screen.devicePixelRatio() if screen else 1.0
        # pil_image is in raw/physical pixels (see capture_engine.py); divide
        # by the display scale to get the logical size Qt actually lays out.
        img_w = pil_image.width / scale
        img_h = pil_image.height / scale

        target_w = int(img_w + CHROME_W)
        target_h = int(img_h + CHROME_H)

        avail = screen.availableGeometry() if screen else None
        max_w = int(avail.width() * 0.9) if avail else 1600
        max_h = int(avail.height() * 0.9) if avail else 1000

        target_w = max(self.minimumWidth(), min(target_w, max_w))
        target_h = max(self.minimumHeight(), min(target_h, max_h))
        self.resize(target_w, target_h)

    # ── Styling ────────────────────────────────────────────────────────────────
    def _apply_style(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {DARK_BG}; color: {TEXT_FG}; font-family: 'Segoe UI'; font-size: 13px; }}
            QToolBar {{ background: {PANEL_BG}; border: none; spacing: 6px; padding: 6px; }}
            QToolButton {{
                background: {TOOL_BTN}; border: none; border-radius: 10px;
                padding: 6px 10px; color: {TEXT_FG};
            }}
            QToolButton:hover {{ background: {TOOL_HOV}; }}
            QToolButton:checked {{ background: {ACCENT2}; color: #1a1a2e; }}
            QPushButton {{
                background: {TOOL_BTN}; border: none; border-radius: 10px;
                padding: 7px 14px; color: {TEXT_FG};
            }}
            QPushButton:hover {{ background: {TOOL_HOV}; }}
            QPushButton#accent {{ background: {ACCENT2}; color: #1a1a2e; font-weight: bold; }}
            QPushButton#accent:hover {{ background: #00b386; }}
            QComboBox, QSpinBox {{
                background: {PANEL_BG}; border: 1px solid {TOOL_BTN};
                border-radius: 8px; padding: 4px 8px; color: {TEXT_FG};
            }}
            QLabel {{ color: {TEXT_FG}; }}
            QGroupBox {{
                border: 1px solid {TOOL_BTN}; border-radius: 10px;
                margin-top: 10px; padding: 10px 8px 4px 8px; font-weight: bold;
                color: {TEXT_FG};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 6px;
                color: {TEXT_FG};
            }}
            QStatusBar {{ background: {PANEL_BG}; color: #aaa; padding: 2px 8px; }}
            QSlider::groove:horizontal {{
                background: {TOOL_BTN}; height: 4px; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {ACCENT2}; width: 14px; height: 14px;
                margin: -5px 0; border-radius: 7px;
            }}
            QMenuBar {{ background: {PANEL_BG}; color: {TEXT_FG}; }}
            QMenuBar::item:selected {{ background: {TOOL_HOV}; border-radius: 8px; }}
            QMenu {{ background: {PANEL_BG}; color: {TEXT_FG}; border: 1px solid {TOOL_BTN}; border-radius: 10px; padding: 4px; }}
            QMenu::item {{ border-radius: 6px; padding: 6px 10px; }}
            QMenu::item:selected {{ background: {TOOL_HOV}; }}
            QTextEdit {{ background: {PANEL_BG}; border: 1px solid {TOOL_BTN}; border-radius: 10px; color: {TEXT_FG}; }}
        """)

    # ── UI Construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Options panel (Share/OCR/AI/Redact) — leftmost, per user preference
        layout.addWidget(self._build_right_panel())

        # Drawing tool panel — next to the canvas it controls
        layout.addWidget(self._build_tool_panel())

        # Canvas
        self.canvas = Canvas()
        self.canvas.status_changed.connect(self._on_canvas_status)
        layout.addWidget(self.canvas, 1)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("  Ready — select a tool and start annotating")

    def _tool_btn(self, label: str, icon: str, tool_id: str, group: QButtonGroup) -> QToolButton:
        btn = QToolButton()
        btn.setText(f"{icon}\n{label}")
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setCheckable(True)
        btn.setFixedSize(64, 58)
        btn.setToolTip(label)
        btn.clicked.connect(lambda: self._set_tool(tool_id))
        group.addButton(btn)
        return btn

    def _build_tool_panel(self) -> QWidget:
        # 13 tools + color picker + width spinner + color grid need ~900px of
        # vertical space — taller than the window can get when it's sized to
        # a small screenshot (see _size_to_image). Without a scroll area, the
        # bottom tools/controls are silently clipped off-window on a short
        # capture. Wrapping in a QScrollArea keeps every control reachable
        # regardless of window height, instead of some just disappearing.
        inner = QWidget()
        inner.setStyleSheet(f"background: {PANEL_BG};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        group = QButtonGroup(self)
        group.setExclusive(True)

        tools = [
            ("Select", "↖", TOOL_SELECT),
            ("Arrow", "→", TOOL_ARROW),
            ("Line", "╱", TOOL_LINE),
            ("Rect", "□", TOOL_RECT),
            ("Ellipse", "○", TOOL_ELLIPSE),
            ("Highlight", "▬", TOOL_HIGHLIGHT),
            ("Text", "T", TOOL_TEXT),
            ("Pen", "✏", TOOL_PEN),
            ("Step", "①", TOOL_STEP),
            ("Callout", "💬", TOOL_CALLOUT),
            ("Blur", "◎", TOOL_BLUR),
            ("Pixelate", "⊞", TOOL_PIXELATE),
            ("Crop", "⊡", TOOL_CROP),
        ]

        self._tool_buttons: Dict[str, QToolButton] = {}
        for label, icon, tid in tools:
            btn = self._tool_btn(label, icon, tid, group)
            self._tool_buttons[tid] = btn
            layout.addWidget(btn)
            if tid == TOOL_ARROW:
                btn.setChecked(True)

        layout.addStretch()

        # Color picker swatch
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(48, 28)
        self._color_btn.setToolTip("Pick color")
        self._update_color_btn()
        self._color_btn.clicked.connect(self._pick_color)
        layout.addWidget(self._color_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Line width
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 20)
        self._width_spin.setValue(3)
        self._width_spin.setToolTip("Stroke width")
        self._width_spin.valueChanged.connect(lambda v: setattr(self.canvas, "line_width", v))
        self._width_spin.setFixedWidth(56)
        layout.addWidget(self._width_spin, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Text/callout font size — previously hardcoded at 18 with no way to
        # change it from the UI at all.
        self._font_spin = QSpinBox()
        self._font_spin.setRange(8, 96)
        self._font_spin.setValue(18)
        self._font_spin.setToolTip("Text size (Text / Callout tools)")
        self._font_spin.valueChanged.connect(lambda v: setattr(self.canvas, "font_size", v))
        self._font_spin.setFixedWidth(56)
        layout.addWidget(self._font_spin, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Fill toggle — Rect/Ellipse only; outline-only stays the default so
        # existing muscle memory/behavior doesn't change.
        self._fill_cb = QCheckBox("Fill")
        self._fill_cb.setToolTip("Fill Rect / Ellipse with the selected color")
        self._fill_cb.toggled.connect(lambda v: setattr(self.canvas, "fill_shape", bool(v)))
        layout.addWidget(self._fill_cb, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Preset colors row
        clr_grid = QGridLayout()
        clr_grid.setSpacing(3)
        for i, hex_c in enumerate(PRESET_COLORS):
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setStyleSheet(f"background:{hex_c}; border-radius:3px; border:none;")
            btn.clicked.connect(lambda _, c=hex_c: self._set_color(QColor(c)))
            clr_grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(clr_grid)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(80)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {PANEL_BG}; border: none; }}")
        return scroll

    def _section_btn(self, label: str, slot) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{ background: {TOOL_BTN}; color: {TEXT_FG}; border: none;
                          border-radius: 9px; padding: 8px 10px; text-align: left; }}
            QPushButton:hover {{ background: {TOOL_HOV}; }}
        """)
        btn.clicked.connect(slot)
        return btn

    def _collapsible_section(self, title: str, content: QWidget, expanded: bool = False) -> QWidget:
        """A custom accordion header, used instead of QToolBox: QToolBox only
        paints its *selected* tab with a visible background via stylesheets
        on this Qt build — every other tab renders as bare unstyled text,
        which is exactly the "some things don't stand out" look reported.
        Reusing the same QPushButton styling as _section_btn for every
        header guarantees all four categories look equally prominent."""
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 4)
        v.setSpacing(4)

        header = QPushButton(f"{'▾' if expanded else '▸'}  {title}")
        header.setCheckable(True)
        header.setChecked(expanded)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setStyleSheet(f"""
            QPushButton {{ background: {TOOL_BTN}; color: {TEXT_FG}; border: none;
                          border-radius: 9px; padding: 10px; text-align: left;
                          font-weight: bold; font-size: 13px; }}
            QPushButton:hover {{ background: {TOOL_HOV}; }}
            QPushButton:checked {{ background: {ACCENT2}; color: #1a1a2e; }}
        """)
        content.setVisible(expanded)

        def _toggle():
            is_open = header.isChecked()
            content.setVisible(is_open)
            header.setText(f"{'▾' if is_open else '▸'}  {title}")

        header.clicked.connect(_toggle)
        v.addWidget(header)
        v.addWidget(content)
        return wrap

    def _build_right_panel(self) -> QWidget:
        # Categories collapse into a custom accordion instead of one long
        # stacked list of ~17 buttons — only expanded categories take up
        # space, which is what made the old panel feel cluttered and forced
        # the window to grow taller than it needed to.
        panel = QWidget()
        panel.setFixedWidth(250)
        panel.setStyleSheet(f"background: {PANEL_BG};")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # Accordion section scrolls independently — on a short window (a
        # small screenshot sizes the whole window small, see _size_to_image)
        # an expanded section could otherwise push content below the visible
        # area with no way to reach it.
        accordion_inner = QWidget()
        accordion_inner.setStyleSheet(f"background: {PANEL_BG};")
        outer = QVBoxLayout(accordion_inner)
        outer.setContentsMargins(8, 8, 8, 0)
        outer.setSpacing(4)

        # ── Share & Export ───────────────────────────────────────────────────
        share_page = QWidget()
        sl = QVBoxLayout(share_page)
        sl.setContentsMargins(4, 6, 4, 4)
        sl.setSpacing(6)
        sl.addWidget(self._section_btn("📋  Copy to Clipboard", self._copy_clipboard))
        sl.addWidget(self._section_btn("💾  Save File", self._save_file))
        sl.addWidget(self._section_btn("📁  Save As…", self._save_as))
        sl.addWidget(self._section_btn(t("pin_to_screen", current_language()), self._pin_to_screen))
        sl.addWidget(self._section_btn("☁  Upload to Imgur", self._upload_imgur))
        sl.addWidget(self._section_btn("✉  Open in Mail", self._open_mail))
        sl.addWidget(self._section_btn("🖌  Open in Paint", self._open_paint))
        outer.addWidget(self._collapsible_section("Share & Export", share_page, expanded=True))

        # ── Extract Text (OCR) ───────────────────────────────────────────────
        ocr_page = QWidget()
        ol = QVBoxLayout(ocr_page)
        ol.setContentsMargins(4, 6, 4, 4)
        ol.setSpacing(6)
        ol.addWidget(self._section_btn("Extract All Text", self._ocr_text))
        ol.addWidget(self._section_btn("Extract as Table/CSV", self._ocr_table))
        outer.addWidget(self._collapsible_section("Extract Text (OCR)", ocr_page))

        # ── AI Tools — grouped by what they do, not one flat list ───────────
        ai_page = QWidget()
        al = QVBoxLayout(ai_page)
        al.setContentsMargins(4, 6, 4, 4)
        al.setSpacing(8)

        self._ai_status = QLabel("⚙  API key not set")
        self._ai_status.setStyleSheet("color: #aaa; font-size: 11px;")
        al.addWidget(self._ai_status)
        self._refresh_ai_status()

        ai_groups = [
            ("Understand", [
                ("📝  Summarize", "summarize"),
                ("♿  Generate Alt-Text", "alt_text"),
            ]),
            ("Extract", [
                ("🔤  Structured Text", "extract"),
                ("📋  Step-by-Step List", "steps"),
            ]),
            ("Create", [
                ("🐛  Bug Report", "bug_report"),
                ("✨  Smart Title/Filename", "title"),
            ]),
        ]
        for group_name, items in ai_groups:
            gl = QLabel(group_name.upper())
            gl.setStyleSheet("color: #9aa4bd; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
            al.addWidget(gl)
            for label, task in items:
                al.addWidget(self._section_btn(label, lambda _, t=task: self._run_ai(t)))
        outer.addWidget(self._collapsible_section("AI Tools", ai_page))

        # ── Smart Redaction ──────────────────────────────────────────────────
        redact_page = QWidget()
        rl = QVBoxLayout(redact_page)
        rl.setContentsMargins(4, 6, 4, 4)
        rl.setSpacing(6)
        rl.addWidget(self._section_btn("Auto-Redact PII", self._auto_redact))
        outer.addWidget(self._collapsible_section("Smart Redaction", redact_page))

        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(accordion_inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {PANEL_BG}; border: none; }}")
        panel_layout.addWidget(scroll, 1)

        # ── Persistent footer: AI output + step reset (visible regardless of
        # which accordion category is open, since results matter no matter
        # which tool produced them) — kept OUTSIDE the scroll area so it never
        # scrolls out of view itself. ────────────────────────────────────────
        footer = QWidget()
        footer.setStyleSheet(f"background: {PANEL_BG};")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(8, 6, 8, 8)
        fl.setSpacing(4)

        self._ai_output = QTextEdit()
        self._ai_output.setPlaceholderText("AI / OCR results appear here…")
        self._ai_output.setFixedHeight(110)
        self._ai_output.setReadOnly(True)
        fl.addWidget(self._ai_output)

        reset_step_btn = QPushButton("↺  Reset Step Counter")
        reset_step_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_step_btn.setStyleSheet("color: #aaa; font-size: 11px; background: transparent; border: none;")
        reset_step_btn.clicked.connect(lambda: setattr(self.canvas, "_step_counter", 1))
        fl.addWidget(reset_step_btn)

        panel_layout.addWidget(footer)
        return panel

    def _hline(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"color: {TOOL_BTN};")
        return f

    # ── Menubar ────────────────────────────────────────────────────────────────
    def _add_action(self, menu, text: str, slot, shortcut: str = None) -> QAction:
        """Build a QAction explicitly instead of QMenu.addAction(text, slot, shortcut) —
        that convenience overload's argument order is not the same across
        PyQt5/PyQt6 and mismatching it raises a TypeError at menu-build time
        (this crashed the editor window on every capture)."""
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _build_menubar(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        self._add_action(file_menu, "Open Image…", self._open_image, "Ctrl+O")
        self._add_action(file_menu, "Save", self._save_file, "Ctrl+S")
        self._add_action(file_menu, "Save As…", self._save_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        self._add_action(file_menu, "Close", self.close, "Ctrl+W")

        edit_menu = mb.addMenu("Edit")
        self._add_action(edit_menu, "Undo", self.canvas.undo, "Ctrl+Z")
        self._add_action(edit_menu, "Redo", self.canvas.redo, "Ctrl+Y")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Copy to Clipboard", self._copy_clipboard, "Ctrl+C")

        view_menu = mb.addMenu("View")
        self._add_action(view_menu, "Fit to Window", self.canvas._fit_to_window, "Ctrl+0")

        tools_menu = mb.addMenu("Tools")
        self._add_action(tools_menu, "OCR — Extract Text", self._ocr_text)
        self._add_action(tools_menu, "OCR — Extract Table", self._ocr_table)
        self._add_action(tools_menu, "Auto-Redact PII", self._auto_redact)
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Settings…", self._open_settings)

        ai_menu = mb.addMenu("AI")
        self._add_action(ai_menu, "Summarize Screenshot", lambda: self._run_ai("summarize"))
        self._add_action(ai_menu, "Generate Alt-Text", lambda: self._run_ai("alt_text"))
        self._add_action(ai_menu, "Extract Structured Text", lambda: self._run_ai("extract"))
        self._add_action(ai_menu, "Generate Step List", lambda: self._run_ai("steps"))
        self._add_action(ai_menu, "Bug Report", lambda: self._run_ai("bug_report"))
        self._add_action(ai_menu, "Smart Filename", lambda: self._run_ai("title"))

    # ── Shortcuts ──────────────────────────────────────────────────────────────
    def _build_shortcuts(self):
        shortcuts = {
            "A": TOOL_ARROW, "L": TOOL_LINE, "R": TOOL_RECT,
            "E": TOOL_ELLIPSE, "T": TOOL_TEXT, "P": TOOL_PEN,
            "H": TOOL_HIGHLIGHT, "S": TOOL_STEP, "B": TOOL_BLUR,
        }
        for key, tool in shortcuts.items():
            # QShortcut lives in QtGui under PyQt6 (it was QtWidgets in PyQt5)
            from PyQt6.QtGui import QShortcut
            QShortcut(QKeySequence(key), self).activated.connect(lambda t=tool: self._set_tool(t))

    # ── Actions ────────────────────────────────────────────────────────────────
    def _set_tool(self, tool_id: str):
        self.canvas.tool = tool_id
        cursor_map = {
            TOOL_SELECT: Qt.CursorShape.ArrowCursor,
            TOOL_TEXT: Qt.CursorShape.IBeamCursor,
            TOOL_BLUR: Qt.CursorShape.PointingHandCursor,
            TOOL_PIXELATE: Qt.CursorShape.PointingHandCursor,
            TOOL_CROP: Qt.CursorShape.SizeFDiagCursor,
        }
        self.canvas.setCursor(cursor_map.get(tool_id, Qt.CursorShape.CrossCursor))
        if tool_id in self._tool_buttons:
            self._tool_buttons[tool_id].setChecked(True)

    def _pick_color(self):
        col = QColorDialog.getColor(self.canvas.color, self, "Choose Color")
        if col.isValid():
            self._set_color(col)

    def _set_color(self, col: QColor):
        self.canvas.color = col
        self._update_color_btn()

    def _update_color_btn(self):
        c = self.canvas.color.name() if hasattr(self, "canvas") else "#00d9a3"
        self._color_btn.setStyleSheet(
            f"background: {c}; border: 2px solid #fff; border-radius: 6px;"
        )

    def _on_canvas_status(self, msg: str):
        self.status.showMessage(msg)

    def _get_final(self) -> Image.Image:
        return self.canvas.get_final_image()

    def _copy_clipboard(self):
        img = self._get_final()
        sm.copy_to_clipboard(img)
        self.status.showMessage("  ✓ Copied to clipboard")

    def _pin_to_screen(self):
        """Open the current annotated image as an always-on-top floating
        window (see PinWindow). Held in a module-level list so it isn't
        garbage-collected the moment this method returns or the editor
        window that spawned it is closed — a pin is meant to outlive the
        editor it came from."""
        img = self._get_final()
        pin = PinWindow(img)
        _PINNED_WINDOWS.append(pin)
        pin.destroyed.connect(lambda: _PINNED_WINDOWS.remove(pin) if pin in _PINNED_WINDOWS else None)
        # Center on the primary screen initially.
        screen = QApplication.primaryScreen().availableGeometry()
        pin.move(
            screen.center().x() - pin.width() // 2,
            screen.center().y() - pin.height() // 2,
        )
        pin.show()
        self.status.showMessage("  📌 Pinned to screen — drag to move, scroll to resize, right-click to close")

    def _save_file(self):
        img = self._get_final()
        path = sm.save_image(img)
        self.status.showMessage(f"  ✓ Saved: {path}")

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot As", str(Path.home() / "screenshot.png"),
            "Images (*.png *.jpg *.webp)"
        )
        if path:
            img = self._get_final()
            dest = Path(path)
            ext = dest.suffix.lower().strip(".") or "png"
            if ext in ("jpg", "jpeg"):
                img.convert("RGB").save(dest, "JPEG", quality=self._conf.get("jpeg_quality", 90), optimize=True)
            elif ext == "webp":
                img.save(dest, "WEBP", quality=90)
            else:
                img.save(dest, "PNG", optimize=True)
            self.status.showMessage(f"  ✓ Saved: {path}")

    def _upload_imgur(self):
        cid = self._conf.get("upload_targets", {}).get("imgur", {}).get("client_id", "")
        if not cid:
            QMessageBox.warning(self, "Imgur", "Set your Imgur Client ID in Settings first.")
            return
        img = self._get_final()
        url = sm.upload_imgur(img, cid)
        if url:
            import pyperclip
            pyperclip.copy(url)
            QMessageBox.information(self, "Imgur", f"Uploaded!\n{url}\n\n(URL copied to clipboard)")
        else:
            QMessageBox.critical(self, "Imgur", "Upload failed.")

    def _open_mail(self):
        img = self._get_final()
        path = sm.save_image(img)
        sm.open_in_mail(path)

    def _open_paint(self):
        img = self._get_final()
        path = sm.save_image(img)
        sm.open_in_paint(path)

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            img = Image.open(path)
            self.canvas.set_image(img)

    def _ocr_text(self):
        img = self._get_final()
        text = ai.ocr_extract_text(img)
        self._show_text_result("OCR — Extracted Text", text)

    def _ocr_table(self):
        img = self._get_final()
        table = ai.ocr_extract_table(img)
        if table:
            csv_text = ai.table_to_csv(table)
            self._show_text_result("OCR — Table (CSV)", csv_text, copyable=True)
        else:
            QMessageBox.information(self, "OCR Table", "No table structure detected in the image.")

    def _auto_redact(self):
        img = self._get_final()
        types = ["email", "phone", "credit_card", "api_key", "israeli_id"]
        redacted, findings = ai.auto_redact(img, types, style="blur")
        if not findings:
            QMessageBox.information(self, "Auto-Redact", "No sensitive data (PII) detected.")
            return
        summary = "\n".join(f"  • {f['type']}: {f['text']}" for f in findings[:10])
        reply = QMessageBox.question(
            self, "Auto-Redact",
            f"Found {len(findings)} sensitive item(s):\n{summary}\n\nApply redaction?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.canvas.set_image(redacted)
            self.status.showMessage(f"  ✓ Redacted {len(findings)} items")

    def _refresh_ai_status(self):
        key = self._conf.get("anthropic_api_key", "")
        if key:
            self._ai_status.setText("✅  Claude API connected")
            self._ai_status.setStyleSheet("color: #1dd1a1; font-size: 11px;")
        else:
            self._ai_status.setText("⚙  Set API key in Settings")

    def _run_ai(self, task: str):
        key = self._conf.get("anthropic_api_key", "")
        if not key:
            reply = QMessageBox.question(
                self, "AI Feature",
                "Anthropic API key not set. Open Settings to add it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._open_settings()
            return

        img = self._get_final()
        self._ai_output.setPlainText("⏳ Running AI analysis…")
        self._ai_worker = AIWorker(task, img, key)
        self._ai_worker.result_ready.connect(self._on_ai_result)
        self._ai_worker.error.connect(lambda e: self._ai_output.setPlainText(f"Error: {e}"))
        self._ai_worker.start()

    def _on_ai_result(self, task: str, result: str):
        labels = {
            "summarize": "📝 Summary",
            "alt_text": "♿ Alt-Text",
            "extract": "🔤 Extracted Text",
            "steps": "📋 Steps",
            "title": "✨ Suggested Filename",
            "bug_report": "🐛 Bug Report",
        }
        label = labels.get(task, task)
        self._ai_output.setPlainText(f"{label}:\n\n{result}")
        self.status.showMessage(f"  ✓ AI {label} complete")

    def _show_text_result(self, title: str, text: str, copyable: bool = False):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumSize(500, 350)
        dlg.setStyleSheet(self.styleSheet())
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setPlainText(text)
        layout.addWidget(te)
        btns = QHBoxLayout()
        if copyable:
            cp = QPushButton("Copy CSV")
            cp.clicked.connect(lambda: pyperclip.copy(text))
            btns.addWidget(cp)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        btns.addWidget(close)
        layout.addLayout(btns)
        dlg.exec()

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self._conf = cfg.load()
            self._refresh_ai_status()


# ── Settings Dialog ────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._conf = cfg.load()
        self._lang = current_language()
        apply_theme(self._conf.get("theme", "system"))
        self.setWindowTitle(t("settings_title", self._lang))
        self.setMinimumSize(500, 560)
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl(self._lang) else Qt.LayoutDirection.LeftToRight
        )
        self.setStyleSheet(parent.styleSheet() if parent else f"""
            QDialog {{ background: {DARK_BG}; color: {TEXT_FG}; font-family: 'Segoe UI'; }}
            QLabel {{ color: {TEXT_FG}; }}
            QLineEdit, QComboBox {{
                background: {PANEL_BG}; color: {TEXT_FG}; border: 1px solid {TOOL_BTN};
                border-radius: 8px; padding: 6px 10px;
            }}
            QCheckBox {{ color: {TEXT_FG}; }}
            QGroupBox {{
                border: 1px solid {TOOL_BTN}; border-radius: 10px;
                margin-top: 10px; padding: 10px 8px 4px 8px; font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 6px;
                color: {TEXT_FG};
            }}
            QTabWidget::pane {{ border: 1px solid {TOOL_BTN}; background: {PANEL_BG}; border-radius: 8px; }}
            QTabBar::tab {{ background: {PANEL_BG}; color: {TEXT_FG}; padding: 8px 16px; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
            QTabBar::tab:selected {{ background: {TOOL_HOV}; }}
            QPushButton {{ background: {TOOL_BTN}; color: {TEXT_FG}; border: none;
                          border-radius: 9px; padding: 8px 18px; }}
            QPushButton#accent {{ background: {ACCENT2}; color: #1a1a2e; font-weight: bold; }}
            QPushButton:hover {{ background: {TOOL_HOV}; }}
        """)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), t("tab_general", self._lang))
        tabs.addTab(self._ai_tab(), t("tab_ai", self._lang))
        tabs.addTab(self._upload_tab(), t("tab_upload", self._lang))
        tabs.addTab(self._hotkeys_tab(), t("tab_hotkeys", self._lang))
        tabs.addTab(self._advanced_tab(), t("tab_advanced", self._lang))
        layout.addWidget(tabs)

        btns = QHBoxLayout()
        save = QPushButton(t("save", self._lang))
        save.setObjectName("accent")
        save.clicked.connect(self._save)
        cancel = QPushButton(t("cancel", self._lang))
        cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    def _row(self, label: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addStretch()
        row.addWidget(widget)
        return row

    def _general_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        lang = self._lang

        # ── Appearance ────────────────────────────────────────────────────────
        appearance_box = QGroupBox(t("grp_appearance", lang))
        al = QVBoxLayout(appearance_box)

        self._lang_combo = QComboBox()
        self._lang_combo.addItem(t("lang_english", "en"), "en")
        self._lang_combo.addItem(t("lang_hebrew", "he"), "he")
        current = self._conf.get("language", "auto")
        if current == "auto":
            current = current_language()
        idx = self._lang_combo.findData(current)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        al.addLayout(self._row(t("lbl_language", lang), self._lang_combo))

        self._theme_combo = QComboBox()
        self._theme_combo.addItem("🖥️ System", "system")
        self._theme_combo.addItem("🌙 Dark", "dark")
        self._theme_combo.addItem("☀️ Light", "light")
        idx = self._theme_combo.findData(self._conf.get("theme", "system"))
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        al.addLayout(self._row(t("lbl_theme", lang), self._theme_combo))

        l.addWidget(appearance_box)

        # ── Capture ───────────────────────────────────────────────────────────
        capture_box = QGroupBox(t("grp_capture", lang))
        cl = QVBoxLayout(capture_box)

        self._save_dir_edit = QLineEdit(self._conf.get("save_dir", ""))
        cl.addLayout(self._row(t("lbl_save_dir", lang), self._save_dir_edit))

        fmt_combo = QComboBox()
        fmt_combo.addItems(["png", "jpg", "webp"])
        fmt_combo.setCurrentText(self._conf.get("image_format", "png"))
        self._fmt_combo = fmt_combo
        cl.addLayout(self._row(t("lbl_format", lang), fmt_combo))

        self._delay_combo = QComboBox()
        for secs in (0, 3, 5, 10):
            label = t("capture_delay_none", lang) if secs == 0 else t("capture_delay_fmt", lang, sec=secs)
            self._delay_combo.addItem(label, secs)
        idx = self._delay_combo.findData(self._conf.get("capture_delay_sec", 0))
        if idx >= 0:
            self._delay_combo.setCurrentIndex(idx)
        cl.addLayout(self._row(t("lbl_capture_delay", lang), self._delay_combo))

        self._auto_copy_cb = QCheckBox(t("cb_auto_copy", lang))
        self._auto_copy_cb.setChecked(self._conf.get("auto_copy", True))
        cl.addWidget(self._auto_copy_cb)

        self._auto_save_cb = QCheckBox(t("cb_auto_save", lang))
        self._auto_save_cb.setChecked(self._conf.get("auto_save", True))
        cl.addWidget(self._auto_save_cb)

        self._capture_sound_cb = QCheckBox(t("cb_capture_sound", lang))
        self._capture_sound_cb.setChecked(self._conf.get("capture_sound", True))
        cl.addWidget(self._capture_sound_cb)

        self._skip_editor_cb = QCheckBox(t("cb_skip_editor", lang))
        self._skip_editor_cb.setChecked(self._conf.get("skip_editor_on_capture", False))
        cl.addWidget(self._skip_editor_cb)

        self._auto_redact_cb = QCheckBox(t("cb_auto_redact", lang))
        self._auto_redact_cb.setChecked(self._conf.get("auto_redact", False))
        cl.addWidget(self._auto_redact_cb)

        redact_style_combo = QComboBox()
        redact_style_combo.addItems(["blur", "pixelate", "black", "label"])
        redact_style_combo.setCurrentText(self._conf.get("redact_style", "blur"))
        self._redact_style_combo = redact_style_combo
        cl.addLayout(self._row(t("lbl_redact_style", lang), redact_style_combo))

        l.addWidget(capture_box)

        l.addStretch()
        return w

    def _ai_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        lang = self._lang
        l.addWidget(QLabel(t("lbl_api_key", lang)))
        self._api_key_edit = QLineEdit(self._conf.get("anthropic_api_key", ""))
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        l.addWidget(self._api_key_edit)
        l.addWidget(QLabel(t("lbl_api_key_hint", lang)))
        l.addStretch()
        return w

    def _upload_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        lang = self._lang
        targets = self._conf.get("upload_targets", {})

        l.addWidget(QLabel(t("lbl_imgur", lang)))
        self._imgur_id_edit = QLineEdit(targets.get("imgur", {}).get("client_id", ""))
        l.addWidget(self._imgur_id_edit)

        l.addWidget(QLabel(t("lbl_webhook", lang)))
        self._custom_url_edit = QLineEdit(targets.get("custom_url", {}).get("url", ""))
        l.addWidget(self._custom_url_edit)

        l.addWidget(QLabel(t("lbl_slack", lang)))
        self._slack_edit = QLineEdit(self._conf.get("slack_webhook", ""))
        l.addWidget(self._slack_edit)

        l.addWidget(QLabel(t("lbl_teams", lang)))
        self._teams_edit = QLineEdit(self._conf.get("teams_webhook", ""))
        l.addWidget(self._teams_edit)

        l.addStretch()
        return w

    def _hotkeys_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        hk = self._conf.get("hotkeys", {})
        self._hk_fields: Dict[str, QLineEdit] = {}
        for key, default in hk.items():
            edit = QLineEdit(default)
            self._hk_fields[key] = edit
            label = key.replace("_", " ").title()
            l.addLayout(self._row(label + ":", edit))
        l.addStretch()
        return w

    def _advanced_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        lang = self._lang

        self._check_updates_cb = QCheckBox(t("cb_check_updates", lang))
        self._check_updates_cb.setChecked(self._conf.get("check_updates", True))
        l.addWidget(self._check_updates_cb)

        check_now_btn = QPushButton(t("btn_check_updates_now", lang))
        check_now_btn.clicked.connect(self._check_for_updates_now)
        row = QHBoxLayout()
        row.addWidget(check_now_btn)
        row.addStretch()
        l.addLayout(row)

        self._watermark_cb = QCheckBox(t("cb_watermark", lang))
        self._watermark_cb.setChecked(self._conf.get("watermark_enabled", False))
        l.addWidget(self._watermark_cb)

        self._watermark_edit = QLineEdit(self._conf.get("watermark_text", ""))
        l.addLayout(self._row(t("lbl_watermark_text", lang), self._watermark_edit))

        l.addSpacing(8)
        self._startup_cb = QCheckBox(t("save_startup", lang))
        self._startup_cb.setChecked(self._is_startup())
        l.addWidget(self._startup_cb)

        l.addStretch()
        return w

    def _check_for_updates_now(self):
        """Manual 'Check for Updates' — runs the same GitHub Releases check
        as the background one, but synchronously (user explicitly asked and
        is waiting), with a wait cursor and a result dialog either way."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = update_checker.check_for_update(cfg.APP_VERSION)
        finally:
            QApplication.restoreOverrideCursor()

        if info:
            reply = QMessageBox.information(
                self, t("update_available_title", self._lang),
                t("update_available_msg", self._lang, version=info["version"]),
            )
            update_checker.open_release_page(info["url"])
        else:
            QMessageBox.information(
                self, t("update_available_title", self._lang),
                t("update_check_latest_msg", self._lang, version=cfg.APP_VERSION),
            )

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

    def _set_startup(self, enable: bool):
        try:
            import winreg, sys
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                 winreg.KEY_SET_VALUE)
            if enable:
                winreg.SetValueEx(key, "SnapCap", 0, winreg.REG_SZ, f'"{sys.executable}"')
            else:
                try:
                    winreg.DeleteValue(key, "SnapCap")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def _validate(self) -> Optional[str]:
        """Returns an error message if a field is invalid, else None.
        Checked before writing to disk so a bad value gets a clear message
        instead of silently corrupting config or failing later at save-time."""
        save_dir = self._save_dir_edit.text().strip()
        if not save_dir:
            return "Save directory cannot be empty."
        try:
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            probe = Path(save_dir) / ".snapcap_write_test"
            probe.touch()
            probe.unlink()
        except Exception as e:
            return f"Save directory isn't writable:\n{save_dir}\n\n{e}"

        url_re = re.compile(r"^https?://\S+$")
        for label, edit in (
            ("Slack webhook", self._slack_edit),
            ("Teams webhook", self._teams_edit),
            ("Custom webhook", self._custom_url_edit),
        ):
            val = edit.text().strip()
            if val and not url_re.match(val):
                return f"{label} doesn't look like a valid URL (must start with http:// or https://):\n{val}"
        return None

    def _save(self):
        error = self._validate()
        if error:
            QMessageBox.warning(self, "Invalid Settings", error)
            return

        self._conf["language"] = self._lang_combo.currentData()
        self._conf["theme"] = self._theme_combo.currentData()
        self._set_startup(self._startup_cb.isChecked())
        self._conf["save_dir"] = self._save_dir_edit.text()
        self._conf["image_format"] = self._fmt_combo.currentText()
        self._conf["auto_copy"] = self._auto_copy_cb.isChecked()
        self._conf["auto_save"] = self._auto_save_cb.isChecked()
        self._conf["capture_delay_sec"] = self._delay_combo.currentData()
        self._conf["capture_sound"] = self._capture_sound_cb.isChecked()
        self._conf["skip_editor_on_capture"] = self._skip_editor_cb.isChecked()
        self._conf["auto_redact"] = self._auto_redact_cb.isChecked()
        self._conf["redact_style"] = self._redact_style_combo.currentText()
        self._conf["anthropic_api_key"] = self._api_key_edit.text().strip()
        self._conf.setdefault("upload_targets", {})
        self._conf["upload_targets"].setdefault("imgur", {})["client_id"] = self._imgur_id_edit.text().strip()
        self._conf.setdefault("upload_targets", {}).setdefault("custom_url", {})["url"] = self._custom_url_edit.text().strip()
        self._conf["slack_webhook"] = self._slack_edit.text().strip()
        self._conf["teams_webhook"] = self._teams_edit.text().strip()
        self._conf["check_updates"] = self._check_updates_cb.isChecked()
        self._conf["watermark_enabled"] = self._watermark_cb.isChecked()
        self._conf["watermark_text"] = self._watermark_edit.text().strip()
        for key, edit in self._hk_fields.items():
            self._conf.setdefault("hotkeys", {})[key] = edit.text().strip()
        cfg.save(self._conf)
        self.accept()


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("SnapCap")
    win = EditorWindow()
    win.show()
    sys.exit(app.exec())
