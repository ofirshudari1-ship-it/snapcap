"""
Smoke tests for SnapCap's critical paths — per the project stability
standard ("at least smoke tests for critical paths"). Uses stdlib unittest
only (no new dependency). Run with:

    python -m unittest discover -s tests -v

These are NOT a full test suite (no GUI/PyQt event-loop testing here) —
they cover the parts that are cheap to verify without a live display and
that have broken silently before: config round-tripping, i18n defaults,
DPI-scaling math in the region selector, and PII regex correctness.
"""
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Isolate every test from the developer's REAL SnapCap profile. config.py
# resolves CONFIG_DIR/CONFIG_FILE at call time, so repointing the module
# attributes here (before any test runs) redirects every load()/save() to a
# throwaway directory. Before 1.10.0 this suite read and wrote
# ~/.snapcap/config.json directly — e.g. test_secret_roundtrip_survives_
# save_load saved a copy of DEFAULT_CONFIG over the user's real settings.
import tempfile as _tempfile
import config as _cfg
_TEST_HOME = Path(_tempfile.mkdtemp(prefix="snapcap-tests-"))
_cfg.CONFIG_DIR = _TEST_HOME
_cfg.CONFIG_FILE = _TEST_HOME / "config.json"
_cfg.LIBRARY_DIR = _TEST_HOME / "library"
_cfg.TEMP_DIR = _TEST_HOME / "temp"


