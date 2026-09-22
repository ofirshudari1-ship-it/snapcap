"""
SnapCap — Main entry point.
Runs as a system-tray app with global hotkeys.
Features: single-instance guard, first-run onboarding wizard, update check.
"""
import sys
import os
import threading
from pathlib import Path
from typing import Optional

# ── Must set QT attributes before QApplication ──────────────────────────────
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox, QDialog, QWidget,
)
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont, QLinearGradient
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject

from PIL import Image
import config as cfg
import update_checker
from i18n import t, is_rtl, current_language
from logger import get_logger

APP_VERSION = cfg.APP_VERSION
log = get_logger("main")


# ── Crash safety net ──────────────────────────────────────────────────────────
# A --windowed PyInstaller build has no console: an unhandled exception that
# reaches Python's default excepthook can fail to write to the (invalid)
# stderr stream and take the whole process down with it — the app "just
# crashes" with no visible error. We install our own hook that logs to a file
# and shows a message box instead, and every capture entry point below is
# additionally wrapped in try/except so a single bad capture never reaches
# this hook in the first place.
def _install_crash_handler():
    import traceback, datetime
    log_path = cfg.CONFIG_DIR / "crash.log"

    def _hook(exc_type, exc_value, exc_tb):
        try:
            cfg._make_dirs()
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass
        try:
            log.error("Unhandled exception: %s", exc_value, exc_info=(exc_type, exc_value, exc_tb))
        except Exception:
            pass
        try:
            QMessageBox.critical(
                None, "SnapCap — Error",
                f"Something went wrong:\n\n{exc_value}\n\n"
                f"Details were saved to:\n{log_path}",
            )
        except Exception:
            pass

    sys.excepthook = _hook


