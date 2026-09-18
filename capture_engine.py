"""
Capture engine — handles all capture modes:
  - Region (freehand rubber-band selection)
  - Fullscreen / per-monitor
  - Active window
  - Scrolling (auto-scroll & stitch)
"""
import time
import ctypes
import ctypes.wintypes
from io import BytesIO
from typing import Optional, Tuple

import mss
import mss.tools
from PIL import Image, ImageGrab

try:
    import win32gui
    import win32con
    import win32ui
    import win32api
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


def _dpi_scale() -> float:
    """Return the primary monitor DPI scale factor."""
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except Exception:
        return 1.0


def capture_fullscreen(monitor_index: int = 0) -> Image.Image:
    """Capture a specific monitor (0 = primary)."""
    with mss.mss() as sct:
        monitors = sct.monitors  # [0] = all, [1..N] = individual
        idx = min(monitor_index + 1, len(monitors) - 1)
        raw = sct.grab(monitors[idx])
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def capture_all_monitors() -> Image.Image:
    """Capture all monitors stitched into one image."""
    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[0])
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def capture_region(x: int, y: int, w: int, h: int) -> Image.Image:
    """Capture a specific pixel rectangle."""
    bbox = {"left": x, "top": y, "width": w, "height": h}
    with mss.mss() as sct:
        raw = sct.grab(bbox)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def capture_active_window() -> Tuple[Optional[Image.Image], str]:
    """Capture the currently active window. Returns (image, window_title)."""
    if not HAS_WIN32:
        img = capture_fullscreen()
        return img, "screenshot"

    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    rect = win32gui.GetWindowRect(hwnd)
    x, y, x2, y2 = rect
    w, h = x2 - x, y2 - y
    if w <= 0 or h <= 0:
        img = capture_fullscreen()
        return img, title

    img = capture_region(x, y, w, h)
    return img, title


def capture_window_by_hwnd(hwnd) -> Image.Image:
    """Use PrintWindow to get a pixel-perfect capture even of off-screen windows."""
    if not HAS_WIN32:
        return capture_fullscreen()

    rect = win32gui.GetWindowRect(hwnd)
    x, y, x2, y2 = rect
    w, h = x2 - x, y2 - y
    if w <= 0 or h <= 0:
        return capture_fullscreen()

    hdc_window = win32gui.GetWindowDC(hwnd)
    hdc_mem = win32ui.CreateDCFromHandle(hdc_window)
    hdc_compat = hdc_mem.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(hdc_mem, w, h)
    hdc_compat.SelectObject(bmp)

    # PW_RENDERFULLCONTENT = 2 (captures Chromium/Electron correctly)
    ctypes.windll.user32.PrintWindow(hwnd, hdc_compat.GetSafeHdc(), 2)

    bmp_info = bmp.GetInfo()
    bmp_raw = bmp.GetBitmapBits(True)
    img = Image.frombuffer(
        "RGB", (bmp_info["bmWidth"], bmp_info["bmHeight"]),
        bmp_raw, "raw", "BGRX", 0, 1
    )

    win32gui.DeleteObject(bmp.GetHandle())
    hdc_compat.DeleteDC()
    hdc_mem.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc_window)
    return img


class ScrollCapture:
    """
    Scrolling screenshot engine.
    Strategy: auto-scroll the target window, capture frames, stitch unique rows.
    Works with Chromium, Electron, and native apps.
    """

    SCROLL_AMOUNT = 500        # pixels to scroll per step
    SCROLL_DELAY = 0.25        # seconds between scrolls
    SIMILARITY_THRESHOLD = 0.97  # how similar two frames' bottom strip must be to detect end

    def __init__(self, hwnd=None):
        self.hwnd = hwnd

    def _capture_frame(self) -> Image.Image:
        if self.hwnd and HAS_WIN32:
            return capture_window_by_hwnd(self.hwnd)
        return capture_active_window()[0]

    def _scroll_down(self):
        if self.hwnd and HAS_WIN32:
            win32api.SendMessage(self.hwnd, win32con.WM_VSCROLL, win32con.SB_PAGEDOWN, 0)
        else:
            # Simulate mouse wheel
            ctypes.windll.user32.mouse_event(0x800, 0, 0, -120 * 5, 0)

    def _images_similar(self, a: Image.Image, b: Image.Image) -> bool:
        """Compare bottom strip of two images for scroll-end detection."""
        try:
            import numpy as np
            strip_h = 60
            sa = np.array(a.crop((0, a.height - strip_h, a.width, a.height)).convert("L"), dtype=float)
            sb = np.array(b.crop((0, b.height - strip_h, b.width, b.height)).convert("L"), dtype=float)
            if sa.shape != sb.shape:
                return False
            corr = np.corrcoef(sa.flatten(), sb.flatten())[0, 1]
            return float(corr) >= self.SIMILARITY_THRESHOLD
        except Exception:
            return False

    def capture(self, progress_callback=None, max_scrolls: int = 40) -> Image.Image:
        frames = []
        prev = None

        for i in range(max_scrolls):
            frame = self._capture_frame()
            if prev is not None and self._images_similar(prev, frame):
                break  # reached bottom
            frames.append(frame.copy())
            prev = frame
            if progress_callback:
                progress_callback(i, max_scrolls)
            self._scroll_down()
            time.sleep(self.SCROLL_DELAY)

        if not frames:
            return self._capture_frame()

        return self._stitch(frames)

    @staticmethod
    def _stitch(frames: list) -> Image.Image:
        """Stitch frames by detecting unique rows between consecutive frames."""
        if len(frames) == 1:
            return frames[0]

        try:
            import numpy as np

            base = np.array(frames[0])
            result_rows = [base]
            total_height = base.shape[0]

            for idx in range(1, len(frames)):
                curr = np.array(frames[idx])
                prev = np.array(frames[idx - 1])
                h = min(prev.shape[0], curr.shape[0])
                w = min(prev.shape[1], curr.shape[1])

                # Find the overlap: scan from top of curr, look for match in prev
                strip_h = 30
                overlap_row = 0
                for row in range(0, h - strip_h, 4):
                    s_curr = curr[row: row + strip_h, :w]
                    # Scan prev from bottom
                    for prev_row in range(h - strip_h, max(0, h - strip_h - 200), -4):
                        s_prev = prev[prev_row: prev_row + strip_h, :w]
                        if s_curr.shape == s_prev.shape:
                            diff = np.mean(np.abs(s_curr.astype(float) - s_prev.astype(float)))
                            if diff < 8:
                                # found overlap; unique part starts at row
                                overlap_row = row
                                break
                    if overlap_row:
                        break

                unique = curr[overlap_row:] if overlap_row > 0 else curr
                result_rows.append(unique)
                total_height += unique.shape[0]

            # Stack all
            combined = np.vstack(result_rows)
            return Image.fromarray(combined)

        except Exception:
            # Fallback: simple vertical stack
            total_height = sum(f.height for f in frames)
            result = Image.new("RGB", (frames[0].width, total_height))
            y = 0
            for f in frames:
                result.paste(f, (0, y))
                y += f.height
            return result