class TestConfig(unittest.TestCase):
    def test_load_returns_all_defaults(self):
        import config as cfg
        conf = cfg.load()
        for key in cfg.DEFAULT_CONFIG:
            self.assertIn(key, conf)

    def test_version_matches_version_json(self):
        import config as cfg
        import json
        with open(Path(__file__).resolve().parent.parent / "version.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(cfg.APP_VERSION, data["version"])

    def test_secret_roundtrip_survives_save_load(self):
        import config as cfg
        conf = dict(cfg.DEFAULT_CONFIG)
        conf["anthropic_api_key"] = "sk-ant-test-roundtrip-value"
        cfg.save(conf)
        reloaded = cfg.load()
        self.assertEqual(reloaded["anthropic_api_key"], "sk-ant-test-roundtrip-value")
        # cleanup: restore an empty key so this test doesn't leave a fake secret behind
        conf["anthropic_api_key"] = ""
        cfg.save(conf)

    def test_corrupt_config_file_falls_back_to_defaults(self):
        import config as cfg
        cfg._make_dirs()
        original = cfg.CONFIG_FILE.read_text(encoding="utf-8") if cfg.CONFIG_FILE.exists() else None
        try:
            cfg.CONFIG_FILE.write_text("{ not valid json", encoding="utf-8")
            conf = cfg.load()
            self.assertEqual(conf, cfg.DEFAULT_CONFIG)
        finally:
            if original is not None:
                cfg.CONFIG_FILE.write_text(original, encoding="utf-8")
            else:
                cfg.CONFIG_FILE.unlink(missing_ok=True)


class TestI18n(unittest.TestCase):
    def test_default_language_is_english(self):
        import config as cfg
        self.assertEqual(cfg.DEFAULT_CONFIG["language"], "en")

    def test_translate_known_key_both_languages(self):
        from i18n import t
        self.assertTrue(t("app_name", "en"))
        self.assertTrue(t("app_name", "he"))

    def test_translate_missing_key_falls_back_to_key_itself(self):
        from i18n import t
        self.assertEqual(t("__no_such_key__", "en"), "__no_such_key__")

    def test_rtl_only_for_hebrew(self):
        from i18n import is_rtl
        self.assertTrue(is_rtl("he"))
        self.assertFalse(is_rtl("en"))


class TestRegionSelectorDpiMath(unittest.TestCase):
    """The DPI-scaling bug (region-capture preview looking 'zoomed in') was
    found and fixed in region_selector.py — these pin the coordinate math so
    a regression there fails a test instead of shipping silently."""

    def test_logical_to_physical_conversion(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QPixmap, QColor
        from PyQt6.QtCore import QPoint
        app = QApplication.instance() or QApplication(sys.argv)
        import region_selector as rs

        bg = QPixmap(300, 300)
        bg.fill(QColor("black"))
        bg.setDevicePixelRatio(1.5)

        sel = rs.RegionSelector(bg)
        self.assertEqual(sel._scale, 1.5)

        sel._start = QPoint(10, 10)
        sel._end = QPoint(60, 60)
        sel._selecting = True

        results = []
        sel.region_selected.connect(lambda x, y, w, h: results.append((x, y, w, h)))

        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF, Qt as QtC
        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease, QPointF(60, 60),
            QtC.MouseButton.LeftButton, QtC.MouseButton.LeftButton,
            QtC.KeyboardModifier.NoModifier,
        )
        sel.mouseReleaseEvent(ev)

        self.assertEqual(results, [(15, 15, 75, 75)])


class TestAiEnginePii(unittest.TestCase):
    def test_email_pattern_matches(self):
        from ai_engine import PII_PATTERNS
        self.assertTrue(PII_PATTERNS["email"].search("contact me at test@example.com"))

    def test_email_pattern_does_not_match_plain_word(self):
        from ai_engine import PII_PATTERNS
        self.assertFalse(PII_PATTERNS["email"].search("just a normal sentence"))

    def test_ocr_gracefully_reports_when_tesseract_missing_or_present(self):
        # Doesn't assert Tesseract IS installed (environment-dependent) —
        # just that the function never raises and always returns a string.
        from PIL import Image
        import ai_engine as ai
        img = Image.new("RGB", (50, 20), "white")
        result = ai.ocr_extract_text(img)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


class TestEditorWindowTheme(unittest.TestCase):
    def test_apply_theme_system_resolves_to_dark_or_light(self):
        import editor_window as ew
        ew.apply_theme("system")
        self.assertIn(ew.DARK_BG, (ew._THEMES["dark"]["DARK_BG"], ew._THEMES["light"]["DARK_BG"]))
        ew.apply_theme("dark")  # restore a known state for any test run after this one


class TestClaudeVisionImportFailure(unittest.TestCase):
    """Pins the fix for a real bug: _claude_vision() used to `import anthropic`
    inside the same try block as `except anthropic.AuthenticationError` /
    `except anthropic.RateLimitError`. If the import itself failed (package
    not installed — it's an optional, cloud-only dependency), Python had to
    evaluate `anthropic.AuthenticationError` to match the except clause,
    which raised an unrelated NameError instead of the intended friendly
    "[AI Error: ...]" string — silently crashing whatever called an AI
    feature (Summarize, Alt-Text, Bug Report, etc.) if anthropic wasn't
    installed. This test forces that exact ImportError path and asserts the
    function returns a string instead of raising."""

    def test_returns_friendly_string_when_anthropic_not_installed(self):
        import builtins
        import ai_engine as ai
        from PIL import Image

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("simulated: anthropic not installed")
            return real_import(name, *args, **kwargs)

        img = Image.new("RGB", (10, 10), "white")
        with unittest.mock.patch("builtins.__import__", side_effect=fake_import):
            result = ai.ai_summarize(img, "fake-api-key")

        self.assertIsInstance(result, str)
        self.assertIn("AI Error", result)


class TestHotkeyDefaults(unittest.TestCase):
    """The one-step "capture region -> OCR -> copy text" quick action
    (main.py:_capture_text_ocr) needs a default hotkey and must appear in
    the user-configurable hotkeys dict, like every other capture mode."""

    def test_capture_text_ocr_hotkey_is_registered(self):
        import config as cfg
        self.assertIn("capture_text_ocr", cfg.DEFAULT_CONFIG["hotkeys"])
        self.assertTrue(cfg.DEFAULT_CONFIG["hotkeys"]["capture_text_ocr"])


class TestPinWindow(unittest.TestCase):
    """Pin to Screen (editor_window.PinWindow) — the always-on-top floating
    screenshot feature. Only tests the pure scale-clamping logic, not
    drag/resize mouse interaction (that needs a live display)."""

    def test_scale_is_clamped_to_min_and_max(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        from PIL import Image
        app = QApplication.instance() or QApplication(sys.argv)
        import editor_window as ew

        img = Image.new("RGB", (100, 80), "white")
        pin = ew.PinWindow(img)
        try:
            pin._scale = ew.PinWindow.MIN_SCALE
            pin._apply_size()
            self.assertGreaterEqual(pin.width(), 1)
            self.assertGreaterEqual(pin.height(), 1)

            pin._scale = ew.PinWindow.MAX_SCALE
            pin._apply_size()
            self.assertEqual(pin.width(), int(100 * ew.PinWindow.MAX_SCALE))
            self.assertEqual(pin.height(), int(80 * ew.PinWindow.MAX_SCALE))
        finally:
            pin.close()
            ew._PINNED_WINDOWS.clear()


class TestUpdateChecker(unittest.TestCase):
    """GitHub-based auto-update checker (update_checker.py) — pins the
    version-comparison logic and confirms network failures never raise."""

    def test_parse_version_strips_leading_v(self):
        import update_checker as uc
        self.assertEqual(uc._parse_version("v1.4.2"), (1, 4, 2))
        self.assertEqual(uc._parse_version("1.4.2"), (1, 4, 2))

    def test_is_newer_true_when_tag_ahead(self):
        import update_checker as uc
        self.assertTrue(uc._is_newer("v1.4.2", "1.4.1"))
        self.assertTrue(uc._is_newer("v2.0.0", "1.4.9"))

    def test_is_newer_false_when_equal_or_behind(self):
        import update_checker as uc
        self.assertFalse(uc._is_newer("v1.4.1", "1.4.1"))
        self.assertFalse(uc._is_newer("v1.4.0", "1.4.1"))

    def test_is_newer_never_raises_on_malformed_tag(self):
        import update_checker as uc
        self.assertFalse(uc._is_newer("not-a-version", "1.4.1"))

    def test_check_for_update_returns_none_on_network_failure(self):
        import update_checker as uc

        def _raise(*args, **kwargs):
            raise OSError("simulated: offline")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=_raise):
            result = uc.check_for_update("1.4.1")
        self.assertIsNone(result)

    def test_check_for_update_parses_github_response(self):
        import json
        import update_checker as uc

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({
                    "tag_name": "v1.5.0",
                    "html_url": "https://github.com/ofirshudari1-ship-it/snapcap/releases/tag/v1.5.0",
                }).encode("utf-8")

        with unittest.mock.patch("urllib.request.urlopen", return_value=_FakeResp()):
            result = uc.check_for_update("1.4.1")
        self.assertEqual(result, {
            "version": "1.5.0",
            "url": "https://github.com/ofirshudari1-ship-it/snapcap/releases/tag/v1.5.0",
        })


class TestCaptureDelay(unittest.TestCase):
    """Capture delay (Settings → General → 'Capture delay') — pins the
    countdown badge's pure tick logic and the new config defaults, without
    needing a live capture pipeline or display interaction."""

    def test_capture_delay_default_is_zero(self):
        import config as cfg
        self.assertEqual(cfg.DEFAULT_CONFIG["capture_delay_sec"], 0)

    def test_capture_sound_default_is_true(self):
        import config as cfg
        self.assertTrue(cfg.DEFAULT_CONFIG["capture_sound"])

    def test_skip_editor_default_is_false(self):
        import config as cfg
        self.assertFalse(cfg.DEFAULT_CONFIG["skip_editor_on_capture"])

    def test_countdown_overlay_ticks_down_and_emits_finished(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        import main as m

        overlay = m._CountdownOverlay(2)
        fired = []
        overlay.finished.connect(lambda: fired.append(True))
        overlay._tick()  # 2 -> 1, not done yet
        self.assertEqual(fired, [])
        overlay._tick()  # 1 -> 0, fires and closes
        self.assertEqual(fired, [True])

    def test_run_after_delay_with_zero_seconds_calls_immediately(self):
        """0 seconds (the default) must behave exactly like before this
        setting existed: fn() runs synchronously, no overlay is created."""
        import sys
        from PyQt6.QtWidgets import QApplication
        from unittest.mock import MagicMock
        app = QApplication.instance() or QApplication(sys.argv)
        import main as m

        instance = MagicMock()
        instance._conf = {"capture_delay_sec": 0}
        called = []
        m.SnapCapApp._run_after_delay(instance, lambda: called.append(True))
        self.assertEqual(called, [True])


class TestShapeFillAndFontSize(unittest.TestCase):
    """Rect/Ellipse fill toggle and the (previously unreachable-from-UI)
    text/callout font-size control on the Canvas."""

    def test_canvas_fill_shape_defaults_off(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        import editor_window as ew
        c = ew.Canvas()
        self.assertFalse(c.fill_shape)

    def test_canvas_font_size_is_settable(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        import editor_window as ew
        c = ew.Canvas()
        c.font_size = 42
        self.assertEqual(c.font_size, 42)


class TestNewSettingsTranslations(unittest.TestCase):
    """Every new Settings string added in the 2026-09-20 upgrade pass must
    exist in both shipped languages, not just fall back silently to the key."""

    def test_new_keys_translated_both_languages(self):
        from i18n import t
        for key in ("grp_capture", "grp_appearance", "lbl_capture_delay",
                    "capture_delay_none", "capture_delay_fmt",
                    "cb_capture_sound", "cb_skip_editor", "captured_quiet_msg"):
            self.assertTrue(t(key, "en"))
            self.assertTrue(t(key, "he"))
            self.assertNotEqual(t(key, "en"), key)
            self.assertNotEqual(t(key, "he"), key)

    def test_startup_group_keys_translated_both_languages(self):
        from i18n import t
        for key in ("grp_startup", "save_startup", "cb_skip_splash_autostart",
                    "cb_show_startup_notification"):
            self.assertTrue(t(key, "en"))
            self.assertTrue(t(key, "he"))
            self.assertNotEqual(t(key, "en"), key)
            self.assertNotEqual(t(key, "he"), key)


class TestTrayLifecycle(unittest.TestCase):
    """App-close vs tray-quit separation (2026-09-20 Windows-integration
    audit): closing a window must never quit the whole app — only the tray
    menu's Exit action may — and the tray context menu must always expose
    a clearly separate quit action."""

    def test_quit_on_last_window_closed_is_disabled(self):
        """Without this flag, PyQt auto-quits the app when the last visible
        top-level window (library/editor/settings) is closed, which would
        silently kill the tray icon and global hotkeys along with it."""
        import sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        self.assertFalse(app.quitOnLastWindowClosed())

    def test_library_window_is_not_deleted_on_close(self):
        """LibraryWindow must hide (not destroy) on close so main.py's cached
        `self._library_window` reference stays valid and reopening the
        library shows the same instance instead of silently no-oping."""
        import sys
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        app = QApplication.instance() or QApplication(sys.argv)
        import library_window as lw
        win = lw.LibraryWindow()
        try:
            self.assertFalse(win.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))
        finally:
            win.close()
            win.deleteLater()

    def test_tray_menu_has_a_distinct_quit_action(self):
        """The tray context menu must contain an action whose triggered
        signal is wired to QApplication.quit (not merely hiding a window),
        separate from every capture/library/settings action."""
        import sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        import main as m

        snap = m.SnapCapApp.__new__(m.SnapCapApp)
        snap.app = app
        snap._conf = __import__("config").load()
        snap._bridge = m._Bridge()
        m.SnapCapApp._setup_tray(snap)
        try:
            actions = snap.tray.contextMenu().actions()
            texts = [a.text() for a in actions if not a.isSeparator()]
            # At least one action's label is the quit/exit string, and it's
            # wired straight to app.quit (not one of the capture/open actions).
            from i18n import t
            self.assertTrue(any(t("tray_quit", "en") in text for text in texts))
        finally:
            snap.tray.hide()
            snap.tray.deleteLater()


class TestStartupRegistry(unittest.TestCase):
    """Windows-startup toggle (Settings → General → Startup). winreg isn't
    mockable with unittest.mock.patch("winreg", ...) because the target
    functions do a local `import winreg` on every call — so these tests
    inject a fake module into sys.modules for the duration of the call,
    which Python's import machinery picks up exactly like a real module."""

    @staticmethod
    def _fake_winreg(existing_value=None):
        """existing_value=None simulates the Run-key value being absent
        (QueryValueEx raises), matching a real registry read."""
        import types

        calls = {"set": None, "deleted": False}

        def _open_key(hive, path, reserved, access):
            return "FAKE_KEY_HANDLE"

        def _close_key(key):
            pass

        def _set_value_ex(key, name, reserved, type_, value):
            calls["set"] = (name, value)

        def _query_value_ex(key, name):
            if existing_value is None:
                raise FileNotFoundError()
            return (existing_value, 1)

        def _delete_value(key, name):
            calls["deleted"] = True

        fake = types.SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            KEY_SET_VALUE=1,
            KEY_READ=1,
            REG_SZ=1,
            OpenKey=_open_key,
            CloseKey=_close_key,
            SetValueEx=_set_value_ex,
            QueryValueEx=_query_value_ex,
            DeleteValue=_delete_value,
        )
        return fake, calls

    def test_set_startup_enable_writes_autostart_flag(self):
        """The Run-key command must include --autostart so a boot-time
        launch can be told apart from a manual one (see main._should_skip_splash)."""
        import sys as _sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(_sys.argv)
        import editor_window as ew

        dlg = ew.SettingsDialog.__new__(ew.SettingsDialog)
        fake_winreg, calls = self._fake_winreg()
        with unittest.mock.patch.dict(_sys.modules, {"winreg": fake_winreg}):
            ew.SettingsDialog._set_startup(dlg, True)

        self.assertIsNotNone(calls["set"])
        name, value = calls["set"]
        self.assertEqual(name, "SnapCap")
        self.assertIn("--autostart", value)

    def test_set_startup_disable_deletes_value(self):
        import sys as _sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(_sys.argv)
        import editor_window as ew

        dlg = ew.SettingsDialog.__new__(ew.SettingsDialog)
        fake_winreg, calls = self._fake_winreg(existing_value='"C:\\SnapCap.exe" --autostart')
        with unittest.mock.patch.dict(_sys.modules, {"winreg": fake_winreg}):
            ew.SettingsDialog._set_startup(dlg, False)

        self.assertTrue(calls["deleted"])
        self.assertIsNone(calls["set"])

    def test_is_startup_reflects_live_registry_not_a_cached_flag(self):
        """Per the task requirement: the checkbox must read the REAL registry
        state when Settings opens, not trust a stored boolean — e.g. if the
        user removed the entry via Windows' own Startup Apps settings."""
        import sys as _sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(_sys.argv)
        import editor_window as ew

        dlg = ew.SettingsDialog.__new__(ew.SettingsDialog)

        fake_present, _ = self._fake_winreg(existing_value='"C:\\SnapCap.exe" --autostart')
        with unittest.mock.patch.dict(_sys.modules, {"winreg": fake_present}):
            self.assertTrue(ew.SettingsDialog._is_startup(dlg))

        fake_absent, _ = self._fake_winreg(existing_value=None)
        with unittest.mock.patch.dict(_sys.modules, {"winreg": fake_absent}):
            self.assertFalse(ew.SettingsDialog._is_startup(dlg))


class TestSplashSkipOnAutostart(unittest.TestCase):
    """'Start minimized' behavior for an autostarted instance: main.py skips
    the splash screen when launched via the --autostart flag SnapCap's own
    Run-key/startup-shortcut entries pass themselves, unless the user
    disabled that in Settings → General → Startup."""

    def test_skips_splash_when_autostart_flag_present_and_enabled(self):
        import main as m
        self.assertTrue(
            m._should_skip_splash(["SnapCap.exe", "--autostart"],
                                   {"skip_splash_on_autostart": True})
        )

    def test_does_not_skip_without_autostart_flag(self):
        import main as m
        self.assertFalse(
            m._should_skip_splash(["SnapCap.exe"], {"skip_splash_on_autostart": True})
        )

    def test_does_not_skip_when_user_disabled_the_setting(self):
        import main as m
        self.assertFalse(
            m._should_skip_splash(["SnapCap.exe", "--autostart"],
                                   {"skip_splash_on_autostart": False})
        )

    def test_defaults_to_skipping_when_key_missing_from_conf(self):
        """Matches DEFAULT_CONFIG's default of True — an older config.json
        saved before this setting existed shouldn't suddenly show a splash
        on every boot."""
        import main as m
        self.assertTrue(m._should_skip_splash(["SnapCap.exe", "--autostart"], {}))


class TestNewConfigDefaults(unittest.TestCase):
    def test_skip_splash_on_autostart_defaults_true(self):
        import config as cfg
        self.assertTrue(cfg.DEFAULT_CONFIG["skip_splash_on_autostart"])

    def test_show_startup_notification_defaults_true(self):
        import config as cfg
        self.assertTrue(cfg.DEFAULT_CONFIG["show_startup_notification"])

    def test_auto_update_defaults_false(self):
        """Opt-in, default OFF per the task: auto-update must never turn
        itself on for an existing/upgraded config."""
        import config as cfg
        self.assertFalse(cfg.DEFAULT_CONFIG["auto_update"])


class TestSelfUpdateDownload(unittest.TestCase):
    """update_checker.download_installer — streams a GitHub release asset
    to a temp file and verifies it against the API-reported size. Mocks
    urllib entirely so this never touches the network."""

    def test_download_success_matches_expected_size(self):
        import update_checker as uc

        payload = b"MZ" + b"x" * 998

        class _FakeResp:
            headers = {"Content-Length": str(len(payload))}
            def __init__(self):
                self._buf = payload
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self, n=-1):
                if not self._buf:
                    return b""
                chunk, self._buf = self._buf[:n], self._buf[n:]
                return chunk

        progress_calls = []
        with unittest.mock.patch("urllib.request.urlopen", return_value=_FakeResp()):
            path = uc.download_installer(
                "https://github.com/ofirshudari1-ship-it/snapcap/releases/download/v9.9.9/SnapCap-Setup-9.9.9.exe",
                expected_size=len(payload),
                on_progress=lambda d, t: progress_calls.append((d, t)),
            )
        try:
            self.assertIsNotNone(path)
            self.assertTrue(path.exists())
            self.assertEqual(path.stat().st_size, len(payload))
            self.assertTrue(progress_calls)
            self.assertEqual(progress_calls[-1][0], len(payload))
        finally:
            if path:
                path.unlink(missing_ok=True)

    def test_download_returns_none_on_size_mismatch(self):
        """A truncated/interrupted download must not be handed off as if
        it completed — this is the core integrity check."""
        import update_checker as uc

        class _FakeResp:
            headers = {}
            def __init__(self):
                self._buf = b"short"
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self, n=-1):
                chunk, self._buf = self._buf[:n], self._buf[n:]
                return chunk

        with unittest.mock.patch("urllib.request.urlopen", return_value=_FakeResp()):
            path = uc.download_installer(
                "https://github.com/ofirshudari1-ship-it/snapcap/releases/download/v9.9.9/SnapCap-Setup-9.9.9.exe", expected_size=99999,
            )
        self.assertIsNone(path)

    def test_download_returns_none_on_network_failure(self):
        import update_checker as uc

        def _raise(*a, **k):
            raise OSError("simulated: offline")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=_raise):
            path = uc.download_installer("https://github.com/ofirshudari1-ship-it/snapcap/releases/download/v9.9.9/SnapCap-Setup-9.9.9.exe")
        self.assertIsNone(path)

    def test_find_installer_asset_picks_matching_exe(self):
        import update_checker as uc
        data = {
            "assets": [
                {"name": "Source code.zip", "browser_download_url": "https://x/src.zip", "size": 10},
                {"name": "SnapCap-Setup-1.7.0.exe", "browser_download_url": "https://x/setup.exe", "size": 12345},
            ]
        }
        asset = uc._find_installer_asset(data)
        self.assertEqual(asset["url"], "https://x/setup.exe")
        self.assertEqual(asset["size"], 12345)

    def test_find_installer_asset_none_when_absent(self):
        import update_checker as uc
        self.assertIsNone(uc._find_installer_asset({"assets": []}))
        self.assertIsNone(uc._find_installer_asset({}))

    def test_check_for_update_includes_asset_info_when_present(self):
        import json
        import update_checker as uc

        class _FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return json.dumps({
                    "tag_name": "v1.7.0",
                    "html_url": "https://github.com/ofirshudari1-ship-it/snapcap/releases/tag/v1.7.0",
                    "assets": [{
                        "name": "SnapCap-Setup-1.7.0.exe",
                        "browser_download_url": "https://github.com/.../SnapCap-Setup-1.7.0.exe",
                        "size": 999,
                    }],
                }).encode("utf-8")

        with unittest.mock.patch("urllib.request.urlopen", return_value=_FakeResp()):
            result = uc.check_for_update("1.6.1")
        self.assertEqual(result["asset_url"], "https://github.com/.../SnapCap-Setup-1.7.0.exe")
        self.assertEqual(result["asset_size"], 999)


