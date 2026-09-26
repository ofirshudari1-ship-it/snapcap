"""
GIF Recorder — short animated-GIF capture of a selected screen region.

Competitor research (2026-09): ShareX ships region GIF recording as a core
feature (default hotkey Ctrl+Shift+PrintScreen); Greenshot has no video/GIF
capture at all. A full video pipeline (audio, long recordings, MP4/H.264
encoding) would need ffmpeg or a platform codec and is a much bigger lift
than fits a single pass — this stays deliberately scoped to what a pure
PyQt6 + Pillow stack can do well: grab frames of one region at a fixed
rate for a capped duration, then encode them into one animated GIF.
No new dependency — Pillow (already required by capture_engine.py) can
both grab-quantize-and-save an animated GIF on its own.
"""
import datetime
from typing import Callable, List, Optional, Tuple

from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QApplication
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont
from PIL import Image

import capture_engine as ce
import a11y
from i18n import t, current_language

Region = Tuple[int, int, int, int]  # (x, y, w, h) in physical pixels


class GifRecordingOverlay(QWidget):
    """Small always-on-top HUD shown while a GIF recording is in progress:
    a recording dot, elapsed seconds, and a Stop button. Excluded from
    capture (a11y.exclude_from_capture) so it never ends up baked into the
    recorded frames — the same technique already used by the capture-delay
    countdown badge in main.py."""

    stop_requested = pyqtSignal()

    def __init__(self, region: Region, max_duration_sec: int):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._elapsed = 0
        self._max = max(1, int(max_duration_sec))
        self.resize(210, 56)
        self._position_near(region)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 10, 8)
        lay.setSpacing(10)
        self._label = QLabel(self._text())
        self._label.setStyleSheet(
            "color: white; font-family: 'Segoe UI'; font-size: 13px; font-weight: bold;"
        )
        lay.addWidget(self._label)

        stop_btn = QPushButton(t("gif_stop_btn", current_language()))
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_btn.setStyleSheet("""
            QPushButton { background: #ef4444; color: white; border: none;
                          border-radius: 8px; padding: 4px 16px; font-weight: bold; }
            QPushButton:hover { background: #dc2626; }
        """)
        stop_btn.clicked.connect(self.stop_requested.emit)
        lay.addWidget(stop_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _position_near(self, region: Region):
        """Places the HUD just above (or, if there's no room, just below)
        the recorded region, centered horizontally on it. `region` is in
        physical pixels (mss/capture space, same convention as
        region_selector.select_region()) — convert back to logical pixels
        for widget placement."""
        x, y, w, h = region
        screen = QApplication.primaryScreen()
        scale = screen.devicePixelRatio() if screen else 1.0
        lx, ly, lw, lh = x / scale, y / scale, w / scale, h / scale
        px = lx + lw / 2 - self.width() / 2
        py = ly - self.height() - 12
        if py < 0:
            py = ly + lh + 12
        self.move(round(px), round(py))

    def _text(self) -> str:
        return t("gif_recording_label", current_language(), sec=self._elapsed)

    def start(self):
        self.show()
        a11y.exclude_from_capture(self)
        self.raise_()
        self._timer.start(1000)

    def _tick(self):
        self._elapsed += 1
        self._label.setText(self._text())
        if self._elapsed >= self._max:
            self._timer.stop()
            self.stop_requested.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(22, 33, 62, 235))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 14, 14)
        p.setBrush(QColor("#ef4444"))
        p.drawEllipse(12, self.height() // 2 - 5, 10, 10)
        p.end()

    def stop(self):
        self._timer.stop()
        self.close()


class GifRecorder:
    """Drives the capture loop with a QTimer: grabs one frame of `region`
    every 1/fps seconds until stop() is called or max_duration_sec worth of
    frames have been collected, then hands the frame list to the
    `on_finished` callback passed to start()."""

    def __init__(self, region: Region, fps: int = 8, max_duration_sec: int = 15):
        self.region = region
        fps = max(1, min(int(fps), 30))
        self.interval_ms = max(60, round(1000 / fps))
        self.max_frames = max(1, round(max_duration_sec * fps))
        self._frames: List[Image.Image] = []
        self._timer = QTimer()
        self._timer.timeout.connect(self._capture_frame)
        self._on_finished: Optional[Callable] = None

    def start(self, on_finished: Callable[[List[Image.Image], int], None]):
        self._on_finished = on_finished
        self._timer.start(self.interval_ms)

    def _capture_frame(self):
        try:
            x, y, w, h = self.region
            self._frames.append(ce.capture_region(x, y, w, h))
        except Exception:
            pass
        if len(self._frames) >= self.max_frames:
            self.stop()

    def stop(self):
        if not self._timer.isActive():
            return
        self._timer.stop()
        frames, self._frames = self._frames, []
        if self._on_finished:
            self._on_finished(frames, self.interval_ms)


def save_gif(frames: List[Image.Image], interval_ms: int, path: str) -> str:
    """Encodes `frames` (PIL RGB images, all the same size) into an
    animated GIF at `path`. GIF is a 256-color format, so each frame is
    palette-quantized with Pillow's adaptive palette first — no ffmpeg or
    extra codec dependency needed for a short region recording."""
    if not frames:
        raise ValueError("No frames captured")
    quantized = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for f in frames]
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=interval_ms,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return path


def default_filename() -> str:
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"SnapCap_{ts}.gif"
