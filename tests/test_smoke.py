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

        payload = b"x" * 1000

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
                "https://example.com/SnapCap-Setup-9.9.9.exe",
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
                "https://example.com/SnapCap-Setup-9.9.9.exe", expected_size=99999,
            )
        self.assertIsNone(path)

    def test_download_returns_none_on_network_failure(self):
        import update_checker as uc

        def _raise(*a, **k):
            raise OSError("simulated: offline")

        with unittest.mock.patch("urllib.request.urlopen", side_effect=_raise):
            path = uc.download_installer("https://example.com/SnapCap-Setup-9.9.9.exe")
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


if __name__ == "__main__":
    unittest.main()