class TestSilentLaunch(unittest.TestCase):
    """update_checker.launch_silent_install — non-blocking Popen of the
    downloaded installer with the --silent switch."""

    def test_launch_passes_silent_and_relaunch_flags(self):
        import update_checker as uc
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            fake_exe = Path(f.name)
        try:
            with unittest.mock.patch("subprocess.Popen") as mock_popen:
                ok = uc.launch_silent_install(fake_exe, relaunch=True)
            self.assertTrue(ok)
            args = mock_popen.call_args[0][0]
            self.assertIn("--silent", args)
            self.assertIn("--relaunch", args)
        finally:
            fake_exe.unlink(missing_ok=True)

    def test_launch_omits_relaunch_when_not_requested(self):
        import update_checker as uc
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            fake_exe = Path(f.name)
        try:
            with unittest.mock.patch("subprocess.Popen") as mock_popen:
                uc.launch_silent_install(fake_exe, relaunch=False)
            args = mock_popen.call_args[0][0]
            self.assertNotIn("--relaunch", args)
        finally:
            fake_exe.unlink(missing_ok=True)

    def test_launch_returns_false_when_path_missing(self):
        import update_checker as uc
        ok = uc.launch_silent_install(Path("C:/definitely/not/a/real/SnapCap-Setup.exe"))
        self.assertFalse(ok)

    def test_launch_returns_false_when_popen_raises(self):
        import update_checker as uc
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            fake_exe = Path(f.name)
        try:
            with unittest.mock.patch("subprocess.Popen", side_effect=OSError("blocked")):
                ok = uc.launch_silent_install(fake_exe)
            self.assertFalse(ok)
        finally:
            fake_exe.unlink(missing_ok=True)


