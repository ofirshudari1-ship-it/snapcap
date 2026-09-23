"""
Accessibility + Windows-integration helpers shared by every SnapCap window.

  - is_high_contrast() / system_colors(): STANDARDS.md §20.2 — Windows High
    Contrast (Contrast Themes) is a user-chosen palette the app must honor,
    not override with its fixed brand colors. Read straight from Win32
    (SystemParametersInfoW(SPI_GETHIGHCONTRAST) + GetSysColor) rather than
    from Qt's palette, so the answer never depends on which Qt style is
    active or on whether Qt refreshed its palette yet.
  - plain_label(): strips the decorative emoji prefix most SnapCap button
    captions carry ("📷  Capture now") so screen readers announce just the
    action ("Capture now") instead of "camera Capture now".
  - exclude_from_capture(): SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)
    — keeps SnapCap's own always-on-top overlays (desktop widget, capture
    countdown) out of every screenshot while leaving them visible on the
    monitor. Verified against the same mss/BitBlt path capture_engine uses.

Every function here is best-effort and never raises: on non-Windows, on
Windows builds older than 10 2004 (no WDA_EXCLUDEFROMCAPTURE), or on any
ctypes failure they return the "feature unavailable" answer.
"""
import ctypes
import sys

_SPI_GETHIGHCONTRAST = 0x0042
_HCF_HIGHCONTRASTON = 0x00000001
_WDA_EXCLUDEFROMCAPTURE = 0x00000011

# GetSysColor indices (winuser.h)
_COLOR_WINDOW = 5
_COLOR_WINDOWTEXT = 8
_COLOR_HIGHLIGHT = 13
_COLOR_HIGHLIGHTTEXT = 14
_COLOR_BTNFACE = 15
_COLOR_GRAYTEXT = 17
_COLOR_BTNTEXT = 18


class _HIGHCONTRASTW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("lpszDefaultScheme", ctypes.c_wchar_p),
    ]


def is_high_contrast() -> bool:
    """True when a Windows Contrast Theme (High Contrast) is active."""
    if sys.platform != "win32":
        return False
    try:
        hc = _HIGHCONTRASTW()
        hc.cbSize = ctypes.sizeof(_HIGHCONTRASTW)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0
        )
        return bool(ok) and bool(hc.dwFlags & _HCF_HIGHCONTRASTON)
    except Exception:
        return False


def _sys_color(index: int) -> str:
    # GetSysColor returns a COLORREF: 0x00BBGGRR
    v = ctypes.windll.user32.GetSysColor(index)
    r, g, b = v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def system_colors() -> dict:
    """The user's active system colors as '#rrggbb' strings. Only meaningful
    while is_high_contrast() is True (that's the only time SnapCap uses
    them). Falls back to a plain black/white/blue set if Win32 is
    unavailable, so callers never need a None check."""
    try:
        return {
            "window": _sys_color(_COLOR_WINDOW),
            "window_text": _sys_color(_COLOR_WINDOWTEXT),
            "highlight": _sys_color(_COLOR_HIGHLIGHT),
            "highlight_text": _sys_color(_COLOR_HIGHLIGHTTEXT),
            "button": _sys_color(_COLOR_BTNFACE),
            "button_text": _sys_color(_COLOR_BTNTEXT),
            "gray_text": _sys_color(_COLOR_GRAYTEXT),
        }
    except Exception:
        return {
            "window": "#000000", "window_text": "#ffffff",
            "highlight": "#1aebff", "highlight_text": "#000000",
            "button": "#000000", "button_text": "#ffffff",
            "gray_text": "#3ff23f",
        }


def plain_label(text: str) -> str:
    """'📷  Capture now' -> 'Capture now'; '↺ רענן' -> 'רענן'. Strips any
    leading run of non-letter/non-digit characters (emoji, arrows, spaces)
    so the accessible name is just the words. Hebrew letters count as
    letters (str.isalnum), so Hebrew captions are handled the same way.
    Returns the original text unchanged if stripping would leave nothing."""
    if not text:
        return text
    i = 0
    while i < len(text) and not text[i].isalnum():
        i += 1
    stripped = text[i:].strip()
    return stripped or text


def exclude_from_capture(widget) -> bool:
    """Marks a top-level Qt window as excluded from screen capture (it stays
    visible on the monitor, but BitBlt/DXGI/mss grabs see what's behind
    it). Must be called after the native window exists (e.g. from
    showEvent). Returns True on success, False if unsupported — callers
    should then fall back to hiding the window around a capture."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False
