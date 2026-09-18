"""
Splash screen — shown briefly on app startup.
Per project standard: 1.5-2.5s (min 800ms even if load is faster, to avoid a
flash), closes itself, non-blocking, logo+name+version+progress+status.
"""
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QProgressBar, QApplication
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QLinearGradient
from PyQt6.QtCore import Qt, QTimer

import config as cfg

_MIN_MS = 800
_MAX_MS = 2200


def _make_logo(size: int = 88) -> QPixmap:
    pxm = QPixmap(size, size)
    pxm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pxm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#00d9a3"))
    grad.setColorAt(1, QColor("#3b82f6"))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setPen(QColor("white"))
    p.setFont(QFont("Arial", int(size * 0.44), QFont.Weight.Bold))
    p.drawText(pxm.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    p.end()
    return pxm


class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(360, 220)

        card = QWidget(self)
        card.setGeometry(0, 0, 360, 220)
        card.setStyleSheet("""
            background: #16213e;
            border-radius: 16px;
            border: 1px solid #1f3a6b;
        """)

        v = QVBoxLayout(card)
        v.setContentsMargins(0, 24, 0, 20)
        v.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(_make_logo())
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(logo)

        name = QLabel("SnapCap")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet("color: #eaeaea; font-size: 18px; font-weight: bold; font-family: 'Segoe UI';")
        v.addWidget(name)

        ver = QLabel(f"v{cfg.APP_VERSION}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet("color: #8892a4; font-size: 11px; font-family: 'Segoe UI';")
        v.addWidget(ver)

        v.addStretch()

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminate — we don't have real load stages to report
        self._bar.setFixedHeight(4)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar { background: #1f3a6b; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                   stop:0 #00d9a3, stop:1 #3b82f6); border-radius: 2px; }
        """)
        v.addWidget(self._bar)

        self._status = QLabel("Starting…")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #8892a4; font-size: 10px; font-family: 'Segoe UI';")
        v.addWidget(self._status)

        self._center()

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


def show_splash_then(app: QApplication, on_done):
    """
    Show the splash for at least _MIN_MS (and at most _MAX_MS), then call
    on_done() and close the splash. Non-blocking — uses the Qt event loop.
    """
    splash = SplashScreen()
    splash.show()
    QApplication.processEvents()

    def _finish():
        splash.close()
        on_done()

    QTimer.singleShot(_MIN_MS, _finish)