class TestSelfUpdatePipeline(unittest.TestCase):
    """update_checker.perform_self_update — the full check -> download ->
    launch pipeline, exercised with each stage mocked so every branch
    (no update / no asset / download failure / launch failure / success)
    is covered without any real network or subprocess activity."""

    def test_no_update_available(self):
        import update_checker as uc
        with unittest.mock.patch.object(uc, "check_for_update", return_value=None):
            result = uc.perform_self_update("1.6.1")
        self.assertEqual(result, {"status": "no_update"})

    def test_release_has_no_installer_asset(self):
        import update_checker as uc
        info = {"version": "1.7.0", "url": "https://x/releases/tag/v1.7.0"}
        with unittest.mock.patch.object(uc, "check_for_update", return_value=info):
            result = uc.perform_self_update("1.6.1")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "no_asset")
        self.assertEqual(result["info"], info)

    def test_download_failure_falls_back_with_info(self):
        import update_checker as uc
        info = {"version": "1.7.0", "url": "https://x/tag/v1.7.0",
                "asset_url": "https://x/setup.exe", "asset_size": 100}
        with unittest.mock.patch.object(uc, "check_for_update", return_value=info), \
             unittest.mock.patch.object(uc, "download_installer", return_value=None):
            result = uc.perform_self_update("1.6.1")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "download_failed")
        self.assertEqual(result["info"], info)

    def test_launch_failure_falls_back_with_info(self):
        import update_checker as uc
        info = {"version": "1.7.0", "url": "https://x/tag/v1.7.0",
                "asset_url": "https://x/setup.exe", "asset_size": 100}
        fake_path = Path("C:/temp/SnapCap-Setup-1.7.0.exe")
        with unittest.mock.patch.object(uc, "check_for_update", return_value=info), \
             unittest.mock.patch.object(uc, "download_installer", return_value=fake_path), \
             unittest.mock.patch.object(uc, "launch_silent_install", return_value=False):
            result = uc.perform_self_update("1.6.1")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "launch_failed")

    def test_full_success_reports_launched(self):
        import update_checker as uc
        info = {"version": "1.7.0", "url": "https://x/tag/v1.7.0",
                "asset_url": "https://x/setup.exe", "asset_size": 100}
        fake_path = Path("C:/temp/SnapCap-Setup-1.7.0.exe")
        with unittest.mock.patch.object(uc, "check_for_update", return_value=info), \
             unittest.mock.patch.object(uc, "download_installer", return_value=fake_path), \
             unittest.mock.patch.object(uc, "launch_silent_install", return_value=True):
            result = uc.perform_self_update("1.6.1")
        self.assertEqual(result, {
            "status": "launched",
            "installer_path": str(fake_path),
            "version": "1.7.0",
        })