def _safe_slot(fn):
    """Decorator: never let an exception from a capture action escape to Qt."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            sys.excepthook(type(e), e, e.__traceback__)
    return wrapper


# ── Single-instance lock (Windows named mutex) ────────────────────────────────
def _acquire_single_instance() -> Optional[object]:
    """
    Returns a mutex handle if this is the first instance.
    Returns None if another instance is already running.
    """
    try:
        import win32event, win32api, winerror
        mutex = win32event.CreateMutex(None, True, "Global\\SnapCap_SingleInstance")
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            return None
        return mutex
    except ImportError:
        # Fallback: lock file
        lock = cfg.CONFIG_DIR / "app.lock"
        try:
            cfg._make_dirs()
            if lock.exists():
                pid = lock.read_text().strip()
                # Check if PID is still alive
                try:
                    import psutil
                    if psutil.pid_exists(int(pid)):
                        return None
                except Exception:
                    pass  # psutil not available — assume stale lock
            lock.write_text(str(os.getpid()))
            return lock  # return path so we can clean up on exit
        except Exception:
            return "ok"  # can't determine — allow start


def _release_lock(handle):
    try:
        if isinstance(handle, Path):
            handle.unlink(missing_ok=True)
        # Win32 mutex is released when the handle is GC'd
    except Exception:
        pass


# ── Tray icon (gradient drawn in code) ───────────────────────────────────────
def _make_tray_icon() -> QIcon:
    pxm = QPixmap(32, 32)
    pxm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pxm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 32, 32)
    grad.setColorAt(0, QColor("#00d9a3"))
    grad.setColorAt(1, QColor("#3b82f6"))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 28, 28)
    p.setPen(QColor("white"))
    p.setFont(QFont("Arial", 13, QFont.Weight.Bold))
    p.drawText(pxm.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    p.end()
    return QIcon(pxm)


# ── Capture-delay countdown overlay ─────────────────────────────────────────────
class _CountdownOverlay(QWidget):
    """A small always-on-top translucent badge shown before a delayed
    capture (Settings → Capture delay). Gives the user a few seconds to
    open a menu, tooltip, or hover state after triggering the hotkey — the
    thing that's otherwise impossible to capture because it disappears the
    moment focus moves. Purely visual; the actual capture fires from
    `finished` once the countdown reaches zero."""
    finished = pyqtSignal()

    def __init__(self, seconds: int):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._remaining = max(1, int(seconds))
        self.resize(84, 84)
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self.show()
        self.raise_()
        self._timer.start(1000)

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.close()
            self.finished.emit()
        else:
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(22, 33, 62, 225))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(self.rect())
        p.setPen(QColor("#00d9a3"))
        p.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(max(1, self._remaining)))
        p.end()


# ── Signal bridge for thread-safe GUI calls ────────────────────────────────────
class _Bridge(QObject):
    trigger_region     = pyqtSignal()
    trigger_fullscreen = pyqtSignal()
    trigger_window     = pyqtSignal()
    trigger_scroll     = pyqtSignal()
    trigger_library    = pyqtSignal()
    trigger_text_ocr   = pyqtSignal()
    show_update_notif  = pyqtSignal(str, str)
    update_launched    = pyqtSignal(str, str)


# ── Main application controller ────────────────────────────────────────────────
class SnapCapApp:
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setApplicationName("SnapCap")
        self.app.setApplicationVersion(APP_VERSION)
        self.app.setQuitOnLastWindowClosed(False)

        self._conf = cfg.load()
        self._bridge = _Bridge()
        self._editor_windows: list = []
        self._library_window = None
        self._widget_window = None

        self._bridge.trigger_region.connect(self._capture_region)
        self._bridge.trigger_fullscreen.connect(self._capture_fullscreen)
        self._bridge.trigger_window.connect(self._capture_window)
        self._bridge.trigger_scroll.connect(self._capture_scroll)
        self._bridge.trigger_library.connect(self._open_library)
        self._bridge.trigger_text_ocr.connect(self._capture_text_ocr)
        self._bridge.show_update_notif.connect(self._notify_update)
        self._bridge.update_launched.connect(self._on_update_launched)

        self._setup_tray()
        self._register_hotkeys()
        self._setup_desktop_widget()

        # ── First-run onboarding wizard ───────────────────────────────────────
        if self._conf.get("first_run", True):
            QTimer.singleShot(400, self._run_onboarding)

        # ── Background update check (GitHub Releases, a few seconds after launch) ──
        # Opt-in auto-update (Settings -> "Automatically download and install
        # updates") downloads + silently installs and only falls back to the
        # notify-only path if something about that fails; default (off)
        # behavior is unchanged from before.
        if self._conf.get("check_updates", True):
            if self._conf.get("auto_update", False):
                update_checker.start_background_autoupdate(
                    APP_VERSION,
                    self._bridge.update_launched.emit,
                    self._bridge.show_update_notif.emit,
                    delay=5.0,
                )
            else:
                update_checker.start_background_check(
                    APP_VERSION, self._bridge.show_update_notif.emit, delay=5.0,
                )

    # ── Onboarding ─────────────────────────────────────────────────────────────
    def _run_onboarding(self):
        from onboarding_wizard import OnboardingWizard
        wiz = OnboardingWizard()
        wiz.exec()
        # Reload config after wizard saves
        self._conf = cfg.load()
        self._setup_tray()  # rebuild tray with updated config
        self._setup_desktop_widget()

    # ── Update notification ────────────────────────────────────────────────────
    def _notify_update(self, latest: str, release_url: str):
        self._latest_release_url = release_url
        lang = current_language()
        self.tray.showMessage(
            t("update_available_title", lang),
            t("update_available_msg", lang, version=latest),
            QSystemTrayIcon.MessageIcon.Information, 8000,
        )

    def _on_update_launched(self, version: str, installer_path: str):
        # The silent installer has already been launched (detached) and is
        # waiting for this process to exit before it overwrites the install
        # directory. Shut down cleanly instead of just calling quit(), so a
        # global hotkey doesn't stay registered against a process that's
        # about to disappear mid-capture.
        log.info("Auto-update: silent installer launched for v%s (%s) — shutting down", version, installer_path)
        self._quit_for_update()

    def _quit_for_update(self):
        """Clean shutdown ahead of a silent-install overwrite: unhook global
        hotkeys and hide the tray icon first (mirrors what a normal process
        exit does via the OS, but proactively — we know exactly why we're
        quitting), then quit the Qt event loop."""
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        try:
            self.tray.hide()
        except Exception:
            pass
        self.app.quit()

    def _on_tray_message_clicked(self):
        # Clicking the balloon opens the release page — but only if the last
        # notification shown was actually the update one (the tray reuses
        # showMessage for capture/save confirmations too).
        url = getattr(self, "_latest_release_url", None)
        if url:
            update_checker.open_release_page(url)

    # ── Tray ───────────────────────────────────────────────────────────────────
    def _setup_tray(self):
        if not hasattr(self, "tray"):
            self.tray = QSystemTrayIcon(_make_tray_icon(), self.app)
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.messageClicked.connect(self._on_tray_message_clicked)
            self.tray.show()

        conf = self._conf
        lang = current_language()
        self.tray.setToolTip(f"{t('app_name', lang)} v{APP_VERSION}")

        menu = QMenu()
        menu.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_rtl(lang) else Qt.LayoutDirection.LeftToRight
        )
        menu.setStyleSheet("""
            QMenu {
                background: #16213e; color: #eaeaea;
                border: 1px solid #1f3a6b;
                border-radius: 10px;
                font-family: 'Segoe UI'; font-size: 13px;
                padding: 6px 4px;
            }
            QMenu::item { padding: 7px 20px; border-radius: 6px; }
            QMenu::item:selected { background: #3b82f6; }
            QMenu::separator { height: 1px; background: #1f3a6b; margin: 4px 10px; }
        """)

        def _add(label: str, fn, shortcut: str = ""):
            display = f"{label}   {shortcut.upper()}" if shortcut else label
            act = menu.addAction(display)
            act.triggered.connect(fn)
            return act

        hk = conf.get("hotkeys", {})
        _add(f"📷  {t('tray_capture_region', lang)}",     self._bridge.trigger_region.emit,     hk.get("capture_region", ""))
        _add(f"🖥️  {t('tray_capture_fullscreen', lang)}",  self._bridge.trigger_fullscreen.emit, hk.get("capture_fullscreen", ""))
        _add(f"🪟  {t('tray_capture_window', lang)}",      self._bridge.trigger_window.emit,     hk.get("capture_window", ""))
        _add(f"📜  {t('tray_capture_scroll', lang)}",      self._bridge.trigger_scroll.emit,     hk.get("capture_scroll", ""))
        _add(f"📝  {t('tray_capture_text_ocr', lang)}",     self._bridge.trigger_text_ocr.emit,   hk.get("capture_text_ocr", ""))
        menu.addSeparator()
        _add(f"📚  {t('tray_library', lang)}",             self._bridge.trigger_library.emit,    hk.get("open_library", ""))
        menu.addSeparator()
        _add(f"⚙️  {t('tray_settings', lang)}",            self._open_settings)
        _add(f"ℹ️  {t('tray_about', lang)}",                self._show_about)
        menu.addSeparator()
        _add(f"✕  {t('tray_quit', lang)}",                  self.app.quit)

        self.tray.setContextMenu(menu)

        if not self._conf.get("first_run", True) and self._conf.get("show_startup_notification", True):
            self.tray.showMessage(
                t("app_name", lang),
                t("tray_running", lang),
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._bridge.trigger_region.emit()

    # ── Hotkeys ────────────────────────────────────────────────────────────────
    def _register_hotkeys(self):
        try:
            import keyboard
            hk = self._conf.get("hotkeys", {})

            def _bind(key: str, signal):
                if key:
                    try:
                        keyboard.add_hotkey(key, signal.emit)
                    except Exception:
                        pass

            _bind(hk.get("capture_region"),    self._bridge.trigger_region)
            _bind(hk.get("capture_fullscreen"), self._bridge.trigger_fullscreen)
            _bind(hk.get("capture_window"),     self._bridge.trigger_window)
            _bind(hk.get("capture_scroll"),     self._bridge.trigger_scroll)
            _bind(hk.get("open_library"),       self._bridge.trigger_library)
            _bind(hk.get("capture_text_ocr"),   self._bridge.trigger_text_ocr)
        except ImportError:
            pass

    # ── Desktop widget ─────────────────────────────────────────────────────────
    def _setup_desktop_widget(self):
        """Creates (once) or shows/hides the floating desktop widget per
        Settings → Desktop Widget → "Show desktop widget" (default ON).
        Called at startup, after the onboarding wizard saves, and after the
        Settings dialog closes — so toggling the checkbox takes effect
        immediately without a restart."""
        show = self._conf.get("show_desktop_widget", True)
        if show:
            if self._widget_window is None:
                from widget_window import WidgetWindow
                self._widget_window = WidgetWindow(
                    on_capture=self._bridge.trigger_region.emit,
                    on_open_library=self._bridge.trigger_library.emit,
                )
            self._widget_window.refresh_stat()
            self._widget_window.show()
        elif self._widget_window is not None:
            self._widget_window.hide()

    # ── Capture delay ──────────────────────────────────────────────────────────
    def _run_after_delay(self, fn):
        """Runs fn() immediately, or — if the user configured a capture
        delay in Settings → General — shows a countdown badge first and
        runs fn() once it reaches zero. Default (0 seconds) preserves the
        exact prior behavior of every capture entry point."""
        seconds = self._conf.get("capture_delay_sec", 0)
        if not seconds:
            fn()
            return
        overlay = _CountdownOverlay(seconds)
        self._active_countdown = overlay  # keep a reference so Qt doesn't GC it mid-countdown
        def _fire():
            self._active_countdown = None
            fn()
        overlay.finished.connect(_fire)
        overlay.start()

    def _play_shutter_sound(self):
        """Best-effort shutter sound (Settings → General → 'Play a shutter
        sound on capture'). Uses the stdlib winsound module — no bundled
        audio asset, matching the rest of the app's zero-extra-dependency
        approach — off the Qt thread so its short blocking call can never
        stutter the capture flow.

        Micro-interaction polish (§18.5): this used to be
        winsound.MessageBeep(MB_OK) — the generic Windows "ding" used for
        dialogs/errors. Fired every capture (often several times in a row
        for scrolling/region captures), that reads as an alert rather than
        confirmation, which is jarring. A quick two-tone high→low blip
        (~70ms total) mimics an actual camera shutter click instead."""
        def _play():
            try:
                import winsound
                winsound.Beep(2800, 40)
                winsound.Beep(1600, 30)
            except Exception:
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_OK)
                except Exception:
                    pass
        threading.Thread(target=_play, daemon=True).start()

    # ── Post-capture pipeline ──────────────────────────────────────────────────
    def _post_capture(self, img: Image.Image):
        if not img:
            return
        conf = cfg.load()

        # Keep the desktop widget's "captured this month" stat current right
        # away, instead of waiting on its own periodic refresh timer.
        if self._widget_window is not None and self._widget_window.isVisible():
            self._widget_window.refresh_stat()

        if conf.get("capture_sound", True):
            self._play_shutter_sound()

        # Auto-redact PII
        if conf.get("auto_redact"):
            import ai_engine as ai
            img, findings = ai.auto_redact(img, style=conf.get("redact_style", "blur"))
            if findings:
                lang = current_language()
                self.tray.showMessage(
                    t("app_name", lang) + " — Auto-Redact",
                    t("redact_msg", lang, count=len(findings)),
                    QSystemTrayIcon.MessageIcon.Information, 2500,
                )

        # Watermark
        if conf.get("watermark_enabled") and conf.get("watermark_text"):
            import ai_engine as ai
            img = ai.add_watermark(img, conf["watermark_text"])

        skip_editor = conf.get("skip_editor_on_capture", False)
        if not skip_editor:
            from editor_window import EditorWindow
            win = EditorWindow(img)
            win.show()
            self._editor_windows.append(win)
            win.destroyed.connect(
                lambda: self._editor_windows.remove(win) if win in self._editor_windows else None
            )

        if conf.get("auto_copy"):
            import share_manager as sm
            sm.copy_to_clipboard(img)

        if conf.get("auto_save"):
            import share_manager as sm
            path = sm.save_image(img)
            lang = current_language()
            self.tray.showMessage(
                t("app_name", lang), t("saved_msg", lang, filename=Path(path).name),
                QSystemTrayIcon.MessageIcon.Information, 2000,
            )
        elif skip_editor:
            # Editor stayed closed and nothing was auto-saved — the user
            # still needs *some* confirmation the hotkey actually worked.
            lang = current_language()
            self.tray.showMessage(
                t("app_name", lang), t("captured_quiet_msg", lang),
                QSystemTrayIcon.MessageIcon.Information, 1200,
            )

    # ── Capture actions ────────────────────────────────────────────────────────
    # Every entry point below is wrapped in try/except: a --windowed EXE has no
    # console, so an unhandled exception here would otherwise take the whole
    # app down silently instead of showing an error (see _install_crash_handler).
    def _capture_region(self):
        log.info("Region capture requested")
        try:
            from region_selector import select_region
            import capture_engine as ce
            result = select_region()
            if result:
                x, y, w, h = result
                log.info("Region selected: %dx%d at (%d,%d)", w, h, x, y)
                self._run_after_delay(lambda: self._post_capture(ce.capture_region(x, y, w, h)))
            else:
                log.info("Region capture cancelled by user")
        except Exception as e:
            sys.excepthook(type(e), e, e.__traceback__)

    def _capture_fullscreen(self):
        log.info("Fullscreen capture requested")
        import capture_engine as ce
        def _do():
            try:
                self._run_after_delay(lambda: self._post_capture(ce.capture_fullscreen()))
            except Exception as e:
                sys.excepthook(type(e), e, e.__traceback__)
        QTimer.singleShot(300, _do)

    def _capture_window(self):
        log.info("Window capture requested")
        import capture_engine as ce
        def _do():
            try:
                self._run_after_delay(lambda: self._post_capture(ce.capture_active_window()[0]))
            except Exception as e:
                sys.excepthook(type(e), e, e.__traceback__)
        QTimer.singleShot(300, _do)

    def _capture_scroll(self):
        try:
            import capture_engine as ce
            from PyQt6.QtWidgets import QProgressDialog

            def _start():
                progress = QProgressDialog("Scrolling and stitching…", "Cancel", 0, 100)
                progress.setWindowTitle("SnapCap — Scrolling Capture")
                progress.setMinimumDuration(0)
                progress.setValue(0)
                progress.show()

                def run():
                    try:
                        sc = ce.ScrollCapture()
                        def cb(i, total):
                            pct = int(i / total * 100)
                            QTimer.singleShot(0, lambda p=pct: progress.setValue(p))
                        img = sc.capture(progress_callback=cb)
                        QTimer.singleShot(0, lambda: _done(img))
                    except Exception as e:
                        QTimer.singleShot(0, lambda: _fail(e))

                def _done(img):
                    progress.close()
                    try:
                        self._post_capture(img)
                    except Exception as e:
                        sys.excepthook(type(e), e, e.__traceback__)

                def _fail(e):
                    progress.close()
                    sys.excepthook(type(e), e, e.__traceback__)

                threading.Thread(target=run, daemon=True).start()

            self._run_after_delay(_start)
        except Exception as e:
            sys.excepthook(type(e), e, e.__traceback__)

    def _capture_text_ocr(self):
        """Quick action: select a region, OCR it locally (Tesseract — no
        network call, no cloud AI key needed), and copy the extracted text
        straight to the clipboard. No editor window opens — this is for the
        "I just need the text, fast" workflow (e.g. grabbing an error message
        or a phone number off-screen), which previously required a full
        capture → open editor → Extract Text → copy round-trip."""
        log.info("Quick text capture (OCR) requested")
        try:
            from region_selector import select_region
            import capture_engine as ce
            import ai_engine as ai
            import pyperclip

            result = select_region()
            if not result:
                log.info("Quick text capture cancelled by user")
                return
            x, y, w, h = result
            img = ce.capture_region(x, y, w, h)
            text = ai.ocr_extract_text(img)
            lang = current_language()

            # ocr_extract_text() returns a bracketed status string (not real
            # extracted text) when Tesseract is missing or nothing was found —
            # don't put that placeholder text on the user's clipboard.
            if not text or text.startswith("[") and text.endswith("]"):
                self.tray.showMessage(
                    t("app_name", lang), t("text_ocr_empty_msg", lang),
                    QSystemTrayIcon.MessageIcon.Information, 3000,
                )
                return

            pyperclip.copy(text)
            log.info("Quick text capture: copied %d characters", len(text))
            self.tray.showMessage(
                t("app_name", lang), t("text_ocr_copied_msg", lang, count=len(text)),
                QSystemTrayIcon.MessageIcon.Information, 2500,
            )
        except Exception as e:
            sys.excepthook(type(e), e, e.__traceback__)

    def _open_library(self):
        from library_window import LibraryWindow
        from editor_window import EditorWindow
        if not self._library_window:
            self._library_window = LibraryWindow()
            self._library_window.open_in_editor.connect(
                lambda path: EditorWindow(Image.open(path)).show()
            )
            self._library_window.destroyed.connect(
                lambda: setattr(self, "_library_window", None)
            )
        self._library_window.show()
        self._library_window.raise_()
        self._library_window.activateWindow()

    def _open_settings(self):
        from editor_window import SettingsDialog
        dlg = SettingsDialog()
        dlg.exec()
        # Reload config in case user changed hotkeys / theme
        self._conf = cfg.load()
        # "Update Now" (Settings -> Advanced) already launched the silent
        # installer synchronously before the dialog closed — same clean
        # shutdown path as the automatic background flow.
        if getattr(dlg, "update_launched", False):
            self._quit_for_update()
        else:
            self._setup_desktop_widget()

    def _show_about(self):
        msg = QMessageBox()
        msg.setWindowTitle("About SnapCap")
        msg.setIconPixmap(_make_tray_icon().pixmap(48, 48))
        msg.setText(
            f"<h2>SnapCap v{APP_VERSION}</h2>"
            "<p>The screenshot tool the market was missing.</p>"
            "<ul>"
            "<li>🎯 Smart region / window / fullscreen / scrolling capture</li>"
            "<li>✏️ Full annotation — arrows, shapes, steps, callouts</li>"
            "<li>🔒 AI PII auto-redaction (emails, keys, IDs, phones)</li>"
            "<li>🔍 OCR with table extraction (CSV / Markdown export)</li>"
            "<li>🤖 Claude AI — summarize, alt-text, bug reports, translate</li>"
            "<li>📚 Searchable screenshot library with OCR index</li>"
            "<li>☁️ Imgur, custom webhook, Slack, Teams, email sharing</li>"
            "</ul>"
            f"<p style='color:#8892a4;'>© 2026 SnapCap · <a href='https://github.com/snapcap' style='color:#00d9a3;'>github.com/snapcap</a></p>"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.setStyleSheet("""
            QMessageBox { background: #16213e; color: #eaeaea; }
            QLabel { color: #eaeaea; }
            QPushButton { background: #00d9a3; color: #1a1a2e; font-weight: bold; border: none;
                          border-radius: 10px; padding: 6px 20px; font-size: 13px; }
            QPushButton:hover { background: #00b386; }
        """)
        msg.exec()

    def run(self):
        sys.exit(self.app.exec())


def _should_skip_splash(argv: list, conf: dict) -> bool:
    """True when this launch should skip the splash screen: it was started
    via the Windows-startup entry SnapCap writes for itself (a trailing
    "--autostart" argument — see editor_window.SettingsDialog._set_startup
    and onboarding_wizard._toggle_startup) AND the user hasn't opted out of
    that quieter boot in Settings → General → Startup."""
    return "--autostart" in argv and conf.get("skip_splash_on_autostart", True)


def _run_uninstall():
    """
    Handle `SnapCap.exe --uninstall`, the command the installer registers
    as UninstallString in the registry — without this, clicking "Uninstall"
    in Windows' Add/Remove Programs would just relaunch the app instead of
    removing it.
    """
    import shutil, winreg

    install_dir = Path(sys.executable).parent
    removed = []

    # Shortcuts
    desktop_lnk = Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "SnapCap.lnk"
    start_menu_dir = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" /
                       "Start Menu" / "Programs" / "SnapCap")
    startup_lnk = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" /
                    "Start Menu" / "Programs" / "Startup" / "SnapCap.lnk")
    for path in (desktop_lnk, startup_lnk):
        try:
            if path.exists():
                path.unlink()
                removed.append(str(path))
        except Exception:
            pass
    try:
        if start_menu_dir.exists():
            shutil.rmtree(start_menu_dir, ignore_errors=True)
            removed.append(str(start_menu_dir))
    except Exception:
        pass

    # Startup registry entry (if the user enabled "launch on startup" from Settings)
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, "SnapCap")
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
    except Exception:
        pass

    # Uninstall registry entry
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\SnapCap")
    except Exception:
        pass

    # Ask whether to also delete user data (config, library, OCR index) —
    # default "no", per the project standard (destructive-by-default is a footgun)
    _app = QApplication.instance() or QApplication(sys.argv)
    reply = QMessageBox.question(
        None, "Uninstall SnapCap",
        "SnapCap will now be removed.\n\n"
        "Also delete your saved settings and screenshot library "
        f"({cfg.CONFIG_DIR})?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if reply == QMessageBox.StandardButton.Yes:
        shutil.rmtree(cfg.CONFIG_DIR, ignore_errors=True)

    QMessageBox.information(
        None, "Uninstall SnapCap",
        "SnapCap has been removed.\n\n"
        "You can now delete the installation folder:\n" + str(install_dir),
    )

    # Self-delete the install directory on next reboot-independent pass isn't
    # reliable while this very EXE is running from inside it (Windows can't
    # delete a running EXE) — schedule removal via a detached cmd that waits
    # for this process to exit, matching how most lightweight installers do it.
    try:
        import subprocess
        subprocess.Popen(
            f'cmd /c timeout /t 2 /nobreak >nul & rmdir /s /q "{install_dir}"',
            shell=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass

    sys.exit(0)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cfg._make_dirs()
    from logger import setup_logging
    setup_logging()
    _install_crash_handler()
    log.info("SnapCap v%s starting", APP_VERSION)

    if "--uninstall" in sys.argv:
        log.info("Uninstall requested via --uninstall flag")
        _run_uninstall()

    # ── Single-instance guard ─────────────────────────────────────────────────
    _lock = _acquire_single_instance()
    if _lock is None:
        # Another instance is running — show a message and exit
        _app = QApplication.instance() or QApplication(sys.argv)
        _lang = current_language()
        QMessageBox.information(
            None, t("tray_already_running_title", _lang),
            t("tray_already_running_msg", _lang),
        )
        sys.exit(0)

    try:
        _app = QApplication.instance() or QApplication(sys.argv)

        # ── Windows-startup launch detection ──────────────────────────────────
        if "--autostart" in sys.argv:
            log.info("Launched via Windows startup (--autostart)")

        if _should_skip_splash(sys.argv, cfg.load()):
            app_holder: dict = {"app": SnapCapApp()}
        else:
            from splash_screen import show_splash_then
            app_holder: dict = {}
            show_splash_then(_app, lambda: app_holder.__setitem__("app", SnapCapApp()))
        sys.exit(_app.exec())
    finally:
        _release_lock(_lock)