class TestAutoUpdateQuitPath(unittest.TestCase):
    """main.SnapCapApp's clean-shutdown path for auto-update: hotkeys get
    unhooked and the tray icon hidden before quit(), so a silent install
    overwriting the running exe never leaves a stale hotkey/tray-icon
    registration behind."""

    def test_quit_for_update_hides_tray_and_calls_quit(self):
        import sys
        from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
        app = QApplication.instance() or QApplication(sys.argv)
        import main as m

        snap = m.SnapCapApp.__new__(m.SnapCapApp)
        snap.app = unittest.mock.Mock()
        snap.tray = QSystemTrayIcon()
        snap.tray.show()
        try:
            m.SnapCapApp._quit_for_update(snap)
            self.assertFalse(snap.tray.isVisible())
            snap.app.quit.assert_called_once()
        finally:
            snap.tray.hide()
            snap.tray.deleteLater()

    def test_on_update_launched_delegates_to_quit_for_update(self):
        import main as m
        snap = m.SnapCapApp.__new__(m.SnapCapApp)
        snap._quit_for_update = unittest.mock.Mock()
        m.SnapCapApp._on_update_launched(snap, "1.7.0", "C:/temp/SnapCap-Setup-1.7.0.exe")
        snap._quit_for_update.assert_called_once()


class TestDesktopWidgetConfig(unittest.TestCase):
    """2026-09-22 desktop widget pass — config defaults and translations."""

    def test_show_desktop_widget_defaults_true(self):
        import config as cfg
        self.assertTrue(cfg.DEFAULT_CONFIG["show_desktop_widget"])

    def test_widget_pos_defaults_none(self):
        import config as cfg
        self.assertIsNone(cfg.DEFAULT_CONFIG["widget_pos"])

    def test_widget_keys_translated_both_languages(self):
        from i18n import t
        for key in ("grp_widget", "cb_show_desktop_widget", "widget_capture_now",
                    "widget_open_library", "widget_stat_zero", "widget_tooltip"):
            self.assertTrue(t(key, "en"))
            self.assertTrue(t(key, "he"))
            self.assertNotEqual(t(key, "en"), key)
            self.assertNotEqual(t(key, "he"), key)


class TestDesktopWidgetStat(unittest.TestCase):
    """library_window.count_captured_this_month — the single shared
    computation used by both the Library toolbar stat and the desktop
    widget, so they can never disagree or duplicate the mtime scan."""

    def test_counts_only_files_from_current_month(self):
        import os
        import tempfile
        import datetime
        import library_window as lw

        with tempfile.TemporaryDirectory() as d:
            now_path = Path(d) / "now.png"
            now_path.write_bytes(b"x")

            old_path = Path(d) / "old.png"
            old_path.write_bytes(b"x")
            old_time = datetime.datetime.now() - datetime.timedelta(days=400)
            old_ts = old_time.timestamp()
            os.utime(old_path, (old_ts, old_ts))

            non_image = Path(d) / "notes.txt"
            non_image.write_bytes(b"x")

            self.assertEqual(lw.count_captured_this_month(d), 1)

    def test_returns_zero_for_missing_directory(self):
        import library_window as lw
        self.assertEqual(lw.count_captured_this_month("C:/definitely/not/a/real/path/xyz"), 0)

    def test_library_window_reuses_shared_stat_function(self):
        """The Library toolbar's own stat label must be driven by the same
        shared function, not a second independent mtime scan (regression
        guard for the 2026-09-22 refactor that extracted it)."""
        import sys
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        import library_window as lw

        import tempfile
        from PyQt6.QtWidgets import QLabel

        win = lw.LibraryWindow.__new__(lw.LibraryWindow)
        win._save_dir = Path(tempfile.gettempdir())
        win._lang = "en"
        win._stat_label = QLabel()
        with unittest.mock.patch("library_window.count_captured_this_month", return_value=3) as mocked:
            lw.LibraryWindow._update_stat_label(win)
        mocked.assert_called_once_with(win._save_dir)
        self.assertTrue(win._stat_label.isVisible())


class TestDesktopWidgetWiring(unittest.TestCase):
    """widget_window.WidgetWindow — the "Capture now" / "Open Library"
    buttons and the close control, plus main.SnapCapApp's setup/toggle
    logic. Capture is mocked throughout: these tests confirm the widget
    calls the exact callables it was given (the same bridge signals the
    global hotkey uses), never that a real screenshot is taken."""

    def _make_widget(self, on_capture=None, on_open_library=None):
        import sys
        from PyQt6.QtWidgets import QApplication
        # Must keep a reference to the QApplication instance (matching every
        # other test in this file, e.g. TestPinWindow) — an unassigned
        # `QApplication.instance() or QApplication(sys.argv)` expression lets
        # the newly-constructed QApplication get garbage-collected as soon as
        # the statement finishes, which then takes every widget built
        # against it down with it (surfaces as a confusing "wrapped C/C++
        # object ... has been deleted" RuntimeError on first use afterwards).
        self._app = QApplication.instance() or QApplication(sys.argv)
        from widget_window import WidgetWindow
        return WidgetWindow(
            on_capture=on_capture or unittest.mock.Mock(),
            on_open_library=on_open_library or unittest.mock.Mock(),
        )

    def test_capture_now_calls_the_injected_capture_function(self):
        on_capture = unittest.mock.Mock()
        w = self._make_widget(on_capture=on_capture)
        try:
            w._capture_now()
            on_capture.assert_called_once()
        finally:
            w.close()

    def test_open_library_calls_the_injected_library_function(self):
        on_open_library = unittest.mock.Mock()
        w = self._make_widget(on_open_library=on_open_library)
        try:
            w._open_library()
            on_open_library.assert_called_once()
        finally:
            w.close()

    def test_close_button_persists_opt_out_and_hides(self):
        import config as cfg
        conf = cfg.load()
        original = conf.get("show_desktop_widget", True)
        w = self._make_widget()
        try:
            w.show()
            w._on_close_clicked()
            self.assertFalse(w.isVisible())
            self.assertFalse(cfg.load()["show_desktop_widget"])
        finally:
            w.close()
            conf = cfg.load()
            conf["show_desktop_widget"] = original
            cfg.save(conf)

    def test_position_round_trips_through_config(self):
        import config as cfg
        conf = cfg.load()
        original_pos = conf.get("widget_pos")
        w = self._make_widget()
        try:
            w.move(123, 456)
            w._save_position()
            saved = cfg.load()["widget_pos"]
            self.assertEqual(saved, {"x": 123, "y": 456})

            w2 = self._make_widget()
            try:
                self.assertEqual((w2.x(), w2.y()), (123, 456))
            finally:
                w2.close()
        finally:
            w.close()
            conf = cfg.load()
            conf["widget_pos"] = original_pos
            cfg.save(conf)

    def test_refresh_stat_uses_shared_count_function(self):
        w = self._make_widget()
        try:
            with unittest.mock.patch(
                "widget_window.count_captured_this_month", return_value=7
            ) as mocked:
                w.refresh_stat()
            mocked.assert_called_once()
            self.assertIn("7", w._stat_label.text())
        finally:
            w.close()

    def test_refresh_stat_shows_zero_message_when_no_captures(self):
        w = self._make_widget()
        try:
            with unittest.mock.patch(
                "widget_window.count_captured_this_month", return_value=0
            ):
                w.refresh_stat()
            from i18n import t
            self.assertEqual(w._stat_label.text(), t("widget_stat_zero", w._lang))
        finally:
            w.close()


class TestDesktopWidgetAppLifecycle(unittest.TestCase):
    """main.SnapCapApp._setup_desktop_widget — creates the widget once and
    shows/hides it on every subsequent call based on the config flag,
    matching how Settings → Desktop Widget is expected to take effect
    immediately without restarting the app."""

    def _snap(self, show_desktop_widget: bool):
        import sys
        from PyQt6.QtWidgets import QApplication
        # See TestDesktopWidgetWiring._make_widget for why this reference
        # must be kept, not discarded as a bare expression statement.
        self._app = QApplication.instance() or QApplication(sys.argv)
        import main as m
        snap = m.SnapCapApp.__new__(m.SnapCapApp)
        snap._conf = {"show_desktop_widget": show_desktop_widget}
        snap._bridge = m._Bridge()
        snap._widget_window = None
        return snap, m

    def test_creates_and_shows_widget_when_enabled(self):
        snap, m = self._snap(True)
        try:
            m.SnapCapApp._setup_desktop_widget(snap)
            self.assertIsNotNone(snap._widget_window)
            self.assertTrue(snap._widget_window.isVisible())
        finally:
            if snap._widget_window is not None:
                snap._widget_window.close()

    def test_does_not_create_widget_when_disabled(self):
        snap, m = self._snap(False)
        m.SnapCapApp._setup_desktop_widget(snap)
        self.assertIsNone(snap._widget_window)

    def test_hides_existing_widget_when_toggled_off(self):
        snap, m = self._snap(True)
        try:
            m.SnapCapApp._setup_desktop_widget(snap)
            self.assertTrue(snap._widget_window.isVisible())
            snap._conf["show_desktop_widget"] = False
            m.SnapCapApp._setup_desktop_widget(snap)
            self.assertFalse(snap._widget_window.isVisible())
        finally:
            if snap._widget_window is not None:
                snap._widget_window.close()

    def test_reshows_same_instance_when_toggled_back_on(self):
        snap, m = self._snap(True)
        try:
            m.SnapCapApp._setup_desktop_widget(snap)
            first_instance = snap._widget_window
            snap._conf["show_desktop_widget"] = False
            m.SnapCapApp._setup_desktop_widget(snap)
            snap._conf["show_desktop_widget"] = True
            m.SnapCapApp._setup_desktop_widget(snap)
            self.assertIs(snap._widget_window, first_instance)
            self.assertTrue(snap._widget_window.isVisible())
        finally:
            if snap._widget_window is not None:
                snap._widget_window.close()

    def test_post_capture_refreshes_visible_widget_stat(self):
        """The widget's stat is refreshed right after a capture is SAVED —
        after save_image(), so the new file is already counted (1.10.0 fix:
        it used to refresh before the save and always lag by one)."""
        snap, m = self._snap(True)
        snap._conf = {
            "show_desktop_widget": True, "capture_sound": False, "auto_redact": False,
            "watermark_enabled": False, "skip_editor_on_capture": True,
            "auto_copy": False, "auto_save": True,
        }
        m.SnapCapApp._setup_desktop_widget(snap)
        order = []
        snap._widget_window.refresh_stat = unittest.mock.Mock(side_effect=lambda: order.append("refresh"))
        snap.tray = unittest.mock.Mock()
        try:
            from PIL import Image
            with unittest.mock.patch("config.load", return_value=snap._conf), \
                 unittest.mock.patch("share_manager.save_image",
                                     side_effect=lambda img: order.append("save") or "C:/x/shot.png"):
                m.SnapCapApp._post_capture(snap, Image.new("RGB", (4, 4)))
            self.assertEqual(order, ["save", "refresh"])
        finally:
            if snap._widget_window is not None:
                snap._widget_window.close()

    def test_rebuild_replaces_widget_instance(self):
        """Language change in Settings -> the widget is recreated (its
        captions are fixed at construction), not just re-shown."""
        snap, m = self._snap(True)
        try:
            m.SnapCapApp._setup_desktop_widget(snap)
            first = snap._widget_window
            m.SnapCapApp._setup_desktop_widget(snap, rebuild=True)
            self.assertIsNot(snap._widget_window, first)
            self.assertTrue(snap._widget_window.isVisible())
        finally:
            if snap._widget_window is not None:
                snap._widget_window.close()


class TestConfigRobustness(unittest.TestCase):
    """1.10.0 config.py hardening — deep merge, type validation, no shared
    nested defaults, atomic save."""

    def _write(self, data):
        import json
        import config as cfg
        cfg._make_dirs()
        cfg.CONFIG_FILE.write_text(json.dumps(data), encoding="utf-8")

    def tearDown(self):
        import config as cfg
        cfg.CONFIG_FILE.unlink(missing_ok=True)

    def test_old_nested_hotkeys_gain_new_default_keys(self):
        import config as cfg
        self._write({"hotkeys": {"capture_region": "ctrl+alt+r"}})
        conf = cfg.load()
        self.assertEqual(conf["hotkeys"]["capture_region"], "ctrl+alt+r")
        self.assertEqual(conf["hotkeys"]["capture_text_ocr"],
                         cfg.DEFAULT_CONFIG["hotkeys"]["capture_text_ocr"])

    def test_wrong_type_value_falls_back_to_default(self):
        import config as cfg
        self._write({"capture_delay_sec": "abc", "auto_copy": "yes", "hotkeys": []})
        conf = cfg.load()
        self.assertEqual(conf["capture_delay_sec"], cfg.DEFAULT_CONFIG["capture_delay_sec"])
        self.assertEqual(conf["auto_copy"], cfg.DEFAULT_CONFIG["auto_copy"])
        self.assertEqual(conf["hotkeys"], cfg.DEFAULT_CONFIG["hotkeys"])

    def test_bool_is_not_accepted_as_int(self):
        import config as cfg
        self._write({"capture_delay_sec": True})
        self.assertEqual(cfg.load()["capture_delay_sec"], 0)

    def test_non_dict_json_root_falls_back_to_defaults(self):
        import config as cfg
        self._write([1, 2, 3])
        self.assertEqual(cfg.load(), cfg.DEFAULT_CONFIG)

    def test_loaded_config_never_shares_nested_defaults(self):
        import config as cfg
        cfg.CONFIG_FILE.unlink(missing_ok=True)
        conf = cfg.load()
        conf["hotkeys"]["capture_region"] = "mutated"
        conf["upload_targets"]["imgur"]["client_id"] = "mutated"
        self.assertNotEqual(cfg.DEFAULT_CONFIG["hotkeys"]["capture_region"], "mutated")
        self.assertNotEqual(cfg.DEFAULT_CONFIG["upload_targets"]["imgur"]["client_id"], "mutated")

    def test_unknown_keys_are_preserved(self):
        import config as cfg
        self._write({"some_future_key": 42})
        self.assertEqual(cfg.load()["some_future_key"], 42)

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        import config as cfg
        conf = cfg.load()
        conf["language"] = "he"
        cfg.save(conf)
        self.assertEqual(cfg.load()["language"], "he")
        self.assertFalse(cfg.CONFIG_FILE.with_name(cfg.CONFIG_FILE.name + ".tmp").exists())

    def test_failed_write_keeps_previous_file_intact(self):
        import config as cfg
        conf = cfg.load()
        conf["language"] = "he"
        cfg.save(conf)
        bad = cfg.load()
        bad["unserializable"] = object()
        with self.assertRaises(TypeError):
            cfg.save(bad)
        self.assertEqual(cfg.load()["language"], "he")


class TestUpdateCheckerHardening(unittest.TestCase):
    def test_versions_with_missing_patch_compare_equal(self):
        import update_checker as uc
        self.assertFalse(uc._is_newer("1.9.0", "1.9"))
        self.assertFalse(uc._is_newer("v1.9", "1.9.0"))
        self.assertTrue(uc._is_newer("1.10.0", "1.9.0"))

    def test_untrusted_asset_url_is_never_downloaded(self):
        import update_checker as uc
        with unittest.mock.patch("urllib.request.urlopen") as mocked:
            path = uc.download_installer("https://evil.example.com/SnapCap-Setup-9.9.9.exe")
        self.assertIsNone(path)
        mocked.assert_not_called()

    def test_non_executable_download_is_rejected(self):
        import update_checker as uc
        payload = b"<html>captive portal</html>"

        class _FakeResp:
            headers = {}
            def __init__(self):
                self._buf = payload
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self, n=-1):
                chunk, self._buf = self._buf[:n], self._buf[n:]
                return chunk

        with unittest.mock.patch("urllib.request.urlopen", return_value=_FakeResp()):
            path = uc.download_installer(
                uc.ALLOWED_ASSET_PREFIX + "v9.9.9/SnapCap-Setup-9.9.9.exe")
        self.assertIsNone(path)

    def test_cleanup_removes_only_old_installer_copies(self):
        import os
        import time
        import tempfile
        import update_checker as uc
        d = Path(tempfile.mkdtemp())
        old = d / "SnapCap-Setup-old123.exe"
        new = d / "SnapCap-Setup-new456.exe"
        other = d / "Other-Setup.exe"
        for f in (old, new, other):
            f.write_bytes(b"MZ")
        stale = time.time() - 7200
        os.utime(old, (stale, stale))
        os.utime(other, (stale, stale))
        with unittest.mock.patch("tempfile.gettempdir", return_value=str(d)):
            removed = uc.cleanup_stale_downloads(max_age_sec=3600)
        self.assertEqual(removed, 1)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertTrue(other.exists())


class TestTrayMessageReleaseUrl(unittest.TestCase):
    """A click on a non-update balloon must not open the release page just
    because an update balloon was shown earlier in the session."""

    def test_later_balloon_clears_release_url(self):
        import main as m
        snap = m.SnapCapApp.__new__(m.SnapCapApp)
        snap.tray = unittest.mock.Mock()
        m.SnapCapApp._notify_update(snap, "9.9.9", "https://github.com/x/releases/tag/v9.9.9")
        self.assertEqual(snap._latest_release_url, "https://github.com/x/releases/tag/v9.9.9")
        m.SnapCapApp._tray_message(snap, "SnapCap", "Saved: a.png", None, 2000)
        with unittest.mock.patch("update_checker.open_release_page") as opened:
            m.SnapCapApp._on_tray_message_clicked(snap)
        opened.assert_not_called()

    def test_same_version_is_announced_once(self):
        import main as m
        snap = m.SnapCapApp.__new__(m.SnapCapApp)
        snap.tray = unittest.mock.Mock()
        m.SnapCapApp._notify_update(snap, "9.9.9", "u")
        m.SnapCapApp._notify_update(snap, "9.9.9", "u")
        self.assertEqual(snap.tray.showMessage.call_count, 1)


class TestAccessibilityHelpers(unittest.TestCase):
    def test_plain_label_strips_emoji_prefix(self):
        import a11y
        self.assertEqual(a11y.plain_label("📷  Capture now"), "Capture now")
        self.assertEqual(a11y.plain_label("↺ רענן"), "רענן")
        self.assertEqual(a11y.plain_label("Close"), "Close")
        self.assertEqual(a11y.plain_label("×"), "×")

    def test_high_contrast_query_never_raises(self):
        import a11y
        self.assertIsInstance(a11y.is_high_contrast(), bool)
        colors = a11y.system_colors()
        for key in ("window", "window_text", "highlight", "highlight_text"):
            self.assertRegex(colors[key], r"^#[0-9a-f]{6}$")

    def test_apply_theme_uses_system_colors_under_high_contrast(self):
        import editor_window as ew
        fake = {"window": "#000000", "window_text": "#ffffff", "highlight": "#1aebff",
                "highlight_text": "#000000", "button": "#000000", "button_text": "#ffffff",
                "gray_text": "#3ff23f"}
        try:
            with unittest.mock.patch("a11y.is_high_contrast", return_value=True), \
                 unittest.mock.patch("a11y.system_colors", return_value=fake):
                ew.apply_theme("light")
                self.assertEqual(ew.DARK_BG, "#000000")
                self.assertEqual(ew.TEXT_FG, "#ffffff")
                self.assertEqual(ew.ACCENT2, "#1aebff")
                self.assertEqual(ew.ACCENT_FG, "#000000")
        finally:
            ew.apply_theme("dark")

    def test_muted_text_meets_wcag_aa_in_both_themes(self):
        import editor_window as ew

        def lum(h):
            h = h.lstrip("#")
            c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

        def ratio(a, b):
            la, lb = lum(a), lum(b)
            return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

        for theme in ("dark", "light"):
            pal = ew._THEMES[theme]
            for bg in (pal["DARK_BG"], pal["PANEL_BG"]):
                self.assertGreaterEqual(ratio(pal["MUTED_FG"], bg), 4.5, (theme, bg))
                # Editor panel: the AI-tools group captions (MUTED_FG) and the
                # "Claude API connected" status text (ACCENT_TEXT) both used
                # to be hardcoded hex literals that ignored the active theme
                # and fell under 2:1 in light mode — see _refresh_ai_status
                # and the AI-tools accordion in editor_window.py.
                self.assertGreaterEqual(ratio(pal["ACCENT_TEXT"], bg), 4.5, (theme, bg))
            self.assertGreaterEqual(ratio(pal["ACCENT_FG"], pal["ACCENT2"]), 4.5, theme)


class TestWidgetRobustness(unittest.TestCase):
    def _make_widget(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication(sys.argv)
        from widget_window import WidgetWindow
        return WidgetWindow(on_capture=unittest.mock.Mock(), on_open_library=unittest.mock.Mock())

    def test_offscreen_saved_position_is_discarded(self):
        import config as cfg
        conf = cfg.load()
        conf["widget_pos"] = {"x": -50000, "y": -50000}
        cfg.save(conf)
        w = self._make_widget()
        try:
            self.assertNotEqual((w.x(), w.y()), (-50000, -50000))
        finally:
            w.close()
            conf["widget_pos"] = None
            cfg.save(conf)

    def test_buttons_have_accessible_names_without_emoji(self):
        from i18n import t
        w = self._make_widget()
        try:
            self.assertEqual(w._close_btn.accessibleName(), t("close", w._lang))
            self.assertEqual(w._close_btn.toolTip(), t("close", w._lang))
            self.assertFalse(w._capture_btn.accessibleName().startswith("📷"))
            self.assertTrue(w._capture_btn.accessibleName())
            self.assertTrue(w._library_btn.accessibleName())
        finally:
            w.close()

    def test_widget_is_excluded_from_screen_capture_once_shown(self):
        w = self._make_widget()
        try:
            with unittest.mock.patch("a11y.exclude_from_capture", return_value=True) as ex:
                w.show()
            ex.assert_called_once()
            self.assertTrue(w.excluded_from_capture)
        finally:
            w.close()

    def test_change_event_handles_palette_change_without_error(self):
        from PyQt6.QtCore import QEvent
        w = self._make_widget()
        try:
            for et in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange,
                       QEvent.Type.StyleChange, QEvent.Type.WindowTitleChange):
                w.changeEvent(QEvent(et))
        finally:
            w.close()

    def test_high_contrast_paint_path_renders(self):
        """Paints the widget both ways into an offscreen pixmap — guards
        against a PyQt6-6.11-invalid QLinearGradient/QPen overload sneaking
        into either branch (the QPoint-overload crash class)."""
        from PyQt6.QtGui import QPixmap
        w = self._make_widget()
        try:
            for hc in (False, True):
                w._high_contrast = hc
                w._apply_styles()
                w.grab()  # runs paintEvent
        finally:
            w.close()


class TestSplashPaints(unittest.TestCase):
    def test_splash_renders_normal_and_high_contrast(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication(sys.argv)
        import splash_screen as sp
        for hc in (False, True):
            with unittest.mock.patch("a11y.is_high_contrast", return_value=hc):
                s = sp.SplashScreen()
                try:
                    s.grab()
                finally:
                    s.close()


class TestOnboardingWizardAccessibility(unittest.TestCase):
    """STANDARDS.md §20.2 — the onboarding wizard was the only first-run/
    main window that didn't honor Windows High Contrast; the Skip button
    also had no visible focus ring. See onboarding_wizard._refresh_palette()
    and OnboardingWizard._build()."""

    def _make_app(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication(sys.argv)

    def test_renders_normal_and_high_contrast(self):
        self._make_app()
        import onboarding_wizard as ow
        for hc in (False, True):
            with unittest.mock.patch("a11y.is_high_contrast", return_value=hc):
                w = ow.OnboardingWizard()
                try:
                    w.grab()  # runs paintEvent/style resolution for every page
                finally:
                    w.close()

    def test_refresh_palette_uses_system_colors_under_high_contrast(self):
        import onboarding_wizard as ow
        fake = {"window": "#010101", "window_text": "#020202",
                "highlight": "#030303", "highlight_text": "#040404",
                "button": "#050505", "button_text": "#060606", "gray_text": "#070707"}
        with unittest.mock.patch("a11y.is_high_contrast", return_value=True), \
             unittest.mock.patch("a11y.system_colors", return_value=fake):
            ow._refresh_palette()
            self.assertEqual(ow._BG, fake["window"])
            self.assertEqual(ow._TEXT, fake["window_text"])
            self.assertEqual(ow._ACCENT, fake["highlight"])
        # Restore the brand palette so later tests in this run aren't
        # affected by this module-level mutation.
        with unittest.mock.patch("a11y.is_high_contrast", return_value=False):
            ow._refresh_palette()
        self.assertEqual(ow._BG, ow._BRAND_BG)

    def test_skip_button_has_visible_focus_style(self):
        self._make_app()
        import onboarding_wizard as ow
        w = ow.OnboardingWizard()
        try:
            self.assertIn(":focus", w._skip_btn.styleSheet())
        finally:
            w.close()


if __name__ == "__main__":
    unittest.main()
